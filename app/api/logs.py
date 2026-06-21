from fastapi import APIRouter, Depends

from app.api.auth import require_admin
from app.services.request_log import (
    get_recent_logs,
    get_error_summary,
    get_warning_summary,
    get_stats,
)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/logs/recent")
async def recent_logs(limit: int = 50):
    return get_recent_logs(limit)


@router.get("/logs/errors")
async def error_summary():
    return get_error_summary()


@router.get("/logs/warnings")
async def warning_summary():
    return get_warning_summary()


@router.get("/logs/stats")
async def stats():
    return get_stats()
