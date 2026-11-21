import logging
import time

import psycopg
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from ehr_rwe_eln.agents.app import AgentRequest, invoke
from ehr_rwe_eln.api import curation, dq, eln, synth, tte
from ehr_rwe_eln.api.limits import (
    ADDRESS_LIMIT_MESSAGE,
    DAILY_LIMIT_MESSAGE,
    client_address,
    next_reset,
    record_call,
    tokens_today,
    within_address_limit,
)
from ehr_rwe_eln.api.log_config import configure_logging
from ehr_rwe_eln.config import DB_CONNECT_TIMEOUT_S, Settings

settings = Settings()

AGENT_OFF_MESSAGE = "The demo agent is turned off for now; every page still works."
AGENT_INCOMPLETE_MESSAGE = "The agent didn't reach an answer. Try a simpler question."
configure_logging(settings.log_level)
log = logging.getLogger("ehr_rwe_eln.api")

app = FastAPI(title="ehr-rwe-eln")

api = APIRouter(prefix="/api")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    fields = {
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if is_page_view(request):
        # Who visits the demo: scripts/demo_visitors.py looks up each address's registered
        # organization. Logs expire after 30 days.
        fields["client"] = client_address(request)
        fields["user_agent"] = request.headers.get("user-agent", "")[:300]
    log.info("request", extra={"fields": fields})
    return response


def is_page_view(request: Request) -> bool:
    path = request.url.path
    return (
        request.method == "GET"
        and not path.startswith(("/api/", "/_next/"))
        and "." not in path.rsplit("/", 1)[-1]
    )


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/health/db")
def health_db() -> dict[str, str]:
    try:
        with settings.connect(connect_timeout=DB_CONNECT_TIMEOUT_S) as conn:
            conn.execute("SELECT 1").fetchone()
    except psycopg.OperationalError as exc:
        log.error("database check failed", extra={"fields": {"error": str(exc)}})
        raise HTTPException(
            status_code=503,
            detail="database unreachable; start it with docker compose up -d db",
        ) from exc
    return {"status": "ok", "database": "reachable"}


def connect() -> psycopg.Connection:
    return settings.connect(connect_timeout=DB_CONNECT_TIMEOUT_S)


@api.get("/usage")
def usage() -> dict:
    """Today's /agent allowance: the limit, tokens used and left, and when it resets."""
    with connect() as con:
        used = tokens_today(con)
    return {
        "limit": settings.daily_token_limit,
        "used": used,
        "remaining": max(settings.daily_token_limit - used, 0),
        "resets_at": next_reset().isoformat(),
    }


@api.post("/agent")
def agent(request: AgentRequest, http_request: Request) -> dict:
    """Public: no sign-in. The switch and both limits are checked before the model is called."""
    if not settings.agent_enabled:
        raise HTTPException(status_code=503, detail=AGENT_OFF_MESSAGE)
    if not within_address_limit(client_address(http_request)):
        log.info("agent address limit", extra={"fields": {}})
        raise HTTPException(status_code=429, detail=ADDRESS_LIMIT_MESSAGE)
    with connect() as con:
        used = tokens_today(con)
    if used >= settings.daily_token_limit:
        log.info("agent daily limit", extra={"fields": {"tokens_today": used}})
        raise HTTPException(status_code=429, detail=DAILY_LIMIT_MESSAGE)
    result = invoke(request)
    with connect() as con:
        record_call(con, result["usage"]["total_tokens"])
    if result["output"] is None:
        log.warning("agent incomplete", extra={"fields": result["usage"]})
        raise HTTPException(status_code=502, detail=AGENT_INCOMPLETE_MESSAGE)
    return result


api.include_router(dq.router)
api.include_router(tte.router)
api.include_router(eln.router)
api.include_router(synth.router)
api.include_router(curation.router)
app.include_router(api)
# Mounted last so it never shadows /api. html=True serves index.html for /.
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True, check_dir=False))
