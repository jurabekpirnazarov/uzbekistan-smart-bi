from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import __version__
from app.services.health import HealthStatus, get_health

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthStatus)
def health(response: Response) -> HealthStatus:
    result = get_health(__version__)
    if result.db != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
