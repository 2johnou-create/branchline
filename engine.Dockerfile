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
RUN useradd --create-home --uid 10001 branchline \
    && mkdir -p uploads logs \
    && chown -R branchline:branchline /app
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=2 \
    FLASK_DEBUG=False
USER branchline
EXPOSE 5001
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "engine_entry:application"]
