# syntax=docker/dockerfile:1

# The synth task's image (infra/terraform/app/synth.tf): Python with the project's locked
# dependencies and the synth group (torch, Opacus, mbi), and no project code. Each run fetches one
# commit's code (synth_task.py), so a code change needs no new image; a dependency change does,
# and changes the tag. Built by CodeBuild on x86 from a zip of this file, synth_task.py,
# pyproject.toml, and uv.lock (scripts/run_synth.py).

FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-default-groups --group synth

FROM python:3.14-slim-trixie
RUN groupadd --system app && useradd --system --gid app --create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY synth_task.py /app/synth_task.py
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
ENTRYPOINT ["python", "/app/synth_task.py"]
