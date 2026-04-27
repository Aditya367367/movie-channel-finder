import re
import os
import json
from pathlib import Path
import pandas as pd
import requests
from rapidfuzz import fuzz
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent

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
    "Dabangg",
    "Jaat",
    "Wanted",
    "Radhe",
    "Stree",
    "Taqdeer"
]

MOVIES_XLSX_PATH = BASE_DIR / "all_films_one_column.xlsx"
CHANNELS_XLSX_PATH = BASE_DIR / "channel names.xlsx"
CHANNELS_WITH_IDS_XLSX_PATH = BASE_DIR / "channels.xlsx"
CHANNEL_ID_CACHE_PATH = BASE_DIR / "channel_id_cache.json"

# =========================
# 📺 CHANNELS
# =========================
DEFAULT_CHANNELS = [
    "Zee-Cinema-HD",
    # "Sony-MAX-HD",
    # "Star-Gold-HD",
    # "Colors-Cineplex-HD"
]

channels = DEFAULT_CHANNELS[:]

# Known IDs discovered from TVWish URLs.
CHANNEL_ID_HINTS = {
    "Zee-Cinema-HD": "15",
    "Zee-Cinema": "15",
    "Sony-MAX-HD": "31",
    "Star-Gold-HD": "1599",
    "Colors-Cineplex-HD": "1280",
    "Star-Plus-HD": "1589",
}

CHANNEL_ID_HINTS_LOWER = {k.lower(): v for k, v in CHANNEL_ID_HINTS.items()}
HD_TAG_PATTERN = re.compile(r"(?i)[\s\-_]*(?:uhd|fhd|hd)(?=\b|\d)")
DAY_ORDER = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

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
    # Keep genuine short single-word titles like "Jaat" (4 chars),
    # while still rejecting very short noise.
    if len(tokens) == 1 and len(tokens[0]) < 4:
        return False

    if len(norm) < 4:
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


def load_channels_from_excel(path):
    if not path.exists():
        return DEFAULT_CHANNELS[:]

    try:
        df = pd.read_excel(path, dtype=str)
    except Exception:
        return DEFAULT_CHANNELS[:]

    if df.empty:
        return DEFAULT_CHANNELS[:]

    first_col = df.columns[0]
    seen = set()
    loaded_channels = []

    for raw in df[first_col].dropna().tolist():
        title = str(raw).strip()
        if not title:
            continue

        dedupe_key = _channel_dedupe_key(title)
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        loaded_channels.append(title)

    return loaded_channels or DEFAULT_CHANNELS[:]


def _channel_has_hd_tag(name):
    return bool(re.search(r"(?i)\b(uhd|fhd|hd)\b", str(name or "")))


def _extract_slug_from_channel_url(url):
    value = str(url or "").strip()
    match = re.search(r"/Channels/([^/]+)/(\d+)", value, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def load_channels_with_ids_from_excel(path):
    if not path.exists():
        return []

    try:
        df = pd.read_excel(path, dtype=str)
    except Exception:
        return []

    if df.empty:
        return []

    lower_cols = {str(c).strip().lower(): c for c in df.columns}
    name_col = lower_cols.get("channel_name") or lower_cols.get("channel") or df.columns[0]
    id_col = lower_cols.get("channel_id") or lower_cols.get("id")
    url_col = lower_cols.get("url")
    if not id_col:
        return []

    selected = {}
    order = []

    for _, row in df.iterrows():
        raw_name = str(row.get(name_col, "") or "").strip()
        raw_id = str(row.get(id_col, "") or "").strip()
        raw_url = str(row.get(url_col, "") or "").strip() if url_col else ""

        if not raw_name:
            continue
        if not re.fullmatch(r"\d+", raw_id):
            continue

        key = _channel_dedupe_key(raw_name)
        if not key:
            continue

        candidate = {
            "name": normalize_channel(raw_name),
            "id": raw_id,
            "source_name": raw_name,
            "url": raw_url,
        }

        existing = selected.get(key)
        if existing is None:
            selected[key] = candidate
            order.append(key)
            continue

        existing_is_hd = _channel_has_hd_tag(existing.get("source_name"))
        candidate_is_hd = _channel_has_hd_tag(raw_name)
        # Prefer non-HD when both are available for same base channel.
        if existing_is_hd and not candidate_is_hd:
            selected[key] = candidate

    channels_with_ids = []
    for key in order:
        entry = selected[key]
        source_name = entry["source_name"]
        slug_candidates = []
        url_slug = _extract_slug_from_channel_url(entry.get("url", ""))
        if url_slug:
            slug_candidates.append(url_slug)
        slug_candidates.extend(_channel_slug_candidates(source_name))
        # Deduplicate slug candidates while preserving order.
        seen = set()
        deduped = []
        for slug in slug_candidates:
            value = str(slug or "").strip()
            if not value:
                continue
            k = value.lower()
            if k in seen:
                continue
            seen.add(k)
            deduped.append(value)

        channels_with_ids.append({
            "name": entry["name"],
            "id": entry["id"],
            "slugs": deduped,
        })

    return channels_with_ids


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
    channel = str(channel or "").strip()
    channel = HD_TAG_PATTERN.sub("", channel).strip("-_ ")
    channel = re.sub(r"[-_]+", " ", channel)
    channel = re.sub(r"\s+", " ", channel).strip()
    return channel.title()


def _channel_base_name(name):
    value = str(name or "").strip()
    value = HD_TAG_PATTERN.sub("", value)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    return value


def _channel_dedupe_key(name):
    value = _channel_base_name(name).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _channel_slug_candidates(name):
    raw_name = str(name or "").strip()
    base_name = _channel_base_name(raw_name)
    if not raw_name and not base_name:
        return []

    candidates = []
    seen = set()

    def add_candidate(raw_value):
        cleaned = str(raw_value or "").strip().strip("-")
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(cleaned)

    name_variants = [raw_name, base_name]
    if base_name and not re.search(r"(?i)\b(uhd|fhd|hd)\b", raw_name):
        name_variants.append(f"{base_name} HD")

    for variant in name_variants:
        if not variant:
            continue
        add_candidate(re.sub(r"\s+", "-", variant))
        add_candidate(re.sub(r"[^A-Za-z0-9]+", "-", variant))
        add_candidate(re.sub(r"[^A-Za-z0-9]+", "-", variant.replace("&", "And")))

    return candidates


def _get_hinted_channel_id(slug_candidates):
    for slug in slug_candidates:
        hinted = CHANNEL_ID_HINTS_LOWER.get(slug.lower())
        if hinted:
            return hinted

    for slug in slug_candidates:
        hinted = CHANNEL_ID_HINTS_LOWER.get(f"{slug.lower()}-hd")
        if hinted:
            return hinted

    return None


def load_channel_id_cache(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    cache = {}
    for key, value in data.items():
        cache[str(key).lower()] = str(value).strip()
    return cache


def save_channel_id_cache(path, cache):
    try:
        path.write_text(
            json.dumps(cache, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except Exception:
        pass


def _extract_channel_id_from_html(text):
    if not text:
        return None

    patterns = [
        r"/Api/ChannelScheduleApi/DayJson/(\d+)",
        r"/Channels/[^/]+/(\d+)",
        r"/Channels/[^/]+/(\d+)/UpcomingJson",
        r'"channelId"\s*:\s*"?(?:\d+)"?',
        r'"ChannelId"\s*:\s*"?(?:\d+)"?',
        r'data-channel-id\s*=\s*"(\d+)"',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            if groups:
                return groups[0]
            digits = re.search(r"\d+", match.group(0))
            if digits:
                return digits.group(0)

    return None


def resolve_channel_id(page, slug_candidates, hinted_id=None, debug=False):
    fallback_id = str(hinted_id).strip() if hinted_id else None

    for slug in slug_candidates:
        url = f"https://www.tvwish.com/IN/Channels/{slug}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=10000)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass

            channel_id = extract_channel_id(page.url)
            if not channel_id:
                html = page.content()
                channel_id = extract_channel_id_from_text(html)
            if not channel_id:
                channel_id = _extract_channel_id_from_html(page.content())

            if debug:
                print(f"   [debug] page url: {page.url}")
                print(f"   [debug] resolved id from page: {channel_id}")

            if channel_id:
                return channel_id
        except Exception as e:
            if debug:
                print(f"   [debug] id discovery failed: {url} -> {e}")

    return fallback_id or None


def discover_channel_ids_from_directory(debug=False):
    directory_urls = [
        "https://www.tvwish.com/IN/Channels",
        "https://www.tvwish.com/IN/channels",
    ]
    discovered = {}
    pattern = re.compile(r"/IN/Channels/([A-Za-z0-9\-]+)/(\d+)", re.IGNORECASE)

    for url in directory_urls:
        try:
            response = requests.get(url, timeout=12)
            if response.status_code != 200:
                if debug:
                    print(f"   [debug] directory fetch failed ({response.status_code}): {url}")
                continue

            for slug, channel_id in pattern.findall(response.text):
                if not slug or not channel_id:
                    continue
                discovered[slug.lower()] = channel_id

            if discovered:
                break
        except Exception as e:
            if debug:
                print(f"   [debug] directory fetch exception: {url} -> {e}")

    if debug:
        print(f"   [debug] directory ids discovered: {len(discovered)}")
    return discovered


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


def _week_day_label_from_index(day_index):
    # TVWish UpcomingJson payload "1" means today, then next days.
    return (datetime.now() + timedelta(days=max(day_index - 1, 0))).strftime("%a")


def _normalize_time_text(time_text, day_hint=None):
    value = str(time_text or "").strip()
    if not value:
        return ""

    value = re.sub(r"\s+", " ", value)
    # Accept "Tue, 2:00 AM", "Tue 2:00 AM", "2:00 AM"
    match = re.match(
        r"^(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*,?\s*)?(\d{1,2}:\d{2}\s*[AP]M)$",
        value,
        flags=re.IGNORECASE,
    )
    if match:
        day = (match.group(1) or day_hint or "").title()[:3]
        time_part = match.group(2).upper().replace(" ", "")
        try:
            dt = datetime.strptime(time_part, "%I:%M%p")
            normalized_time = dt.strftime("%I:%M %p")
            if day in DAY_ORDER:
                return f"{day}, {normalized_time}"
            return normalized_time
        except Exception:
            pass

    for fmt in ("%a, %I:%M %p", "%a %I:%M %p", "%I:%M %p"):
        try:
            dt = datetime.strptime(value, fmt)
            normalized_time = dt.strftime("%I:%M %p")
            day = day_hint
            if fmt.startswith("%a"):
                day = value[:3].title()
            if day in DAY_ORDER:
                return f"{day}, {normalized_time}"
            return normalized_time
        except Exception:
            continue

    return value


def _extract_day_and_minutes(normalized_time):
    value = str(normalized_time or "").strip()
    if not value:
        return (99, 24 * 60 + 1)

    day = None
    time_part = value
    day_match = re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*,\s*(.+)$", value, flags=re.IGNORECASE)
    if day_match:
        day = day_match.group(1).title()
        time_part = day_match.group(2).strip()

    try:
        dt = datetime.strptime(time_part.upper(), "%I:%M %p")
        minutes = dt.hour * 60 + dt.minute
    except Exception:
        minutes = 24 * 60 + 1

    return (DAY_ORDER.get(day, 99), minutes)


def _fetch_week_schedule_items(slug_candidates, channel_id, debug=False):
    endpoint_patterns = [
        "https://www.tvwish.com/undefined/Channels/{slug}/{channel_id}/UpcomingJson",
        "https://www.tvwish.com/IN/Channels/{slug}/{channel_id}/UpcomingJson",
    ]
    base_headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": "https://www.tvwish.com",
        "Referer": "https://www.tvwish.com/",
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
    }

    for slug in slug_candidates:
        slug_value = str(slug or "").strip()
        if not slug_value:
            continue

        weekly_items = []
        for day_index in range(1, 8):
            payload = str(day_index)
            day_items = []
            day_resolved = False

            for endpoint in endpoint_patterns:
                url = endpoint.format(slug=slug_value, channel_id=channel_id)
                request_attempts = [
                    # Matches payload style user observed: "1" with JSON body.
                    {
                        "headers": {**base_headers, "Content-Type": "application/json; charset=UTF-8"},
                        "json": payload,
                    },
                    # Some backends accept a plain JSON number.
                    {
                        "headers": {**base_headers, "Content-Type": "application/json; charset=UTF-8"},
                        "json": day_index,
                    },
                    # Fallback plain text payload.
                    {
                        "headers": {**base_headers, "Content-Type": "text/plain; charset=UTF-8"},
                        "data": payload,
                    },
                ]

                for attempt in request_attempts:
                    try:
                        response = requests.post(url, timeout=8, **attempt)
                        if response.status_code != 200:
                            if debug:
                                print(
                                    f"   [debug] UpcomingJson status {response.status_code}: "
                                    f"{url} payload={payload} ct={attempt['headers'].get('Content-Type')}"
                                )
                            continue

                        data = response.json()
                        items = _extract_items(data)
                        day_items = items
                        day_resolved = True
                        if debug:
                            print(
                                f"   [debug] UpcomingJson ok: {url} payload={payload} "
                                f"items={len(items)} ct={attempt['headers'].get('Content-Type')}"
                            )
                        break
                    except Exception as e:
                        if debug:
                            print(f"   [debug] UpcomingJson failed: {url} payload={payload} -> {e}")

                if day_resolved:
                    break

            weekly_items.append((day_index, day_items))

        if any(items for _, items in weekly_items):
            return weekly_items

    return []


def _time_sort_key(show):
    day_index = show.get("_day_index", 99)
    minutes = show.get("_minutes", 24 * 60 + 1)
    return (show.get("channel", ""), day_index, minutes, show.get("title", ""))


# =========================
# 📡 FETCH ALL DATA
# =========================
def fetch_all():
    all_shows = []
    debug = os.getenv("TVWISH_DEBUG", "").strip() == "1"
    channel_id_cache = load_channel_id_cache(CHANNEL_ID_CACHE_PATH)
    needs_directory_lookup = any(not isinstance(channel, dict) for channel in channels)
    directory_id_map = discover_channel_ids_from_directory(debug=debug) if needs_directory_lookup else {}
    cache_dirty = False
    for channel in channels:
        if isinstance(channel, dict):
            channel_display_name = normalize_channel(channel.get("name", ""))
            channel_id = str(channel.get("id", "")).strip()
            slug_candidates = [s for s in channel.get("slugs", []) if str(s).strip()]
            if not channel_id or not re.fullmatch(r"\d+", channel_id):
                continue
            if not slug_candidates:
                slug_candidates = _channel_slug_candidates(channel_display_name)
        else:
            slug_candidates = _channel_slug_candidates(channel)
            if not slug_candidates:
                continue

            channel_display_name = normalize_channel(channel)
            hinted_id = _get_hinted_channel_id(slug_candidates)
            cached_id = None
            directory_id = None
            for slug in slug_candidates:
                cached_id = channel_id_cache.get(slug.lower())
                if not directory_id:
                    directory_id = directory_id_map.get(slug.lower())
                if cached_id:
                    break

            # Fast path for performance: avoid browser startup and use known IDs.
            channel_id = str(hinted_id or directory_id or cached_id or "").strip()
            if not re.fullmatch(r"\d+", channel_id):
                if debug:
                    print(f"   [debug] no valid channel id for {channel_display_name}, skipping")
                continue

        shows = []
        seen = set()

        print(f"\nFetching {channel_display_name}...")

        def add_items(items, day_index=None):
            day_label = _week_day_label_from_index(day_index) if day_index else None
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

                normalized_time = _normalize_time_text(time, day_hint=day_label)
                sort_day_index, sort_minutes = _extract_day_and_minutes(normalized_time)
                if day_index and sort_day_index == 99:
                    # If payload day is known but API omitted day text, trust payload ordering.
                    sort_day_index = DAY_ORDER.get(day_label, 99)
                    normalized_time = _normalize_time_text(time, day_hint=day_label)

                key = (title.lower(), normalized_time)
                if key in seen:
                    continue
                seen.add(key)

                shows.append({
                    "title": title,
                    "channel": channel_display_name,
                    "time": normalized_time or str(time or "").strip(),
                    "_day_index": sort_day_index,
                    "_minutes": sort_minutes,
                })

        for slug in slug_candidates:
            if channel_id_cache.get(slug.lower()) != channel_id:
                channel_id_cache[slug.lower()] = channel_id
                cache_dirty = True

        weekly_items = _fetch_week_schedule_items(
            slug_candidates=slug_candidates,
            channel_id=channel_id,
            debug=debug,
        )

        for day_index, items in weekly_items:
            add_items(items, day_index=day_index)

        print(f"   -> {len(shows)} week shows")
        all_shows.extend(shows)

    if cache_dirty:
        save_channel_id_cache(CHANNEL_ID_CACHE_PATH, channel_id_cache)

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
    channels = load_channels_with_ids_from_excel(CHANNELS_WITH_IDS_XLSX_PATH)
    channels_source_name = CHANNELS_WITH_IDS_XLSX_PATH.name
    if not channels:
        channels = load_channels_from_excel(CHANNELS_XLSX_PATH)
        channels_source_name = CHANNELS_XLSX_PATH.name
    usable_movies = build_movie_pairs(my_movies)
    print(
        f"Loaded {len(my_movies)} films from {MOVIES_XLSX_PATH.name} "
        f"(usable for matching: {len(usable_movies)})"
    )
    print(
        f"Loaded {len(channels)} channels from {channels_source_name} "
        f"(HD/UHD duplicates removed)"
    )
    print("Fetching WEEK TV schedule...\n")

    tv_data = fetch_all()

    print("\nWEEK SHOWS:\n")
    for show in tv_data:
        print(f"{show['channel']} | {show['time']} | {show['title']}")

    print("\nMatching...\n")
    results = match_movies(tv_data)

    print("\nMATCHES:\n")

    if not results:
        print("No matches")
    else:
        for r in results:
            print(f"{r['movie']} -> {r['channel']} | {r['time']}")
