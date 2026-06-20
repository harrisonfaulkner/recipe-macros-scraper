from pydantic import BaseModel, HttpUrl


class RecipeParseRequest(BaseModel):
    url: HttpUrl


class ParsedIngredientDetail(BaseModel):
    name: str
    quantity: float | None = None
    unit: str | None = None
    confidence: float | None = None


class NutritionMatch(BaseModel):
    usda_name: str
    fdc_id: int
    match_confidence: float | None = None


class MacroSummary(BaseModel):
    calories: float = 0
    protein_g: float = 0
    fat_g: float = 0
    carbs_g: float = 0
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0


class IngredientResult(BaseModel):
    original_text: str
    parsed: ParsedIngredientDetail | None = None
    nutrition_match: NutritionMatch | None = None
    macros: MacroSummary | None = None


class RecipeParseResponse(BaseModel):
    title: str
    source_url: str
    servings: int | None = None
    serving_size: str | None = None
    per_serving: MacroSummary | None = None
    total: MacroSummary | None = None
    ingredients: list[IngredientResult] = []
    instructions: str | None = None
    warnings: list[str] = []
