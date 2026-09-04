"""Health check en dos niveles.

- ``GET /api/v1/health/live``: el proceso responde. Sin dependencias.
- ``GET /api/v1/health/ready``: estado por dependencia y estado agregado.
  Devuelve 200 con estado ``ok`` o ``degraded`` (el sistema sirve tráfico,
  quizá parcialmente) y 503 solo cuando una dependencia crítica está caída.
"""

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from elsa.core.health import (
    SystemStatus,
    aggregate,
    current_dependency_reports,
)

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: str


class DependencyHealth(BaseModel):
    status: str
    critical: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    environment: str
    dependencies: dict[str, DependencyHealth]


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    reports = current_dependency_reports()
    system_status = aggregate(reports)
    if system_status is SystemStatus.DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status=system_status.value,
        environment=request.app.state.settings.env.value,
        dependencies={
            report.name: DependencyHealth(
                status=report.status.value,
                critical=report.critical,
                detail=report.detail,
            )
            for report in reports
        },
    )
