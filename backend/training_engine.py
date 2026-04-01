"""
CardioCoach - Training Engine

Periodization engine and training load management.
Calculations based on:
- ACWR (Acute:Chronic Workload Ratio)
- TSB (Training Stress Balance)
- Preparation phases (Build, Intensification, Taper, Race)

Usage:
    from training_engine import (
        build_training_context,
        determine_phase,
        determine_target_load,
        compute_acwr
    )
"""

import datetime
from typing import Dict, Optional, List


# ============================================================
# CONFIGURATION BY GOAL
# ============================================================

GOAL_CONFIG = {
    "5K": {
        "cycle_weeks": 6,
        "long_run_ratio": 0.25,
        "intensity_pct": 20,
        "description": "5 kilometers"
    },
    "10K": {
        "cycle_weeks": 8,
        "long_run_ratio": 0.30,
        "intensity_pct": 18,
        "description": "10 kilometers"
    },
    "SEMI": {
        "cycle_weeks": 12,
        "long_run_ratio": 0.35,
        "intensity_pct": 15,
        "description": "Half-marathon"
    },
    "MARATHON": {
        "cycle_weeks": 16,
        "long_run_ratio": 0.40,
        "intensity_pct": 12,
        "description": "Marathon"
    },
    "ULTRA": {
        "cycle_weeks": 20,
        "long_run_ratio": 0.45,
        "intensity_pct": 10,
        "description": "Ultra-trail"
    }
}

# Safety thresholds
ACWR_SAFE_MIN = 0.8
ACWR_SAFE_MAX = 1.3
ACWR_DANGER = 1.5
TSB_FATIGUE_THRESHOLD = -20
TSB_FRESH_THRESHOLD = 10


# ============================================================
# BASE CALCULATIONS
# ============================================================

def compute_week_number(start_date: datetime.date) -> int:
    """Calculates the week number since the start of the cycle."""
    today = datetime.date.today()
    delta_days = (today - start_date).days
    return max(1, delta_days // 7 + 1)


def compute_acwr(load_7: float, load_28: float) -> float:
    """
    Calculates the ACWR (Acute:Chronic Workload Ratio).

    - < 0.8: Under-training
    - 0.8-1.3: Optimal zone
    - 1.3-1.5: Risk zone
    - > 1.5: Injury danger
    """
    if load_28 == 0:
        return 1.0
    chronic_avg = load_28 / 4  # Average over 4 weeks
    return round(load_7 / chronic_avg, 2)


def compute_tsb(ctl: float, atl: float) -> float:
    """
    Calculates the TSB (Training Stress Balance).
    TSB = CTL - ATL

    - Negative: Accumulated fatigue
    - Positive: Freshness
    - Ideal for race: +5 to +15
    """
    return round(ctl - atl, 1)


def compute_monotony(daily_loads: List[float]) -> float:
    """
    Calculates training monotony.
    Monotony = Mean / Standard Deviation

    - < 1.5: Good variety
    - > 2.0: Too monotonous (overtraining risk)
    """
    if not daily_loads or len(daily_loads) < 2:
        return 0

    avg = sum(daily_loads) / len(daily_loads)
    variance = sum((x - avg) ** 2 for x in daily_loads) / len(daily_loads)
    std = variance ** 0.5

    if std == 0:
        return 0
    return round(avg / std, 2)


def compute_strain(weekly_load: float, monotony: float) -> float:
    """
    Calculates training strain.
    Strain = Load × Monotony

    Indicator of overall stress on the body.
    """
    return round(weekly_load * monotony, 0)


# ============================================================
# PREPARATION PHASES
# ============================================================

def determine_phase(week: int, total_weeks: int) -> str:
    """
    Determines the preparation phase based on the week.

    Phases:
    - build: Base building (60% of cycle)
    - deload: Recovery week (mid-cycle)
    - intensification: Intensity increase
    - taper: Pre-race taper (last 2 weeks)
    - race: Race week
    """
    if week >= total_weeks:
        return "race"

    if week >= total_weeks - 2:
        return "taper"

    # Deload week in the middle
    if week == total_weeks // 2:
        return "deload"

    # Deload week every 4 weeks
    if week > 4 and week % 4 == 0:
        return "deload"

    if week < total_weeks * 0.6:
        return "build"

    return "intensification"


def get_phase_description(phase: str, lang: str = "en") -> Dict:
    """Return phase description and advice in the requested language."""
    phases_en = {
        "build": {
            "name": "Build",
            "description": "Aerobic base development phase",
            "focus": "Volume in fundamental endurance (Z1-Z2)",
            "intensity_pct": 15,
            "advice": "Prioritise long runs at comfortable pace"
        },
        "deload": {
            "name": "Recovery",
            "description": "Unload week to absorb training",
            "focus": "Reduce volume by 20-30%",
            "intensity_pct": 10,
            "advice": "Short easy runs, stretching, sleep"
        },
        "intensification": {
            "name": "Intensification",
            "description": "Race-pace specific phase",
            "focus": "Quality sessions (tempo, threshold, intervals)",
            "intensity_pct": 25,
            "advice": "Include sessions at race pace"
        },
        "taper": {
            "name": "Taper",
            "description": "Progressive reduction before race",
            "focus": "Maintain intensity, reduce volume",
            "intensity_pct": 20,
            "advice": "Keep some speed work, rest up"
        },
        "race": {
            "name": "Race",
            "description": "Race week",
            "focus": "Maximum freshness",
            "intensity_pct": 0,
            "advice": "Light run before, trust your training"
        }
    }
    phases_fr = {
        "build": {
            "name": "Construction",
            "description": "Phase de développement de la base aérobie",
            "focus": "Volume en endurance fondamentale (Z1-Z2)",
            "intensity_pct": 15,
            "advice": "Privilégie les sorties longues à allure confortable"
        },
        "deload": {
            "name": "Récupération",
            "description": "Semaine de décharge pour assimiler le travail",
            "focus": "Réduction du volume de 20-30%",
            "intensity_pct": 10,
            "advice": "Sorties courtes et faciles, étirements, sommeil"
        },
        "intensification": {
            "name": "Intensification",
            "description": "Phase de travail spécifique à l'allure cible",
            "focus": "Séances de qualité (tempo, seuil, fractionné)",
            "intensity_pct": 25,
            "advice": "Intègre des séances à allure course"
        },
        "taper": {
            "name": "Affûtage",
            "description": "Réduction progressive avant la course",
            "focus": "Maintien de l'intensité, baisse du volume",
            "intensity_pct": 20,
            "advice": "Garde quelques rappels de vitesse, repose-toi"
        },
        "race": {
            "name": "Course",
            "description": "Semaine de compétition",
            "focus": "Fraîcheur maximale",
            "intensity_pct": 0,
            "advice": "Footing léger avant, confiance en ton travail"
        }
    }
    phases = phases_en if lang == "en" else phases_fr
    return phases.get(phase, phases["build"])


# ============================================================
# LOAD ADJUSTMENT
# ============================================================

def adjust_load_by_fatigue(base_load: float, tsb: float, acwr: float) -> float:
    """
    Adjusts recommended load based on fatigue.

    Rules:
    - ACWR > 1.3: Reduce by 15%
    - TSB < -20: Reduce by 10%
    - TSB > +10: Increase by 5%
    """
    adjusted = base_load

    # ACWR too high = injury risk
    if acwr > ACWR_DANGER:
        adjusted *= 0.70  # Strong reduction
    elif acwr > ACWR_SAFE_MAX:
        adjusted *= 0.85

    # Very negative TSB = accumulated fatigue
    if tsb < TSB_FATIGUE_THRESHOLD:
        adjusted *= 0.90

    # Positive TSB = freshness, can push a bit
    elif tsb > TSB_FRESH_THRESHOLD:
        adjusted *= 1.05

    return adjusted


def determine_target_load(context: Dict, phase: str) -> int:
    """
    Determines the target load for the week.

    Args:
        context: Fitness data (ctl, atl, tsb, acwr)
        phase: Current phase of the cycle

    Returns:
        Target load in load units (TSS/TRIMP)
    """
    ctl = context.get("ctl", 40)
    base = ctl

    # Phase multipliers
    phase_multipliers = {
        "build": 1.05,
        "deload": 0.75,
        "intensification": 1.10,
        "taper": 0.65,
        "race": 0.30
    }

    multiplier = phase_multipliers.get(phase, 1.0)
    base *= multiplier

    # Adjust based on fatigue
    adjusted = adjust_load_by_fatigue(
        base,
        context.get("tsb", 0),
        context.get("acwr", 1.0)
    )

    return int(adjusted)


def determine_target_km(context: Dict, phase: str, goal: str = "10K") -> float:
    """
    Determines the target mileage for the week.
    """
    weekly_km = context.get("weekly_km", 30)

    phase_multipliers = {
        "build": 1.05,
        "deload": 0.75,
        "intensification": 1.0,
        "taper": 0.60,
        "race": 0.25
    }

    multiplier = phase_multipliers.get(phase, 1.0)
    target = weekly_km * multiplier

    # ACWR adjustment
    acwr = context.get("acwr", 1.0)
    if acwr > ACWR_SAFE_MAX:
        target *= 0.85

    return round(target, 1)


# ============================================================
# CONTEXT BUILDING
# ============================================================

def build_training_context(
    fitness_data: Dict,
    weekly_km: float,
    daily_loads: List[float] = None
) -> Dict:
    """
    Builds the complete training context.

    Args:
        fitness_data: Fitness data (ctl, atl, load_7, load_28)
        weekly_km: Average weekly mileage
        daily_loads: Daily loads (for monotony)

    Returns:
        Complete context for recommendations
    """
    load_7 = fitness_data.get("load_7", 300)
    load_28 = fitness_data.get("load_28", 1200)
    ctl = fitness_data.get("ctl", 40)
    atl = fitness_data.get("atl", 45)

    acwr = compute_acwr(load_7, load_28)
    tsb = compute_tsb(ctl, atl)

    context = {
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "acwr": acwr,
        "weekly_km": weekly_km,
        "load_7": load_7,
        "load_28": load_28
    }

    # Add monotony if data available
    if daily_loads:
        context["monotony"] = compute_monotony(daily_loads)
        context["strain"] = compute_strain(load_7, context["monotony"])

    # Risk assessment
    context["risk_level"] = evaluate_risk(acwr, tsb)

    return context


def evaluate_risk(acwr: float, tsb: float) -> str:
    """
    Evaluates the risk level of injury/overtraining.

    Returns:
        "low", "moderate", "high", "critical"
    """
    if acwr > ACWR_DANGER or tsb < -30:
        return "critical"

    if acwr > ACWR_SAFE_MAX or tsb < TSB_FATIGUE_THRESHOLD:
        return "high"

    if acwr < ACWR_SAFE_MIN:
        return "low"  # Under-training

    if tsb < -10:
        return "moderate"

    return "low"


# ============================================================
# RECOMMENDATIONS
# ============================================================

def generate_week_recommendation(
    context: Dict,
    phase: str,
    goal: str = "10K"
) -> Dict:
    """
    Generates recommendations for the week.
    """
    goal_config = GOAL_CONFIG.get(goal, GOAL_CONFIG["10K"])
    phase_info = get_phase_description(phase)

    target_load = determine_target_load(context, phase)
    target_km = determine_target_km(context, phase, goal)

    # Recommended distribution
    long_run_km = round(target_km * goal_config["long_run_ratio"], 1)
    easy_km = round(target_km * (1 - goal_config["long_run_ratio"] - goal_config["intensity_pct"]/100), 1)
    intensity_km = round(target_km * goal_config["intensity_pct"] / 100, 1)

    return {
        "phase": phase,
        "phase_info": phase_info,
        "target_load": target_load,
        "target_km": target_km,
        "distribution": {
            "long_run_km": long_run_km,
            "easy_km": easy_km,
            "intensity_km": intensity_km
        },
        "risk_level": context.get("risk_level", "low"),
        "acwr": context.get("acwr", 1.0),
        "tsb": context.get("tsb", 0),
        "advice": phase_info.get("advice", "")
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "GOAL_CONFIG",
    "compute_week_number",
    "compute_acwr",
    "compute_tsb",
    "compute_monotony",
    "compute_strain",
    "determine_phase",
    "get_phase_description",
    "adjust_load_by_fatigue",
    "determine_target_load",
    "determine_target_km",
    "build_training_context",
    "evaluate_risk",
    "generate_week_recommendation"
]
