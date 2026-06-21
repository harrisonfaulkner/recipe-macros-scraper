import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from recipe_scrapers import scrape_html

from app.config import settings

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_url(url: str) -> None:
    """Block SSRF: reject non-HTTP schemes and private/internal IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL")
    for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
        addr = ipaddress.ip_address(info[4][0])
        for net in _BLOCKED_NETWORKS:
            if addr in net:
                raise ValueError(f"URLs pointing to internal addresses are not allowed")


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
    _validate_url(url)

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        response = await client.get(
            url,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        # Validate the final URL after redirects (prevent redirect-based SSRF)
        _validate_url(str(response.url))
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
