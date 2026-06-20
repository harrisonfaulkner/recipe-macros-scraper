import httpx
from recipe_scrapers import scrape_html

from app.config import settings

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class ScrapedRecipe:
    def __init__(self, title: str, ingredients: list[str], servings: int | None,
                 source_url: str, instructions: str | None = None,
                 yields_text: str | None = None):
        self.title = title
        self.ingredients = ingredients
        self.servings = servings
        self.source_url = source_url
        self.instructions = instructions
        self.yields_text = yields_text


async def scrape_recipe(url: str) -> ScrapedRecipe:
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        response = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        response.raise_for_status()

    scraper = scrape_html(html=response.text, org_url=url, supported_only=False)

    title = scraper.title()
    ingredients = scraper.ingredients()

    yields_text = None
    servings = None
    try:
        yields_text = scraper.yields()
        servings = int(yields_text.split()[0])
    except (ValueError, AttributeError, IndexError):
        pass

    try:
        instructions = scraper.instructions()
    except Exception:
        instructions = None

    return ScrapedRecipe(
        title=title,
        ingredients=ingredients,
        servings=servings,
        source_url=url,
        instructions=instructions,
        yields_text=yields_text,
    )
