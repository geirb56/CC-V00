"""
CardioCoach Analysis Engine
100% Backend, Deterministic, No LLM Dependencies
Strava API Compliant - No data leaves the infrastructure

RÈGLE DE PRIORITÉ DES DONNÉES (OBLIGATOIRE)
1. SI données de fréquence cardiaque disponibles : Analyse physiologique PRIORITAIRE
2. SI PAS de fréquence cardiaque : Analyse STRUCTURELLE uniquement (JAMAIS de fatigue/zones/surcharge)
"""

import random
from typing import Dict, List, Optional
from datetime import datetime, timezone


# ============================================================
# TEMPLATES DE TEXTES - FRANÇAIS (variés, ton coach humain)
# ============================================================

# --- RÉSUMÉ DU COACH (1 phrase courte) ---
SUMMARY_TEMPLATES_WITH_HR = {
    "easy": [
        "Sortie maîtrisée, avec une intensité bien contrôlée du début à la fin.",
        "Séance confortable, pensée pour accumuler du volume sans forcer.",
        "Sortie facile bien exécutée, parfaite pour la récupération active.",
        "Effort mesuré, exactement ce qu'il faut pour construire la base.",
    ],
    "moderate": [
        "Séance équilibrée avec un effort bien dosé.",
        "Sortie correctement menée, ni trop facile ni trop dure.",
        "Entraînement modéré qui construit la forme progressivement.",
        "Séance de travail solide, bon équilibre effort/récupération.",
    ],
    "hard": [
        "Séance soutenue, plus exigeante que tes sorties habituelles.",
        "Séance plus dense que la moyenne, avec un vrai engagement cardio.",
        "Effort soutenu aujourd'hui, le corps a bien travaillé.",
        "Sortie exigeante qui sollicite bien l'organisme.",
    ],
    "very_hard": [
        "Séance très intense, proche de tes limites.",
        "Gros effort fourni, le corps va avoir besoin de repos.",
        "Entraînement à haute intensité, récupère bien après ça.",
        "Sortie vraiment appuyée, tu as poussé fort.",
    ],
}

SUMMARY_TEMPLATES_WITHOUT_HR = {
    "short": [
        "Sortie courte mais utile pour maintenir le rythme.",
        "Séance brève, parfois c'est ce qu'il faut.",
        "Petit entraînement efficace.",
    ],
    "medium": [
        "Séance de volume correct cette sortie.",
        "Entraînement standard, bon pour la régularité.",
        "Sortie classique au compteur.",
    ],
    "long": [
        "Belle sortie longue pour développer l'endurance.",
        "Volume conséquent aujourd'hui, bon travail de fond.",
        "Séance longue réussie, ça construit la caisse.",
    ],
}

# --- EXÉCUTION DE LA SÉANCE ---
EXECUTION_TEMPLATES_WITH_HR = [
    "Ta fréquence cardiaque est restée majoritairement en zones {zones_dominantes}, ce qui correspond à un effort {qualificatif}.",
    "L'intensité a été {qualificatif} avec {pct_principal}% du temps en zone {zone_principale}.",
    "Répartition de l'effort : {pct_z1_z2}% en zones faciles, {pct_z3}% en tempo, {pct_z4_z5}% en zones hautes.",
    "FC moyenne de {fc_moy} bpm, majoritairement en {zones_dominantes}.",
]

EXECUTION_TEMPLATES_WITH_HR_HARD = [
    "La présence marquée en zones hautes ({pct_z4_z5}%) montre une séance clairement appuyée.",
    "Beaucoup de temps en Z4-Z5, l'intensité était au rendez-vous.",
    "L'effort est monté haut avec {pct_z4_z5}% du temps au-dessus du seuil.",
]

EXECUTION_TEMPLATES_WITH_HR_EASY = [
    "L'effort est resté en zones basses, parfait pour l'endurance fondamentale.",
    "Intensité bien maîtrisée avec {pct_z1_z2}% en zones faciles.",
    "FC sous contrôle tout au long de la séance.",
]

EXECUTION_TEMPLATES_WITHOUT_HR = [
    "La séance est homogène en durée et en allure.",
    "L'allure varie peu, ce qui montre une bonne régularité d'exécution.",
    "{distance_km} km parcourus en {duree} ({allure_moy}/km de moyenne).",
    "Sortie de {distance_km} km à {allure_moy}/km, durée {duree}.",
]

# --- CE QUE ÇA SIGNIFIE (lecture coach) ---
MEANING_TEMPLATES_WITH_HR = {
    "aerobic": [
        "Cette séance stimule clairement l'endurance aérobie.",
        "Tu as travaillé la base, c'est fondamental pour progresser.",
        "L'effort en zone facile développe le système cardiovasculaire en douceur.",
    ],
    "threshold": [
        "Cette séance travaille le seuil, c'est exigeant mais efficace.",
        "L'effort soutenu améliore ta capacité à tenir l'allure.",
        "Tu as sollicité le système lactique, ça fait progresser.",
    ],
    "mixed": [
        "L'effort était varié, bon pour la polyvalence.",
        "Tu as alterné les zones, c'est intéressant pour le corps.",
        "Séance mixte qui stimule plusieurs filières énergétiques.",
    ],
    "overload": [
        "C'est un type d'effort qui augmente la charge globale de la semaine.",
        "Séance exigeante qui crée un stimulus fort pour progresser.",
        "Le corps a été bien sollicité, il va s'adapter si tu récupères.",
    ],
}

MEANING_TEMPLATES_WITHOUT_HR = [
    "Cette séance augmente surtout ton volume d'entraînement.",
    "Elle s'inscrit comme une sortie structurante dans ta semaine.",
    "C'est du temps de jambes accumulé, ça compte.",
    "Sortie qui contribue à la régularité de l'entraînement.",
]

# --- RÉCUPÉRATION ---
RECOVERY_TEMPLATES_WITH_HR = {
    "needs_rest": [
        "Compte tenu de l'intensité, une récupération active ou une journée facile est recommandée.",
        "La charge de cette séance mérite d'être absorbée avant un nouvel effort soutenu.",
        "Après cet effort, une journée de repos ou très facile demain serait idéale.",
        "Laisse le temps à l'organisme d'absorber cette séance avant de forcer à nouveau.",
    ],
    "light_recovery": [
        "Une sortie facile demain aidera à bien récupérer.",
        "Récupération active conseillée : footing très léger ou repos.",
        "Pas de grosse séance demain, le corps doit assimiler.",
    ],
    "ready": [
        "Tu peux enchaîner demain si tu te sens bien.",
        "L'effort était gérable, tu as de la marge pour continuer.",
        "Bonne gestion, tu peux repartir sans problème.",
    ],
}

RECOVERY_TEMPLATES_WITHOUT_HR = [
    "Une récupération standard est suffisante si les sensations restent bonnes.",
    "Écoute ton corps pour ajuster la prochaine séance.",
    "Pas de recommandation particulière, adapte selon tes sensations.",
]

# --- CONSEIL DU COACH (OBLIGATOIRE, 1 phrase actionnable) ---
ADVICE_TEMPLATES = {
    "reduce_intensity": [
        "Sur la prochaine séance, vise une intensité plus basse pour équilibrer la charge.",
        "Baisse un peu l'intensité générale, tu forces beaucoup.",
        "Privilégie les sorties faciles cette semaine.",
    ],
    "maintain": [
        "Continue comme ça, la régularité paie sur le long terme.",
        "Garde ce rythme d'entraînement, c'est la clé de la progression.",
        "Tu es sur la bonne voie, reste constant.",
    ],
    "space_sessions": [
        "Garde ce type de séance, mais espace-la davantage dans la semaine.",
        "Laisse plus de récupération entre les séances soutenues.",
    ],
    "add_easy": [
        "Ajoute une sortie facile de 30-40 min en zone 2 cette semaine.",
        "Prévois une course tranquille pour équilibrer l'intensité.",
    ],
    "add_intensity": [
        "Tu pourrais intégrer une séance plus rythmée cette semaine.",
        "Une séance tempo ou fractionné court serait bénéfique.",
    ],
    "shorten": [
        "Si tu répètes ce format, limite légèrement la durée.",
        "Même effort mais un peu plus court la prochaine fois.",
    ],
}

# --- BILAN HEBDOMADAIRE ---
WEEKLY_SUMMARY_TEMPLATES = [
    "Semaine globalement bien maîtrisée, avec une charge en progression.",
    "Semaine dense, marquée par des efforts plus soutenus que d'habitude.",
    "Semaine équilibrée, sans excès notable.",
    "Bonne semaine d'entraînement avec {nb_seances} séances et {volume_km} km.",
    "Semaine solide : {nb_seances} sorties pour un total de {volume_km} km.",
]

WEEKLY_SUMMARY_LIGHT = [
    "Semaine légère avec {nb_seances} séance(s) et {volume_km} km.",
    "Volume réduit cette semaine, parfois nécessaire.",
    "Semaine tranquille côté entraînement.",
]

WEEKLY_SUMMARY_INTENSE = [
    "Semaine orientée intensité avec beaucoup de temps en zones hautes.",
    "L'intensité était au rendez-vous cette semaine.",
    "Semaine exigeante, le corps a été bien sollicité.",
]

WEEKLY_READING_TEMPLATES = {
    "balanced": [
        "La répartition effort facile/intense est bonne. Tu construis une base solide.",
        "Bon équilibre entre endurance et intensité cette semaine.",
        "L'entraînement est bien dosé, continue comme ça.",
    ],
    "too_intense": [
        "L'augmentation du volume combinée à une intensité plus élevée demande de la vigilance.",
        "L'intensité domine, le risque de fatigue augmente. Plus de Z2 nécessaire.",
        "Beaucoup de temps en zones hautes ({pct_z4_z5}%). Ajoute plus de sorties faciles.",
    ],
    "too_easy": [
        "Principalement en zone facile. C'est bien pour la base, mais un peu d'intensité aiderait.",
        "Semaine tranquille, tu peux te permettre une séance plus rythmée.",
    ],
    "good_continuity": [
        "La semaine montre une bonne continuité, sans rupture majeure.",
        "Bon enchaînement des séances, c'est ce qui fait progresser.",
    ],
}

WEEKLY_ADVICE_TEMPLATES = {
    "reduce": [
        "Allège légèrement l'intensité sur les prochaines sorties.",
        "Baisse le rythme quelques jours pour absorber la charge.",
    ],
    "maintain_reduce_hard": [
        "Garde le volume mais réduis les séances soutenues.",
        "Continue sur ce volume, en privilégiant les sorties faciles.",
    ],
    "maintain": [
        "Continue sur ce rythme, c'est efficace.",
        "Garde cette dynamique pour la semaine prochaine.",
    ],
    "add_volume": [
        "Tu peux ajouter une sortie supplémentaire la semaine prochaine.",
        "Augmente légèrement le volume si tu te sens frais.",
    ],
    "add_intensity": [
        "Une séance plus intense serait bénéfique.",
        "Ajoute un peu de rythme : tempo ou fractionné.",
    ],
    "recover": [
        "Semaine de récupération conseillée.",
        "Baisse le volume et l'intensité quelques jours.",
    ],
}


# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def has_hr_data(workout: dict) -> bool:
    """Check if workout has meaningful HR data"""
    zones = workout.get("effort_zone_distribution", {})
    avg_hr = workout.get("avg_heart_rate")
    
    # Must have either valid zones OR avg HR
    if zones and any(v and v > 0 for v in zones.values()):
        return True
    if avg_hr and avg_hr > 50:  # Basic sanity check
        return True
    return False


def calculate_intensity_from_zones(zones: dict) -> str:
    """
    Determine intensity level from HR zones using spec rules:
    - >70% in Z1-Z2 → easy
    - >30% in Z3 → moderate/sustained
    - >15% in Z4-Z5 → hard
    """
    if not zones:
        return None
    
    z1 = zones.get("z1", 0) or 0
    z2 = zones.get("z2", 0) or 0
    z3 = zones.get("z3", 0) or 0
    z4 = zones.get("z4", 0) or 0
    z5 = zones.get("z5", 0) or 0
    
    z1_z2 = z1 + z2
    z4_z5 = z4 + z5
    
    # Apply rules from spec
    if z4_z5 >= 40:
        return "very_hard"
    elif z4_z5 >= 15:
        return "hard"
    elif z3 >= 30:
        return "moderate"
    elif z1_z2 >= 70:
        return "easy"
    else:
        return "moderate"


def get_dominant_zones_label(zones: dict) -> str:
    """Get human-readable label for dominant zones"""
    if not zones:
        return "modérées"
    
    z1_z2 = (zones.get("z1", 0) or 0) + (zones.get("z2", 0) or 0)
    z3 = zones.get("z3", 0) or 0
    z4_z5 = (zones.get("z4", 0) or 0) + (zones.get("z5", 0) or 0)
    
    if z1_z2 >= 60:
        return "Z1-Z2 (faciles)"
    elif z4_z5 >= 40:
        return "Z4-Z5 (hautes)"
    elif z3 >= 40:
        return "Z3 (tempo)"
    elif z4_z5 >= 20:
        return "Z3-Z4 (soutenues)"
    else:
        return "intermédiaires"


def get_intensity_qualifier(intensity: str) -> str:
    """Get French qualifier for intensity level"""
    qualifiers = {
        "easy": "facile",
        "moderate": "modéré",
        "hard": "soutenu",
        "very_hard": "très intense"
    }
    return qualifiers.get(intensity, "modéré")


def calculate_session_type_structural(distance_km: float, duration_min: int) -> str:
    """Determine session type based on volume only (no HR)"""
    if duration_min >= 90 or distance_km >= 15:
        return "long"
    elif duration_min <= 25 or distance_km <= 4:
        return "short"
    return "medium"


def format_duration(minutes: int) -> str:
    """Format duration as Xh XXmin"""
    if not minutes:
        return "0min"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h{mins:02d}" if mins > 0 else f"{hours}h"
    return f"{mins}min"


def format_pace(pace_min_km: float) -> str:
    """Format pace as X:XX/km"""
    if not pace_min_km:
        return "-"
    total_seconds = round(pace_min_km * 60)
    mins = total_seconds // 60
    secs = total_seconds % 60
    return f"{mins}:{secs:02d}"


def pick(templates: list) -> str:
    """Select a random template from a list"""
    return random.choice(templates)


# ============================================================
# GÉNÉRATEUR D'ANALYSE DE SÉANCE
# ============================================================

def generate_session_analysis(workout: dict, baseline: dict = None, language: str = "en") -> dict:
    """
    Generate complete session analysis following mandatory structure.
    PRIORITÉ FC: Si données FC disponibles → analyse physiologique
    SINON: Analyse structurelle uniquement (JAMAIS de fatigue/zones/surcharge)
    """
    
    # Extract workout data
    distance_km = workout.get("distance_km", 0) or 0
    duration_min = workout.get("duration_minutes", 0) or 0
    avg_pace = workout.get("avg_pace_min_km")
    avg_hr = workout.get("avg_heart_rate")
    zones = workout.get("effort_zone_distribution", {})
    cadence = workout.get("avg_cadence_spm")
    workout_type = workout.get("type", "run")
    
    # Determine if we have HR data
    hr_available = has_hr_data(workout)
    
    # Calculate zone percentages
    z1_z2 = (zones.get("z1", 0) or 0) + (zones.get("z2", 0) or 0)
    z3 = zones.get("z3", 0) or 0
    z4_z5 = (zones.get("z4", 0) or 0) + (zones.get("z5", 0) or 0)
    
    # Build placeholders for templates
    placeholders = {
        "distance_km": round(distance_km, 1),
        "duree": format_duration(duration_min),
        "allure_moy": format_pace(avg_pace) if avg_pace else "-",
        "fc_moy": avg_hr or "-",
        "cadence": cadence or "-",
        "pct_z1_z2": round(z1_z2),
        "pct_z3": round(z3),
        "pct_z4_z5": round(z4_z5),
        "zones_dominantes": get_dominant_zones_label(zones),
        "pct_principal": max(z1_z2, z3, z4_z5),
        "zone_principale": "Z1-Z2" if z1_z2 >= max(z3, z4_z5) else ("Z4-Z5" if z4_z5 >= z3 else "Z3"),
    }
    
    # ============================================
    # MODE 1: AVEC DONNÉES FC (analyse physiologique)
    # ============================================
    if hr_available:
        intensity = calculate_intensity_from_zones(zones)
        placeholders["qualificatif"] = get_intensity_qualifier(intensity)
        
        # 1. RÉSUMÉ DU COACH
        summary = pick(SUMMARY_TEMPLATES_WITH_HR.get(intensity, SUMMARY_TEMPLATES_WITH_HR["moderate"]))
        
        # 2. EXÉCUTION
        if intensity in ["hard", "very_hard"]:
            execution = pick(EXECUTION_TEMPLATES_WITH_HR_HARD).format(**placeholders)
        elif intensity == "easy":
            execution = pick(EXECUTION_TEMPLATES_WITH_HR_EASY).format(**placeholders)
        else:
            execution = pick(EXECUTION_TEMPLATES_WITH_HR).format(**placeholders)
        
        # 3. CE QUE ÇA SIGNIFIE
        if z1_z2 >= 70:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["aerobic"])
        elif z4_z5 >= 25:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["threshold"])
        elif z4_z5 >= 15 or duration_min >= 60:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["overload"])
        else:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["mixed"])
        
        # 4. RÉCUPÉRATION
        if intensity == "very_hard" or (intensity == "hard" and duration_min >= 60):
            recovery = pick(RECOVERY_TEMPLATES_WITH_HR["needs_rest"])
        elif intensity == "hard":
            recovery = pick(RECOVERY_TEMPLATES_WITH_HR["light_recovery"])
        else:
            recovery = pick(RECOVERY_TEMPLATES_WITH_HR["ready"])
        
        # 5. CONSEIL DU COACH
        if intensity == "very_hard":
            advice = pick(ADVICE_TEMPLATES["reduce_intensity"])
        elif intensity == "hard" and z1_z2 < 30:
            advice = pick(ADVICE_TEMPLATES["space_sessions"])
        elif intensity == "easy" and z4_z5 < 5:
            advice = pick(ADVICE_TEMPLATES["add_intensity"])
        elif duration_min >= 90:
            advice = pick(ADVICE_TEMPLATES["shorten"])
        else:
            advice = pick(ADVICE_TEMPLATES["maintain"])
    
    # ============================================
    # MODE 2: SANS FC (analyse structurelle UNIQUEMENT)
    # ============================================
    else:
        session_type = calculate_session_type_structural(distance_km, duration_min)
        
        # 1. RÉSUMÉ DU COACH
        summary = pick(SUMMARY_TEMPLATES_WITHOUT_HR.get(session_type, SUMMARY_TEMPLATES_WITHOUT_HR["medium"]))
        
        # 2. EXÉCUTION
        execution = pick(EXECUTION_TEMPLATES_WITHOUT_HR).format(**placeholders)
        
        # 3. CE QUE ÇA SIGNIFIE
        meaning = pick(MEANING_TEMPLATES_WITHOUT_HR)
        
        # 4. RÉCUPÉRATION (sans parler de fatigue/charge)
        recovery = pick(RECOVERY_TEMPLATES_WITHOUT_HR)
        
        # 5. CONSEIL DU COACH
        if duration_min >= 90:
            advice = pick(ADVICE_TEMPLATES["shorten"])
        elif duration_min <= 25:
            advice = pick(ADVICE_TEMPLATES["add_easy"])
        else:
            advice = pick(ADVICE_TEMPLATES["maintain"])
        
        intensity = None
    
    return {
        "summary": summary,
        "execution": execution,
        "meaning": meaning,
        "recovery": recovery,
        "advice": advice,
        "metrics": {
            "intensity_level": intensity,
            "session_type": calculate_session_type_structural(distance_km, duration_min),
            "has_hr_data": hr_available,
            "zones": {
                "easy": round(z1_z2),
                "moderate": round(z3),
                "hard": round(z4_z5)
            } if hr_available else None
        }
    }


# ============================================================
# GÉNÉRATEUR DE BILAN HEBDOMADAIRE
# ============================================================

def generate_weekly_review(
    workouts: List[dict],
    previous_week_workouts: List[dict] = None,
    user_goal: dict = None,
    language: str = "en"
) -> dict:
    """
    Generate weekly review ("Bilan de la semaine") following mandatory 6-bloc structure.
    """
    
    if not workouts:
        return {
            "summary": "Aucune séance cette semaine.",
            "meaning": "Une semaine de repos complet, parfois nécessaire.",
            "recovery": "Tu es probablement bien reposé.",
            "advice": "Reprends doucement avec une sortie facile.",
            "metrics": {"total_sessions": 0, "total_km": 0, "total_duration_min": 0}
        }
    
    # Calculate weekly metrics
    nb_seances = len(workouts)
    volume_km = round(sum(w.get("distance_km", 0) or 0 for w in workouts), 1)
    total_duration = sum(w.get("duration_minutes", 0) or 0 for w in workouts)
    
    # Check if we have HR data for the week
    workouts_with_hr = [w for w in workouts if has_hr_data(w)]
    hr_available = len(workouts_with_hr) >= len(workouts) * 0.5  # At least 50% with HR
    
    # Calculate average zones if HR available
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    
    for w in workouts_with_hr:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z in ["z1", "z2", "z3", "z4", "z5"]:
                zone_totals[z] += zones.get(z, 0) or 0
            zone_count += 1
    
    avg_zones = {z: round(v / zone_count) if zone_count > 0 else 0 for z, v in zone_totals.items()}
    z1_z2 = avg_zones["z1"] + avg_zones["z2"]
    z4_z5 = avg_zones["z4"] + avg_zones["z5"]
    
    # Compare to previous week
    prev_volume = sum(w.get("distance_km", 0) or 0 for w in previous_week_workouts) if previous_week_workouts else 0
    volume_change = round(((volume_km - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0)
    
    placeholders = {
        "nb_seances": nb_seances,
        "volume_km": volume_km,
        "duree_totale": format_duration(total_duration),
        "pct_z1_z2": round(z1_z2),
        "pct_z4_z5": round(z4_z5),
    }
    
    # ========================================
    # 1. SYNTHÈSE DU COACH (1 phrase)
    # ========================================
    if volume_km < 15 or nb_seances <= 1:
        summary = pick(WEEKLY_SUMMARY_LIGHT).format(**placeholders)
    elif hr_available and z4_z5 >= 30:
        summary = pick(WEEKLY_SUMMARY_INTENSE)
    else:
        summary = pick(WEEKLY_SUMMARY_TEMPLATES).format(**placeholders)
    
    # ========================================
    # 2. SIGNAUX CLÉS (built in signals dict)
    # ========================================
    signals = {
        "volume": "bas" if volume_km < 20 else ("élevé" if volume_km > 50 else "modéré"),
        "regularity": "stable" if nb_seances >= 3 else "variable"
    }
    
    # ONLY add intensity if HR available
    if hr_available:
        signals["intensity"] = "élevée" if z4_z5 >= 30 else ("basse" if z1_z2 >= 75 else "modérée")
    
    # ========================================
    # 3. CHIFFRES ESSENTIELS (in metrics)
    # ========================================
    metrics = {
        "total_sessions": nb_seances,
        "total_km": volume_km,
        "total_duration_min": total_duration,
        "volume_change_pct": volume_change
    }
    
    if hr_available:
        metrics["avg_zones"] = avg_zones
    
    # ========================================
    # 4. LECTURE DU COACH (2 phrases max)
    # ========================================
    if hr_available:
        if z4_z5 >= 35:
            meaning = pick(WEEKLY_READING_TEMPLATES["too_intense"]).format(**placeholders)
        elif z1_z2 >= 80 and z4_z5 < 10:
            meaning = pick(WEEKLY_READING_TEMPLATES["too_easy"])
        else:
            meaning = pick(WEEKLY_READING_TEMPLATES["balanced"])
    else:
        meaning = pick(WEEKLY_READING_TEMPLATES["good_continuity"])
    
    # ========================================
    # 5. PRÉCONISATIONS (OBLIGATOIRE)
    # ========================================
    if hr_available and z4_z5 >= 35:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["reduce"])
    elif hr_available and z4_z5 >= 25 and volume_km > 40:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["maintain_reduce_hard"])
    elif hr_available and z1_z2 >= 85 and z4_z5 < 10:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["add_intensity"])
    elif volume_km < 20 and nb_seances < 3:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["add_volume"])
    elif volume_km > 60:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["recover"])
    else:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["maintain"])
    
    # Add goal context if present
    if user_goal and user_goal.get("event_name"):
        try:
            event_date = datetime.fromisoformat(user_goal["event_date"]).date()
            today = datetime.now(timezone.utc).date()
            days_until = (event_date - today).days
            if days_until and days_until > 0:
                advice += f" Objectif {user_goal['event_name']} dans {days_until} jours."
        except:
            pass
    
    # ========================================
    # 6. Recovery suggestion
    # ========================================
    if hr_available and z4_z5 >= 30:
        recovery = pick(RECOVERY_TEMPLATES_WITH_HR["needs_rest"])
    elif volume_km > 50:
        recovery = pick(RECOVERY_TEMPLATES_WITH_HR["light_recovery"])
    else:
        recovery = pick(RECOVERY_TEMPLATES_WITH_HR["ready"])
    
    return {
        "summary": summary,
        "meaning": meaning,
        "recovery": recovery,
        "advice": advice,
        "metrics": metrics,
        "signals": [
            {
                "key": "load",
                "label": "Volume",
                "status": "up" if volume_change > 15 else "down" if volume_change < -15 else "stable",
                "value": f"{volume_change:+d}%" if volume_change != 0 else "="
            },
            {
                "key": "intensity",
                "label": "Intensité",
                "status": signals.get("intensity", "N/A"),
                "value": f"{z4_z5}% Z4-Z5" if hr_available else "N/A"
            },
            {
                "key": "consistency",
                "label": "Régularité",
                "status": "high" if nb_seances >= 4 else "moderate" if nb_seances >= 2 else "low",
                "value": f"{nb_seances} séances"
            }
        ]
    }


# ============================================================
# GÉNÉRATEUR D'INSIGHT DASHBOARD
# ============================================================

def generate_dashboard_insight(
    week_stats: dict,
    month_stats: dict,
    recovery_score: int = None,
    language: str = "en"
) -> str:
    """Generate single dashboard insight sentence without LLM"""
    
    sessions = week_stats.get("sessions", 0)
    volume = week_stats.get("volume_km", 0)
    
    if sessions == 0:
        return pick([
            "Pas encore de séance cette semaine, c'est le moment de s'y mettre.",
            "Semaine vierge pour l'instant, une sortie facile serait parfaite.",
            "Aucune activité cette semaine, le corps est reposé.",
        ])
    elif sessions == 1:
        return pick([
            "Une séance cette semaine, bon début. Continue sur cette lancée.",
            "Première sortie faite, ajoute une sortie facile.",
            "C'est parti pour la semaine avec une séance au compteur.",
        ])
    elif volume > 40:
        return pick([
            "Belle charge cette semaine, pense à bien récupérer.",
            "Volume conséquent, le corps travaille dur.",
            "Grosse semaine en cours, écoute ton corps.",
        ])
    elif recovery_score and recovery_score < 50:
        return pick([
            "Récupération correcte, privilégie une séance facile.",
            "Corps un peu fatigué, pas de forcing aujourd'hui.",
            "Récupération en cours, reste tranquille.",
        ])
    else:
        return pick([
            "Entraînement en cours, continue comme ça.",
            "Bonne dynamique cette semaine, garde le rythme.",
            "Tu avances bien, reste régulier.",
        ])
