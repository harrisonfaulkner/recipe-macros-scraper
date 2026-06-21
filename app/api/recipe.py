import logging
import re
import time
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    IngredientResult,
    RecipeParseRequest,
    RecipeParseResponse,
)
from app.services.scraper import scrape_recipe
from app.services.parser import parse_ingredient_text
from app.services.nutrition import lookup_ingredient
from app.services.calculator import (
    calculate_macros,
    divide_macros,
    ingredient_to_grams,
    sum_macros,
)
from app.services.request_log import log_request

logger = logging.getLogger(__name__)

router = APIRouter()


_TRACKING_PARAMS = re.compile(
    r'^(utm_.*|fbclid|gclid|gclsrc|dclid|gbraid|wbraid|msclkid|mc_[ce]id'
    r'|oly_[ae].*|_openstat|vero_id|wickedid|yclid|__s|_hsenc|_hsmi'
    r'|mkt_tok|ref|sref|partner|campaign_id|ad_id|adgroup|placement'
    r'|network|matchtype|creative|keyword|device|irclickid|irgwc'
    r'|si|igsh|igshid|share_source|feature|s)$',
    re.IGNORECASE,
)


def _strip_tracking_params(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if not _TRACKING_PARAMS.match(k)}
    new_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return urlunparse(parsed._replace(query=new_query))


@router.post("/recipe/parse", response_model=RecipeParseResponse)
async def parse_recipe(request: RecipeParseRequest):
    url = _strip_tracking_params(str(request.url))
    start = time.time()

    try:
        scraped = await scrape_recipe(url)
    except ValueError as e:
        # URL validation failures (SSRF protection)
        duration = time.time() - start
        log_request(url=url, success=False, error=str(e), duration_s=duration)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        duration = time.time() - start
        error_str = str(e)
        logger.warning(f"Scrape failed for {url}: {error_str}")
        log_request(url=url, success=False, error=error_str, duration_s=duration)
        if "403" in error_str:
            detail = "This site blocked our request. Some sites use bot protection that prevents scraping."
        elif "404" in error_str:
            detail = "Recipe page not found (404). Check that the URL is correct."
        else:
            detail = "Could not scrape recipe from the provided URL."
        raise HTTPException(status_code=422, detail=detail)

    warnings: list[str] = []
    ingredients: list[IngredientResult] = []
    all_macros: list = []
    total_grams = 0.0

    for text in scraped.ingredients:
        parsed = parse_ingredient_text(text)
        if parsed is None:
            warnings.append(f"Could not parse ingredient: {text}")
            ingredients.append(IngredientResult(original_text=text))
            continue

        # Look up nutrition data
        match, nutrients_per_100g, warning = lookup_ingredient(parsed.name)
        if warning:
            warnings.append(warning)

        # Calculate macros for this ingredient
        ingredient_macros = None
        if match and nutrients_per_100g:
            grams = ingredient_to_grams(parsed, match.fdc_id)
            if grams is not None:
                ingredient_macros = calculate_macros(nutrients_per_100g, grams)
                all_macros.append(ingredient_macros)
                total_grams += grams
            else:
                if parsed.quantity is None:
                    warnings.append(
                        f"No quantity specified for '{parsed.name}' — cannot calculate macros"
                    )
                else:
                    warnings.append(
                        f"Could not convert '{parsed.quantity} {parsed.unit or 'units'}' "
                        f"of '{parsed.name}' to grams"
                    )

        ingredients.append(IngredientResult(
            original_text=text,
            parsed=parsed,
            nutrition_match=match,
            macros=ingredient_macros,
        ))

    # Aggregate totals
    total = sum_macros(all_macros) if all_macros else None
    per_serving = None
    if total and scraped.servings and scraped.servings > 0:
        per_serving = divide_macros(total, scraped.servings)

    # Build serving size string
    serving_size = None
    if scraped.yields_text and scraped.servings:
        # Use the recipe's own description if it's more than just "N servings"
        yields_parts = scraped.yields_text.strip().split(None, 1)
        if len(yields_parts) > 1 and yields_parts[1].lower() != "servings":
            serving_size = "1 " + yields_parts[1].rstrip("s")
    if not serving_size and total_grams > 0 and scraped.servings:
        per_serving_g = round(total_grams / scraped.servings)
        serving_size = f"~{per_serving_g}g (raw weight)"

    duration = time.time() - start
    log_request(
        url=url,
        success=True,
        title=scraped.title,
        ingredient_count=len(ingredients),
        warning_count=len(warnings),
        warnings="; ".join(warnings) if warnings else None,
        duration_s=duration,
    )

    return RecipeParseResponse(
        title=scraped.title,
        source_url=scraped.source_url,
        servings=scraped.servings,
        serving_size=serving_size,
        per_serving=per_serving,
        total=total,
        ingredients=ingredients,
        instructions=scraped.instructions,
        warnings=warnings,
    )
