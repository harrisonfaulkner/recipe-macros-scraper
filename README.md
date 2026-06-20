# Recipe Macros

Paste a recipe URL, get per-serving macro nutrition info (calories, protein, fat, carbs, fiber, sugar, sodium).

Supports 646+ recipe websites including BBC Good Food, Budget Bytes, Food Network, Serious Eats, and many more via [recipe-scrapers](https://github.com/hhursev/recipe-scrapers).

## How It Works

1. **Scrape** -- fetches the recipe page and extracts ingredients, servings, and instructions
2. **Parse** -- NLP-based ingredient parser ([ingredient-parser-nlp](https://github.com/strangetom/ingredient-parser)) breaks each line into name, quantity, and unit
3. **Match** -- looks up each ingredient against a local USDA FoodData Central database (Foundation Foods + SR Legacy, 8,180 foods) using SQLite FTS5 full-text search
4. **Calculate** -- converts quantities to grams using USDA portion data, ingredient-specific density tables, and unit conversion, then computes macros from per-100g nutrition data
5. **Aggregate** -- sums per-ingredient macros into recipe totals, divides by servings

## Quick Start

```bash
cp .env.example .env
# Add your USDA API key (get one free at https://fdc.nal.usda.gov/api-key-signup)
# The API key is optional -- the local database handles most lookups

docker compose build
docker compose up -d
```

The app will be available at `http://localhost:8000` (via nginx) or directly on port 8000 from the app container.

## API

The backend is API-first, so it can serve both the web frontend and future clients (e.g., a mobile app).

### `POST /api/v1/recipe/parse`

```json
// Request
{ "url": "https://example.com/recipe/..." }

// Response
{
  "title": "Slow Cooker Short Rib Ragu",
  "source_url": "https://...",
  "servings": 8,
  "serving_size": "~489g (raw weight)",
  "per_serving": {
    "calories": 619, "protein_g": 42.0, "fat_g": 23.0,
    "carbs_g": 54.0, "fiber_g": 3.2, "sugar_g": 8.1, "sodium_mg": 580
  },
  "total": { ... },
  "ingredients": [
    {
      "original_text": "2 tablespoons extra virgin olive oil",
      "parsed": { "name": "extra virgin olive oil", "quantity": 2.0, "unit": "tablespoon" },
      "nutrition_match": { "usda_name": "Oil, olive, salad or cooking", "fdc_id": 171413 },
      "macros": { "calories": 239, "protein_g": 0, "fat_g": 27.0, ... }
    }
  ],
  "instructions": "Step 1: ...",
  "warnings": []
}
```

### `GET /api/v1/nutrition/search?q=chicken+breast`

Search the USDA database directly.

### `GET /api/v1/logs/recent`

Recent request logs for debugging and monitoring accuracy.

## Deployment with SSL

The project includes nginx and certbot configuration for HTTPS deployment.

1. Point your domain's DNS A record to your server IP
2. Update the domain in `nginx/nginx.conf`, `nginx/nginx-init.conf`, and `init-ssl.sh`
3. Update the email in `init-ssl.sh`
4. Set up `.env` with your `USDA_API_KEY`
5. Run the SSL bootstrap script:

```bash
sudo ./init-ssl.sh
```

This starts the app, obtains a Let's Encrypt certificate via HTTP challenge, then restarts with full SSL. Certbot auto-renews every 12 hours.

## Architecture

```
Browser / Mobile App
    |
    | POST /api/v1/recipe/parse
    v
FastAPI (app)
    |-- scraper.py     httpx + recipe-scrapers
    |-- parser.py      ingredient-parser-nlp
    |-- nutrition.py   SQLite FTS5 lookup + USDA API fallback
    |-- calculator.py  unit conversion + macro math
    |
    +-- SQLite (nutrition.db, built at Docker build time)
```

The USDA nutrition database (~8,180 foods, ~54K nutrient entries, ~14K portion entries) is downloaded and built into the Docker image at build time. No external database required at runtime.

## Project Structure

```
app/
  api/           route handlers (recipe, nutrition, logs)
  services/      business logic (scraper, parser, nutrition, calculator)
  models/        pydantic schemas
  data/          nutrition DB build script
  templates/     web frontend (single page, Pico CSS)
nginx/           nginx configs (SSL + HTTP-only init)
```

## Limitations

- Some sites (notably AllRecipes) use aggressive bot protection that blocks server-side scraping
- "To taste" ingredients (salt, pepper) have no quantity and can't contribute to macro totals
- Volume-to-weight conversion uses density approximations when USDA portion data is unavailable
- Serving size is calculated from raw ingredient weights when the recipe doesn't specify one -- actual cooked weight will differ
