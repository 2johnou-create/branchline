FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcairo2 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY engine/mirofish/backend/ ./
COPY deploy/install_engine.py /opt/branchline/install_engine.py
RUN UV_NO_CACHE=1 python /opt/branchline/install_engine.py
COPY engine/mirofish/locales/ /app/locales/
COPY deploy/engine_entry.py ./engine_entry.py
COPY deploy/engine_boot.py ./engine_boot.py
COPY deploy/engine_cleanup.py ./engine_cleanup.py
COPY deploy/run_twitter_simulation.py ./scripts/run_twitter_simulation.py
RUN useradd --create-home --uid 10001 --shell /bin/sh branchline \
    && mkdir -p /home/branchline/.ssh \
    && chmod 700 /home/branchline/.ssh \
    && chown -R branchline:branchline /home/branchline/.ssh \
    && mkdir -p uploads logs \
    && chown -R branchline:branchline /app
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 \
    FLASK_DEBUG=False
COPY deploy/container_entry.py /opt/branchline/container_entry.py
COPY deploy/engine_boot.py /opt/branchline/engine_boot.py
EXPOSE 5001
ENTRYPOINT ["python", "/opt/branchline/container_entry.py", "engine"]
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "engine_entry:application"]
