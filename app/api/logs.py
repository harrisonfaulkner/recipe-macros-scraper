from fastapi import APIRouter

from app.services.request_log import get_recent_logs, get_error_summary, get_warning_summary

router = APIRouter()


@router.get("/logs/recent")
async def recent_logs(limit: int = 50):
    return get_recent_logs(limit)


@router.get("/logs/errors")
async def error_summary():
    return get_error_summary()


@router.get("/logs/warnings")
async def warning_summary():
    return get_warning_summary()
