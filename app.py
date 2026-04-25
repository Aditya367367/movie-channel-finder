import re
import os
from pathlib import Path
import pandas as pd
from rapidfuzz import fuzz
from playwright.sync_api import sync_playwright
from datetime import datetime

# =========================
# 🎬 MOVIES LIST
# =========================
my_movies = [
    "Dangal",
    "3 Idiots",
    "Krrish",
    "Sholay",
    "Surya: The Soldier",
    "Skanda",
    "Deva",
    "Gangaajal",
    "Dabangg 2",
    "Wanted",
    "Stree",
    "Taqdeer"
]

MOVIES_XLSX_PATH = Path("/home/aditya367/Desktop/test/tv-scraper/all_films_one_column.xlsx")

# =========================
# 📺 CHANNELS
# =========================
channels = [
    "Zee-Cinema-HD",
    "Sony-MAX-HD",
    "Star-Gold-HD",
    "Colors-Cineplex-HD"
]

# Known IDs discovered from TVWish URLs.
CHANNEL_ID_HINTS = {
    "Zee-Cinema-HD": "7",
    "Sony-MAX-HD": "31",
    "Star-Gold-HD": "1599",
    "Colors-Cineplex-HD": "1280",
}

# =========================
# 🧹 CLEAN TITLE
# =========================
def clean_title(title):
    return re.sub(r'[^a-z0-9 ]', '', title.lower()).strip()


NOISE_WORDS = {
    "hindi", "english", "tamil", "telugu", "malayalam", "kannada", "bengali",
    "punjabi", "marathi", "bhojpuri", "dubbed", "dual", "audio", "original",
    "uncut", "movie", "full", "film", "hd", "uhd", "sd", "hq", "webrip",
    "hdrip", "brrip", "bluray", "camrip", "dvdrip", "part"
}


def normalize_movie_text(text):
    value = str(text or "").strip()
    if not value:
        return ""

    value = re.sub(r"\b(19|20)\d{2}\b", " ", value)
    value = re.sub(r"\b(480p|720p|1080p|2160p|4k)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[()\[\]{}]", " ", value)
    value = re.sub(r"[:|/\\,_-]+", " ", value)
    value = clean_title(value)

    tokens = [tok for tok in value.split() if tok and tok not in NOISE_WORDS]
    return " ".join(tokens)


def is_valid_movie_title_for_matching(raw_title, normalized_title):
    raw = str(raw_title or "").strip()
    norm = str(normalized_title or "").strip()
    if not raw or not norm:
        return False

    # Reject numeric or very short junk entries like "2", "3", etc.
    if re.fullmatch(r"\d+", raw) or re.fullmatch(r"\d+", norm):
        return False

    tokens = norm.split()
    if len(tokens) == 1 and len(tokens[0]) < 5:
        return False

    if len(norm) < 5:
        return False

    return True


def load_movies_from_excel(path):
    if not path.exists():
        return my_movies

    try:
        df = pd.read_excel(path, dtype=str)
    except Exception:
        return my_movies

    if df.empty:
        return my_movies

    first_col = df.columns[0]
    names = []

    for raw in df[first_col].dropna().tolist():
        title = str(raw).strip()
        if not title:
            continue
        names.append(title)

    return names or my_movies


def build_movie_pairs(movie_list):
    pairs = []
    seen_norm = set()

    for movie in movie_list:
        norm = normalize_movie_text(movie)
        if not is_valid_movie_title_for_matching(movie, norm):
            continue
        if norm in seen_norm:
            continue
        seen_norm.add(norm)
        pairs.append((movie, norm))

    return pairs


def get_show_variants(raw_title):
    raw = str(raw_title or "").strip()
    variants = set()

    base = normalize_movie_text(raw)
    if base:
        variants.add(base)

    # Handle titles like "Skanda: The Attacker" -> "skanda"
    for sep in (":", "-", "|"):
        if sep in raw:
            left = normalize_movie_text(raw.split(sep, 1)[0])
            if left:
                variants.add(left)

    return sorted(variants, key=len, reverse=True)

# =========================
# 📺 NORMALIZE CHANNEL NAME
# =========================
def normalize_channel(channel):
    channel = channel.replace("-HD", "")
    return channel.replace("-", " ").title()


def extract_channel_id(url):
    match = re.search(r"/Channels/[^/]+/(\d+)", url)
    if match:
        return match.group(1)

    match = re.search(r"/DayJson/(\d+)", url)
    if match:
        return match.group(1)

    return None


def extract_channel_id_from_text(text):
    if not text:
        return None

    match = re.search(r"/Api/ChannelScheduleApi/DayJson/(\d+)", text, re.IGNORECASE)
    if match:
        return match.group(1)

    match = re.search(r"/Channels/[^/]+/(\d+)", text, re.IGNORECASE)
    if match:
        return match.group(1)

    return None

# =========================
# 📅 GET TODAY (Sat, Sun)
# =========================
def get_today():
    return datetime.now().strftime("%a")


def _pick_first(d, keys):
    for key in keys:
        value = d.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _extract_items(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "result", "items", "programs"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def _normalize_time_text(time_text):
    value = (time_text or "").strip()
    if not value:
        return ""

    for fmt in ("%a, %I:%M %p", "%I:%M %p"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%I:%M %p")
        except Exception:
            continue

    return value.lower()


def _time_sort_key(show):
    time_text = _normalize_time_text(show.get("time", ""))
    try:
        dt = datetime.strptime(time_text, "%I:%M %p")
        return (show.get("channel", ""), dt.hour, dt.minute, show.get("title", ""))
    except Exception:
        return (show.get("channel", ""), 99, 99, show.get("title", ""))


# =========================
# 📡 FETCH ALL DATA
# =========================
def fetch_all():
    all_shows = []
    today = get_today()
    debug = os.getenv("TVWISH_DEBUG", "").strip() == "1"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        for channel in channels:
            channel_id = CHANNEL_ID_HINTS.get(channel)
            shows = []
            seen = set()
            page = context.new_page()

            print(f"\n📺 Fetching {channel}...")

            if not channel_id:
                if debug:
                    print("   [debug] no channel id hint")
                print("   → 0 today shows")
                page.close()
                continue

            def add_items(items, is_upcoming_json=False):
                for item in items:
                    if not isinstance(item, dict):
                        continue

                    title = _pick_first(
                        item,
                        ("spn", "title", "pn", "programName", "name")
                    )
                    time = _pick_first(
                        item,
                        ("stf", "startTime", "start_time", "start", "tm", "time")
                    )

                    if not title:
                        continue

                    if "show" in title.lower():
                        continue

                    if is_upcoming_json and time:
                        if not (time.startswith(today) or today.lower() in time.lower()):
                            continue

                    normalized_time = _normalize_time_text(time)
                    key = (title.lower(), normalized_time)
                    if key in seen:
                        continue
                    seen.add(key)

                    shows.append({
                        "title": title,
                        "channel": normalize_channel(channel),
                        "time": time
                    })

            def handle_response(response):
                response_url = response.url.lower()
                is_upcoming_json = "upcomingjson" in response_url
                is_day_json = "/api/channelscheduleapi/dayjson/" in response_url

                if not (is_upcoming_json or is_day_json):
                    return

                if f"/{channel_id}/" not in response_url and not response_url.endswith(f"/{channel_id}"):
                    return

                try:
                    data = response.json()
                    items = _extract_items(data)
                    if debug:
                        print(f"   [debug] API hit: {response.url}")
                        print(f"   [debug] payload items: {len(items)}")
                    add_items(items, is_upcoming_json=is_upcoming_json)
                except Exception as e:
                    if debug:
                        print(f"   [debug] parse failed: {response.url} -> {e}")

            page.on("response", handle_response)

            urls = [
                f"https://www.tvwish.com/IN/Channels/{channel}/{channel_id}",
                f"https://www.tvwish.com/IN/Channels/{channel}/{channel_id}/Schedule/Today",
            ]

            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=12000)
                    page.wait_for_timeout(800)
                except Exception as e:
                    if debug:
                        print(f"   [debug] navigation failed: {url} -> {e}")

            print(f"   → {len(shows)} today shows")
            all_shows.extend(shows)
            page.close()

        browser.close()

    return sorted(all_shows, key=_time_sort_key)

# =========================
# 🔍 MATCH MOVIES
# =========================
def match_movies(tv_data):
    matches = []
    seen_matches = set()
    movie_pairs = build_movie_pairs(my_movies)

    for show in tv_data:
        show_variants = get_show_variants(show["title"])
        if not show_variants:
            continue

        for movie, movie_clean in movie_pairs:
            if not movie_clean:
                continue

            movie_tokens = set(movie_clean.split())
            if not movie_tokens:
                continue

            matched = False
            for show_clean in show_variants:
                show_tokens = set(show_clean.split())
                if not show_tokens:
                    continue

                score = fuzz.token_set_ratio(movie_clean, show_clean)
                if score < 90:
                    continue

                overlap = movie_tokens.intersection(show_tokens)
                if not overlap:
                    continue

                # Single-word movie names must match a show variant exactly.
                if len(movie_tokens) == 1:
                    if movie_clean != show_clean:
                        continue
                elif len(show_tokens) == 1:
                    # Prevent long-title subset mismatches (e.g. "stree janma..." vs "stree").
                    continue
                else:
                    token_ratio = min(len(overlap) / len(movie_tokens), len(overlap) / len(show_tokens))
                    if token_ratio < 0.6:
                        continue

                matched = True
                break

            if not matched:
                continue

            key = (movie.lower(), show["channel"].lower(), _normalize_time_text(show["time"]))
            if key in seen_matches:
                continue
            seen_matches.add(key)

            matches.append({
                "movie": movie,
                "channel": show["channel"],
                "time": show["time"]
            })

    return matches

# =========================
# 🚀 MAIN
# =========================
if __name__ == "__main__":
    my_movies = load_movies_from_excel(MOVIES_XLSX_PATH)
    usable_movies = build_movie_pairs(my_movies)
    print(
        f"🎬 Loaded {len(my_movies)} films from {MOVIES_XLSX_PATH.name} "
        f"(usable for matching: {len(usable_movies)})"
    )
    print("📡 Fetching TODAY TV schedule...\n")

    tv_data = fetch_all()

    # 🔥 DEBUG: show all today shows
    print("\n📺 TODAY SHOWS:\n")
    for show in tv_data:
        print(f"{show['channel']} | {show['time']} | {show['title']}")

    print("\n🔍 Matching...\n")
    results = match_movies(tv_data)

    print("\n🎬 MATCHES:\n")

    if not results:
        print("❌ No matches")
    else:
        for r in results:
            print(f"{r['movie']} → {r['channel']} | {r['time']}")
