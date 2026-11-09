"""Shared constants and deterministic helpers (used by generator and validator)."""
import math
import zlib

BBOX = {"lat_min": 17.20, "lat_max": 17.60, "lon_min": 78.25, "lon_max": 78.65}
DEPOT_ID = "SITE-000000"
DEPOT_LL = (17.4400, 78.4983)
SPEED_KMPH = 32.0                      # clear-road urban speed used for base_minutes
LOAD_MIN = 20                          # depot loading time before departure (min)
RETURN_BUFFER = 15                     # planner keeps >=15 min slack before shift end
BANDS = ["offpeak", "am_peak", "midday", "pm_peak"]
BAND_MULT = {"offpeak": 1.0, "am_peak": 1.45, "midday": 1.10, "pm_peak": 1.60}
SCEN_MULT = {"NORMAL": 1.0, "RAIN": 1.25, "EVENT_CONGESTION": 1.35, "HOLIDAY_LIGHT": 0.85}
SCEN_SIGMA = {"NORMAL": 0.10, "RAIN": 0.18, "EVENT_CONGESTION": 0.20, "HOLIDAY_LIGHT": 0.08}
HARD_GRACE, SOFT_GRACE = 15, 30


def det(*parts):
    """Deterministic pseudo-random float in [0,1) from arbitrary parts (order independent of iteration)."""
    return zlib.crc32("|".join(str(p) for p in parts).encode()) / 2 ** 32


def band_index(minute):
    if minute < 420 or minute >= 1200:
        return 0          # offpeak
    if minute < 600:
        return 1          # 07:00-10:00 am_peak
    if minute < 990:
        return 2          # 10:00-16:30 midday
    return 3              # 16:30-20:00 pm_peak


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(a))


def circuity(seed, a_id, b_id):
    a, b = sorted((a_id, b_id))
    return 1.20 + 0.25 * det(seed, "circ", a, b)


def road_km(seed, a_id, a_ll, b_id, b_ll):
    if a_id == b_id:
        return 0.0
    return round(haversine_km(*a_ll, *b_ll) * circuity(seed, a_id, b_id), 3)


def base_minutes(dist_km):
    return round(dist_km / SPEED_KMPH * 60, 2)


def band_minutes(base, mult, band_idx):
    return round(base * mult * BAND_MULT[BANDS[band_idx]], 2)
