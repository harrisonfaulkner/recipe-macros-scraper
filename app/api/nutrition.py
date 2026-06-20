from fastapi import APIRouter

from app.services.nutrition import search_local

router = APIRouter()


@router.get("/nutrition/search")
async def search_nutrition(q: str, limit: int = 10):
    results = search_local(q, limit=limit)
    return {"query": q, "results": results}
