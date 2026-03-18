"""
CardioCoach - Training Engine

Moteur de périodisation et gestion de charge d'entraînement.
Calculs basés sur:
- ACWR (Acute:Chronic Workload Ratio)
- TSB (Training Stress Balance) 
- Phases de préparation (Build, Intensification, Taper, Race)

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
# CONFIGURATION PAR OBJECTIF
# ============================================================

GOAL_CONFIG = {
    "5K": {
        "cycle_weeks": 6,
        "long_run_ratio": 0.25,
        "intensity_pct": 20,
        "description": "5 kilomètres"
    },
    "10K": {
        "cycle_weeks": 8,
        "long_run_ratio": 0.30,
        "intensity_pct": 18,
        "description": "10 kilomètres"
    },
    "SEMI": {
        "cycle_weeks": 12,
        "long_run_ratio": 0.35,
        "intensity_pct": 15,
        "description": "Semi-marathon"
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

# Seuils de sécurité
ACWR_SAFE_MIN = 0.8
ACWR_SAFE_MAX = 1.3
ACWR_DANGER = 1.5
TSB_FATIGUE_THRESHOLD = -20
TSB_FRESH_THRESHOLD = 10


# ============================================================
# CALCULS DE BASE
# ============================================================

def compute_week_number(start_date: datetime.date) -> int:
    """Calcule le numéro de semaine depuis le début du cycle."""
    today = datetime.date.today()
    delta_days = (today - start_date).days
    return max(1, delta_days // 7 + 1)


def compute_acwr(load_7: float, load_28: float) -> float:
    """
    Calcule l'ACWR (Acute:Chronic Workload Ratio).
    
    - < 0.8: Sous-entraînement
    - 0.8-1.3: Zone optimale
    - 1.3-1.5: Zone à risque
    - > 1.5: Danger de blessure
    """
    if load_28 == 0:
        return 1.0
    chronic_avg = load_28 / 4  # Moyenne sur 4 semaines
    return round(load_7 / chronic_avg, 2)


def compute_tsb(ctl: float, atl: float) -> float:
    """
    Calcule le TSB (Training Stress Balance).
    TSB = CTL - ATL
    
    - Négatif: Fatigue accumulée
    - Positif: Fraîcheur
    - Idéal course: +5 à +15
    """
    return round(ctl - atl, 1)


def compute_monotony(daily_loads: List[float]) -> float:
    """
    Calcule la monotonie d'entraînement.
    Monotonie = Moyenne / Écart-type
    
    - < 1.5: Bonne variété
    - > 2.0: Trop monotone (risque surentraînement)
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
    Calcule la contrainte d'entraînement.
    Strain = Load × Monotony
    
    Indicateur de stress global sur l'organisme.
    """
    return round(weekly_load * monotony, 0)


# ============================================================
# PHASES DE PRÉPARATION
# ============================================================

def determine_phase(week: int, total_weeks: int) -> str:
    """
    Détermine la phase de préparation selon la semaine.
    
    Phases:
    - build: Construction de base (60% du cycle)
    - deload: Semaine de récupération (milieu de cycle)
    - intensification: Montée en intensité
    - taper: Affûtage pré-course (2 dernières semaines)
    - race: Semaine de course
    """
    if week >= total_weeks:
        return "race"
    
    if week >= total_weeks - 2:
        return "taper"
    
    # Semaine de décharge au milieu
    if week == total_weeks // 2:
        return "deload"
    
    # Semaine de décharge toutes les 4 semaines
    if week > 4 and week % 4 == 0:
        return "deload"
    
    if week < total_weeks * 0.6:
        return "build"
    
    return "intensification"


def get_phase_description(phase: str, lang: str = "en") -> Dict:
    """Return phase description and advice in the requested language."""
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
    phases = phases_en if lang == "en" else phases_fr
    return phases.get(phase, phases["build"])


# ============================================================
# AJUSTEMENT DE CHARGE
# ============================================================

def adjust_load_by_fatigue(base_load: float, tsb: float, acwr: float) -> float:
    """
    Ajuste la charge recommandée selon la fatigue.
    
    Règles:
    - ACWR > 1.3: Réduire de 15%
    - TSB < -20: Réduire de 10%
    - TSB > +10: Augmenter de 5%
    """
    adjusted = base_load
    
    # ACWR trop élevé = risque de blessure
    if acwr > ACWR_DANGER:
        adjusted *= 0.70  # Forte réduction
    elif acwr > ACWR_SAFE_MAX:
        adjusted *= 0.85
    
    # TSB très négatif = fatigue accumulée
    if tsb < TSB_FATIGUE_THRESHOLD:
        adjusted *= 0.90
    
    # TSB positif = fraîcheur, peut pousser un peu
    elif tsb > TSB_FRESH_THRESHOLD:
        adjusted *= 1.05
    
    return adjusted


def determine_target_load(context: Dict, phase: str) -> int:
    """
    Détermine la charge cible pour la semaine.
    
    Args:
        context: Données de fitness (ctl, atl, tsb, acwr)
        phase: Phase actuelle du cycle
        
    Returns:
        Charge cible en unités de charge (TSS/TRIMP)
    """
    ctl = context.get("ctl", 40)
    base = ctl
    
    # Multiplicateurs par phase
    phase_multipliers = {
        "build": 1.05,
        "deload": 0.75,
        "intensification": 1.10,
        "taper": 0.65,
        "race": 0.30
    }
    
    multiplier = phase_multipliers.get(phase, 1.0)
    base *= multiplier
    
    # Ajustement selon fatigue
    adjusted = adjust_load_by_fatigue(
        base,
        context.get("tsb", 0),
        context.get("acwr", 1.0)
    )
    
    return int(adjusted)


def determine_target_km(context: Dict, phase: str, goal: str = "10K") -> float:
    """
    Détermine le kilométrage cible pour la semaine.
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
    
    # Ajustement ACWR
    acwr = context.get("acwr", 1.0)
    if acwr > ACWR_SAFE_MAX:
        target *= 0.85
    
    return round(target, 1)


# ============================================================
# CONSTRUCTION DU CONTEXTE
# ============================================================

def build_training_context(
    fitness_data: Dict,
    weekly_km: float,
    daily_loads: List[float] = None
) -> Dict:
    """
    Construit le contexte d'entraînement complet.
    
    Args:
        fitness_data: Données de fitness (ctl, atl, load_7, load_28)
        weekly_km: Kilométrage hebdomadaire moyen
        daily_loads: Charges quotidiennes (pour monotonie)
        
    Returns:
        Contexte complet pour les recommandations
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
    
    # Ajouter monotonie si données disponibles
    if daily_loads:
        context["monotony"] = compute_monotony(daily_loads)
        context["strain"] = compute_strain(load_7, context["monotony"])
    
    # Évaluation du risque
    context["risk_level"] = evaluate_risk(acwr, tsb)
    
    return context


def evaluate_risk(acwr: float, tsb: float) -> str:
    """
    Évalue le niveau de risque de blessure/surentraînement.
    
    Returns:
        "low", "moderate", "high", "critical"
    """
    if acwr > ACWR_DANGER or tsb < -30:
        return "critical"
    
    if acwr > ACWR_SAFE_MAX or tsb < TSB_FATIGUE_THRESHOLD:
        return "high"
    
    if acwr < ACWR_SAFE_MIN:
        return "low"  # Sous-entraînement
    
    if tsb < -10:
        return "moderate"
    
    return "low"


# ============================================================
# RECOMMANDATIONS
# ============================================================

def generate_week_recommendation(
    context: Dict,
    phase: str,
    goal: str = "10K"
) -> Dict:
    """
    Génère les recommandations pour la semaine.
    """
    goal_config = GOAL_CONFIG.get(goal, GOAL_CONFIG["10K"])
    phase_info = get_phase_description(phase)
    
    target_load = determine_target_load(context, phase)
    target_km = determine_target_km(context, phase, goal)
    
    # Répartition recommandée
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
