import logging
import time

import psycopg
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from ehr_rwe_eln.agents.app import AgentRequest, invoke
from ehr_rwe_eln.api.log_config import configure_logging
from ehr_rwe_eln.config import Settings

settings = Settings()
configure_logging(settings.log_level)
log = logging.getLogger("ehr_rwe_eln.api")

app = FastAPI(title="ehr-rwe-eln")

api = APIRouter(prefix="/api")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log.info(
        "request",
        extra={
            "fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        },
    )
    return response


@api.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/health/db")
def health_db() -> dict[str, str]:
    # A fresh connection per call, no pool: idle pooled connections would stop Aurora pausing.
    # connect_timeout covers the ~15 s Aurora takes to resume from 0 ACU and stays under the
    # Gateway's 55 s limit, so a slow resume returns this 503 rather than a Gateway timeout.
    try:
        with psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password.get_secret_value(),
            connect_timeout=20,
        ) as conn:
            conn.execute("SELECT 1").fetchone()
    except psycopg.OperationalError as exc:
        log.error("database check failed", extra={"fields": {"error": str(exc)}})
        raise HTTPException(
            status_code=503,
            detail="database unreachable; it may be resuming from pause, retry in about 30 seconds",
        ) from exc
    return {"status": "ok", "database": "reachable"}


@api.post("/agent")
def agent(request: AgentRequest) -> dict:
    return invoke(request)


app.include_router(api)
# Mounted last so it never shadows /api. html=True serves index.html for /.
app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True, check_dir=False))
