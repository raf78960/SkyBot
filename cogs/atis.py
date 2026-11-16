"""
Cog ATIS / aviation : METAR, calcul de pistes, diffusion vocale, commandes slash.
"""

import os
import asyncio
import shutil
import tempfile
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
import requests
from gtts import gTTS

from config import CHECKWX_API_KEY, ATC_ROLE_ID, GUILD_ID
try:
    from config import AIRPORT_DB_TOKEN
except ImportError:
    AIRPORT_DB_TOKEN = os.getenv("AIRPORT_DB_TOKEN", "")

import database as db


# ---------------------------------------------------------------------------
# Données aéroports / pistes
# ---------------------------------------------------------------------------

ATIS_LETTERS = [
    "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
    "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima",
    "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo",
    "Sierra", "Tango", "Uniform", "Victor", "Whiskey",
    "Xray", "Yankee", "Zulu",
]

RUNWAYS = {
    "LFPG": ["08L", "08R", "09L", "09R", "26L", "26R"],
    "LFPO": ["06", "07", "24", "25"],
    "LFOB": ["12", "30"],
    "LFQQ": ["08", "26"],
    "LFRS": ["03", "21"],
    "LFRB": ["07", "25"],
    "LFBD": ["05", "23", "11", "29"],
    "LFLL": ["17L", "17R", "35L", "35R"],
    "LFBO": ["14L", "14R", "32L", "32R"],
    "LFML": ["13L", "13R", "31L", "31R"],
    "LFMN": ["04L", "04R", "22L", "22R"],
    "LFKJ": ["02", "20"],
    "LEMA": ["06", "24"],
    "LEPA": ["06L", "24R"],
    "TFFF": ["10", "28"],
    "TFFR": ["09", "27"],
    "FMEE": ["12", "30"],
    "EGLL": ["09L", "09R", "27L", "27R"],
    "EGKK": ["08L", "08R", "26L", "26R"],
    "EDDF": ["07L", "07C", "07R", "25L", "25C", "25R"],
    "EDDM": ["08L", "08R", "26L", "26R"],
    "LEMD": ["14L", "14R", "18L", "18R", "32L", "32R", "36L", "36R"],
    "LEBL": ["02", "06L", "06R", "24L", "24R"],
    "LIRF": ["07", "16L", "16R", "25", "34L", "34R"],
    "LIMC": ["17L", "17R", "35L", "35R"],
    "EHAM": ["04", "06", "09", "18L", "18C", "18R", "22", "24", "27", "36"],
    "LSZH": ["10", "14", "16", "28", "32", "34"],
    "LSGG": ["04", "22"],
    "GMMN": ["10", "28"],
    "GMMX": ["10", "28"],
    "LPPT": ["02", "20"],
    "LPMA": ["05", "23"],
}

RUNWAY_ROWS = [
    ("LFPG", "08L", 80, 4215, 350, 170, "DEP"),
    ("LFPG", "26R", 260, 4215, 170, 350, "DEP"),
    ("LFPG", "08R", 80, 2700, 350, 170, "ARR"),
    ("LFPG", "26L", 260, 2700, 170, 350, "ARR"),
    ("LFPG", "09L", 90, 2700, 0, 180, "ARR"),
    ("LFPG", "27R", 270, 2700, 180, 360, "ARR"),
    ("LFPG", "09R", 90, 4200, 0, 180, "DEP"),
    ("LFPG", "27L", 270, 4200, 180, 360, "DEP"),
    ("LFPO", "06", 60, 3650, 330, 150, "DEP"),
    ("LFPO", "24", 240, 3650, 150, 330, "ARR"),
    ("LFPO", "07", 70, 3320, 340, 160, "DEP"),
    ("LFPO", "25", 250, 3320, 160, 340, "ARR"),
    ("LFRS", "03", 30, 2900, 300, 120, "DEP"),
    ("LFRS", "21", 210, 2900, 120, 300, "ARR"),
    ("LFBD", "05", 50, 3100, 320, 140, "DEP"),
    ("LFBD", "23", 230, 3100, 140, 320, "ARR"),
    ("LFLL", "17R", 170, 4000, 80, 260, "DEP"),
    ("LFLL", "35L", 350, 4000, 260, 80, "DEP"),
    ("LFLL", "17L", 170, 2670, 80, 260, "ARR"),
    ("LFLL", "35R", 350, 2670, 260, 80, "ARR"),
    ("LFBO", "14L", 140, 3500, 50, 230, "DEP"),
    ("LFBO", "32R", 320, 3500, 230, 50, "DEP"),
    ("LFBO", "14R", 140, 3000, 50, 230, "ARR"),
    ("LFBO", "32L", 320, 3000, 230, 50, "ARR"),
    ("LFML", "13L", 130, 3500, 40, 220, "DEP"),
    ("LFML", "31R", 310, 3500, 220, 40, "DEP"),
    ("LFML", "13R", 130, 2400, 40, 220, "ARR"),
    ("LFML", "31L", 310, 2400, 220, 40, "ARR"),
    ("LFMN", "04R", 40, 2900, 310, 130, "DEP"),
    ("LFMN", "22L", 220, 2900, 130, 310, "DEP"),
    ("LFMN", "04L", 40, 2600, 310, 130, "ARR"),
    ("LFMN", "22R", 220, 2600, 130, 310, "ARR"),
    ("EBBR", "07L", 70, 3600, 340, 160, "DEP"),
    ("EBBR", "25R", 250, 3600, 160, 340, "DEP"),
    ("EBBR", "07R", 70, 3200, 340, 160, "ARR"),
    ("EBBR", "25L", 250, 3200, 160, 340, "ARR"),
    ("EBBR", "01", 10, 2980, 280, 100, "ARR"),
    ("EBBR", "19", 190, 2980, 100, 280, "ARR"),
    ("EBCI", "06", 60, 2550, 330, 150, "DEP"),
    ("EBCI", "24", 240, 2550, 150, 330, "ARR"),
    ("EBLG", "04", 40, 3700, 310, 130, "DEP"),
    ("EBLG", "22", 220, 3700, 130, 310, "ARR"),
    ("EHAM", "18R", 180, 3800, 90, 270, "DEP"),
    ("EHAM", "36L", 360, 3800, 270, 90, "DEP"),
    ("EHAM", "18C", 180, 3400, 90, 270, "DEP"),
    ("EHAM", "36C", 360, 3400, 270, 90, "DEP"),
    ("EHAM", "18L", 180, 3300, 90, 270, "ARR"),
    ("EHAM", "36R", 360, 3300, 270, 90, "ARR"),
    ("EHAM", "06", 60, 3500, 330, 150, "DEP"),
    ("EHAM", "24", 240, 3500, 150, 330, "ARR"),
    ("EHAM", "09", 90, 3400, 0, 180, "DEP"),
    ("EHAM", "27", 270, 3400, 180, 360, "ARR"),
    ("EGLL", "09L", 90, 3900, 0, 180, "DEP"),
    ("EGLL", "27R", 270, 3900, 180, 360, "DEP"),
    ("EGLL", "09R", 90, 3900, 0, 180, "ARR"),
    ("EGLL", "27L", 270, 3900, 180, 360, "ARR"),
    ("EGKK", "08R", 80, 3300, 350, 170, "DEP"),
    ("EGKK", "26L", 260, 3300, 170, 350, "ARR"),
    ("EDDF", "07C", 70, 4000, 340, 160, "DEP"),
    ("EDDF", "25C", 250, 4000, 160, 340, "DEP"),
    ("EDDF", "07L", 70, 4000, 340, 160, "ARR"),
    ("EDDF", "25R", 250, 4000, 160, 340, "ARR"),
    ("EDDF", "07R", 70, 4000, 340, 160, "ARR"),
    ("EDDF", "25L", 250, 4000, 160, 340, "ARR"),
    ("EDDF", "18", 180, 4000, 90, 270, "DEP"),
    ("EDDM", "08L", 80, 4000, 350, 170, "DEP"),
    ("EDDM", "26R", 260, 4000, 170, 350, "DEP"),
    ("EDDM", "08R", 80, 4000, 350, 170, "ARR"),
    ("EDDM", "26L", 260, 4000, 170, 350, "ARR"),
    ("LSZH", "28", 280, 3700, 190, 10, "DEP"),
    ("LSZH", "14", 140, 3300, 50, 230, "DEP"),
    ("LSZH", "16", 160, 2500, 70, 250, "ARR"),
    ("LSZH", "32", 320, 3300, 230, 50, "ARR"),
    ("LSGG", "04", 40, 3900, 310, 130, "DEP"),
    ("LSGG", "22", 220, 3900, 130, 310, "ARR"),
    ("LIRF", "07", 70, 3900, 340, 160, "DEP"),
    ("LIRF", "25", 250, 3900, 160, 340, "ARR"),
    ("LIRF", "16R", 160, 3900, 70, 250, "DEP"),
    ("LIRF", "34L", 340, 3900, 250, 70, "ARR"),
    ("LIRF", "16L", 160, 3900, 70, 250, "ARR"),
    ("LIRF", "34R", 340, 3900, 250, 70, "DEP"),
    ("LIMC", "17L", 170, 3920, 80, 260, "DEP"),
    ("LIMC", "35R", 350, 3920, 260, 80, "ARR"),
    ("LIMC", "17R", 170, 3920, 80, 260, "ARR"),
    ("LIMC", "35L", 350, 3920, 260, 80, "DEP"),
    ("LEMD", "14L", 140, 3500, 50, 230, "DEP"),
    ("LEMD", "32R", 320, 3500, 230, 50, "DEP"),
    ("LEMD", "14R", 140, 3500, 50, 230, "ARR"),
    ("LEMD", "32L", 320, 3500, 230, 50, "ARR"),
    ("LEMD", "18L", 180, 3500, 90, 270, "DEP"),
    ("LEMD", "36R", 360, 3500, 270, 90, "ARR"),
    ("LEMD", "18R", 180, 3500, 90, 270, "ARR"),
    ("LEMD", "36L", 360, 3500, 270, 90, "DEP"),
    ("LEBL", "07R", 70, 3200, 340, 160, "DEP"),
    ("LEBL", "25L", 250, 3200, 160, 340, "ARR"),
    ("LEBL", "07L", 70, 2700, 340, 160, "ARR"),
    ("LEBL", "25R", 250, 2700, 160, 340, "DEP"),
    ("GMMN", "17R", 170, 3700, 80, 260, "DEP"),
    ("GMMN", "35L", 350, 3700, 260, 80, "ARR"),
    ("GMMX", "10", 100, 3200, 10, 190, "DEP"),
    ("GMMX", "28", 280, 3200, 190, 10, "ARR"),
    ("GMMX", "06", 60, 3100, 330, 150, "DEP"),
    ("GMMX", "24", 240, 3100, 150, 330, "ARR"),
    ("LGAV", "03L", 30, 4000, 300, 120, "DEP"),
    ("LGAV", "21R", 210, 4000, 120, 300, "ARR"),
    ("LGAV", "03R", 30, 4000, 300, 120, "ARR"),
    ("LGAV", "21L", 210, 4000, 120, 300, "DEP"),
    ("LGIR", "09", 90, 2700, 0, 180, "DEP"),
    ("LGIR", "27", 270, 2700, 180, 360, "ARR"),
    ("LGKR", "17", 170, 2400, 80, 260, "DEP"),
    ("LGKR", "35", 350, 2400, 260, 80, "ARR"),
    ("TFFR", "12", 120, 3400, 30, 210, "DEP"),
    ("TFFR", "30", 300, 3400, 210, 30, "ARR"),
    ("TFFF", "10", 100, 3300, 10, 190, "DEP/ARR"),
    ("TFFF", "28", 280, 3300, 190, 10, "DEP/ARR"),
    # Portugal — LPPT (Lisbonne) / LPMA (Madère)
    ("LPPT", "02", 20, 3705, 0, 179, "DEP/ARR"),
    ("LPPT", "20", 200, 3705, 180, 359, "DEP/ARR"),
    ("LPMA", "05", 50, 2781, 0, 179, "DEP/ARR"),
    ("LPMA", "23", 230, 2781, 180, 359, "DEP/ARR"),
]

RUNWAY_RULES = {}
for icao, runway, qfu, length_m, sector_start, sector_end, uses in RUNWAY_ROWS:
    RUNWAY_RULES.setdefault(icao, []).append({
        "runway": runway,
        "qfu": qfu,
        "length_m": length_m,
        "sector": (sector_start, sector_end),
        "uses": uses.split("/"),
    })
for icao, rules in RUNWAY_RULES.items():
    RUNWAYS[icao] = sorted({rule["runway"] for rule in rules})

AIRPORT_CONFIG = {
    "LFPG": {
        "east": {"departures": ["09L", "08R"], "arrivals": ["08L", "09R"]},
        "west": {"departures": ["27L", "26R"], "arrivals": ["26L", "27R"]},
    },
    "LFPO": {
        "east": {"departures": ["07"], "arrivals": ["06"]},
        "west": {"departures": ["25"], "arrivals": ["24"]},
    },
    "LFLL": {
        "south": {"departures": ["17R"], "arrivals": ["17L"]},
        "north": {"departures": ["35L"], "arrivals": ["35R"]},
    },
    "LFBO": {
        "south": {"departures": ["14R"], "arrivals": ["14L"]},
        "north": {"departures": ["32L"], "arrivals": ["32R"]},
    },
    "LFML": {
        "south": {"departures": ["31R"], "arrivals": ["31L"]},
        "north": {"departures": ["13L"], "arrivals": ["13R"]},
    },
    "LFMN": {
        "south": {"departures": ["22R"], "arrivals": ["22L"]},
        "north": {"departures": ["04L"], "arrivals": ["04R"]},
    },
    "EGLL": {
        "east": {"departures": ["09L", "08R"], "arrivals": ["08L", "09R"]},
        "west": {"departures": ["27L", "26R"], "arrivals": ["26L", "27R"]},
    },
    "EGKK": {
        "east": {"departures": ["08L", "08R"], "arrivals": ["26R", "26L"]},
        "west": {"departures": ["26R", "26L"], "arrivals": ["08L", "08R"]},
    },
    "EDDF": {
        "east": {"departures": ["07L", "07C"], "arrivals": ["07R"]},
        "west": {"departures": ["25R", "25C"], "arrivals": ["25L"]},
    },
    "EDDM": {
        "east": {"departures": ["08L"], "arrivals": ["08R"]},
        "west": {"departures": ["26R"], "arrivals": ["26L"]},
    },
    "LEMD": {
        "north": {"departures": ["18R"], "arrivals": ["18L"]},
        "east": {"departures": ["15L"], "arrivals": ["15R"]},
    },
    "LEBL": {
        "northeast": {"departures": ["06L", "06R"], "arrivals": ["24R", "24L"]},
        "north": {"departures": ["02"], "arrivals": ["20"]},
    },
    "LIRF": {
        "south": {"departures": ["16L", "16R"], "arrivals": ["34R", "34L"]},
        "east": {"departures": ["07"], "arrivals": ["25"]},
    },
    "LIMC": {
        "south": {"departures": ["17L", "17R"], "arrivals": ["35R", "35L"]},
        "north": {"departures": ["35R", "35L"], "arrivals": ["17L", "17R"]},
    },
    "EHAM": {
        "north": {"departures": ["18L", "18C", "18R"], "arrivals": ["36R", "36C", "36L"]},
        "east": {"departures": ["09"], "arrivals": ["27"]},
        "northeast": {"departures": ["06"], "arrivals": ["24"]},
        "northwest": {"departures": ["04"], "arrivals": ["22"]},
    },
    "LSZH": {
        "east": {"departures": ["10"], "arrivals": ["28"]},
        "north": {"departures": ["16"], "arrivals": ["34"]},
        "south": {"departures": ["14"], "arrivals": ["32"]},
    },
    "LSGG": {
        "north": {"departures": ["04"], "arrivals": ["22"]},
        "south": {"departures": ["22"], "arrivals": ["04"]},
    },
    "GMMN": {
        "south": {"departures": ["17L", "17R"], "arrivals": ["35R", "35L"]},
        "north": {"departures": ["35R", "35L"], "arrivals": ["17L", "17R"]},
    },
    "GMMX": {
        "east": {"departures": ["10"], "arrivals": ["28"]},
        "west": {"departures": ["28"], "arrivals": ["10"]},
    },
    "LPPT": {
        "north": {"departures": ["02"], "arrivals": ["02"]},
        "south": {"departures": ["20"], "arrivals": ["20"]},
    },
    "LPMA": {
        "northeast": {"departures": ["05"], "arrivals": ["05"]},
        "southwest": {"departures": ["23"], "arrivals": ["23"]},
    },
}

AVIATION_NUMBERS = {
    "0": "zéro", "1": "un", "2": "deux", "3": "trois", "4": "quatre",
    "5": "cinq", "6": "six", "7": "sept", "8": "huit", "9": "neuf",
}


def say_number_aviation(number):
    return " ".join(AVIATION_NUMBERS[d] for d in str(number))


def say_runway(runway):
    number = "".join(filter(str.isdigit, runway))
    side = runway[len(number):]
    spoken = say_number_aviation(number)
    if side == "L":
        spoken += " gauche"
    elif side == "R":
        spoken += " droite"
    elif side == "C":
        spoken += " centre"
    return spoken


def normalize_heading(degrees):
    degrees = int(degrees or 0) % 360
    return 360 if degrees == 0 else degrees


def heading_diff(a, b):
    a = normalize_heading(a)
    b = normalize_heading(b)
    diff = abs(a - b)
    return min(diff, 360 - diff)


def wind_in_sector(wind_deg, sector):
    wind = normalize_heading(wind_deg)
    start, end = sector
    start = normalize_heading(start)
    end = normalize_heading(end)
    if start <= end:
        return start <= wind <= end
    return wind >= start or wind <= end


def _dedupe(rules):
    seen, ordered = set(), []
    for rule in rules:
        if rule["runway"] not in seen:
            seen.add(rule["runway"])
            ordered.append(rule["runway"])
    return ordered


def select_rule_runways(rules, wind_deg, use):
    """Pistes à annoncer, dans le vent.

    Règle : les pistes les plus LONGUES servent aux DÉPARTS, les plus COURTES aux ARRIVÉES.
    Une seule piste (ou des pistes de même longueur) dans le vent : elle sert aux deux.
    """
    cands = [r for r in rules if wind_in_sector(wind_deg, r["sector"])] or list(rules)
    if not cands:
        return []
    # uniquement les pistes qui font face au vent (≤ 90°), s'il y en a
    into = [r for r in cands if heading_diff(wind_deg, r["qfu"]) <= 90] or cands
    best = min(heading_diff(wind_deg, r["qfu"]) for r in into)
    near = [r for r in into if heading_diff(wind_deg, r["qfu"]) <= best + 35]
    longest = max(r["length_m"] for r in near)
    deps = [r for r in near if r["length_m"] >= 0.95 * longest]
    arrs = [r for r in near if r not in deps] or deps
    if use == "DEP":
        chosen = sorted(deps, key=lambda r: (-r["length_m"], heading_diff(wind_deg, r["qfu"]), r["runway"]))
    else:
        chosen = sorted(arrs, key=lambda r: (r["length_m"], heading_diff(wind_deg, r["qfu"]), r["runway"]))
    return _dedupe(chosen)


def dynamic_runway(icao, wind_deg, wind_speed, manual_runway):
    if icao in manual_runway:
        rwy = manual_runway[icao]
        return {"departures": [rwy], "arrivals": [rwy]}

    if icao in RUNWAY_RULES:
        rules = RUNWAY_RULES[icao]
        departures = select_rule_runways(rules, wind_deg, "DEP")
        arrivals = select_rule_runways(rules, wind_deg, "ARR")
        return {
            "departures": departures or ["N/A"],
            "arrivals": arrivals or ["N/A"],
        }

    if icao in AIRPORT_CONFIG:
        config = AIRPORT_CONFIG[icao]
        best_config = None
        best_angle = 999

        def reference_heading(runways_list):
            for rwy in runways_list:
                number = "".join(filter(str.isdigit, rwy))
                if number:
                    return int(number) * 10
            return None

        for direction, runways in config.items():
            sample_list = runways.get("departures") or runways.get("arrivals") or []
            heading = reference_heading(sample_list)
            if heading is None:
                continue
            angle = abs(wind_deg - heading)
            if angle > 180:
                angle = 360 - angle
            if angle < best_angle:
                best_angle = angle
                best_config = runways

        if best_config:
            departures = list(best_config.get("departures", []))
            arrivals = list(best_config.get("arrivals", []))
            if not departures:
                departures = [r for cfg in config.values() for r in cfg.get("departures", [])]
            if not arrivals:
                arrivals = [r for cfg in config.values() for r in cfg.get("arrivals", [])]
            return {
                "departures": departures or ["N/A"],
                "arrivals": arrivals or ["N/A"],
            }

    runways = RUNWAYS.get(icao, [])
    scored = []
    for rwy in runways:
        number = "".join(filter(str.isdigit, rwy))
        if not number:
            continue
        heading = int(number) * 10
        angle = abs(wind_deg - heading)
        if angle > 180:
            angle = 360 - angle
        if angle <= 90:
            scored.append((angle, rwy))
    if scored:
        scored.sort()
        usable = [rwy for _, rwy in scored]
        return {"departures": usable, "arrivals": usable}
    if runways:
        return {"departures": list(runways), "arrivals": list(runways)}
    return {"departures": ["N/A"], "arrivals": ["N/A"]}


def find_ffmpeg():
    custom_path = os.getenv("FFMPEG_PATH")
    if custom_path and os.path.exists(custom_path):
        return custom_path
    return shutil.which("ffmpeg")


def ensure_voice_dependencies():
    try:
        import nacl.secret  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "La lecture vocale Discord nécessite PyNaCl. "
            "Installe-la avec `pip install pynacl`."
        )
    if not getattr(discord.voice_state, "has_dave", False):
        raise RuntimeError(
            "La lecture vocale Discord nécessite la bibliothèque `davey`. "
            "Installe-la avec `pip install davey`."
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


def _fetch_airportdb(icao: str):
    """AirportDB.io — terrain (pistes, fréquences, nom). Cache process simple."""
    token = (globals().get("AIRPORT_DB_TOKEN") or os.getenv("AIRPORT_DB_TOKEN", "") or "").strip()
    if not token:
        return None
    code = (icao or "").upper().strip()[:4]
    if len(code) < 4:
        return None
    cache = getattr(_fetch_airportdb, "_cache", {})
    import time
    now = time.time()
    hit = cache.get(code)
    if hit and now - hit[0] < 6 * 3600:
        return hit[1]
    try:
        r = requests.get(
            f"https://airportdb.io/api/v1/airport/{code}",
            params={"apiToken": token},
            timeout=12,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict) or not data.get("ident"):
            return None
        cache[code] = (now, data)
        _fetch_airportdb._cache = cache
        return data
    except Exception as e:
        print(f"[ATIS] AirportDB {code}: {e}")
        return None


def _airportdb_runways(airport: dict, wind_deg: float, wind_speed: float) -> dict:
    import math
    ends = []
    for rw in airport.get("runways") or []:
        if str(rw.get("closed") or "0") in ("1", "true", "True"):
            continue
        for hdg_key, ident_key in (("le_heading_degT", "le_ident"), ("he_heading_degT", "he_ident")):
            ident = (rw.get(ident_key) or "").strip()
            if not ident:
                continue
            try:
                hdg = float(rw.get(hdg_key) or 0)
            except (TypeError, ValueError):
                hdg = 0.0
            try:
                length = int(float(rw.get("length_ft") or 0))
            except (TypeError, ValueError):
                length = 0
            ends.append({"ident": ident.upper(), "heading": hdg, "length_ft": length})
    if not ends:
        return {"departures": [], "arrivals": []}
    if wind_speed < 3:
        # vent calme : départs sur la piste la plus longue ; arrivées sur la plus courte allant dans le même sens
        by_len = sorted(ends, key=lambda e: e["length_ft"], reverse=True)
        dep = by_len[0]

        def _same_way(e):
            d = abs((e["heading"] - dep["heading"] + 180) % 360 - 180)
            return d <= 45

        shorter = [e for e in by_len if _same_way(e) and e["length_ft"] < 0.95 * dep["length_ft"]]
        arr = min(shorter, key=lambda e: e["length_ft"]) if shorter else dep
        return {"departures": [dep["ident"]], "arrivals": [arr["ident"]]}

    def headwind(e):
        diff = math.radians((wind_deg - e["heading"] + 180) % 360 - 180)
        return wind_speed * math.cos(diff)

    ranked = sorted(ends, key=headwind, reverse=True)
    best = headwind(ranked[0])
    # pistes bien dans le vent (≈ ±30° de la meilleure)
    top = [e for e in ranked if headwind(e) >= best * 0.97] or [ranked[0]]
    ref = max(top, key=lambda e: e["length_ft"])  # référence : la plus longue parmi les mieux au vent

    def _near_ref(e):
        return abs((e["heading"] - ref["heading"] + 180) % 360 - 180) <= 25

    usable = [e for e in ranked if headwind(e) > 0 and _near_ref(e)] or [ref]
    # les plus longues = départs, les plus courtes = arrivées (une seule piste / même longueur : les deux)
    longest = max(e["length_ft"] for e in usable)
    deps = [e for e in usable if e["length_ft"] >= 0.95 * longest] or usable
    arrs = [e for e in usable if e not in deps] or deps
    deps = sorted(deps, key=lambda e: (-e["length_ft"], -headwind(e)))
    arrs = sorted(arrs, key=lambda e: (e["length_ft"], -headwind(e)))
    return {
        "departures": list(dict.fromkeys(e["ident"] for e in deps))[:3],
        "arrivals": list(dict.fromkeys(e["ident"] for e in arrs))[:3],
    }


def _airportdb_freqs(airport: dict) -> dict:
    out = {}
    for f in airport.get("freqs") or []:
        typ = (f.get("type") or "").strip().upper()
        mhz = f.get("frequency_mhz")
        if not typ or mhz is None:
            continue
        if typ not in out:
            try:
                out[typ] = f"{float(mhz):g}"
            except (TypeError, ValueError):
                out[typ] = str(mhz)
    return out


class AtisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.airport_data = {}
        self.metar_history = {}
        self.active_repeats = {}
        self.atc_status = {}
        self.manual_runway = {}

    def log(self, msg: str):
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")

    async def get_metar(self, icao: str):
        def fetch():
            if not CHECKWX_API_KEY:
                print(f"[ERROR] CHECKWX_API_KEY manquant")
                return self._empty_metar()
            url = f"https://api.checkwx.com/metar/{icao}/decoded"
            headers = {"X-API-Key": CHECKWX_API_KEY}
            try:
                r = requests.get(url, headers=headers, timeout=30)
                r.raise_for_status()
                data = r.json().get("data") or []
                if not data:
                    print(f"[ERROR] METAR {icao} non disponible : réponse vide")
                    return self._empty_metar()
                return data[0]
            except requests.exceptions.RequestException as e:
                print(f"[ERROR] METAR {icao} impossible à récupérer : {e}")
                return self._empty_metar()

        return await asyncio.to_thread(fetch)

    @staticmethod
    def _empty_metar():
        return {
            "raw_text": "N/A",
            "wind": {"degrees": 0, "speed_kts": 0},
            "visibility": {"meters": 0},
            "temperature": {"celsius": 0},
            "barometer": {"hpa": 0},
        }


    async def _positions_online_for_icao(self, icao: str) -> str:
        """Liste les positions ouvertes sur cet ICAO via les fréquences actives."""
        icao = (icao or "").upper().strip()
        try:
            freqs = await db.list_active_frequencies()
        except Exception:
            freqs = []
        positions = []
        for f in freqs:
            f_icao = (f.get("icao") or "").upper().strip()
            if f_icao != icao:
                continue
            pos = (f.get("position") or "").strip().upper()
            if not pos:
                name = (f.get("name") or "").upper()
                for p in ("APP", "TWR", "GND", "DEL", "CTR", "DEP"):
                    if p in name:
                        pos = p
                        break
            label = pos or "ATC"
            if label not in positions:
                positions.append(label)
        return ", ".join(positions) if positions else "Aucun"

    async def generate_atis(self, icao: str):
        metar = await self.get_metar(icao)
        if icao not in self.metar_history:
            self.metar_history[icao] = []
        self.metar_history[icao].append(metar.get("raw_text", "N/A"))
        self.metar_history[icao] = self.metar_history[icao][-5:]

        # Lettre ATIS : ne change que si la météo change de façon significative
        # (vent, QNH, visibilité, phénomènes) — pas sur un simple timer.
        wind = metar.get("wind") or {}
        wind_deg = wind.get("degrees", 0) or 0
        wind_speed = wind.get("speed_kts", 0) or 0
        vis_m = int((metar.get("visibility") or {}).get("meters", 0) or 0)
        qnh = round((metar.get("barometer") or {}).get("hpa", 0) or 0)
        temp = (metar.get("temperature") or {}).get("celsius", 0) or 0
        wx = metar.get("raw_text") or ""
        # Empreinte « significative » : vent arrondi 10°, vitesse 5 kt, QNH, vis catégorie
        vis_cat = 0 if vis_m < 1000 else 1 if vis_m < 5000 else 2 if vis_m < 10000 else 3
        wind_bucket = (int(wind_deg) // 10) * 10
        speed_bucket = (int(wind_speed) // 5) * 5
        sig = (wind_bucket, speed_bucket, qnh, vis_cat, "TS" in wx or "RA" in wx or "SN" in wx or "FG" in wx)

        if icao not in self.airport_data:
            self.airport_data[icao] = {}
        prev = self.airport_data[icao]
        letter_index = prev.get("letter_index")
        if letter_index is None:
            # première lettre stable par ICAO
            letter_index = sum(ord(c) for c in (icao or "").upper()) % 26
            prev["letter_index"] = letter_index
            prev["weather_sig"] = sig
        elif prev.get("weather_sig") != sig:
            # météo significativement différente → lettre suivante
            letter_index = (int(letter_index) + 1) % 26
            prev["letter_index"] = letter_index
            prev["weather_sig"] = sig
        letter = ATIS_LETTERS[letter_index]
        prev["letter"] = letter

        # AirportDB.io (terrain) prioritaire pour pistes / nom / fréquences
        adb = await asyncio.to_thread(_fetch_airportdb, icao)
        if adb:
            runways = _airportdb_runways(adb, float(wind_deg or 0), float(wind_speed or 0))
        else:
            runways = dynamic_runway(icao, wind_deg, wind_speed, self.manual_runway)
        runway_depart = ", ".join(runways["departures"]) or "—"
        runway_arrive = ", ".join(runways["arrivals"]) or "—"

        atc_online = await self._positions_online_for_icao(icao)

        name = (adb or {}).get("name") if adb else None
        elev = None
        if adb and adb.get("elevation_ft") not in (None, ""):
            try:
                elev = int(float(adb["elevation_ft"]))
            except (TypeError, ValueError):
                elev = None
        freqs = _airportdb_freqs(adb) if adb else {}
        atis_freq = freqs.get("ATIS") or freqs.get("INFO")

        lines = [f"{icao} Information {letter}"]
        if name:
            lines.append(name + (f" · élév. {elev} ft" if elev is not None else ""))
        lines.append(f"Émis {datetime.now(timezone.utc).strftime('%H%M')}Z")
        if atis_freq:
            lines.append(f"Fréquence ATIS {atis_freq} MHz")
        lines.extend([
            f"Vent {wind_deg}° {wind_speed}kt",
            f"Visibilité {int((metar.get('visibility') or {}).get('meters', 0) / 1000)} km",
            f"Piste départ: {runway_depart}",
            f"Piste arrivée: {runway_arrive}",
            f"Température: {(metar.get('temperature') or {}).get('celsius', 0)}°C",
            f"QNH: {round((metar.get('barometer') or {}).get('hpa', 0) or 0)} hPa",
        ])
        for typ in ("GND", "TWR", "APP"):
            if freqs.get(typ):
                lines.append(f"{typ} {freqs[typ]} MHz")
        lines.append(f"ATC: {atc_online}")
        lines.append(f"Confirmez information {letter} au premier contact")
        atis_text = chr(10).join(lines)
        return atis_text, letter

    def build_embed(self, icao, letter, text, repeat_info=None):
        embed = discord.Embed(
            title=f"📡 ATIS {icao} — Information {letter}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Broadcast", value=f"```{text}```", inline=False)
        if repeat_info:
            embed.add_field(name="Répétition", value=repeat_info)
        embed.set_footer(text="ATIS System • Professional Mode")
        return embed

    async def play_atis(self, icao, voice_channel, text_channel, repeat_info=None):
        atis_text, letter = await self.generate_atis(icao)
        try:
            ensure_voice_dependencies()
            ffmpeg_path = find_ffmpeg()
            if ffmpeg_path:
                temp_dir = tempfile.gettempdir()
                filename = os.path.join(temp_dir, f"atis_{icao}_{letter}.mp3")
                playback_error = None
                voice_client = None
                try:
                    await asyncio.to_thread(
                        lambda: gTTS(text=atis_text, lang="fr").save(filename)
                    )
                    voice_client = discord.utils.get(
                        self.bot.voice_clients, guild=voice_channel.guild
                    )
                    if voice_client and voice_client.is_connected():
                        await voice_client.move_to(voice_channel)
                    else:
                        voice_client = await voice_channel.connect(self_deaf=True)
                    if voice_client.is_playing():
                        voice_client.stop()
                    finished = asyncio.Event()

                    def after_play(error):
                        nonlocal playback_error
                        playback_error = error
                        self.bot.loop.call_soon_threadsafe(finished.set)

                    source = discord.FFmpegOpusAudio(filename, executable=ffmpeg_path)
                    voice_client.play(source, after=after_play)
                    await finished.wait()
                    if playback_error:
                        raise RuntimeError(f"Erreur pendant la lecture audio: {playback_error}")
                    self.log(f"ATIS diffusé {icao} {letter}")
                finally:
                    if voice_client and voice_client.is_connected():
                        await voice_client.disconnect()
                    if os.path.exists(filename):
                        os.remove(filename)
        except Exception as e:
            self.log(f"Voice failed for {icao}: {e}")

        embed = self.build_embed(icao, letter, atis_text, repeat_info)
        await text_channel.send(embed=embed)

    def _atc_only(self, interaction: discord.Interaction):
        if not ATC_ROLE_ID:
            return
        role = discord.utils.get(interaction.user.roles, id=ATC_ROLE_ID)
        if not role:
            raise app_commands.AppCommandError("Commande réservée aux ATC")

    # ---------- Commandes ----------

    @app_commands.command(name="atis", description="Afficher l'ATIS d'un aéroport")
    async def atis_cmd(self, interaction: discord.Interaction, icao: str):
        await interaction.response.defer()
        try:
            text, letter = await self.generate_atis(icao.upper())
            embed = self.build_embed(icao.upper(), letter, text)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ {e}")

    @app_commands.command(name="play_atis", description="Diffuser l'ATIS en vocal")
    async def play_cmd(self, interaction: discord.Interaction, icao: str):
        if not interaction.user.voice:
            await interaction.response.send_message("❌ Vous devez être en vocal.")
            return
        await interaction.response.defer()
        try:
            await self.play_atis(
                icao.upper(), interaction.user.voice.channel, interaction.channel
            )
            await interaction.followup.send("✅ Diffusion ATIS terminée.")
        except Exception as e:
            self.log(f"Erreur play_atis {icao.upper()}: {e}")
            await interaction.followup.send(f"❌ Diffusion vocale impossible: {e}")

    @app_commands.command(name="repeat_atis", description="Diffuser plusieurs fois l'ATIS")
    async def repeat_cmd(
        self, interaction: discord.Interaction, icao: str, repetitions: int
    ):
        self._atc_only(interaction)
        icao = icao.upper()
        if icao in self.active_repeats:
            await interaction.response.send_message(f"⚠️ ATIS déjà actif pour {icao}")
            return
        if not interaction.user.voice:
            await interaction.response.send_message("❌ Vous devez être en vocal.")
            return
        await interaction.response.send_message(
            f"🔁 ATIS {icao} lancé ({repetitions} diffusions)."
        )

        async def task():
            try:
                for i in range(repetitions):
                    await self.play_atis(
                        icao,
                        interaction.user.voice.channel,
                        interaction.channel,
                        repeat_info=f"{i + 1}/{repetitions}",
                    )
                    if i < repetitions - 1:
                        await asyncio.sleep(1800)
            except asyncio.CancelledError:
                await interaction.channel.send(f"🛑 Répétition annulée pour {icao}")
                self.log(f"ATIS annulé {icao}")
            except Exception as e:
                await interaction.channel.send(
                    f"❌ Erreur pendant la répétition ATIS {icao}: {e}"
                )
                self.log(f"Erreur repeat_atis {icao}: {e}")
            finally:
                self.active_repeats.pop(icao, None)

        self.active_repeats[icao] = self.bot.loop.create_task(task())

    @app_commands.command(name="stop_atis", description="Arrêter la diffusion répétée")
    async def stop_cmd(self, interaction: discord.Interaction, icao: str):
        self._atc_only(interaction)
        icao = icao.upper()
        if icao not in self.active_repeats:
            await interaction.response.send_message(f"❌ Aucun ATIS actif pour {icao}")
            return
        self.active_repeats[icao].cancel()
        await interaction.response.send_message(f"🛑 Arrêt demandé pour {icao}")

    @app_commands.command(
        name="last_metar", description="Afficher le dernier METAR récupéré"
    )
    async def last_metar_cmd(self, interaction: discord.Interaction, icao: str):
        icao = icao.upper()
        if icao in self.metar_history:
            await interaction.response.send_message(
                f"```{self.metar_history[icao][-1]}```"
            )
        else:
            await interaction.response.send_message("Aucun METAR enregistré.")

    @app_commands.command(name="set_runway", description="Définir la piste manuellement")
    async def set_runway_cmd(
        self, interaction: discord.Interaction, icao: str, runway: str
    ):
        self._atc_only(interaction)
        self.manual_runway[icao.upper()] = runway.upper()
        await interaction.response.send_message(
            f"✅ Piste {runway.upper()} définie manuellement pour {icao.upper()}"
        )

    @app_commands.command(
        name="auto_runway", description="Activer le mode automatique pour la piste"
    )
    async def auto_runway_cmd(self, interaction: discord.Interaction, icao: str):
        self._atc_only(interaction)
        icao = icao.upper()
        if icao in self.manual_runway:
            self.manual_runway.pop(icao)
            await interaction.response.send_message(
                f"🔄 Mode automatique activé pour {icao}"
            )
        else:
            await interaction.response.send_message(
                f"⚠️ {icao} est déjà en mode automatique"
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AtisCog(bot))