from fastapi import HTTPException

from ehr_rwe_eln.config import Settings


def not_in_public_demo() -> None:
    """For routes that write records someone could deface (curator decisions). The public AWS
    deployment has no login, so PUBLIC_DEMO=true turns them off there; they work as usual
    everywhere else. /agent stays open there, bounded by the limits in api/limits.py."""
    if Settings().public_demo:
        raise HTTPException(
            status_code=403,
            detail="disabled in the public demo; run the app locally to use it",
        )
