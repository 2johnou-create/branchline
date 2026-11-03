FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt \
    && groupadd --gid 10001 branchline \
    && useradd --uid 10001 --gid branchline --create-home --shell /bin/sh branchline \
    && mkdir -p /home/branchline/.ssh \
    && chown branchline:branchline /home/branchline/.ssh \
    && chmod 700 /home/branchline/.ssh \
    && mkdir -p /data && chown branchline:branchline /data && chmod 700 /data
COPY --chown=branchline:branchline server /app/server
COPY --chown=branchline:branchline scripts /app/scripts
COPY --chown=branchline:branchline dist /app/dist
COPY deploy/container_entry.py /opt/branchline/container_entry.py
EXPOSE 8080
ENTRYPOINT ["python", "/opt/branchline/container_entry.py", "gateway"]
CMD ["python", "-m", "server"]

