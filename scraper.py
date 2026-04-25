import requests
from rapidfuzz import fuzz
import re

# =========================
# MOVIE LIST
# =========================
my_movies = [
    "Dangal",
    "3 Idiots",
    "Krrish",
    "Sholay"
]

# =========================
# CLEAN FUNCTION
# =========================
def clean_title(title):
    title = title.lower()
    title = re.sub(r'[^a-z0-9 ]', '', title)
    title = re.sub(r'\s+', ' ', title).strip()
    return title

# =========================
# FETCH TV DATA (API BASED 🔥)
# =========================
def fetch_tv_schedule():
    shows = []

    # ⚠️ Ye API change ho sakti hai future me
    url = "https://tm.tapi.videoready.tv/content-detail/pub/api/v2/channels"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()

        # 🔥 Channels ke andar programs hote hain
        for channel in data.get("data", []):
            channel_name = channel.get("channel_name", "Unknown")

            for program in channel.get("programs", []):
                title = program.get("title", "")
                start_time = program.get("start_time", "")

                if title:
                    shows.append({
                        "title": title,
                        "channel": channel_name,
                        "time": start_time
                    })

        print(f"📺 Shows fetched: {len(shows)}")
        return shows

    except Exception as e:
        print("❌ API Error:", e)
        return []

# =========================
# MATCH MOVIES
# =========================
def match_movies(tv_data):
    matches = []

    for show in tv_data:
        show_clean = clean_title(show["title"])

        for movie in my_movies:
            movie_clean = clean_title(movie)

            score = fuzz.ratio(movie_clean, show_clean)

            if score > 85:
                matches.append({
                    "movie": movie,
                    "found_as": show["title"],
                    "channel": show["channel"],
                    "time": show["time"],
                    "score": score
                })

    return matches

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    print("📡 Fetching TV schedule...")
    tv_data = fetch_tv_schedule()

    print("🔍 Matching movies...")
    results = match_movies(tv_data)

    print("\n🎬 MATCHES:\n")

    if not results:
        print("❌ No matches found (try different movies)")
    else:
        for r in results:
            print(r)







            https://www.tvwish.com/Api/ChannelScheduleApi/DayJson/1280










            import re
import os
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

        for channel in channels:
            page = browser.new_page()
            shows = []
            channel_id = None
            seen = set()

            print(f"\n📺 Fetching {channel}...")

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

                    # ❌ skip non-movie
                    if "show" in title.lower():
                        continue

                    # UpcomingJson may contain other days, so keep only today-ish rows.
                    if is_upcoming_json:
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
                response_url = response.url
                response_url_l = response_url.lower()

                is_upcoming_json = "upcomingjson" in response_url_l
                is_day_json = "/api/channelscheduleapi/dayjson" in response_url_l

                if not (is_upcoming_json or is_day_json):
                    return

                if is_upcoming_json and channel.lower() not in response_url_l:
                    return

                try:
                    data = response.json()
                    items = _extract_items(data)
                    if debug:
                        print(f"   [debug] API hit: {response_url}")
                        print(f"   [debug] payload items: {len(items)}")
                    add_items(items, is_upcoming_json=is_upcoming_json)

                except:
                    pass

            page.on("response", handle_response)
            hinted_id = CHANNEL_ID_HINTS.get(channel)
            candidate_urls = []
            if hinted_id:
                candidate_urls.append(f"https://www.tvwish.com/IN/Channels/{channel}/{hinted_id}")
                candidate_urls.append(f"https://www.tvwish.com/IN/Channels/{channel}/{hinted_id}/Schedule/Today")
            candidate_urls.append(f"https://www.tvwish.com/IN/Channels/{channel}")
            candidate_urls.append(f"https://www.tvwish.com/IN/Channels/{channel}/Schedule/Today")
            # Keep order but avoid duplicate visits.
            candidate_urls = list(dict.fromkeys(candidate_urls))

            for url in candidate_urls:
                try:
                    page.goto(url)
                    page.wait_for_load_state("networkidle")

                    # Try to detect channel id from whichever URL/content resolves.
                    if not channel_id:
                        channel_id = extract_channel_id(page.url)
                    if not channel_id:
                        channel_id = extract_channel_id_from_text(page.content())

                    if debug:
                        print(f"   [debug] page url: {page.url}")
                        print(f"   [debug] channel id: {channel_id}")

                    # Scroll to trigger lazy API calls (UpcomingJson / DayJson).
                    for _ in range(3):
                        page.mouse.wheel(0, 2500)
                        page.wait_for_timeout(700)

                    page.wait_for_timeout(1000)
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

    for show in tv_data:
        show_clean = clean_title(show["title"])

        for movie in my_movies:
            movie_clean = clean_title(movie)

            if fuzz.token_set_ratio(movie_clean, show_clean) > 85:
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
































import re
import os
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

    for show in tv_data:
        show_clean = clean_title(show["title"])

        for movie in my_movies:
            movie_clean = clean_title(movie)

            if fuzz.token_set_ratio(movie_clean, show_clean) > 85:
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
