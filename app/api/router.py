from fastapi import APIRouter

from app.api.recipe import router as recipe_router
from app.api.nutrition import router as nutrition_router
from app.api.logs import router as logs_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(recipe_router)
api_router.include_router(nutrition_router)
api_router.include_router(logs_router)
