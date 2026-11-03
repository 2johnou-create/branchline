"""Bounded adapter for the pinned MiroFish HTTP API, never a general proxy."""
import asyncio
from urllib.parse import quote

import httpx


class EngineFailure(Exception):
    """Safe public failure message; upstream response bodies never leave the adapter."""


class Engine:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def client(self):
        return httpx.AsyncClient(
            base_url=self.settings.engine_url,
            timeout=self.settings.request_timeout,
            follow_redirects=False, transport=self.transport,
            headers={"Accept-Language": "en"},
        )

    async def call(self, client, method, path, **kwargs):
        try:
            response = await client.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise EngineFailure("The simulation engine could not complete this stage. Contact your workspace operator.")
            if len(response.content) > 4_000_000:
                raise EngineFailure("The engine response exceeded the permitted size.")
            body = response.json()
            if body.get("success") is not True:
                raise EngineFailure("The simulation engine reported a stage failure. Contact your workspace operator.")
            data = body.get("data", {})
            if not isinstance(data, dict):
                raise EngineFailure("The simulation engine returned an unexpected response.")
            return data
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise EngineFailure("The simulation engine is unavailable or returned an invalid response.") from exc

    @staticmethod
    def identifier(data, key):
        value = data.get(key)
        if not isinstance(value, str) or not value or len(value) > 160:
            raise EngineFailure("The simulation engine returned an incomplete response.")
        return value

    async def task(self, client, method, path, *, body=None, update=None, base=0, span=10):
        while True:
            data = await self.call(client, method, path, **({"json": body} if body else {}))
            status = data.get("status")
            if status in ("failed", "error"):
                raise EngineFailure("A simulation preparation or report task failed. Contact your workspace operator.")
            if update:
                progress = data.get("progress", 0)
                update(progress=base + int(min(100, max(0, float(progress))) * span / 100))
            if status in ("completed", "ready") or data.get("already_prepared"):
                return data
            await asyncio.sleep(self.settings.poll_interval)

    async def run(self, payload, update):
        async with self.client() as client:
            update(status="building", stage="Reading context", progress=3)
            requirement = f"{payload['question']}\n\nAudience: {payload['audience']}\n\nTreat this as a synthetic scenario, not a prediction of real people."
            context = payload["context"] + "\n\nAudience definition:\n" + payload["audience"]
            data = await self.call(client, "POST", "/api/graph/ontology/generate",
                data={"simulation_requirement": requirement,
                      "project_name": payload["title"],
                      "additional_context": f"Use English. Keep the scenario small: no more than {self.settings.max_agents} individual simulated entities."},
                files={"files": ("context.txt", context.encode("utf-8"), "text/plain")})
            project_id = self.identifier(data, "project_id")
            update(upstream={"project_id": project_id}, stage="Building scenario graph", progress=10)
            graph = await self.call(client, "POST", "/api/graph/build", json={"project_id": project_id})
            task_id = graph.get("task_id")
            if task_id:
                await self.task(client, "GET", "/api/graph/task/" + quote(str(task_id), safe=""), update=update, base=10, span=20)
            project = await self.call(client, "GET", "/api/graph/project/" + quote(project_id, safe=""))
            graph_id = self.identifier(project, "graph_id")
            update(upstream={"graph_id": graph_id}, progress=30)
            entities = await self.call(client, "GET", "/api/simulation/entities/" + quote(graph_id, safe=""), params={"enrich": "false"})
            count = entities.get("filtered_count")
            if not isinstance(count, int) or count < 1:
                raise EngineFailure("The scenario did not produce any usable simulated entities. Try a more specific audience and context.")
            if count > self.settings.max_agents:
                raise EngineFailure("This scenario exceeds the workspace agent limit. Narrow the context before trying again.")
            created = await self.call(client, "POST", "/api/simulation/create", json={
                "project_id": project_id, "graph_id": graph_id,
                "enable_twitter": True, "enable_reddit": False})
            sid = self.identifier(created, "simulation_id")
            update(upstream={"simulation_id": sid}, status="preparing", stage="Preparing synthetic participants", progress=32)
            prepared = await self.call(client, "POST", "/api/simulation/prepare", json={"simulation_id": sid, "parallel_profile_count": 2})
            if prepared.get("status") != "ready":
                await self.task(client, "POST", "/api/simulation/prepare/status",
                    body={"simulation_id": sid, "task_id": self.identifier(prepared, "task_id")},
                    update=update, base=32, span=23)
            update(status="running", stage="Running scenario", progress=55)
            await self.call(client, "POST", "/api/simulation/start", json={
                "simulation_id": sid, "platform": "twitter", "max_rounds": payload["rounds"],
                "enable_graph_memory_update": False})
            environment_closed = False
            while True:
                state = await self.call(client, "GET", "/api/simulation/" + quote(sid, safe="") + "/run-status")
                status = state.get("runner_status")
                if status in ("completed", "stopped"):
                    break
                if status == "failed":
                    raise EngineFailure("The scenario run failed. Contact your workspace operator.")
                # Upstream keeps the process alive for interviews after the
                # simulation_end event. Its runner becomes terminal only after
                # the environment closes; 100% progress alone is not sufficient.
                if state.get("twitter_completed") is True and not environment_closed:
                    await self.call(client, "POST", "/api/simulation/close-env", json={"simulation_id": sid, "timeout": 10})
                    environment_closed = True
                progress = min(100, max(0, float(state.get("progress_percent", 0))))
                update(progress=55 + int(progress * .25))
                await asyncio.sleep(self.settings.poll_interval)
            update(status="reporting", stage="Writing scenario report", progress=82)
            report = await self.call(client, "POST", "/api/report/generate", json={"simulation_id": sid})
            if report.get("report_id"):
                update(upstream={"report_id": report["report_id"]})
            if report.get("status") != "completed" and not report.get("already_generated"):
                await self.task(client, "POST", "/api/report/generate/status",
                    body={"simulation_id": sid, "task_id": self.identifier(report, "task_id")},
                    update=update, base=82, span=16)
            report = await self.call(client, "GET", "/api/report/by-simulation/" + quote(sid, safe=""))
            if report.get("report_id"):
                update(upstream={"report_id": report["report_id"]})
            markdown = report.get("markdown_content")
            if not isinstance(markdown, str) or not markdown.strip():
                raise EngineFailure("The engine completed without a readable report.")
            return {"markdown": markdown[:1_000_000]}

    async def stop(self, refs):
        sid = refs.get("simulation_id")
        if not sid:
            return False
        try:
            async with self.client() as client:
                state = await self.call(client, "GET", "/api/simulation/" + quote(sid, safe="") + "/run-status")
                if state.get("runner_status") in ("starting", "running", "paused", "stopping"):
                    await self.call(client, "POST", "/api/simulation/stop", json={"simulation_id": sid})
            return True
        except EngineFailure:
            return False

    async def cleanup(self, refs):
        receipt = {"project_and_cloud_graph": "not_created", "report": "not_created",
                   "simulation_artifacts": "operator_cleanup_required" if refs.get("simulation_id") else "not_created"}
        await self.stop(refs)
        async with self.client() as client:
            for key, route, label in (("report_id", "/api/report/", "report"),
                                       ("project_id", "/api/graph/project/", "project_and_cloud_graph")):
                if refs.get(key):
                    try:
                        response = await client.delete(route + quote(refs[key], safe=""))
                        body = response.json()
                        receipt[label] = "deletion_acknowledged" if response.status_code == 404 or (response.is_success and body.get("success") is True) else "operator_cleanup_required"
                    except (httpx.HTTPError, ValueError, AttributeError):
                        receipt[label] = "operator_cleanup_required"
            if refs.get("simulation_id") and self.settings.engine_cleanup_secret:
                try:
                    response = await client.delete("/internal/branchline/simulations/" + quote(refs["simulation_id"], safe=""),
                        headers={"X-Branchline-Cleanup-Key": self.settings.engine_cleanup_secret})
                    body = response.json()
                    # A generic 404 could mean an older engine lacks the route,
                    # not that its simulation artifacts were removed.
                    if response.is_success and body.get("success") is True and body.get("data", {}).get("deleted") is True:
                        receipt["simulation_artifacts"] = "deletion_acknowledged"
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass
        return receipt

