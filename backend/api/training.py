from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Dict
import logging
from datetime import datetime, timezone, timedelta

from database import db
from models import TrainingGoalRequest, TrainingGoalResponse
from api.deps import auth_user
from training_engine import GOAL_CONFIG, compute_week_number, compute_acwr, determine_phase, get_phase_description, build_training_context, generate_week_recommendation
from coach_service import generate_dynamic_training_plan
from llm_coach import generate_cycle_week

router = APIRouter()
logger = logging.getLogger(__name__)


def _generate_fallback_week_plan(context: dict, phase: str, target_load: int, goal: str) -> dict:
    """Génère un plan de secours basé sur des templates."""
    weekly_km = context.get("weekly_km", 30)
    
    # Ajuster selon la phase
    phase_multipliers = {
        "build": 1.0,
        "deload": 0.7,
        "intensification": 1.05,
        "taper": 0.6,
        "race": 0.25
    }
    adjusted_km = weekly_km * phase_multipliers.get(phase, 1.0)
    
    # Allures de référence (à personnaliser selon le profil utilisateur)
    # Format: allure en min:sec/km
    paces = {
        "z1": "6:30-7:00",  # Récupération
        "z2": "5:45-6:15",  # Endurance fondamentale
        "z3": "5:15-5:30",  # Tempo / Allure marathon
        "z4": "4:45-5:00",  # Seuil
        "z5": "4:15-4:30",  # VMA
        "semi": "5:00-5:15", # Allure semi-marathon
        "10k": "4:40-4:55",  # Allure 10K
    }
    
    # FC cibles (à personnaliser selon FC max utilisateur ~185 bpm)
    hr_zones = {
        "z1": "120-135",
        "z2": "135-150", 
        "z3": "150-165",
        "z4": "165-175",
        "z5": "175-185",
    }
    
    # Templates par phase avec détails enrichis
    if phase == "deload":
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements ou yoga", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "30min", "details": f"5 km • {paces['z1']}/km • FC {hr_zones['z1']} bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 5},
            {"day": "Mercredi", "type": "Repos", "duration": "0min", "details": "Récupération active • Marche ou natation légère", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Jeudi", "type": "Endurance", "duration": "35min", "details": f"6 km • {paces['z2']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": 6},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Sommeil prioritaire", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Endurance", "duration": "40min", "details": f"7 km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 35, "distance_km": 7},
            {"day": "Dimanche", "type": "Repos", "duration": "0min", "details": "Récupération complète • Prépare la semaine suivante", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    elif phase == "taper":
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Hydratation ++", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "30min", "details": f"5 km + 4×100m vite • {paces['z2']}/km puis sprint • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": 5.5},
            {"day": "Mercredi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Préparation mentale", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Jeudi", "type": "Tempo court", "duration": "25min", "details": f"4 km dont 2 km à allure course • {paces['semi']}/km • FC {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": 35, "distance_km": 4},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Repos total • Dernière préparation équipement", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Activation", "duration": "20min", "details": f"3 km + 3×200m allure course • {paces['z2']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 3.6},
            {"day": "Dimanche", "type": "Repos", "duration": "0min", "details": "VEILLE DE COURSE • Repos total, alimentation glucides", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    else:  # build, intensification
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements recommandés", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "50min", "details": f"8 km • {paces['z2']}/km • FC {hr_zones['z2']} bpm • Zone 2 stricte", "intensity": "easy", "estimated_tss": 50, "distance_km": 8},
            {"day": "Mercredi", "type": "Seuil", "duration": "40min", "details": f"7 km dont 20min à {paces['z4']}/km • FC {hr_zones['z4']} bpm • Récup 2min entre blocs", "intensity": "hard", "estimated_tss": 55, "distance_km": 7},
            {"day": "Jeudi", "type": "Récupération", "duration": "30min", "details": f"5 km très léger • {paces['z1']}/km • FC <{hr_zones['z1'].split('-')[1]} bpm max", "intensity": "easy", "estimated_tss": 25, "distance_km": 5},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Cross-training possible (vélo, natation)", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Tempo", "duration": "45min", "details": f"8 km dont 25min à {paces['semi']}/km • FC {hr_zones['z3']} bpm • Allure semi-marathon", "intensity": "moderate", "estimated_tss": 60, "distance_km": 8},
            {"day": "Dimanche", "type": "Sortie longue", "duration": "70min", "details": f"12 km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr_zones['z2']} → {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": 45, "distance_km": 12},
        ]
    
    total_tss = sum(s["estimated_tss"] for s in sessions)
    total_km = sum(s.get("distance_km", 0) for s in sessions)
    
    return {
        "focus": phase,
        "planned_load": target_load,
        "weekly_km": round(total_km, 1),
        "sessions": sessions,
        "total_tss": total_tss,
        "advice": get_phase_description(phase).get("advice", "Continue sur ta lancée !")
    }


@router.post("/training/set-goal")
async def set_training_goal(
    goal: str = Query(..., description="10K | SEMI | MARATHON"),
    user: dict = Depends(auth_user)
):
    """
    Définit l'objectif principal du cycle.
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        return {"error": "Invalid goal"}
    
    goal_upper = goal.upper()
    
    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "goal": goal_upper,
            "start_date": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    logger.info(f"[Training] Goal set for user {user['id']}: {goal_upper}")
    
    return {"status": "updated", "goal": goal_upper}


@router.get("/training/plan")
async def get_training_plan_v2(user: dict = Depends(auth_user)):
    """
    Génère ou met à jour le plan d'entraînement dynamique
    selon les dernières données fitness.
    """
    return await generate_dynamic_training_plan(db, user["id"])


@router.post("/training/refresh")
async def refresh_training_plan(sessions: int = None, user: dict = Depends(auth_user)):
    """
    Force le recalcul complet du plan
    (après sync Strava par exemple).
    sessions: nombre de séances souhaitées (3, 4, 5, 6)
    """
    # Vider le cache pour cet utilisateur
    from coach_service import _plan_cache
    keys_to_remove = [k for k in _plan_cache if user["id"] in k]
    for k in keys_to_remove:
        del _plan_cache[k]
    
    # Sauvegarder le nombre de séances si spécifié
    if sessions and sessions in [3, 4, 5, 6]:
        await db.training_prefs.update_one(
            {"user_id": user["id"]},
            {"$set": {"sessions_per_week": sessions}},
            upsert=True
        )
    
    return await generate_dynamic_training_plan(db, user["id"], sessions_override=sessions)


@router.delete("/training/goal")
async def delete_training_goal(user_id: str = "default"):
    """Supprime l'objectif d'entraînement"""
    
    result = await db.training_goals.delete_one({"user_id": user_id})
    await db.training_context.delete_one({"user_id": user_id})
    await db.training_cycles.delete_one({"user_id": user_id})
    
    return {
        "success": result.deleted_count > 0,
        "message": "Objectif supprimé" if result.deleted_count > 0 else "Aucun objectif trouvé"
    }


@router.get("/training-plan")
async def get_training_plan(user: dict = Depends(auth_user)):
    """
    Récupère le plan d'entraînement dynamique pour l'utilisateur.
    Génère automatiquement les séances via LLM basé sur le cycle.
    """
    return await generate_dynamic_training_plan(db, user["id"])


@router.post("/training-plan/set-goal")
async def set_training_plan_goal(goal: str, user: dict = Depends(auth_user)):
    """
    Définit l'objectif d'entraînement (10K, SEMI, MARATHON, etc.)
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        return {"error": "Invalid goal"}
    
    goal_upper = goal.upper()
    config = GOAL_CONFIG[goal_upper]
    
    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "goal": goal_upper,
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    logger.info(f"[Training] Goal updated for user {user['id']}: {goal_upper}")
    
    return {
        "status": "updated",
        "goal": goal_upper,
        "cycle_weeks": config["cycle_weeks"],
        "description": config["description"]
    }


# Garder l'ancien endpoint pour compatibilité
@router.get("/training/dynamic-plan")
async def get_dynamic_training_plan_legacy(user_id: str = "default"):
    """Legacy endpoint - utiliser /training-plan à la place"""
    return await generate_dynamic_training_plan(db, user_id)


@router.get("/training/goals")
async def get_available_goals():
    """Liste les types d'objectifs disponibles"""
    return {
        "goals": [
            {
                "type": goal_type,
                "description": config["description"],
                "cycle_weeks": config["cycle_weeks"],
                "long_run_ratio": config["long_run_ratio"],
                "intensity_pct": config["intensity_pct"]
            }
            for goal_type, config in GOAL_CONFIG.items()
        ]
    }


@router.get("/training/metrics")
async def get_training_metrics(user: dict = Depends(auth_user)):
    """
    Retourne les métriques d'entraînement: ACWR, TSB, charge, monotonie.
    Utilisé par le Dashboard pour afficher l'état de forme.
    """
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    # Récupérer les activités Strava
    activities_7 = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    activities_28 = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)
    
    # Fallback sur workouts manuels si pas de Strava
    if not activities_28:
        activities_7 = await db.workouts.find({
            "date": {"$gte": seven_days_ago.isoformat()}
        }).to_list(100)
        activities_28 = await db.workouts.find({
            "date": {"$gte": twenty_eight_days_ago.isoformat()}
        }).to_list(300)
    
    # Calculer les charges (en km, simplifié)
    def get_distance(a):
        dist = a.get("distance", 0)
        if dist > 1000:  # Strava retourne en mètres
            return dist / 1000
        return a.get("distance_km", dist)
    
    load_7 = sum(get_distance(a) for a in activities_7)
    load_28 = sum(get_distance(a) for a in activities_28)
    
    # ACWR
    chronic_avg = load_28 / 4 if load_28 > 0 else 1
    acwr = round(load_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    
    # TSB simplifié (basé sur la différence entre charge récente et moyenne)
    # CTL = moyenne mobile sur 42 jours (approximé par 28j/4*6)
    # ATL = moyenne mobile sur 7 jours
    ctl = load_28 / 4  # Approximation fitness
    atl = load_7  # Fatigue récente
    tsb = round(ctl - atl, 1)
    
    # Calculer la monotonie (7 derniers jours)
    daily_loads = []
    for i in range(7):
        day = (today - timedelta(days=i)).date()
        day_load = 0
        for a in activities_7:
            try:
                a_date_str = a.get("start_date_local", a.get("date", ""))
                if a_date_str:
                    a_date = datetime.fromisoformat(a_date_str.replace("Z", "+00:00")).date()
                    if a_date == day:
                        day_load += get_distance(a)
            except:
                pass
        daily_loads.append(day_load)
    
    # Monotonie = moyenne / écart-type
    if daily_loads and len(daily_loads) >= 2:
        avg_load = sum(daily_loads) / len(daily_loads)
        variance = sum((x - avg_load) ** 2 for x in daily_loads) / len(daily_loads)
        std = variance ** 0.5
        monotony = round(avg_load / std, 2) if std > 0 else 0
    else:
        monotony = 0
    
    # Strain = Load * Monotony
    strain = round(load_7 * monotony, 0) if monotony > 0 else 0
    
    # Interpréter ACWR
    if acwr < 0.8:
        acwr_status = "low"
        acwr_label = "Sous-entraînement"
    elif acwr <= 1.3:
        acwr_status = "optimal"
        acwr_label = "Zone optimale"
    elif acwr <= 1.5:
        acwr_status = "warning"
        acwr_label = "Zone à risque"
    else:
        acwr_status = "danger"
        acwr_label = "Danger"
    
    # Interpréter TSB
    if tsb > 10:
        tsb_status = "fresh"
        tsb_label = "Très frais"
    elif tsb > 0:
        tsb_status = "ready"
        tsb_label = "Prêt"
    elif tsb > -10:
        tsb_status = "training"
        tsb_label = "En charge"
    else:
        tsb_status = "fatigued"
        tsb_label = "Fatigué"
    
    return {
        "acwr": acwr,
        "acwr_status": acwr_status,
        "acwr_label": acwr_label,
        "tsb": tsb,
        "tsb_status": tsb_status,
        "tsb_label": tsb_label,
        "load_7": round(load_7, 1),
        "load_28": round(load_28, 1),
        "monotony": monotony,
        "strain": strain,
        "ctl": round(ctl, 1),
        "atl": round(atl, 1)
    }


@router.get("/training/race-predictions")
async def get_race_predictions(user: dict = Depends(auth_user)):
    """
    Prédit les temps de course pour 5K, 10K, Semi, Marathon, Ultra
    basé sur le profil d'entraînement de l'athlète.
    Utilise une fenêtre de 6 semaines (42 jours) pour la VMA.
    """
    today = datetime.now(timezone.utc)
    six_weeks_ago = today - timedelta(days=42)  # 6 semaines comme pour VO2MAX
    
    # Récupérer les activités des 6 dernières semaines
    activities = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": six_weeks_ago.isoformat()}
    }).to_list(500)
    
    if not activities:
        activities = await db.workouts.find({
            "date": {"$gte": six_weeks_ago.isoformat()}
        }).to_list(500)
    
    if not activities:
        return {
            "has_data": False,
            "message": "Pas assez de données pour prédire. Continue à t'entraîner !",
            "predictions": []
        }
    
    # Extraire les métriques clés
    def get_distance(a):
        dist = a.get("distance", 0)
        if dist > 1000:
            return dist / 1000
        return a.get("distance_km", dist)
    
    def get_duration_minutes(a):
        """Retourne la durée en minutes"""
        # Strava: moving_time en secondes
        moving_time = a.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        # Fallback: elapsed_time
        elapsed = a.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        # Fallback: duration_minutes
        return a.get("duration_minutes", 0)
    
    def get_pace(a):
        # Pace en min/km
        pace = a.get("avg_pace_min_km")
        if pace:
            return pace
        # Calculer depuis vitesse moyenne (m/s)
        speed = a.get("average_speed", 0)
        if speed > 0:
            return (1000 / speed) / 60
        # Calculer depuis distance/durée
        dist = get_distance(a)
        duration_min = get_duration_minutes(a)
        if dist > 0 and duration_min > 0:
            return duration_min / dist
        return None
    
    # Collecter les données
    total_km = 0
    total_sessions = 0
    paces = []
    long_runs = []  # Sorties > 15km
    vma_efforts = []  # Efforts >= 6 min pour calcul VMA
    distances = []
    
    MIN_VMA_DURATION = 6  # Minutes minimum pour calcul VMA
    
    for a in activities:
        dist = get_distance(a)
        pace = get_pace(a)
        duration_min = get_duration_minutes(a)
        
        if dist > 0:
            total_km += dist
            total_sessions += 1
            distances.append(dist)
            
            if pace and 3 < pace < 10:  # Pace réaliste
                paces.append(pace)
                
                # Pour la VMA : effort >= 6 minutes ET allure rapide (< 5:30/km)
                if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                    vma_efforts.append({
                        "distance": dist, 
                        "pace": pace, 
                        "duration": duration_min,
                        "speed_kmh": 60 / pace
                    })
                
                if dist >= 15:  # Sortie longue
                    long_runs.append({"distance": dist, "pace": pace})
    
    if not paces:
        return {
            "has_data": False,
            "message": "Pas assez de données d'allure. Assure-toi que tes séances ont des données GPS.",
            "predictions": []
        }
    
    # Calculer les métriques de base
    weekly_km = total_km / 6  # 6 semaines
    avg_pace = sum(paces) / len(paces)
    best_pace = min(paces) if paces else avg_pace
    max_long_run = max(distances) if distances else 0
    
    # Estimer la VMA (Vitesse Maximale Aérobie)
    # Basé sur les efforts >= 6 minutes (physiologiquement représentatif)
    vma_method = "estimated"
    
    if vma_efforts:
        # Prendre le meilleur effort de >= 6 minutes
        best_vma_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
        best_sustained_speed = best_vma_effort["speed_kmh"]
        
        # La VMA est environ 5-10% au-dessus de l'allure soutenue sur 6+ min
        # Plus l'effort est long, plus on est proche de la VMA
        duration = best_vma_effort["duration"]
        if duration >= 20:
            # Effort long (20+ min) = environ 85% VMA → VMA = vitesse / 0.85
            estimated_vma = best_sustained_speed / 0.85
        elif duration >= 12:
            # Effort moyen (12-20 min) = environ 90% VMA
            estimated_vma = best_sustained_speed / 0.90
        else:
            # Effort court (6-12 min) = environ 95% VMA
            estimated_vma = best_sustained_speed / 0.95
        
        vma_method = f"effort_{int(duration)}min"
    else:
        # Pas d'effort rapide >= 6 min, estimation depuis allure moyenne
        # L'allure moyenne d'endurance est environ 70% VMA
        avg_speed_kmh = 60 / avg_pace
        estimated_vma = avg_speed_kmh / 0.70
        vma_method = "from_avg_pace"
    
    # Prédictions basées sur VMA et volume
    predictions = []
    
    # Facteurs de prédiction par distance
    race_configs = [
        {
            "distance": "5K",
            "km": 5,
            "vma_pct": 0.95,  # 5K = ~95% VMA
            "min_weekly_km": 15,
            "min_long_run": 8,
            "description": "5 kilomètres"
        },
        {
            "distance": "10K",
            "km": 10,
            "vma_pct": 0.90,  # 10K = ~90% VMA
            "min_weekly_km": 25,
            "min_long_run": 12,
            "description": "10 kilomètres"
        },
        {
            "distance": "Semi",
            "km": 21.1,
            "vma_pct": 0.82,  # Semi = ~82% VMA
            "min_weekly_km": 35,
            "min_long_run": 18,
            "description": "Semi-marathon"
        },
        {
            "distance": "Marathon",
            "km": 42.195,
            "vma_pct": 0.75,  # Marathon = ~75% VMA
            "min_weekly_km": 50,
            "min_long_run": 30,
            "description": "Marathon"
        },
        {
            "distance": "Ultra",
            "km": 50,
            "vma_pct": 0.65,  # Ultra = ~65% VMA
            "min_weekly_km": 70,
            "min_long_run": 35,
            "description": "Ultra-trail (50km)"
        }
    ]
    
    for config in race_configs:
        # Vitesse de course prédite
        race_speed = estimated_vma * config["vma_pct"]
        race_pace = 60 / race_speed  # min/km
        
        # Temps prédit
        predicted_minutes = config["km"] * race_pace
        
        # Ajuster selon le volume d'entraînement
        volume_factor = min(1.0, weekly_km / config["min_weekly_km"])
        if volume_factor < 0.7:
            # Volume insuffisant = temps plus lent
            predicted_minutes *= (1 + (1 - volume_factor) * 0.15)
        
        # Ajuster selon sortie longue max
        endurance_factor = min(1.0, max_long_run / config["min_long_run"])
        if endurance_factor < 0.8 and config["km"] > 10:
            predicted_minutes *= (1 + (1 - endurance_factor) * 0.10)
        
        # Formater le temps
        hours = int(predicted_minutes // 60)
        mins = int(predicted_minutes % 60)
        secs = int((predicted_minutes % 1) * 60)
        
        if hours > 0:
            time_str = f"{hours}h{mins:02d}"
            time_range = f"{hours}h{max(0,mins-3):02d} - {hours}h{mins+5:02d}"
        else:
            time_str = f"{mins}:{secs:02d}"
            time_range = f"{max(0,mins-2)}:{secs:02d} - {mins+3}:{secs:02d}"
        
        # Évaluer la capacité
        readiness_score = (volume_factor * 0.5 + endurance_factor * 0.5) * 100
        
        if readiness_score >= 80:
            readiness = "ready"
            readiness_label = "Prêt"
            readiness_color = "#22c55e"
        elif readiness_score >= 60:
            readiness = "possible"
            readiness_label = "Possible"
            readiness_color = "#f59e0b"
        elif readiness_score >= 40:
            readiness = "challenging"
            readiness_label = "Ambitieux"
            readiness_color = "#f97316"
        else:
            readiness = "not_ready"
            readiness_label = "Pas prêt"
            readiness_color = "#ef4444"
        
        # Allure prédite formatée
        pace_mins = int(race_pace)
        pace_secs = int((race_pace % 1) * 60)
        pace_str = f"{pace_mins}:{pace_secs:02d}/km"
        
        predictions.append({
            "distance": config["distance"],
            "distance_km": config["km"],
            "description": config["description"],
            "predicted_time": time_str,
            "predicted_range": time_range,
            "predicted_pace": pace_str,
            "readiness": readiness,
            "readiness_label": readiness_label,
            "readiness_color": readiness_color,
            "readiness_score": round(readiness_score),
            "volume_factor": round(volume_factor * 100),
            "endurance_factor": round(endurance_factor * 100)
        })
    
    return {
        "has_data": True,
        "athlete_profile": {
            "weekly_km": round(weekly_km, 1),
            "avg_pace": f"{int(avg_pace)}:{int((avg_pace % 1) * 60):02d}/km",
            "best_pace": f"{int(best_pace)}:{int((best_pace % 1) * 60):02d}/km",
            "max_long_run": round(max_long_run, 1),
            "estimated_vma": round(estimated_vma, 1),
            "estimated_vo2max": round(estimated_vma * 3.5, 1),
            "vma_method": vma_method,
            "vma_efforts_count": len(vma_efforts),
            "total_sessions_6w": total_sessions,
            "calculation_window": "6 weeks"
        },
        "predictions": predictions,
        "methodology": {
            "vma_min_duration": f"{MIN_VMA_DURATION} min",
            "vma_calculation": "Basé sur le meilleur effort ≥ 6 min. Effort 6-12min = ~95% VMA, 12-20min = ~90% VMA, 20+min = ~85% VMA.",
            "vo2max_formula": "VO2MAX (ml/kg/min) = VMA (km/h) × 3.5",
            "note": "Les prédictions sont des estimations. Un test VMA réel ou des temps de course donnent des prédictions plus précises."
        }
    }


@router.get("/training/vma-history")
async def get_vma_history(user: dict = Depends(auth_user)):
    """
    Retourne l'historique du VO2MAX sur les 12 derniers mois.
    2 points par mois (1ère et 2ème quinzaine).
    VO2MAX (ml/kg/min) = VMA (km/h) × 3.5
    """
    today = datetime.now(timezone.utc)
    twelve_months_ago = today - timedelta(days=365)
    
    # Récupérer toutes les activités des 12 derniers mois
    activities = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": twelve_months_ago.isoformat()}
    }).to_list(2000)
    
    if not activities:
        activities = await db.workouts.find({
            "date": {"$gte": twelve_months_ago.isoformat()}
        }).to_list(2000)
    
    if not activities:
        return {"has_data": False, "history": []}
    
    # Helper functions
    def get_distance(a):
        dist = a.get("distance", 0)
        if dist > 1000:
            return dist / 1000
        return a.get("distance_km", dist)
    
    def get_duration(a):
        moving_time = a.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        elapsed = a.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        return a.get("duration_minutes", 0)
    
    def get_pace(a):
        pace = a.get("avg_pace_min_km")
        if pace:
            return pace
        speed = a.get("average_speed", 0)
        if speed > 0:
            return (1000 / speed) / 60
        dist = get_distance(a)
        duration_min = get_duration(a)
        if dist > 0 and duration_min > 0:
            return duration_min / dist
        return None
    
    def get_activity_date(a):
        date_str = a.get("start_date_local", a.get("date", ""))
        if date_str:
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                try:
                    return datetime.strptime(date_str[:10], "%Y-%m-%d")
                except:
                    return None
        return None
    
    # Helper function to calculate VO2MAX for a given set of activities
    def calculate_vo2max_for_activities(acts):
        MIN_VMA_DURATION = 6
        vma_efforts = []
        paces = []
        
        for a in acts:
            dist = get_distance(a)
            pace = get_pace(a)
            duration_min = get_duration(a)
            
            if dist > 0 and pace and 3 < pace < 10:
                paces.append(pace)
                # Efforts >= 6 min avec allure rapide
                if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                    vma_efforts.append({
                        "pace": pace,
                        "duration": duration_min,
                        "speed_kmh": 60 / pace
                    })
        
        if not paces:
            return None, None
        
        avg_pace = sum(paces) / len(paces)
        
        if vma_efforts:
            best_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
            best_speed = best_effort["speed_kmh"]
            duration = best_effort["duration"]
            
            if duration >= 20:
                estimated_vma = best_speed / 0.85
            elif duration >= 12:
                estimated_vma = best_speed / 0.90
            else:
                estimated_vma = best_speed / 0.95
        else:
            avg_speed = 60 / avg_pace
            estimated_vma = avg_speed / 0.70
        
        vo2max = round(estimated_vma * 3.5, 1)
        
        # Exclude unrealistic values
        if vo2max > 70:
            return None, None
        
        return round(estimated_vma, 1), vo2max
    
    # Generate data points for 12 months (24 half-month periods)
    # Each point uses a ROLLING 6-WEEK WINDOW ending at that date
    month_names_fr = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    vo2max_history = []
    
    for i in range(24):  # 24 half-month periods over 12 months
        # Calculate the end date for this period
        months_back = 11 - (i // 2)
        half = 1 if (i % 2 == 0) else 2
        
        # Target date for this data point
        target_month_date = today - timedelta(days=30 * months_back)
        year = target_month_date.year
        month = target_month_date.month
        
        # End of period: 15th or end of month
        if half == 1:
            period_end = datetime(year, month, 15, tzinfo=timezone.utc)
        else:
            # Last day of month
            if month == 12:
                period_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
            else:
                period_end = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        
        # 6-week window ending at period_end
        period_start = period_end - timedelta(days=42)
        
        # Filter activities within this 6-week window
        def is_in_window(a):
            activity_date = get_activity_date(a)
            if activity_date is None:
                return False
            if activity_date.tzinfo is None:
                activity_date = activity_date.replace(tzinfo=timezone.utc)
            return period_start <= activity_date <= period_end
        
        window_activities = [a for a in activities if is_in_window(a)]
        
        # Calculate VO2MAX for this window
        vma, vo2max = calculate_vo2max_for_activities(window_activities)
        
        month_name = month_names_fr[month - 1]
        period_label = f"{month_name} {half}"
        period_key = f"{year}-{month:02d}-{half}"
        
        vo2max_history.append({
            "period": period_key,
            "period_label": period_label,
            "month": f"{year}-{month:02d}",
            "month_label": month_name,
            "half": half,
            "vma": vma,
            "vo2max": vo2max,
            "sessions": len(window_activities),
            "window_days": 42
        })
    
    result_history = vo2max_history
    
    # Current VO2MAX = last non-null value from the graph (already based on 6 weeks)
    current_vma = None
    current_vo2max = None
    for h in reversed(result_history):
        if h["vma"] is not None:
            current_vma = h["vma"]
            current_vo2max = h["vo2max"]
            break
    
    # Calculate trend (based on VO2MAX over 12 months)
    valid_vo2max = [h["vo2max"] for h in result_history if h["vo2max"] is not None]
    if len(valid_vo2max) >= 2:
        trend = valid_vo2max[-1] - valid_vo2max[0]
        trend_pct = (trend / valid_vo2max[0]) * 100 if valid_vo2max[0] > 0 else 0
    else:
        trend = 0
        trend_pct = 0
    
    return {
        "has_data": len(valid_vo2max) > 0 or current_vo2max is not None,
        "current_vma": current_vma,
        "current_vo2max": current_vo2max,
        "calculation_window": "6 weeks",
        "trend": round(trend, 1),
        "trend_pct": round(trend_pct, 1),
        "period_count": 24,
        "months": 12,
        "history": result_history
    }


@router.get("/training/full-cycle")
async def get_full_training_cycle(
    user: dict = Depends(auth_user),
    lang: str = Query("en", description="Language for phase and session labels (en, fr)")
):
    """
    Returns the full training cycle overview with all weeks.
    Phase names/focus and session type keys are returned; frontend translates keys via i18n.
    """
    # Récupérer le cycle utilisateur
    cycle = await db.training_cycles.find_one({"user_id": user["id"]})
    
    if not cycle:
        # Créer un cycle par défaut
        default_cycle = {
            "user_id": user["id"],
            "goal": "SEMI",
            "start_date": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }
        await db.training_cycles.insert_one(default_cycle)
        cycle = await db.training_cycles.find_one({"user_id": user["id"]})
    
    goal = cycle.get("goal", "SEMI")
    config = GOAL_CONFIG.get(goal, GOAL_CONFIG["SEMI"])
    total_weeks = config["cycle_weeks"]
    
    # Récupérer les préférences de séances
    prefs = await db.training_prefs.find_one({"user_id": user["id"]})
    sessions_per_week = prefs.get("sessions_per_week", 4) if prefs else 4
    
    # Calculer la semaine actuelle
    start_date = cycle.get("start_date")
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    current_week = compute_week_number(start_date.date() if isinstance(start_date, datetime) else start_date)
    
    # Récupérer le volume actuel de l'athlète (basé sur les 28 derniers jours)
    today = datetime.now(timezone.utc)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_28 = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(200)
    
    # Si pas de données Strava, essayer les workouts manuels
    if not workouts_28:
        workouts_28 = await db.workouts.find({
            "date": {"$gte": twenty_eight_days_ago.isoformat()}
        }).to_list(200)
    
    km_28 = sum(w.get("distance", w.get("distance_km", 0) * 1000) / 1000 for w in workouts_28)
    base_weekly_km = km_28 / 4 if km_28 > 0 else 25  # Volume hebdo de base
    
    # Générer l'aperçu de toutes les semaines
    weeks_overview = []
    
    for week_num in range(1, total_weeks + 1):
        phase = determine_phase(week_num, total_weeks)
        phase_info = get_phase_description(phase, lang)
        
        # Target volume by phase and progression
        progression_factor = 1 + (week_num / total_weeks) * 0.3  # +30% max over cycle
        
        if phase == "build":
            volume_factor = 1.0 * progression_factor
        elif phase == "deload":
            volume_factor = 0.7  # -30% deload
        elif phase == "intensification":
            volume_factor = 1.1 * progression_factor
        elif phase == "taper":
            weeks_to_race = total_weeks - week_num
            volume_factor = 0.6 - (0.1 * (2 - weeks_to_race))
        elif phase == "race":
            volume_factor = 0.3
        else:
            volume_factor = 1.0
        
        target_km = round(base_weekly_km * volume_factor)
        
        # Session type keys (frontend translates via i18n trainingPlan.sessionType.*)
        if phase == "build":
            session_types = ["endurance", "endurance", "long_run"] if sessions_per_week <= 3 else ["endurance", "endurance", "fartlek", "long_run"]
        elif phase == "deload":
            session_types = ["recovery", "easy", "short_easy"]
        elif phase == "intensification":
            session_types = ["endurance", "tempo", "intervals", "long_run"]
        elif phase == "taper":
            session_types = ["easy", "speed_reminder", "easy_run"]
        elif phase == "race":
            session_types = ["activation", "race"]
        else:
            session_types = ["endurance", "long_run"]
        
        weeks_overview.append({
            "week": week_num,
            "phase": phase,
            "phase_name": phase_info.get("name", phase),
            "phase_focus": phase_info.get("focus", ""),
            "target_km": target_km,
            "sessions": sessions_per_week if phase not in ["taper", "race"] else min(3, sessions_per_week),
            "session_types": session_types[:sessions_per_week],
            "is_current": week_num == current_week,
            "is_completed": week_num < current_week,
            "intensity_pct": phase_info.get("intensity_pct", 15)
        })
    
    return {
        "goal": goal,
        "goal_description": config["description"],
        "total_weeks": total_weeks,
        "current_week": current_week,
        "start_date": start_date.isoformat() if start_date else None,
        "sessions_per_week": sessions_per_week,
        "base_weekly_km": round(base_weekly_km),
        "weeks": weeks_overview
    }


@router.get("/training/week-plan")
async def get_week_plan(user_id: str = "default"):
    """
    Génère un plan d'entraînement détaillé pour la semaine via LLM.
    Utilise le contexte d'entraînement et l'objectif défini.
    """
    # Récupérer l'objectif
    goal = await db.training_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    if not goal:
        raise HTTPException(status_code=400, detail="Aucun objectif défini. Utilisez /api/training/set-goal d'abord.")
    
    # Récupérer les données récentes pour le contexte
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_7 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    workouts_28 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(100)
    
    # Calculer les métriques
    km_7 = sum(w.get("distance_km", 0) or 0 for w in workouts_7)
    km_28 = sum(w.get("distance_km", 0) or 0 for w in workouts_28)
    load_7 = km_7 * 10
    load_28 = km_28 * 10
    
    # Construire le contexte
    context = {
        "ctl": load_28 / 4 if load_28 > 0 else 30,
        "atl": load_7 if load_7 > 0 else 35,
        "tsb": (load_28 / 4 - load_7) if load_28 > 0 else -5,
        "acwr": (load_7 / (load_28 / 4)) if load_28 > 0 else 1.0,
        "weekly_km": km_28 / 4 if km_28 > 0 else 20
    }
    
    # Calculer la phase
    start_date = goal["start_date"]
    cycle_weeks = goal["cycle_weeks"]
    
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    
    if today < start_date:
        current_week = 0
    else:
        delta_days = (today - start_date).days
        current_week = min(delta_days // 7 + 1, cycle_weeks + 1)
    
    phase = determine_phase(current_week, cycle_weeks)
    
    # Calculer la charge cible
    from training_engine import determine_target_load
    target_load = determine_target_load(context, phase)
    
    # Générer le plan via LLM
    plan, success, metadata = await generate_cycle_week(
        context=context,
        phase=phase,
        target_load=target_load,
        goal=goal["goal_type"],
        user_id=user_id
    )
    
    if not success or not plan:
        # Fallback: plan générique basé sur la phase
        plan = _generate_fallback_week_plan(context, phase, target_load, goal["goal_type"])
    
    return {
        "goal": {
            "type": goal["goal_type"],
            "name": goal["event_name"],
            "event_date": goal["event_date"].isoformat() if isinstance(goal["event_date"], datetime) else goal["event_date"]
        },
        "current_week": current_week,
        "total_weeks": cycle_weeks,
        "phase": phase,
        "context": context,
        "plan": plan,
        "generated_by": "llm" if success else "fallback",
        "metadata": metadata
    }
