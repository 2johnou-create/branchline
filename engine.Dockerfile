FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/
WORKDIR /app/backend
COPY engine/mirofish/backend/ ./
RUN uv sync --frozen --no-dev \
    && uv pip install --python .venv/bin/python gunicorn==23.0.0
COPY engine/mirofish/locales/ /app/locales/
COPY deploy/engine_entry.py ./engine_entry.py
RUN useradd --create-home --uid 10001 branchline \
    && mkdir -p uploads logs \
    && chown -R branchline:branchline /app
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_DEBUG=False
USER branchline
EXPOSE 5001
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--timeout", "120", "--access-logfile", "/dev/null", "--error-logfile", "-", "engine_entry:application"]
