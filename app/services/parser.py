from ingredient_parser import parse_ingredient
from app.models.schemas import ParsedIngredientDetail

SKIP_PHRASES = {"to taste", "as needed", "for garnish", "optional"}


def parse_ingredient_text(text: str) -> ParsedIngredientDetail | None:
    """Parse a raw ingredient string into structured data.

    Returns None for unparseable or negligible ingredients (e.g. "to taste").
    """
    text_lower = text.lower().strip()

    # Skip ingredients that contribute negligible macros
    if any(phrase in text_lower for phrase in SKIP_PHRASES):
        # Still try to parse, but flag low confidence
        pass

    try:
        result = parse_ingredient(text)
    except Exception:
        return None

    if not result.name:
        return None

    name = result.name[0].text
    confidence = result.name[0].confidence

    quantity = None
    unit = None
    if result.amount:
        amt = result.amount[0]
        quantity = float(amt.quantity)
        if amt.unit is not None:
            unit = str(amt.unit)

        # Handle container-based quantities like "2 (14-oz) cans"
        # If there are multiple amounts, use the second one for weight
        if len(result.amount) > 1:
            secondary = result.amount[1]
            secondary_unit = str(secondary.unit) if secondary.unit else None
            # If secondary has a weight unit (oz, g, lb), multiply for total
            if secondary_unit in ("ounce", "gram", "pound", "kilogram"):
                quantity = float(amt.quantity) * float(secondary.quantity)
                unit = secondary_unit

    return ParsedIngredientDetail(
        name=name,
        quantity=quantity,
        unit=unit,
        confidence=confidence,
    )
