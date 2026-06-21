from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth import require_admin
from app.services.overrides import list_overrides, set_override, delete_override
from app.services.nutrition import get_nutrients, _get_db

router = APIRouter(dependencies=[Depends(require_admin)])


class OverrideRequest(BaseModel):
    ingredient_name: str
    fdc_id: int


@router.get("/overrides")
async def get_overrides():
    """List all ingredient overrides."""
    return list_overrides()


@router.post("/overrides")
async def add_override(req: OverrideRequest):
    """Add or update an ingredient override."""
    # Validate that the fdc_id exists in the nutrition database
    conn = _get_db()
    try:
        cur = conn.execute(
            "SELECT description FROM food WHERE fdc_id = ?", (req.fdc_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"fdc_id {req.fdc_id} not found in nutrition database",
            )
        usda_description = row["description"]
    finally:
        conn.close()

    set_override(req.ingredient_name, req.fdc_id, usda_description)
    return {
        "ingredient_name": req.ingredient_name.lower().strip(),
        "fdc_id": req.fdc_id,
        "usda_description": usda_description,
    }


@router.delete("/overrides/{ingredient_name}")
async def remove_override(ingredient_name: str):
    """Delete an ingredient override."""
    if not delete_override(ingredient_name):
        raise HTTPException(status_code=404, detail="Override not found")
    return {"deleted": ingredient_name}
