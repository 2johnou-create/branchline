FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt \
    && groupadd --gid 10001 branchline \
    && useradd --uid 10001 --gid branchline --create-home branchline \
    && mkdir -p /data && chown branchline:branchline /data && chmod 700 /data
COPY --chown=branchline:branchline server /app/server
COPY --chown=branchline:branchline scripts/provision-workspace.py /app/scripts/provision-workspace.py
USER branchline
EXPOSE 8080
CMD ["python", "-m", "server"]

