# syntax=docker/dockerfile:1

# Frontend stage: build the Next.js app to static files in /frontend/out.
FROM node:24.19.0-trixie-slim AS frontend
WORKDIR /frontend
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=bind,source=frontend/package.json,target=package.json \
    --mount=type=bind,source=frontend/package-lock.json,target=package-lock.json \
    npm ci
COPY frontend ./
RUN npm run build

# Build stage: install locked dependencies and the project into /app/.venv with uv.
FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, in their own layer, so code changes don't reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-default-groups
COPY pyproject.toml uv.lock LICENSE NOTICE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --no-editable

# Runtime stage: same Python base, the finished virtual environment and static frontend, non-root user.
FROM python:3.14-slim-trixie
RUN groupadd --system app && useradd --system --gid app --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=frontend --chown=app:app /frontend/out /app/frontend/out
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 FRONTEND_DIR=/app/frontend/out
USER app
EXPOSE 8000
CMD ["uvicorn", "ehr_rwe_eln.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
