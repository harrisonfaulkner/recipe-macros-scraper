"""Unit conversion and macro calculation.

USDA nutrition data is per 100g. This service converts ingredient quantities
to grams, then calculates actual macros.
"""

from app.models.schemas import MacroSummary, ParsedIngredientDetail
from app.services.nutrition import get_portion_weight

# Gram weights for common volume measures of water-like density.
# Used as last resort when USDA portion data is unavailable.
VOLUME_TO_GRAMS = {
    "cup": 240,
    "tablespoon": 15,
    "tbsp": 15,
    "teaspoon": 5,
    "tsp": 5,
    "fl oz": 30,
    "liter": 1000,
    "milliliter": 1,
    "ml": 1,
    "pint": 473,
    "quart": 946,
    "gallon": 3785,
    "pinch": 0.36,      # ~1/16 teaspoon
    "dash": 0.72,       # ~1/8 teaspoon
    "smidgen": 0.18,    # ~1/32 teaspoon
}

# Ingredient-specific density overrides (grams per cup)
# for common ingredients where volume != weight
DENSITY_GRAMS_PER_CUP = {
    "flour": 125, "all-purpose flour": 125, "bread flour": 127,
    "whole wheat flour": 120, "cake flour": 114,
    "sugar": 200, "granulated sugar": 200, "white sugar": 200,
    "brown sugar": 220, "powdered sugar": 120, "confectioners sugar": 120,
    "butter": 227, "margarine": 227,
    "oil": 218, "vegetable oil": 218, "olive oil": 216, "cooking oil": 218,
    "canola oil": 218, "coconut oil": 218,
    "milk": 244, "whole milk": 244, "skim milk": 245,
    "cream": 238, "heavy cream": 238, "sour cream": 230,
    "honey": 340, "maple syrup": 312, "molasses": 328,
    "rice": 185, "white rice": 185, "brown rice": 190,
    "oats": 80, "rolled oats": 80,
    "cocoa powder": 86, "cornstarch": 128,
    "breadcrumbs": 108, "panko": 60,
    "shredded cheese": 113, "grated parmesan": 100,
    "peanut butter": 258, "almond butter": 256,
    "walnuts": 120, "pecans": 109, "almonds": 143,
    "chocolate chips": 170,
    "raisins": 145, "dried cranberries": 120,
    "salt": 292, "baking soda": 220, "baking powder": 230,
}

# Weight units to grams
WEIGHT_TO_GRAMS = {
    "g": 1, "gram": 1, "grams": 1,
    "kg": 1000, "kilogram": 1000,
    "oz": 28.3495, "ounce": 28.3495,
    "lb": 453.592, "pound": 453.592,
    "mg": 0.001, "milligram": 0.001,
}

# Count-based defaults (grams per 1 unit) for items with no unit
COUNT_DEFAULTS = {
    "egg": 50, "eggs": 50,
    "banana": 118, "bananas": 118,
    "apple": 182, "apples": 182,
    "lemon": 58, "lemons": 58,
    "lime": 67, "limes": 67,
    "orange": 131, "oranges": 131,
    "onion": 150, "onions": 150,
    "brown onion": 150, "yellow onion": 150, "white onion": 150, "red onion": 150,
    "garlic clove": 3, "clove garlic": 3, "clove": 3, "garlic": 3,
    "potato": 213, "potatoes": 213,
    "carrot": 61, "carrots": 61,
    "celery stalk": 40, "stalk celery": 40, "celery": 40,
    "chicken breast": 174, "breast": 174,
    "tortilla": 49, "tortillas": 49,
    "slice bread": 30, "bread slice": 30,
    "bay leaf": 0.6, "bay leaves": 0.6,
    "thyme": 1, "sprig thyme": 1,
}

# Units that are really count-based (not volume/weight)
UNIT_TO_GRAMS = {
    "stick": 40,        # celery stick
    "stalk": 40,        # celery stalk
    "clove": 3,         # garlic clove
    "sprig": 1,         # herb sprig
    "leaf": 0.6,        # bay leaf etc.
    "slice": 30,        # bread slice
    "strip": 10,        # bacon strip
    "link": 68,         # sausage link
    "patty": 113,       # burger patty
    "fillet": 170,      # fish fillet
    "breast": 174,      # chicken breast
    "thigh": 125,       # chicken thigh
    "drumstick": 75,    # chicken drumstick
    "wing": 32,         # chicken wing
    "can": 400,         # standard can
    "head": 600,        # head of lettuce/cabbage
    "bunch": 150,       # bunch of herbs/greens
    "bulb": 136,        # garlic bulb
}


def _normalize_unit(unit: str | None) -> str | None:
    """Normalize unit strings for comparison."""
    if not unit:
        return None
    u = unit.lower().strip().rstrip("s")
    # Handle plurals and abbreviations
    aliases = {
        "tbsp": "tablespoon", "tablespoon": "tablespoon",
        "tsp": "teaspoon", "teaspoon": "teaspoon",
        "cup": "cup",
        "oz": "ounce", "ounce": "ounce",
        "lb": "pound", "pound": "pound",
        "g": "gram", "gram": "gram",
        "kg": "kilogram", "kilogram": "kilogram",
        "ml": "milliliter", "milliliter": "milliliter",
        "fl oz": "fl oz",
        "pinch": "pinch", "dash": "dash", "smidgen": "smidgen",
        "stick": "stick", "stalk": "stalk", "clove": "clove",
        "sprig": "sprig", "leaf": "leaf", "slice": "slice",
        "strip": "strip", "link": "link", "can": "can",
        "head": "head", "bunch": "bunch", "bulb": "bulb",
    }
    return aliases.get(u, u)


def ingredient_to_grams(
    parsed: ParsedIngredientDetail,
    fdc_id: int | None,
) -> float | None:
    """Convert a parsed ingredient quantity to grams.

    Strategy:
    1. If unit is a weight unit, convert directly.
    2. If USDA has portion data for this food+unit, use that.
    3. If we have a density override for this ingredient, use that.
    4. If unit is a volume, use water-density fallback.
    5. If no unit (count-based), check count defaults or USDA portions.
    """
    quantity = parsed.quantity
    if quantity is None or quantity <= 0:
        return None

    unit = parsed.unit
    name = parsed.name.lower() if parsed.name else ""
    norm_unit = _normalize_unit(unit)

    # 1. Direct weight conversion
    if norm_unit and norm_unit in ("gram", "kilogram", "ounce", "pound", "milligram"):
        weight_key = norm_unit + ("s" if norm_unit not in WEIGHT_TO_GRAMS else "")
        factor = WEIGHT_TO_GRAMS.get(norm_unit, WEIGHT_TO_GRAMS.get(weight_key))
        if factor:
            return quantity * factor

    # 2. USDA portion data
    if fdc_id and unit:
        portion_grams = get_portion_weight(fdc_id, unit)
        if portion_grams:
            return quantity * portion_grams

    # 3. Density overrides for common volume units
    if norm_unit in ("cup", "tablespoon", "teaspoon", "fl oz"):
        for key in [name, name.rstrip("s")]:
            if key in DENSITY_GRAMS_PER_CUP:
                grams_per_cup = DENSITY_GRAMS_PER_CUP[key]
                vol_in_cups = quantity
                if norm_unit == "tablespoon":
                    vol_in_cups = quantity / 16
                elif norm_unit == "teaspoon":
                    vol_in_cups = quantity / 48
                elif norm_unit == "fl oz":
                    vol_in_cups = quantity / 8
                return vol_in_cups * grams_per_cup

    # 4. Generic volume fallback (pinch, dash, cups without density override, etc.)
    if norm_unit and norm_unit in VOLUME_TO_GRAMS:
        return quantity * VOLUME_TO_GRAMS[norm_unit]
    vol_key = (unit.lower().rstrip("s") if unit else None)
    if vol_key and vol_key in VOLUME_TO_GRAMS:
        return quantity * VOLUME_TO_GRAMS[vol_key]

    # 5. Count-like units (stick, clove, sprig, etc.)
    if norm_unit and norm_unit in UNIT_TO_GRAMS:
        return quantity * UNIT_TO_GRAMS[norm_unit]

    # 6. Count-based (no unit or unit is a size like "large", "medium")
    if not unit or norm_unit in ("large", "medium", "small", ""):
        # Check USDA portions first
        if fdc_id:
            portion_grams = get_portion_weight(fdc_id, norm_unit or "medium")
            if portion_grams:
                return quantity * portion_grams

        # Check our count defaults
        for key in [name, name.rstrip("s"), name + "s"]:
            if key in COUNT_DEFAULTS:
                return quantity * COUNT_DEFAULTS[key]

    return None


def calculate_macros(nutrients_per_100g: MacroSummary, grams: float) -> MacroSummary:
    """Scale per-100g nutrients to the actual gram weight."""
    factor = grams / 100.0
    return MacroSummary(
        calories=round(nutrients_per_100g.calories * factor, 1),
        protein_g=round(nutrients_per_100g.protein_g * factor, 2),
        fat_g=round(nutrients_per_100g.fat_g * factor, 2),
        carbs_g=round(nutrients_per_100g.carbs_g * factor, 2),
        fiber_g=round(nutrients_per_100g.fiber_g * factor, 2),
        sugar_g=round(nutrients_per_100g.sugar_g * factor, 2),
        sodium_mg=round(nutrients_per_100g.sodium_mg * factor, 1),
    )


def sum_macros(macro_list: list[MacroSummary]) -> MacroSummary:
    """Sum a list of MacroSummary objects."""
    return MacroSummary(
        calories=round(sum(m.calories for m in macro_list), 1),
        protein_g=round(sum(m.protein_g for m in macro_list), 2),
        fat_g=round(sum(m.fat_g for m in macro_list), 2),
        carbs_g=round(sum(m.carbs_g for m in macro_list), 2),
        fiber_g=round(sum(m.fiber_g for m in macro_list), 2),
        sugar_g=round(sum(m.sugar_g for m in macro_list), 2),
        sodium_mg=round(sum(m.sodium_mg for m in macro_list), 1),
    )


def divide_macros(macros: MacroSummary, divisor: int) -> MacroSummary:
    """Divide macros by a number (e.g., servings)."""
    if divisor <= 0:
        return macros
    return MacroSummary(
        calories=round(macros.calories / divisor, 1),
        protein_g=round(macros.protein_g / divisor, 2),
        fat_g=round(macros.fat_g / divisor, 2),
        carbs_g=round(macros.carbs_g / divisor, 2),
        fiber_g=round(macros.fiber_g / divisor, 2),
        sugar_g=round(macros.sugar_g / divisor, 2),
        sodium_mg=round(macros.sodium_mg / divisor, 1),
    )
