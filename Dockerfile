FROM ghcr.io/astral-sh/uv:0.9.3 AS uv-bin

FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv-bin /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra postgres
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY backend/ ./backend/
RUN useradd --create-home --uid 10001 signaldesk && chown -R signaldesk:signaldesk /app
USER signaldesk
EXPOSE 8787
CMD ["uv", "run", "--frozen", "uvicorn", "backend.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787"]
