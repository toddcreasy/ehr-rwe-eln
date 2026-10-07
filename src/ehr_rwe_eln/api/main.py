import logging
import time

import psycopg
from fastapi import FastAPI, HTTPException, Request

from ehr_rwe_eln.api.log_config import configure_logging
from ehr_rwe_eln.config import Settings

settings = Settings()
configure_logging(settings.log_level)
log = logging.getLogger("ehr_rwe_eln.api")

app = FastAPI(title="ehr-rwe-eln")


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict[str, str]:
    # A fresh connection per call, no pool: idle pooled connections would stop Aurora pausing.
    # connect_timeout covers the ~15 s Aurora takes to resume from 0 ACU.
    try:
        with psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password.get_secret_value(),
            connect_timeout=30,
        ) as conn:
            conn.execute("SELECT 1").fetchone()
    except psycopg.OperationalError as exc:
        log.error("database check failed", extra={"fields": {"error": str(exc)}})
        raise HTTPException(status_code=503, detail="database unreachable") from exc
    return {"status": "ok", "database": "reachable"}
