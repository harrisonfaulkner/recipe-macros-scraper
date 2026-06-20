"""Download USDA FoodData Central CSVs and build a local SQLite nutrition database.

Combines Foundation Foods (high quality, ~387 foods) and SR Legacy (~7,793 foods)
for broad coverage. Creates FTS5 index for fuzzy ingredient name matching.

Run: python -m app.data.build_nutrition_db
"""

import csv
import io
import os
import sqlite3
import urllib.request
import zipfile

FOUNDATION_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_foundation_food_csv_2024-10-31.zip"
SR_LEGACY_URL = "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip"

DB_PATH = os.environ.get("DATABASE_PATH", "data/nutrition.db")

# Nutrient IDs we care about (from nutrient.csv)
NUTRIENT_IDS = {
    1008: "calories",       # Energy (kcal)
    1003: "protein_g",      # Protein
    1004: "fat_g",          # Total lipid (fat)
    1005: "carbs_g",        # Carbohydrate, by difference
    1079: "fiber_g",        # Fiber, total dietary
    1063: "sugar_g",        # Sugars, Total NLEA
    2000: "sugar_g",        # Sugars, Total (SR Legacy uses this ID)
    1093: "sodium_mg",      # Sodium, Na
}

# Fallback energy nutrient IDs if 1008 is missing
ENERGY_FALLBACKS = [2047, 2048]  # Atwater General/Specific Factors


def download_and_extract(url: str) -> dict[str, bytes]:
    """Download a zip file and return {filename: contents} for CSVs."""
    print(f"Downloading {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": "calorie-app/0.1"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()

    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith(".csv"):
                basename = os.path.basename(name)
                files[basename] = zf.read(name)
    return files


def read_csv(data: bytes) -> list[dict]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def build_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create tables
    cur.executescript("""
        CREATE TABLE food (
            fdc_id INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            data_type TEXT NOT NULL,
            food_category_id INTEGER
        );

        CREATE TABLE food_nutrient (
            fdc_id INTEGER NOT NULL,
            nutrient_key TEXT NOT NULL,
            amount REAL NOT NULL,
            PRIMARY KEY (fdc_id, nutrient_key)
        );

        CREATE TABLE food_portion (
            id INTEGER PRIMARY KEY,
            fdc_id INTEGER NOT NULL,
            amount REAL,
            measure_unit TEXT,
            portion_description TEXT,
            modifier TEXT,
            gram_weight REAL NOT NULL
        );

        CREATE VIRTUAL TABLE food_fts USING fts5(
            description,
            content='food',
            content_rowid='fdc_id'
        );
    """)

    # Measure unit ID -> name mapping
    measure_units = {
        "1000": "cup", "1001": "tablespoon", "1002": "teaspoon",
        "1009": "fl oz", "1029": "large", "1030": "lb",
        "1036": "medium", "1038": "oz", "1052": "small",
        "1099": "egg", "1049": "serving",
    }

    for label, url in [("Foundation", FOUNDATION_URL), ("SR Legacy", SR_LEGACY_URL)]:
        print(f"\nProcessing {label}...")
        files = download_and_extract(url)

        # Load measure_unit.csv if present to extend our mapping
        if "measure_unit.csv" in files:
            for row in read_csv(files["measure_unit.csv"]):
                uid = row["id"].strip('"')
                if uid not in measure_units:
                    measure_units[uid] = row["name"].strip('"')

        # Import foods — only foundation_food and sr_legacy_food types
        food_rows = read_csv(files["food.csv"])
        valid_types = {"foundation_food", "sr_legacy_food"}
        food_ids = set()

        for row in food_rows:
            dtype = row["data_type"].strip('"')
            if dtype not in valid_types:
                continue
            fdc_id = int(row["fdc_id"].strip('"'))
            desc = row["description"].strip('"')
            cat_id = row.get("food_category_id", "").strip('"')
            cat_id = int(cat_id) if cat_id else None

            cur.execute(
                "INSERT OR IGNORE INTO food VALUES (?, ?, ?, ?)",
                (fdc_id, desc, dtype, cat_id),
            )
            food_ids.add(fdc_id)

        # Import nutrients
        all_nutrient_ids = set(NUTRIENT_IDS.keys()) | set(ENERGY_FALLBACKS)
        nutrient_rows = read_csv(files["food_nutrient.csv"])
        for row in nutrient_rows:
            fdc_id = int(row["fdc_id"].strip('"'))
            if fdc_id not in food_ids:
                continue
            nutrient_id = int(row["nutrient_id"].strip('"'))
            if nutrient_id not in all_nutrient_ids:
                continue
            amount = float(row["amount"].strip('"') or 0)

            # Map to our key name
            if nutrient_id in NUTRIENT_IDS:
                key = NUTRIENT_IDS[nutrient_id]
            elif nutrient_id in ENERGY_FALLBACKS:
                key = "calories"
            else:
                continue

            cur.execute(
                "INSERT OR IGNORE INTO food_nutrient VALUES (?, ?, ?)",
                (fdc_id, key, amount),
            )

        # Import portions
        if "food_portion.csv" in files:
            portion_rows = read_csv(files["food_portion.csv"])
            for row in portion_rows:
                fdc_id = int(row["fdc_id"].strip('"'))
                if fdc_id not in food_ids:
                    continue
                pid = int(row["id"].strip('"'))
                amt_str = row.get("amount", "").strip('"')
                amount = float(amt_str) if amt_str else None
                unit_id = row.get("measure_unit_id", "").strip('"')
                unit_name = measure_units.get(unit_id, "")
                portion_desc = row.get("portion_description", "").strip('"')
                modifier = row.get("modifier", "").strip('"')
                gw = row.get("gram_weight", "").strip('"')
                gram_weight = float(gw) if gw else 0

                if gram_weight <= 0:
                    continue

                cur.execute(
                    "INSERT OR IGNORE INTO food_portion VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pid, fdc_id, amount, unit_name, portion_desc, modifier, gram_weight),
                )

        print(f"  {label}: imported {len(food_ids)} foods")

    # Build FTS index
    print("\nBuilding FTS index...")
    cur.execute("INSERT INTO food_fts(food_fts) VALUES ('rebuild')")

    conn.commit()

    # Stats
    cur.execute("SELECT COUNT(*) FROM food")
    food_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM food_nutrient")
    nutrient_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM food_portion")
    portion_count = cur.fetchone()[0]

    print(f"\nDone! Database: {DB_PATH}")
    print(f"  Foods: {food_count}")
    print(f"  Nutrient entries: {nutrient_count}")
    print(f"  Portion entries: {portion_count}")

    conn.close()


if __name__ == "__main__":
    build_db()
