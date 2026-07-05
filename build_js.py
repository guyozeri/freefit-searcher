#!/usr/bin/env python3
"""Build the JS data files for the search page, with city name normalization."""

import json
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"

# Explicit merges: variant -> canonical name
CITY_ALIASES = {
    "תל-אביב": "תל אביב",
    "תלאביב": "תל אביב",
    "ת\"א": "תל אביב",
    "ת\u05f4א": "תל אביב",
    "תל אביב יפו": "תל אביב",
    "תל אביב-יפו": "תל אביב",
    "תל אביב -יפו": "תל אביב",
    "תל אביב, יפו": "תל אביב",
    "תל אביב (מלון קראון פלאזה)": "תל אביב",
    "מלון דן פנורמה": "תל אביב",
    "אום-אל-פחם": "אום אל-פחם",
    "הקניון הגדול פתח תקווה": "פתח תקווה",
    "הרצליה (חניה ברחוב הדסה 15)": "הרצליה",
    "זכרון יעקב סטודיו עדנה": "זכרון יעקב",
    "חיפה (קריית חיים )": "חיפה",
    "יבנה קניון G": "יבנה",
    "מאחורי קניון גבעתיים": "גבעתיים",
    "קניון צים אורבן סנטר": "חיפה",
    "קרית אתא (קניון כפיר)": "קריית אתא",
    "רמת גן (קניון אילון)": "רמת גן",
    "ג'וליס": "גוליס",
    "דליית אל כרמל": "דלית אל כרמל",
    "הוד השרון.": "הוד השרון",
    "הרמן צבי שפירא 45": "פתח תקווה",
    "הזית 61": "חצב",
    "ראשון לציון כניסה 3": "ראשון לציון",
    "מודיעין קומה 1 במעלית": "מודיעין",
    "מכבים קומה 2": "מכבים",
    "מורד הגיא 100": "כרמיאל",
    "דרום": "",
    "יבנה – חניון פארק הנחל": "יבנה",
    "מודיעין – מרכז מליבו סנטר": "מודיעין",
    # Spelling variants
    "טירת כרמל": "טירת הכרמל",
    "יקנעם": "יוקנעם",
    "יקנעם עילית": "יוקנעם עילית",
    "יקנעם עלית": "יוקנעם עילית",
    "אשקלן": "אשקלון",
    "פתח תקוה": "פתח תקווה",
    "פתח תקווה אם המושבות": "פתח תקווה",
    "ראשל\"צ": "ראשון לציון",
    "ראשל\u05f4צ": "ראשון לציון",
    # קריית / קרית
    "קרית אונו": "קריית אונו",
    "קרית אתא": "קריית אתא",
    "קרית ביאליק": "קריית ביאליק",
    "קרית גת": "קריית גת",
    "קרית חיים": "קריית חיים",
    "קרית טבעון": "קריית טבעון",
    "קרית ים": "קריית ים",
    "קרית מוצקין": "קריית מוצקין",
    "קרית מלאכי": "קריית מלאכי",
    "קרית שמונה": "קריית שמונה",
    # Compound city names
    "יהוד מונוסון": "יהוד",
    "נווה מונוסון יהוד": "יהוד",
    "מודיעין מכבים רעות": "מודיעין",
    "מודיעין עילית": "מודיעין",
    "מודיעין עלית": "מודיעין",
    "מכבים רעות": "מודיעין",
    "בנימינה גבעת עדה": "בנימינה",
    "פרדס חנה כרכור": "פרדס חנה",
    "פרדס חנה אור עקיבא": "פרדס חנה",
    "מעלות תרשיחא": "מעלות",
    "קדימה צורן": "קדימה",
    "רחובות החדשה": "רחובות",
    "חולון ראשון לציון": "חולון",
    "כפר סבא הירוקה": "כפר סבא",
    "הרצליה הירוקה": "הרצליה",
    "רעננה כפר סבא": "רעננה",
    "אזור התעשייה לב הארץ": "שוהם",
    "מרכז שוסטר רמת אביב": "תל אביב",
    "ביתר עילית": "ביתר",
    "גני הרצליה": "הרצליה",
    "רמה\"ש": "רמת השרון",
    "רמה\u05f4ש": "רמת השרון",
}

# Patterns that indicate the "city" is not actually a city (floor, entrance, description, etc.)
JUNK_PATTERNS = [
    r'^קומה\b',
    r'^קומת\b',
    r'^כניסה\b',
    r'ממתחילים',
    r'מתקדמים',
    r'שיעור',
]


def normalize_city(raw_city: str) -> str:
    raw_city = raw_city.strip()
    # Strip trailing punctuation
    raw_city = raw_city.rstrip('.')
    # Strip leading house numbers (e.g. "11 פתח תקווה" -> "פתח תקווה")
    raw_city = re.sub(r'^\d+\s+', '', raw_city)
    if raw_city in CITY_ALIASES:
        return CITY_ALIASES[raw_city]
    # Catch any remaining "תל אביב" variants
    if re.search(r'תל[\s\-]?אביב', raw_city) and raw_city != "תל אביב":
        return "תל אביב"
    # Discard junk entries (floors, entrances, description fragments)
    for pattern in JUNK_PATTERNS:
        if re.search(pattern, raw_city):
            return ""
    # Discard entries that end with a number (likely street address, not city)
    if re.search(r'\d+$', raw_city):
        return ""
    return raw_city


def main():
    with open(OUTPUT_DIR / "clubs_detailed.json", encoding="utf-8") as f:
        clubs = json.load(f)

    slim = []
    cities_set = set()
    for c in clubs:
        addr = c.get("address", "")
        city = ""
        if "," in addr:
            city = normalize_city(addr.split(",")[-1].strip())
            if city:
                cities_set.add(city)
        entry = {
            "id": c["id"],
            "t": c["title"],
            "a": addr,
            "c": city,
            "d": c.get("description", ""),
        }
        # Booking constants, when the data came from the API (fetch_clubs.py).
        if c.get("terminal_id"):
            entry["tid"] = c["terminal_id"]
            entry["bt"] = c.get("bin_type", 2)
        slim.append(entry)

    cities_sorted = sorted(cities_set)

    with open(OUTPUT_DIR / "_clubs_data.js", "w", encoding="utf-8") as f:
        f.write("const CLUBS = ")
        json.dump(slim, f, ensure_ascii=False)
        f.write(";\nconst CITIES = ")
        json.dump(cities_sorted, f, ensure_ascii=False)
        f.write(";\n")

    print(f"Wrote {len(slim)} clubs, {len(cities_sorted)} cities")

    # Also rebuild coords JS
    try:
        with open(OUTPUT_DIR / "city_coords.json", encoding="utf-8") as f:
            raw_city = json.load(f)
    except FileNotFoundError:
        raw_city = {}
    try:
        with open(OUTPUT_DIR / "address_coords.json", encoding="utf-8") as f:
            raw_addr = json.load(f)
    except FileNotFoundError:
        raw_addr = {}

    city_coords = {}
    for city, data in raw_city.items():
        if data:
            canonical = normalize_city(city)
            city_coords[canonical] = [round(data["lat"], 5), round(data["lng"], 5)]

    clean_addr = {k: v for k, v in raw_addr.items() if v}

    with open(OUTPUT_DIR / "_city_coords.js", "w", encoding="utf-8") as f:
        f.write("const CITY_COORDS = ")
        json.dump(city_coords, f, ensure_ascii=False)
        f.write(";\nconst ADDR_COORDS = ")
        json.dump(clean_addr, f, ensure_ascii=False)
        f.write(";\n")

    print(f"Wrote {len(city_coords)} city coords + {len(clean_addr)} address coords")


if __name__ == "__main__":
    main()
