#!/usr/bin/env python3
"""
lead_finder — ищет и квалифицирует малый/средний бизнес под услуги автоматизации
              (сайты, приём оплаты, боты записи, TG/MAX-боты).

Источник данных — OpenStreetMap (Overpass API): бесплатно, без ключа, по России,
с сайтами и телефонами прямо в данных. Никаких поисковиков и скрейпинга.

Примеры:
  # все ниши по городу:
  python3 lead_finder.py --city "Казань" --out leads.csv

  # только выбранные ниши:
  python3 lead_finder.py --city "Казань" --niches автосервис "салон красоты" --out leads.csv

  # посмотреть список доступных ниш:
  python3 lead_finder.py --list-niches

  # квалифицировать готовый список сайтов:
  python3 lead_finder.py --urls site1.ru site2.ru --out leads.csv
"""

import argparse
import csv
import re
import sys
import time
from datetime import datetime

import requests

UA = "lead-finder/1.0 (business research)"
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124 Safari/537.36")
THIS_YEAR = datetime.now().year

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# ---------- ниша (человекочитаемо) -> OSM-фильтры (key, value) ----------
NICHES = {
    # авто
    "автосервис":            [("shop", "car_repair")],
    "шиномонтаж":            [("shop", "tyres")],
    "автозапчасти":          [("shop", "car_parts")],
    "автомойка":             [("amenity", "car_wash")],
    "автошкола":             [("amenity", "driving_school")],
    "автосалон":             [("shop", "car")],
    # красота / здоровье
    "парикмахерская":        [("shop", "hairdresser")],
    "салон красоты":         [("shop", "beauty")],
    "spa/массаж":            [("leisure", "spa"), ("shop", "massage")],
    "тату-студия":           [("shop", "tattoo")],
    "стоматология":          [("amenity", "dentist"), ("healthcare", "dentist")],
    "медцентр/клиника":      [("amenity", "clinic"), ("amenity", "doctors")],
    "ветклиника":            [("amenity", "veterinary")],
    "оптика":                [("shop", "optician")],
    "аптека":                [("amenity", "pharmacy")],
    # спорт
    "фитнес-центр":          [("leisure", "fitness_centre")],
    "спортклуб":             [("leisure", "sports_centre")],
    "спорттовары":           [("shop", "sports")],
    "велосипеды":            [("shop", "bicycle")],
    # еда
    "ресторан":              [("amenity", "restaurant")],
    "кафе":                  [("amenity", "cafe")],
    "фастфуд":               [("amenity", "fast_food")],
    "бар/паб":               [("amenity", "bar"), ("amenity", "pub")],
    "пекарня":               [("shop", "bakery")],
    "кондитерская":          [("shop", "confectionery")],
    # ритейл
    "цветы":                 [("shop", "florist")],
    "одежда":                [("shop", "clothes")],
    "обувь":                 [("shop", "shoes")],
    "ювелирка":              [("shop", "jewelry")],
    "подарки":               [("shop", "gift")],
    "мебель":                [("shop", "furniture")],
    "электроника":           [("shop", "electronics")],
    "компьютеры":            [("shop", "computer")],
    "телефоны":              [("shop", "mobile_phone")],
    "зоомагазин":            [("shop", "pet")],
    # услуги
    "ателье/пошив":          [("shop", "tailor"), ("craft", "tailor")],
    "химчистка/прачечная":   [("shop", "dry_cleaning"), ("shop", "laundry")],
    "турагентство":          [("shop", "travel_agency")],
    "фотостудия":            [("shop", "photo"), ("craft", "photographer")],
    "языковая школа":        [("amenity", "language_school")],
    "отель/гостиница":       [("tourism", "hotel"), ("tourism", "guest_house"), ("tourism", "hostel")],
    "юристы":                [("office", "lawyer")],
    "бухгалтерия":           [("office", "accountant"), ("office", "tax_advisor")],
    "недвижимость":          [("office", "estate_agent")],
}

# ---------- платформы: маркер в HTML -> название ----------
PLATFORMS = {
    "Tilda":      ["tildacdn", "tilda.cc", "tilda.ws", "data-tilda"],
    "WordPress":  ["wp-content", "wp-json", "wp-includes"],
    "Bitrix":     ["/bitrix/", "bx-core", "bitrix24"],
    "Wix":        ["wix.com", "_wixcssbundle", "wixstatic"],
    "Webflow":    ["webflow.io", ".webflow."],
    "Shopify":    ["cdn.shopify", "myshopify"],
    "InSales":    ["insales", "static-cdn.insales"],
    "Joomla":     ["/components/com_", "joomla"],
    "Ucoz":       ["ucoz", "u-coz"],
}
PAY_MARKERS = [
    "yookassa", "юkassa", "юкасса", "robokassa", "робокасса", "cloudpayments",
    "stripe", "paypal", "tinkoff", "тинькофф", "сбербанк", "эквайринг",
    "оплатить онлайн", "оплата картой", "/cart", "корзина", "add-to-cart",
]
BOOKING_MARKERS = ["онлайн-запис", "записаться онлайн", "yclients", "забронир", "бронирование"]
MESSENGER_MARKERS = ["t.me/", "tg://", "telegram", "wa.me", "whatsapp", "max.ru/",
                     "bothelp", "viber", "онлайн-чат", "jivosite", "jivo"]


# ============================================================ DISCOVERY (OSM)

def geocode_bbox(city: str):
    """Город -> bounding box (south, west, north, east) через Nominatim."""
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{city}, Россия", "format": "json", "limit": 1},
        headers={"User-Agent": UA}, timeout=20,
    )
    data = r.json()
    if not data:
        return None
    bb = data[0]["boundingbox"]   # [south_lat, north_lat, west_lon, east_lon]
    return float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3])


def build_overpass_query(niches, bbox):
    south, west, north, east = bbox
    box = f"({south},{west},{north},{east})"
    parts = []
    for niche in niches:
        for k, v in NICHES[niche]:
            parts.append(f'node["{k}"="{v}"]{box};')
            parts.append(f'way["{k}"="{v}"]{box};')
    body = "\n".join(parts)
    return f"[out:json][timeout:90];\n(\n{body}\n);\nout center tags;"


def classify_niche(tags):
    for niche, filters in NICHES.items():
        for k, v in filters:
            if tags.get(k) == v:
                return niche
    return ""


def discover_osm(niches, city, limit=60):
    bbox = geocode_bbox(city)
    if not bbox:
        print(f"Не удалось определить город '{city}'", file=sys.stderr)
        return []
    query = build_overpass_query(niches, bbox)
    data = None
    for ep in OVERPASS_MIRRORS:
        for attempt in range(3):
            try:
                r = requests.post(ep, data={"data": query},
                                  headers={"User-Agent": UA}, timeout=120)
                if r.status_code == 200:
                    data = r.json()
                    break
                if r.status_code in (429, 504):       # перегружен — подождём и повторим
                    wait = 15 * (attempt + 1)
                    print(f"  {ep}: HTTP {r.status_code}, жду {wait}с...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"  {ep}: HTTP {r.status_code}", file=sys.stderr)
                break
            except Exception as e:
                print(f"  {ep}: {e}", file=sys.stderr)
                break
        if data:
            break
    if not data:
        print("Overpass недоступен (рейт-лимит/перегрузка). Попробуй через минуту "
              "или меньше ниш за раз.", file=sys.stderr)
        return []

    out = []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        name = t.get("name") or t.get("name:ru") or ""
        if not name:
            continue
        site = t.get("website") or t.get("contact:website") or t.get("url") or ""
        phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or ""
        street = t.get("addr:street", "")
        house = t.get("addr:housenumber", "")
        addr = (street + " " + house).strip()
        out.append({
            "name": name, "url": site.strip(), "phone": phone.strip(),
            "address": addr, "niche": classify_niche(t),
        })

    # сначала те, кого реально можно обработать/достать: есть сайт -> есть телефон -> остальные
    out.sort(key=lambda b: (b["url"] == "", b["phone"] == ""))
    return out[:limit]


# ============================================================ QUALIFY

def normalize(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def fetch(url):
    try:
        return requests.get(normalize(url), headers={"User-Agent": BROWSER_UA},
                            timeout=12, allow_redirects=True)
    except Exception as e:
        return e


def detect_platform(low):
    for name, markers in PLATFORMS.items():
        if any(m in low for m in markers):
            return name
    return "самопис/неизвестно"


def has_any(low, markers):
    return any(m in low for m in markers)


def find_copyright_year(html):
    years = re.findall(r"©\s*(?:\d{4}\s*[—\-–]\s*)?(\d{4})", html)
    years += re.findall(r"(?:copyright|все права)[^0-9]{0,20}(\d{4})", html, re.I)
    yrs = [int(y) for y in years if 2000 <= int(y) <= THIS_YEAR]
    return max(yrs) if yrs else None


def qualify(url):
    res = {"url": url, "platform": "", "mobile": False, "has_pay": False,
           "has_booking": False, "has_messenger": False, "copyright_year": "",
           "score": 0, "products": "", "angle": "", "note": ""}
    r = fetch(url)
    if isinstance(r, Exception):
        res.update(platform="битый сайт", score=85,
                   products="новый сайт + бот", note=f"не открылся: {type(r).__name__}",
                   angle="сайт не открывается — повод предложить новый")
        return res

    low = (r.text or "").lower()
    res["https"] = r.url.startswith("https://")
    res["platform"] = detect_platform(low)
    res["mobile"] = ('name="viewport"' in low) or ("name='viewport'" in low)
    res["has_pay"] = has_any(low, PAY_MARKERS)
    res["has_booking"] = has_any(low, BOOKING_MARKERS)
    res["has_messenger"] = has_any(low, MESSENGER_MARKERS)
    yr = find_copyright_year(r.text or "")
    res["copyright_year"] = yr or ""

    score, gaps, products = 0, [], []
    if not res["has_pay"]:
        score += 30; gaps.append("нет онлайн-оплаты"); products.append("сайт с приёмом оплаты")
    if not res["has_booking"]:
        score += 25; gaps.append("нет онлайн-записи"); products.append("бот/виджет записи")
    if not res["has_messenger"]:
        score += 20; gaps.append("нет связи через мессенджер"); products.append("TG/MAX-бот")
    if res["platform"] in ("Tilda", "Ucoz", "Wix"):
        score += 15; gaps.append(f"сайт на {res['platform']}"); products.append("замена конструктора")
    if not res["mobile"]:
        score += 15; gaps.append("нет мобильной версии")
    if not res.get("https"):
        score += 10; gaps.append("нет HTTPS")
    if yr and (THIS_YEAR - yr) >= 2:
        score += 10; gaps.append(f"не обновлялся с {yr}")

    res["score"] = min(score, 100)
    res["products"] = "; ".join(dict.fromkeys(products))
    res["angle"] = ("У них " + ", ".join(gaps[:3]) + " → " + (res["products"] or "автоматизация")) \
        if gaps else "Всё закрыто — низкий приоритет."
    return res


# ============================================================ CSV / ИМЯ ФАЙЛА

CSV_FIELDS = ["score", "niche", "name", "phone", "url", "address", "platform",
              "has_pay", "has_booking", "has_messenger", "mobile",
              "copyright_year", "products", "angle", "note"]


def slugify(s: str) -> str:
    """Строка -> безопасный кусок имени файла (кириллицу оставляем)."""
    s = (s or "").lower().strip()
    s = re.sub(r'[\\/:*?"<>|]+', "-", s)   # запрещённые в имени файла символы
    s = re.sub(r"\s+", "-", s)
    return s.strip("-") or "leads"


def make_filename(city, niches):
    """Имя CSV из комбинации ниша + город."""
    city_part = slugify(city) if city else "сайты"
    total = len(NICHES)
    if not niches or len(niches) >= total:
        niche_part = "все-ниши"
    elif len(niches) == 1:
        niche_part = slugify(niches[0])
    else:
        niche_part = f"{slugify(niches[0])}-и-ещё-{len(niches) - 1}"
    return f"{city_part}__{niche_part}.csv"


def write_csv(rows, out):
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ============================================================ ЯДРО

def run_search(city=None, niches=None, urls=None, limit=60, out=None, progress=None):
    """Поиск + квалификация + запись CSV. progress(msg) — колбэк для лога.

    Возвращает (rows, out_path).
    """
    log = progress or print

    if city:
        niches = niches or list(NICHES.keys())
        niches = [n for n in niches if n in NICHES]
        log(f"Ищу {len(niches)} ниш в '{city}' через OpenStreetMap...")
        biz = discover_osm(niches, city, limit)
        ws = sum(1 for b in biz if b["url"])
        ph = sum(1 for b in biz if b["phone"])
        log(f"Взял {len(biz)} организаций | с сайтом: {ws} | с телефоном: {ph}")
    elif urls:
        biz = [{"name": "", "url": u, "phone": "", "address": "", "niche": ""} for u in urls]
    else:
        raise ValueError("дай city (+ опц. niches) или urls")

    if out is None:
        out = make_filename(city, niches) if city else "сайты.csv"

    rows, seen = [], set()
    for b in biz:
        url = b["url"]
        if url:
            host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
            if host in seen:
                continue
            seen.add(host)
            log(f"  проверяю {url} ...")
            q = qualify(url)
        else:
            reachable = bool(b["phone"])
            q = {"url": "", "platform": "сайта нет", "mobile": False,
                 "has_pay": False, "has_booking": False, "has_messenger": False,
                 "copyright_year": "", "score": 90 if reachable else 50,
                 "products": "сайт с нуля + бот + приём оплаты",
                 "angle": "Сайта нет — заходить с нуля: сайт + бот"
                          + ("" if reachable else " (нет телефона — сложно достучаться)"),
                 "note": "сайт не найден"}
            log(f"  [нет сайта] {b['name'][:40]}")
        q.update(name=b["name"], phone=b["phone"], address=b["address"], niche=b["niche"])
        rows.append(q)

    rows.sort(key=lambda x: x["score"], reverse=True)
    write_csv(rows, out)
    log(f"Готово -> {out}  (всего лидов: {len(rows)})")
    return rows, out


# ============================================================ MAIN (CLI)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", help="город, напр. 'Казань'")
    ap.add_argument("--niches", nargs="*", help="ниши (по умолчанию — все)")
    ap.add_argument("--urls", nargs="*", help="готовый список сайтов")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--list-niches", action="store_true")
    ap.add_argument("--out", default=None, help="имя CSV (по умолчанию — ниша+город)")
    args = ap.parse_args()

    if args.list_niches:
        print("Доступные ниши:")
        for n in NICHES:
            print("  -", n)
        return

    if args.city:
        unknown = [n for n in (args.niches or []) if n not in NICHES]
        if unknown:
            print(f"Неизвестные ниши: {unknown}. Список: --list-niches", file=sys.stderr)
    elif not args.urls:
        ap.error("дай --city (+ опц. --niches) или --urls")

    rows, out = run_search(city=args.city, niches=args.niches, urls=args.urls,
                           limit=args.limit, out=args.out)

    print(f"\n{'СКОР':>4}  {'НИША':<16} {'ТЕЛЕФОН':<18} {'САЙТ'}")
    print("-" * 78)
    for r in rows[:25]:
        print(f"{r['score']:>4}  {r['niche'][:15]:<16} {(r['phone'] or '-')[:17]:<18} {r['url'] or '(нет сайта) ' + r['name'][:30]}")


if __name__ == "__main__":
    main()