import logging
import time
from typing import Annotated

import jwt
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ehr_rwe_eln.agents.app import AgentRequest, invoke
from ehr_rwe_eln.api.log_config import configure_logging
from ehr_rwe_eln.config import Settings

settings = Settings()
configure_logging(settings.log_level)
log = logging.getLogger("ehr_rwe_eln.api")

app = FastAPI(title="ehr-rwe-eln")

# Pool IDs start with their region, e.g. us-east-1_AbC123.
cognito_issuer = (
    f"https://cognito-idp.{settings.cognito_user_pool_id.split('_')[0]}.amazonaws.com/"
    f"{settings.cognito_user_pool_id}"
)
# Fetches Cognito's public signing keys once and caches them.
jwks_client = jwt.PyJWKClient(f"{cognito_issuer}/.well-known/jwks.json")
bearer = HTTPBearer()


def current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)]) -> dict:
    """Verify a Cognito access token: signature, expiry, issuer, and our app client."""
    token = credentials.credentials
    try:
        key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=cognito_issuer)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc
    # Access tokens carry client_id, not aud, so check it by hand.
    if claims.get("token_use") != "access" or claims.get("client_id") != settings.cognito_client_id:
        raise HTTPException(status_code=401, detail="invalid token")
    return claims


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


@app.get("/me")
def me(claims: Annotated[dict, Depends(current_user)]) -> dict[str, str]:
    return {"username": claims["username"], "sub": claims["sub"]}


@app.get("/health/db")
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


@app.post("/agent")
def agent(request: AgentRequest) -> dict:
    return invoke(request)
