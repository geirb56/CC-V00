"""
mock_runner.py — Dynamic mock API for CardioCoach running data.

This module exposes two FastAPI endpoints under the ``/api`` prefix:

* ``GET /api/mock-runner``   – full runner profile with 10 recent races,
  7-day daily biometrics, and a "today" summary derived from those metrics.
* ``GET /api/mock-runner/races`` – only the list of 10 races.

All data is generated **dynamically** using a seeded PRNG whose seed is the
current UTC date (``int(YYYYMMDD)``).  This means the values are stable
throughout the same calendar day but change each new day — useful for
demonstrating the dashboard without a live Terra token.

No database, no external HTTP calls, no Terra token required.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter

# ---------------------------------------------------------------------------
# Router — prefix "/api" is added by server.py via api_router.include_router
# ---------------------------------------------------------------------------
mock_runner_router = APIRouter(prefix="/mock-runner", tags=["mock-runner"])

# ---------------------------------------------------------------------------
# Static runner profile (same every day — only biometrics & races vary)
# ---------------------------------------------------------------------------
_USER_PROFILE = {
    "user_id": "mock-runner-001",
    "name": "Alex Dupont",
    "vma": 18.5,          # Velocity at VO2max in km/h
    "goal": "Sub-3h Marathon",
    "sessions_per_week": 5,
    "age": 34,
    "weight_kg": 72.0,
    "hr_max": 188,        # Max heart-rate (220 − age heuristic ≈ 186, rounded up)
    "hr_rest": 47,        # Resting heart-rate for a trained runner
}

# Abbreviated day-of-week labels (Mon = 0 … Sun = 6 via weekday())
_DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Workout name pool for race generation
_WORKOUT_NAMES = [
    "Morning Run",
    "Long Run",
    "Tempo Run",
    "Easy Recovery Run",
    "Interval Session",
    "Progression Run",
    "Trail Run",
    "Fartlek Run",
    "Threshold Run",
    "Race Day",
]


def _make_seed() -> int:
    """Return an integer seed derived from today's UTC date (YYYYMMDD).

    Using the date as seed ensures reproducibility within a day while
    producing different values on subsequent days.
    """
    return int(datetime.now(timezone.utc).strftime("%Y%m%d"))


def _generate_races(rng: random.Random, today: datetime) -> List[dict]:
    """Generate 10 synthetic races covering roughly the last 80 days.

    Distances follow a realistic mix: mostly 5–10 km, occasional half-
    marathon or marathon.  All derived fields (pace, HR, TSS, etc.) are
    computed from each other to keep internal consistency.

    Args:
        rng:   Seeded Random instance for reproducibility.
        today: Reference date (UTC) used as day-0.

    Returns:
        List of 10 race dicts ordered from most-recent to oldest.
    """
    weight_kg = _USER_PROFILE["weight_kg"]
    hr_max = _USER_PROFILE["hr_max"]

    # Realistic distance pool (km) — heavier weight on shorter races
    distance_pool = [5.0, 5.0, 10.0, 10.0, 10.0, 21.1, 21.1, 42.2, 8.0, 15.0]

    races: List[dict] = []
    for i in range(10):
        # Each race is ~8 days apart with ±2-day jitter
        jitter = rng.randint(-2, 2)
        days_ago = i * 8 + jitter
        race_date = (today - timedelta(days=days_ago)).strftime("%Y-%m-%d")

        distance_km = rng.choice(distance_pool)

        # Pace: shorter races run faster (3.8–5.2 min/km for 5 K,
        #       4.5–6.5 for marathon).  Linear interpolation across range.
        base_pace = 3.8 + (distance_km / 42.2) * 2.7
        # Add small noise (±0.3 min/km)
        pace_min_per_km = round(base_pace + rng.uniform(-0.3, 0.3), 2)
        pace_sec_per_km = int(pace_min_per_km * 60)

        speed_kmh = round(60.0 / pace_min_per_km, 2)

        duration_min = round(distance_km * pace_min_per_km, 1)
        duration_seconds = int(duration_min * 60)

        # Heart rate: inversely correlated with pace (faster → higher HR)
        # Map pace 3.8→178 bpm, 6.5→145 bpm
        hr_factor = (6.5 - pace_min_per_km) / (6.5 - 3.8)  # 0 (slow) → 1 (fast)
        heart_rate_avg = int(145 + hr_factor * (178 - 145) + rng.randint(-3, 3))
        heart_rate_max = heart_rate_avg + rng.randint(8, 18)
        heart_rate_min = heart_rate_avg - rng.randint(15, 25)

        # Calories ≈ distance × 72 × (weight_kg / 70) — running economy constant
        calories = int(distance_km * 72 * (weight_kg / 70))

        # Training Stress Score: (duration_h) × (HR_avg / HR_max)² × 100
        tss = round((duration_min / 60) * (heart_rate_avg / hr_max) ** 2 * 100, 1)

        elevation_gain_m = rng.randint(10, 320)

        cadence_avg = rng.randint(168, 182)  # steps per minute (both feet)

        # Stride length: speed(m/s) / (cadence in steps/s)
        speed_ms = speed_kmh / 3.6
        # cadence_avg counts both feet; strides per second = cadence / 60 / 2
        strides_per_sec = cadence_avg / 60 / 2
        stride_length_m = round(speed_ms / strides_per_sec, 2)

        # VO2max estimate (Daniels formula approximation, range 55–65)
        vo2max_estimate = round(rng.uniform(55.0, 65.0), 1)

        # Training effect: 1.5 (easy) – 5.0 (overreaching)
        training_effect = round(1.5 + hr_factor * 3.5 + rng.uniform(-0.3, 0.3), 1)
        training_effect = max(1.5, min(5.0, training_effect))

        name = _WORKOUT_NAMES[i % len(_WORKOUT_NAMES)]

        races.append({
            "race_id": f"race_{i + 1:02d}",
            "date": race_date,
            "activity_type": "running",
            "name": name,
            # Distance
            "distance_km": round(distance_km, 2),
            "distance_meters": int(distance_km * 1000),
            # Duration
            "duration_min": duration_min,
            "duration_seconds": duration_seconds,
            # Pace / speed
            "pace_min_per_km": pace_min_per_km,
            "pace_sec_per_km": pace_sec_per_km,
            "speed_kmh": speed_kmh,
            # Heart-rate
            "heart_rate_avg": heart_rate_avg,
            "heart_rate_max": heart_rate_max,
            "heart_rate_min": heart_rate_min,
            # Load & effort
            "calories": calories,
            "tss": tss,
            # Elevation
            "elevation_gain_m": elevation_gain_m,
            # Running mechanics
            "cadence_avg": cadence_avg,
            "stride_length_m": stride_length_m,
            # Performance estimates
            "vo2max_estimate": vo2max_estimate,
            "training_effect": training_effect,
        })

    return races


def _generate_daily_biometrics(rng: random.Random, today: datetime) -> List[dict]:
    """Generate 7 days of synthetic daily biometric data (days −6 … today).

    HRV, RHR, sleep, training load, and fatigue ratio are mutually correlated:
    - Higher sleep efficiency → higher HRV → lower RHR.
    - Higher training load → higher fatigue ratio.
    - Recommendation derived from fatigue + sleep quality.

    Args:
        rng:   Seeded Random instance.
        today: Reference date (UTC).

    Returns:
        List of 7 dicts, index 0 = 6 days ago, index 6 = today.
    """
    days: List[dict] = []

    for i in range(7):
        # i=0 → 6 days ago, i=6 → today
        day_date = (today - timedelta(days=6 - i)).strftime("%Y-%m-%d")
        day_abbr = _DAY_ABBR[(today - timedelta(days=6 - i)).weekday()]

        # Sleep first — drives HRV
        sleep_hours = round(rng.uniform(6.0, 8.5), 1)
        sleep_efficiency = round(rng.uniform(0.72, 0.96), 2)

        # Sleep score (0–100)
        sleep_score = round(sleep_hours * sleep_efficiency / 8.5 * 100, 1)

        # HRV (ms): 42–75, nudged up by good sleep quality
        sleep_quality_factor = (sleep_score - 50) / 50  # roughly −1 … +1
        hrv_ms = round(rng.uniform(42.0, 75.0) + sleep_quality_factor * 5, 1)
        hrv_ms = max(42.0, min(75.0, hrv_ms))

        # RHR (bpm): inversely correlated with HRV
        # HRV 42→56 bpm, HRV 75→44 bpm
        rhr_bpm = int(56 - (hrv_ms - 42) / (75 - 42) * (56 - 44))
        rhr_bpm += rng.randint(-1, 1)  # tiny noise
        rhr_bpm = max(44, min(56, rhr_bpm))

        # Training load (ACWR-like): 0.7–1.45
        training_load = round(rng.uniform(0.70, 1.45), 2)

        # Fatigue ratio: training_load × (1 − HRV / 80), clipped to [0.3, 2.0]
        fatigue_ratio = training_load * (1.0 - hrv_ms / 80.0)
        fatigue_ratio = round(max(0.3, min(2.0, fatigue_ratio)), 2)

        # Recommendation thresholds
        if fatigue_ratio < 0.9 and sleep_score > 70:
            recommendation = "RUN HARD"
        elif fatigue_ratio < 1.2:
            recommendation = "EASY"
        else:
            recommendation = "REST"

        days.append({
            "date": day_date,
            "day_abbr": day_abbr,
            "hrv_ms": hrv_ms,
            "rhr_bpm": rhr_bpm,
            "sleep_hours": sleep_hours,
            "sleep_efficiency": sleep_efficiency,
            "sleep_score": sleep_score,
            "training_load": training_load,
            "fatigue_ratio": fatigue_ratio,
            "recommendation": recommendation,
        })

    return days


def _build_today_section(biometrics: List[dict]) -> dict:
    """Derive the ``today`` summary block from the 7-day biometric array.

    The last entry in *biometrics* (index 6) is always today.
    Baselines are means across all 7 days.

    Args:
        biometrics: Output of :func:`_generate_daily_biometrics`.

    Returns:
        ``today`` dict with recommendation, metrics, reasons, and history.
    """
    today_bio = biometrics[-1]  # index 6 = today

    # --- Baselines (7-day means) ---
    hrv_baseline = round(sum(d["hrv_ms"] for d in biometrics) / len(biometrics), 1)
    rhr_baseline = round(sum(d["rhr_bpm"] for d in biometrics) / len(biometrics), 1)

    hrv_today = today_bio["hrv_ms"]
    rhr_today = float(today_bio["rhr_bpm"])
    hrv_delta = round(hrv_today - hrv_baseline, 1)
    rhr_delta = round(rhr_today - rhr_baseline, 1)

    sleep_hours = today_bio["sleep_hours"]
    sleep_efficiency = today_bio["sleep_efficiency"]
    sleep_score = today_bio["sleep_score"]
    training_load = today_bio["training_load"]
    fatigue_ratio = today_bio["fatigue_ratio"]

    # --- Status colours (green / yellow / red) ---
    # HRV: above baseline is good
    if hrv_delta >= 2:
        hrv_status = "green"
    elif hrv_delta >= -3:
        hrv_status = "yellow"
    else:
        hrv_status = "red"

    # RHR: below baseline is good
    if rhr_delta <= -2:
        rhr_status = "green"
    elif rhr_delta <= 2:
        rhr_status = "yellow"
    else:
        rhr_status = "red"

    # Sleep score
    if sleep_score >= 75:
        sleep_status = "green"
    elif sleep_score >= 55:
        sleep_status = "yellow"
    else:
        sleep_status = "red"

    # Training load (ACWR)
    if 0.8 <= training_load <= 1.3:
        training_load_status = "green"
    elif training_load < 0.6 or training_load > 1.5:
        training_load_status = "red"
    else:
        training_load_status = "yellow"

    # Fatigue ratio
    if fatigue_ratio < 0.9:
        fatigue_status = "green"
    elif fatigue_ratio < 1.2:
        fatigue_status = "yellow"
    else:
        fatigue_status = "red"

    # fatigue_physio: physiological fatigue estimate (0 = no fatigue)
    # Simplified: positive when fatigue_ratio > 1.0
    fatigue_physio = round(max(0.0, fatigue_ratio - 1.0), 2)

    # --- Overall recommendation ---
    rec = today_bio["recommendation"]
    if rec == "RUN HARD":
        rec_emoji = "🟢"
        rec_color = "green"
        next_label = "Intervals – 6 × 800 m"
    elif rec == "EASY RUN" or rec == "EASY":
        rec = "EASY RUN"
        rec_emoji = "🟡"
        rec_color = "yellow"
        next_label = "Easy 40-min jog (Z2)"
    else:
        rec_emoji = "🔴"
        rec_color = "red"
        next_label = "Rest day or gentle stretching"

    # --- Human-readable reasons ---
    hrv_dir = "above" if hrv_delta >= 0 else "below"
    rhr_dir = "below" if rhr_delta <= 0 else "above"
    reasons = [
        f"HRV deviation {hrv_delta:+.1f} ms vs baseline → today {hrv_dir} baseline"
        + (" (good recovery)" if hrv_status == "green" else ""),
        f"RHR {rhr_delta:+.1f} bpm vs baseline → "
        + ("rested" if rhr_status == "green" else "slightly elevated"),
        f"Sleep {sleep_hours} h at {int(sleep_efficiency * 100)}% efficiency",
        f"Training load (ACWR) {training_load:.2f} → "
        + ("optimal" if training_load_status == "green" else "watch out"),
        f"Fatigue Ratio {fatigue_ratio:.2f} → "
        + ("ready to perform" if fatigue_status == "green" else "moderate fatigue"),
    ]

    # --- 7-day history list (one entry per day) ---
    history = [
        {
            "day": d["day_abbr"],
            "hrv": d["hrv_ms"],
            "training_load": d["training_load"],
            "fatigue_ratio": d["fatigue_ratio"],
        }
        for d in biometrics
    ]

    return {
        "recommendation": rec,
        "recommendation_emoji": rec_emoji,
        "recommendation_color": rec_color,
        "next_workout": {"label": next_label, "icon": "run"},
        "metrics": {
            # HRV
            "hrv_today": hrv_today,
            "hrv_baseline": hrv_baseline,
            "hrv_delta": hrv_delta,
            "hrv_status": hrv_status,
            # Resting heart rate
            "rhr_today": rhr_today,
            "rhr_baseline": rhr_baseline,
            "rhr_delta": rhr_delta,
            "rhr_status": rhr_status,
            # Sleep
            "sleep_hours": sleep_hours,
            "sleep_efficiency": sleep_efficiency,
            "sleep_score": sleep_score,
            "sleep_status": sleep_status,
            # Training load (ACWR)
            "training_load": training_load,
            "training_load_status": training_load_status,
            # Fatigue
            "fatigue_physio": fatigue_physio,
            "fatigue_ratio": fatigue_ratio,
            "fatigue_status": fatigue_status,
        },
        "reasons": reasons,
        "history": history,
        "mock": True,
    }


def _build_full_profile() -> dict:
    """Build the complete mock runner profile for the current UTC day.

    Returns:
        Dict with ``user``, ``recent_races``, ``daily_biometrics``, ``today``.
    """
    seed = _make_seed()
    rng = random.Random(seed)

    # today as a naive datetime (UTC date) — only date arithmetic needed
    today_dt = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    races = _generate_races(rng, today_dt)
    biometrics = _generate_daily_biometrics(rng, today_dt)
    today_section = _build_today_section(biometrics)

    return {
        "user": _USER_PROFILE,
        "recent_races": races,
        "daily_biometrics": biometrics,
        "today": today_section,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@mock_runner_router.get("")
async def get_mock_runner():
    """Return a full dynamic mock runner profile.

    Includes:
    - Static user profile (``user``)
    - 10 recent races (``recent_races``)
    - 7-day daily biometrics (``daily_biometrics``)
    - Today's summary + recommendation (``today``)

    Data is seeded by the current UTC date: stable within a day, different
    each new day.
    """
    return _build_full_profile()


@mock_runner_router.get("/races")
async def get_mock_runner_races():
    """Return only the 10 recent races for the mock runner.

    Useful for lightweight race-list widgets that don't need the full profile.
    """
    profile = _build_full_profile()
    races = profile["recent_races"]
    return {
        "user_id": _USER_PROFILE["user_id"],
        "count": len(races),
        "races": races,
    }
