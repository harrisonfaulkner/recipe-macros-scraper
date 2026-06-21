import hmac

from fastapi import Header, HTTPException

from app.config import settings


async def require_admin(x_api_key: str = Header()):
    """Dependency that checks for a valid admin API key."""
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    if not hmac.compare_digest(x_api_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
