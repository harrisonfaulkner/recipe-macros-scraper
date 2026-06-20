"""USDA nutrition lookup with local SQLite FTS5 search and API fallback."""

import re
import sqlite3

import httpx

from app.config import settings
from app.models.schemas import MacroSummary, NutritionMatch

USDA_API_BASE = "https://api.nal.usda.gov/fdc/v1"

# Common ingredient names mapped to preferred USDA fdc_ids
# Used when FTS matching consistently picks the wrong entry
INGREDIENT_OVERRIDES: dict[str, int] = {
    # Proteins
    "egg": 171287,          # Egg, whole, raw, fresh
    "eggs": 171287,
    # Dairy
    "butter": 173410,       # Butter, salted
    "milk": 171265,         # Milk, whole, 3.25% milkfat
    "cream cheese": 2346385,# Cream cheese, full fat, block
    "sour cream": 171257,   # Cream, sour, cultured
    "parmesan cheese": 171247,  # Cheese, parmesan, grated
    "parmesan": 171247,
    # Oils
    "olive oil": 171413,    # Oil, olive, salad or cooking
    "extra virgin olive oil": 171413,
    "vegetable oil": 171411,# Oil, soybean, salad or cooking
    "cooking oil": 171411,
    # Nuts
    "walnuts": 170187,      # Nuts, walnuts, english
    "walnut": 170187,
    "pecans": 170182,       # Nuts, pecans
    "almonds": 170567,      # Nuts, almonds
    # Spices & seasonings
    "cinnamon": 171320,     # Spices, cinnamon, ground
    "black pepper": 170931, # Spices, pepper, black
    "pepper": 170931,
    "bay leaves": 170917,   # Spices, bay leaf
    "bay leaf": 170917,
    "sea salt": 173468,     # Salt, table
    "sea salt flakes": 173468,
    "kosher salt": 173468,
    "salt": 173468,
    # Vegetables
    "onion": 170000,        # Onions, raw
    "onions": 170000,
    "brown onion": 170000,
    "yellow onion": 170000,
    "white onion": 170000,
    "red onion": 790577,    # Onions, red, raw
    "garlic": 169230,       # Garlic, raw
    # Canned goods
    "canned tomatoes": 333281,      # Tomatoes, canned, red, ripe, diced
    "canned chopped tomatoes": 333281,
    "canned diced tomatoes": 333281,
    "diced tomatoes": 333281,
    "crushed tomatoes": 170501,     # Tomato products, crushed, canned
    "tomato paste": 170460,         # Tomato products, canned, puree
    "beef broth": 171538,           # Soup, beef broth, canned, ready-to-serve
    "beef stock": 171538,
    "chicken broth": 172192,        # Soup, chicken broth, ready-to-serve
    "chicken stock": 172192,
}

# Words to strip from ingredient names before searching
PREP_WORDS = {
    "chopped", "diced", "minced", "sliced", "grated", "shredded",
    "crushed", "ground", "mashed", "melted", "softened", "frozen",
    "thawed", "drained", "rinsed", "cooked", "raw", "fresh",
    "dried", "canned", "packed", "sifted", "peeled", "pitted",
    "seeded", "trimmed", "boneless", "skinless", "unsalted",
    "salted", "roasted", "toasted", "blanched", "deveined",
}


def _normalize_name(name: str) -> str:
    """Normalize an ingredient name for searching."""
    name = name.lower().strip()
    # Remove parenthetical notes
    name = re.sub(r"\([^)]*\)", "", name)
    # Replace hyphens and special chars with spaces (FTS5 interprets them as operators)
    name = re.sub(r"[^\w\s]", " ", name)
    # Remove prep words
    words = name.split()
    words = [w for w in words if w not in PREP_WORDS and len(w) > 1]
    return " ".join(words).strip()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _rerank_results(results: list[dict], query_terms: list[str]) -> list[dict]:
    """Re-rank FTS results by description similarity to the query.

    Prefers: shorter descriptions (more specific), foundation foods,
    and descriptions where query terms make up a larger fraction.
    """
    for r in results:
        desc = r["description"].lower()
        desc_words = re.sub(r"[^\w\s]", " ", desc).split()
        # Stem both sides by stripping trailing 's' for comparison
        desc_word_set = {w.rstrip("s") or w for w in desc_words}

        query_set = {t.rstrip("s") or t for t in query_terms}
        overlap = query_set & desc_word_set

        # What fraction of query terms appear in description
        query_coverage = len(overlap) / len(query_set) if query_set else 0
        # What fraction of description words are query terms (penalizes long descriptions)
        desc_coverage = len(overlap) / len(desc_words) if desc_words else 0

        # Bonus for foundation foods (higher quality data)
        type_bonus = 0.05 if r["data_type"] == "foundation_food" else 0

        # Penalty for very long descriptions (compound/prepared foods)
        brevity_bonus = max(0, 0.1 - len(desc_words) * 0.01)

        # Bonus when the description starts with a query term
        # (USDA format: primary food first, e.g. "Egg, whole, raw" vs "Bread, egg")
        first_desc_word = (desc_words[0].rstrip("s") or desc_words[0]) if desc_words else ""
        starts_with_query = 0.15 if first_desc_word in query_set else 0

        # Prefer raw/fresh ingredients (recipes use raw inputs)
        raw_bonus = 0.05 if any(w in desc_word_set for w in ("raw", "fresh")) else 0
        # Penalize processed forms when query doesn't specify them
        processed_words = {"dried", "frozen", "cooked", "canned", "powder",
                           "substitute", "mix", "prepared", "baked", "fried"}
        has_unwanted_processed = bool(processed_words & desc_word_set - query_set)
        processed_penalty = -0.08 if has_unwanted_processed else 0

        r["match_score"] = (
            query_coverage * 0.35
            + desc_coverage * 0.4
            + type_bonus
            + brevity_bonus
            + starts_with_query
            + raw_bonus
            + processed_penalty
        )

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results


def search_local(ingredient_name: str, limit: int = 5) -> list[dict]:
    """Search the local USDA SQLite database using FTS5."""
    normalized = _normalize_name(ingredient_name)
    if not normalized:
        return []

    conn = _get_db()
    try:
        results = []
        # Strip trailing 's' from each term to handle singular/plural
        terms = [t.rstrip("s") or t for t in normalized.split()]

        # Fetch more candidates than needed, then re-rank
        fetch_limit = max(limit * 4, 20)

        # Try all terms together (AND match with prefix matching)
        if len(terms) > 1:
            and_query = " AND ".join(f'{t}*' for t in terms)
            cur = conn.execute(
                """
                SELECT f.fdc_id, f.description, f.data_type,
                       rank * -1 as score
                FROM food_fts
                JOIN food f ON f.fdc_id = food_fts.rowid
                WHERE food_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (and_query, fetch_limit),
            )
            results = [dict(r) for r in cur.fetchall()]

        # Fall back to OR query
        if not results:
            or_query = " OR ".join(f'{t}*' for t in terms)
            cur = conn.execute(
                """
                SELECT f.fdc_id, f.description, f.data_type,
                       rank * -1 as score
                FROM food_fts
                JOIN food f ON f.fdc_id = food_fts.rowid
                WHERE food_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (or_query, fetch_limit),
            )
            results = [dict(r) for r in cur.fetchall()]

        # Re-rank by description similarity
        results = _rerank_results(results, terms)
        return results[:limit]
    finally:
        conn.close()


def get_nutrients(fdc_id: int) -> MacroSummary:
    """Get macro nutrients for a food by fdc_id."""
    conn = _get_db()
    try:
        cur = conn.execute(
            "SELECT nutrient_key, amount FROM food_nutrient WHERE fdc_id = ?",
            (fdc_id,),
        )
        nutrients = {row["nutrient_key"]: row["amount"] for row in cur.fetchall()}

        return MacroSummary(
            calories=nutrients.get("calories", 0),
            protein_g=nutrients.get("protein_g", 0),
            fat_g=nutrients.get("fat_g", 0),
            carbs_g=nutrients.get("carbs_g", 0),
            fiber_g=nutrients.get("fiber_g", 0),
            sugar_g=nutrients.get("sugar_g", 0),
            sodium_mg=nutrients.get("sodium_mg", 0),
        )
    finally:
        conn.close()


def get_portion_weight(fdc_id: int, unit: str | None) -> float | None:
    """Get gram weight for a portion of the given food.

    Returns grams per 1 unit, or None if not found.
    """
    if not unit:
        return None

    conn = _get_db()
    try:
        unit_lower = unit.lower().rstrip("s")  # normalize plural

        # Search by measure_unit or modifier or portion_description
        cur = conn.execute(
            """
            SELECT amount, gram_weight, measure_unit, modifier, portion_description
            FROM food_portion
            WHERE fdc_id = ?
            """,
            (fdc_id,),
        )
        portions = cur.fetchall()

        for p in portions:
            mu = (p["measure_unit"] or "").lower().rstrip("s")
            mod = (p["modifier"] or "").lower()
            desc = (p["portion_description"] or "").lower()

            if unit_lower in (mu, mod, desc) or unit_lower in mod or unit_lower in desc:
                amount = p["amount"] or 1
                # gram_weight is for `amount` units, so per-unit is gram_weight / amount
                return p["gram_weight"] / amount if amount else p["gram_weight"]

        return None
    finally:
        conn.close()


async def search_usda_api(query: str, limit: int = 5) -> list[dict]:
    """Search the USDA FoodData Central API as fallback."""
    if not settings.usda_api_key:
        return []

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        resp = await client.get(
            f"{USDA_API_BASE}/foods/search",
            params={
                "api_key": settings.usda_api_key,
                "query": query,
                "dataType": ["Foundation", "SR Legacy"],
                "pageSize": limit,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for food in data.get("foods", []):
        results.append({
            "fdc_id": food["fdcId"],
            "description": food["description"],
            "data_type": food.get("dataType", ""),
            "score": food.get("score", 0),
        })
    return results


def lookup_ingredient(name: str) -> tuple[NutritionMatch | None, MacroSummary | None, str | None]:
    """Look up an ingredient in the local database.

    Returns (match, nutrients_per_100g, warning).
    Nutrients are per 100g as stored in USDA data.
    """
    name_lower = name.lower().strip()

    # Check for manual overrides first
    override_fdc_id = INGREDIENT_OVERRIDES.get(name_lower)
    if override_fdc_id:
        conn = _get_db()
        try:
            cur = conn.execute(
                "SELECT description, data_type FROM food WHERE fdc_id = ?",
                (override_fdc_id,),
            )
            row = cur.fetchone()
            if row:
                match = NutritionMatch(
                    usda_name=row["description"],
                    fdc_id=override_fdc_id,
                    match_confidence=0.95,
                )
                nutrients = get_nutrients(override_fdc_id)
                return match, nutrients, None
        finally:
            conn.close()

    results = search_local(name)

    if not results:
        return None, None, f"No nutrition data found for '{name}'"

    best = results[0]
    fdc_id = best["fdc_id"]

    # Use the re-ranking match_score (0-1 range), capped at 1.0
    confidence = min(best.get("match_score", 0.5), 1.0)

    match = NutritionMatch(
        usda_name=best["description"],
        fdc_id=fdc_id,
        match_confidence=round(confidence, 3),
    )

    nutrients = get_nutrients(fdc_id)

    warning = None
    if confidence < 0.3:
        warning = f"Low confidence match for '{name}': {best['description']}"

    return match, nutrients, warning
