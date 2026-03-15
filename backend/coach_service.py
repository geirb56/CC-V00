"""
CardioCoach - Service de Coaching Cascade avec Cache et Métriques

Stratégie:
1. Vérifier cache (0ms)
2. Analyse déterministe (instantanée) via rag_engine
3. Enrichissement LLM (~500ms) si disponible
4. Stocker en cache + métriques

Usage:
    from coach_service import analyze_workout, weekly_review, chat_response, get_metrics
"""

import hashlib
import logging
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional

from llm_coach import (
    enrich_chat_response,
    enrich_weekly_review,
    enrich_workout_analysis,
    generate_cycle_week,
    LLM_MODEL
)
from training_engine import (
    GOAL_CONFIG,
    compute_week_number,
    determine_phase,
    build_training_context,
    determine_target_load,
    get_phase_description
)

logger = logging.getLogger(__name__)


# ============================================================
# METRICS
# ============================================================

@dataclass
class CoachMetrics:
    """Métriques du service de coaching"""
    llm_success: int = 0
    llm_fallback: int = 0
    cache_hits: int = 0
    total_requests: int = 0
    avg_latency_ms: float = 0.0
    llm_avg_latency_ms: float = 0.0
    cache_avg_latency_ms: float = 0.0
    workout_requests: int = 0
    weekly_requests: int = 0
    chat_requests: int = 0
    plan_requests: int = 0


metrics = CoachMetrics()


def get_metrics() -> dict:
    """Retourne les métriques actuelles"""
    data = asdict(metrics)
    total_llm = metrics.llm_success + metrics.llm_fallback
    data["llm_success_rate"] = round(metrics.llm_success / total_llm * 100, 1) if total_llm > 0 else 0
    data["cache_hit_rate"] = round(metrics.cache_hits / metrics.total_requests * 100, 1) if metrics.total_requests > 0 else 0
    return data


def reset_metrics() -> dict:
    """Reset les métriques"""
    global metrics
    old = get_metrics()
    metrics = CoachMetrics()
    return old


def _update_latency(latency_ms: float, is_llm: bool = False, is_cache: bool = False) -> None:
    """Met à jour les moyennes mobiles de latence"""
    alpha = 0.1
    metrics.avg_latency_ms = (metrics.avg_latency_ms * (1 - alpha)) + (latency_ms * alpha)
    if is_llm:
        metrics.llm_avg_latency_ms = (metrics.llm_avg_latency_ms * (1 - alpha)) + (latency_ms * alpha)
    if is_cache:
        metrics.cache_avg_latency_ms = (metrics.cache_avg_latency_ms * (1 - alpha)) + (latency_ms * alpha)


# ============================================================
# CACHE CONFIGURATION
# ============================================================

CACHE_TTL_SECONDS = 3600
MAX_CACHE_SIZE = 500

_workout_cache: Dict[str, Tuple[dict, float]] = {}
_weekly_cache: Dict[str, Tuple[dict, float]] = {}
_plan_cache: Dict[str, Tuple[dict, float]] = {}


def _cache_key(data: dict, prefix: str = "") -> str:
    key_parts = [prefix]
    for field in ["id", "distance_km", "duration_minutes", "avg_heart_rate", "type"]:
        key_parts.append(str(data.get(field, "")))
    return hashlib.md5("_".join(key_parts).encode()).hexdigest()


def _is_cache_valid(timestamp: float) -> bool:
    return (time.time() - timestamp) < CACHE_TTL_SECONDS


def _cleanup_cache(cache: dict) -> None:
    if len(cache) > MAX_CACHE_SIZE:
        expired_keys = [k for k, (_, ts) in cache.items() if not _is_cache_valid(ts)]
        for k in expired_keys:
            del cache[k]
        if len(cache) > MAX_CACHE_SIZE:
            sorted_items = sorted(cache.items(), key=lambda x: x[1][1])
            for k, _ in sorted_items[:len(cache) - MAX_CACHE_SIZE]:
                del cache[k]


# ============================================================
# FONCTIONS PRINCIPALES
# ============================================================

async def analyze_workout(
    workout: dict,
    rag_result: dict,
    user_id: str = "default"
) -> Tuple[str, bool]:
    """Analyse séance avec cache + métriques + stratégie cascade."""
    start = time.time()
    metrics.total_requests += 1
    metrics.workout_requests += 1
    
    cache_key = _cache_key(workout, "workout")
    if cache_key in _workout_cache:
        cached_result, timestamp = _workout_cache[cache_key]
        if _is_cache_valid(timestamp):
            metrics.cache_hits += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_cache=True)
            return cached_result["summary"], cached_result["used_llm"]
    
    deterministic_summary = rag_result.get("summary", "")
    
    try:
        workout_stats = {
            "distance_km": workout.get("distance_km", 0),
            "duree_min": workout.get("duration_minutes", 0),
            "allure": rag_result.get("pace_str", "N/A"),
            "fc_moy": workout.get("avg_heart_rate"),
            "fc_max": workout.get("max_heart_rate"),
            "denivele": workout.get("elevation_gain_m"),
            "type": workout.get("type"),
            "zones": workout.get("effort_zone_distribution", {}),
            "splits": rag_result.get("splits_analysis", {}),
            "comparison": rag_result.get("comparison", {}).get("progression", ""),
            "points_forts": rag_result.get("points_forts", []),
            "points_ameliorer": rag_result.get("points_ameliorer", []),
        }
        
        enriched, success, meta = await enrich_workout_analysis(
            workout=workout_stats,
            user_id=user_id
        )
        
        if success and enriched:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            _workout_cache[cache_key] = ({"summary": enriched, "used_llm": True}, time.time())
            _cleanup_cache(_workout_cache)
            return enriched, True
            
    except Exception as e:
        logger.warning(f"[Coach] Séance fallback: {e}")
    
    metrics.llm_fallback += 1
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    _workout_cache[cache_key] = ({"summary": deterministic_summary, "used_llm": False}, time.time())
    _cleanup_cache(_workout_cache)
    return deterministic_summary, False


async def weekly_review(
    rag_result: dict,
    user_id: str = "default"
) -> Tuple[str, bool]:
    """Bilan hebdomadaire avec cache + métriques + stratégie cascade."""
    start = time.time()
    metrics.total_requests += 1
    metrics.weekly_requests += 1
    
    m = rag_result.get("metrics", {})
    cache_data = {
        "id": f"weekly_{m.get('nb_seances', 0)}_{m.get('km_total', 0)}",
        "distance_km": m.get("km_total", 0),
        "duration_minutes": m.get("duree_totale", 0),
    }
    cache_key = _cache_key(cache_data, "weekly")
    
    if cache_key in _weekly_cache:
        cached_result, timestamp = _weekly_cache[cache_key]
        if _is_cache_valid(timestamp):
            metrics.cache_hits += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_cache=True)
            return cached_result["summary"], cached_result["used_llm"]
    
    deterministic_summary = rag_result.get("summary", "")
    
    try:
        weekly_stats = {
            "km_semaine": m.get("km_total", 0),
            "nb_seances": m.get("nb_seances", 0),
            "allure_moy": m.get("allure_moyenne", "N/A"),
            "cadence_moy": m.get("cadence_moyenne", 0),
            "zones": m.get("zones", {}),
            "ratio_charge": m.get("ratio", 1.0),
            "points_forts": rag_result.get("points_forts", []),
            "points_ameliorer": rag_result.get("points_ameliorer", []),
            "tendance": rag_result.get("comparison", {}).get("evolution", "stable"),
        }
        
        enriched, success, meta = await enrich_weekly_review(
            stats=weekly_stats,
            user_id=user_id
        )
        
        if success and enriched:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            _weekly_cache[cache_key] = ({"summary": enriched, "used_llm": True}, time.time())
            _cleanup_cache(_weekly_cache)
            return enriched, True
            
    except Exception as e:
        logger.warning(f"[Coach] Bilan fallback: {e}")
    
    metrics.llm_fallback += 1
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    _weekly_cache[cache_key] = ({"summary": deterministic_summary, "used_llm": False}, time.time())
    _cleanup_cache(_weekly_cache)
    return deterministic_summary, False


async def chat_response(
    message: str,
    context: dict,
    history: List[dict],
    user_id: str,
    workouts: List[dict] = None,
    user_goal: dict = None
) -> Tuple[str, bool, dict]:
    """Réponse chat avec métriques (pas de cache)."""
    start = time.time()
    metrics.total_requests += 1
    metrics.chat_requests += 1
    
    try:
        response, success, meta = await enrich_chat_response(
            user_message=message,
            context=context,
            conversation_history=history,
            user_id=user_id
        )
        
        if success and response:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            return response, True, meta
            
    except Exception as e:
        logger.warning(f"[Coach] Chat LLM error: {e}")
    
    metrics.llm_fallback += 1
    language = context.get("language", "en")
    if language == "fr":
        error_msg = "Le service de coaching IA n'est pas disponible actuellement."
    else:
        error_msg = "The AI coaching service is currently unavailable."
    return error_msg, False, {}


# ============================================================
# GÉNÉRATION DE PLAN D'ENTRAÎNEMENT DYNAMIQUE
# ============================================================

async def generate_dynamic_training_plan(db, user_id: str, sessions_override: int = None) -> dict:
    """
    Génère un plan d'entraînement dynamique basé sur les données utilisateur.
    
    Intègre:
    - VMA pour calculer les allures personnalisées
    - Prédictions de course pour adapter la durée de préparation
    
    Args:
        db: Instance de base de données MongoDB (async)
        user_id: ID utilisateur
        sessions_override: Nombre de séances forcé (3, 4, 5, 6)
        
    Returns:
        Plan d'entraînement avec semaine, phase, objectif et séances
    """
    start = time.time()
    metrics.total_requests += 1
    metrics.plan_requests += 1
    
    # Récupérer les préférences utilisateur (nombre de séances)
    prefs = await db.training_prefs.find_one({"user_id": user_id})
    sessions_per_week = sessions_override or (prefs.get("sessions_per_week") if prefs else None)
    
    # 1. Récupérer ou créer le cycle d'entraînement
    cycle = await db.training_cycles.find_one({"user_id": user_id})
    
    if not cycle:
        # Créer un cycle par défaut
        default_cycle = {
            "user_id": user_id,
            "goal": "SEMI",
            "start_date": datetime.now(timezone.utc),
            "race_date": None,
            "created_at": datetime.now(timezone.utc)
        }
        await db.training_cycles.insert_one(default_cycle)
        cycle = await db.training_cycles.find_one({"user_id": user_id})
        logger.info(f"[Coach] Cycle créé pour user {user_id}")
    
    goal = cycle.get("goal", "SEMI")
    
    if goal not in GOAL_CONFIG:
        goal = "SEMI"
    
    config = GOAL_CONFIG[goal]
    
    # 2. Récupérer les données d'entraînement (6 semaines pour cohérence avec VMA)
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    six_weeks_ago = today - timedelta(days=42)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    # Essayer d'abord les activités Strava (avec ou sans user_id car certaines sont globales)
    workouts_7 = await db.strava_activities.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "start_date_local": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    workouts_28 = await db.strava_activities.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "start_date_local": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)
    
    # Données sur 6 semaines pour le calcul VMA
    workouts_6w = await db.strava_activities.find({
        "$or": [
            {"user_id": user_id},
            {"user_id": None},
            {"user_id": {"$exists": False}}
        ],
        "start_date_local": {"$gte": six_weeks_ago.isoformat()}
    }).to_list(500)
    
    # Fallback sur workouts locaux si pas de données Strava
    if not workouts_28:
        workouts_7 = await db.workouts.find({
            "date": {"$gte": seven_days_ago.isoformat()}
        }).to_list(100)
        
        workouts_28 = await db.workouts.find({
            "date": {"$gte": twenty_eight_days_ago.isoformat()}
        }).to_list(300)
        
        workouts_6w = await db.workouts.find({
            "date": {"$gte": six_weeks_ago.isoformat()}
        }).to_list(500)
    
    # 3. Calculer les métriques de base
    def get_distance_km(w):
        """Extrait la distance en km (Strava = mètres, workouts = km)"""
        dist = w.get("distance", 0)
        if dist > 1000:  # Strava retourne en mètres
            return dist / 1000
        return w.get("distance_km", dist) or 0
    
    def get_duration_min(w):
        """Extrait la durée en minutes"""
        moving_time = w.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        elapsed = w.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        return w.get("duration_minutes", 0)
    
    def get_pace(w):
        """Calcule l'allure en min/km"""
        dist = get_distance_km(w)
        duration = get_duration_min(w)
        if dist > 0 and duration > 0:
            return duration / dist
        return None
    
    km_7 = sum(get_distance_km(w) for w in workouts_7)
    km_28 = sum(get_distance_km(w) for w in workouts_28)
    weekly_km = km_28 / 4 if km_28 > 0 else 20
    
    # 4. CALCULER LA VMA (même logique que /api/training/vma-history)
    vma_efforts = []
    paces = []
    MIN_VMA_DURATION = 6
    
    for w in workouts_6w:
        dist = get_distance_km(w)
        pace = get_pace(w)
        duration = get_duration_min(w)
        
        if dist > 0 and pace and 3 < pace < 10:
            paces.append(pace)
            # Efforts >= 6 min avec allure rapide (< 5:30/km)
            if duration >= MIN_VMA_DURATION and pace < 5.5:
                vma_efforts.append({
                    "pace": pace,
                    "duration": duration,
                    "speed_kmh": 60 / pace
                })
    
    # Calcul de la VMA
    if paces:
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
            vma_method = "effort"
        else:
            avg_speed = 60 / avg_pace
            estimated_vma = avg_speed / 0.70
            vma_method = "average"
        
        # Sanity check
        if estimated_vma * 3.5 > 70:
            estimated_vma = 14.0  # Valeur par défaut réaliste
            vma_method = "default"
    else:
        estimated_vma = 12.0  # VMA par défaut
        vma_method = "default"
    
    estimated_vma = round(estimated_vma, 1)
    vo2max = round(estimated_vma * 3.5, 1)
    
    # 5. CALCULER LES ZONES D'ALLURE PERSONNALISÉES basées sur la VMA
    def vma_to_pace(vma_pct):
        """Convertit un % de VMA en allure min/km"""
        speed = estimated_vma * vma_pct
        if speed > 0:
            pace = 60 / speed
            return pace
        return 6.0
    
    def format_pace(pace):
        """Formate une allure en min:sec/km"""
        mins = int(pace)
        secs = int((pace % 1) * 60)
        return f"{mins}:{secs:02d}"
    
    personalized_paces = {
        "z1": f"{format_pace(vma_to_pace(0.65))}-{format_pace(vma_to_pace(0.70))}",  # 65-70% VMA (récup)
        "z2": f"{format_pace(vma_to_pace(0.75))}-{format_pace(vma_to_pace(0.80))}",  # 75-80% VMA (endurance)
        "z3": f"{format_pace(vma_to_pace(0.82))}-{format_pace(vma_to_pace(0.87))}",  # 82-87% VMA (tempo)
        "z4": f"{format_pace(vma_to_pace(0.88))}-{format_pace(vma_to_pace(0.93))}",  # 88-93% VMA (seuil)
        "z5": f"{format_pace(vma_to_pace(0.95))}-{format_pace(vma_to_pace(1.00))}",  # 95-100% VMA
        "marathon": f"{format_pace(vma_to_pace(0.78))}-{format_pace(vma_to_pace(0.82))}",  # 78-82% VMA
        "semi": f"{format_pace(vma_to_pace(0.82))}-{format_pace(vma_to_pace(0.85))}",  # 82-85% VMA
    }
    
    # 6. ADAPTER LA DURÉE DE PRÉPARATION selon le niveau
    # Calculer le "readiness score" pour l'objectif
    goal_requirements = {
        "5K": {"min_weekly_km": 15, "min_vo2max": 35, "base_weeks": 6},
        "10K": {"min_weekly_km": 25, "min_vo2max": 38, "base_weeks": 8},
        "SEMI": {"min_weekly_km": 35, "min_vo2max": 42, "base_weeks": 12},
        "MARATHON": {"min_weekly_km": 50, "min_vo2max": 45, "base_weeks": 16},
        "ULTRA": {"min_weekly_km": 60, "min_vo2max": 48, "base_weeks": 20},
    }
    
    req = goal_requirements.get(goal, goal_requirements["SEMI"])
    
    # Score de préparation (0-100)
    volume_score = min(100, (weekly_km / req["min_weekly_km"]) * 100) if req["min_weekly_km"] > 0 else 50
    fitness_score = min(100, (vo2max / req["min_vo2max"]) * 100) if req["min_vo2max"] > 0 else 50
    readiness_score = (volume_score * 0.6 + fitness_score * 0.4)  # Volume compte plus
    
    # Adapter le nombre de semaines
    base_weeks = req["base_weeks"]
    if readiness_score >= 90:
        # Très prêt → préparation courte (-25%)
        adjusted_weeks = max(4, int(base_weeks * 0.75))
        prep_status = "avancé"
    elif readiness_score >= 70:
        # Prêt → préparation normale
        adjusted_weeks = base_weeks
        prep_status = "normal"
    elif readiness_score >= 50:
        # Besoin de progresser → préparation longue (+25%)
        adjusted_weeks = int(base_weeks * 1.25)
        prep_status = "progressif"
    else:
        # Débutant → préparation très longue (+50%)
        adjusted_weeks = int(base_weeks * 1.5)
        prep_status = "débutant"
    
    # Mettre à jour la config avec la durée adaptée
    config = {**config, "cycle_weeks": adjusted_weeks}
    
    # 7. Calculer la semaine et la phase
    start_date = cycle.get("start_date")
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    
    week = compute_week_number(start_date.date() if isinstance(start_date, datetime) else start_date)
    phase = determine_phase(week, adjusted_weeks)
    
    # 8. Calcul ACWR et TSB
    chronic_avg = km_28 / 4 if km_28 > 0 else 1
    acwr = round(km_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    
    ctl = km_28 / 4
    atl = km_7
    tsb = round(ctl - atl, 1)
    
    load_7 = km_7 * 10
    load_28 = km_28 * 10
    
    fitness_data = {
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "load_7": load_7,
        "load_28": load_28,
        "acwr": acwr
    }
    
    # 9. Construire le contexte enrichi avec VMA
    context = build_training_context(fitness_data, weekly_km)
    context["vma"] = estimated_vma
    context["vo2max"] = vo2max
    context["vma_method"] = vma_method
    context["paces"] = personalized_paces
    context["readiness_score"] = round(readiness_score, 1)
    context["prep_status"] = prep_status
    context["adjusted_weeks"] = adjusted_weeks
    
    # 10. Calculer la charge cible
    target_load = determine_target_load(context, phase)
    
    # 11. Vérifier le cache
    cache_key = f"plan_{user_id}_{week}_{phase}_{goal}_{estimated_vma}"
    if cache_key in _plan_cache:
        cached_plan, timestamp = _plan_cache[cache_key]
        if _is_cache_valid(timestamp):
            metrics.cache_hits += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_cache=True)
            logger.debug(f"[Coach] Plan cache hit ({latency:.1f}ms)")
            return cached_plan
    
    # 12. Générer le plan via LLM avec allures personnalisées
    try:
        week_plan, success, meta = await generate_cycle_week(
            context=context,
            phase=phase,
            target_load=target_load,
            goal=goal,
            user_id=user_id,
            sessions_per_week=sessions_per_week,
            personalized_paces=personalized_paces
        )
        
        if success and week_plan:
            metrics.llm_success += 1
            latency = (time.time() - start) * 1000
            _update_latency(latency, is_llm=True)
            logger.info(f"[Coach] ✅ Plan LLM ({latency:.0f}ms)")
        else:
            raise Exception("LLM plan generation failed")
            
    except Exception as e:
        logger.warning(f"[Coach] Plan fallback: {e}")
        metrics.llm_fallback += 1
        week_plan = _deterministic_plan(context, phase, target_load, goal, sessions_per_week, personalized_paces)
    
    # 13. Construire le résultat
    result = {
        "week": week,
        "phase": phase,
        "phase_info": get_phase_description(phase),
        "goal": goal,
        "goal_config": config,
        "context": context,
        "plan": week_plan,
        "sessions_per_week": sessions_per_week,
        "vma": estimated_vma,
        "vo2max": vo2max,
        "paces": personalized_paces,
        "readiness_score": round(readiness_score, 1),
        "prep_status": prep_status,
        "adjusted_weeks": adjusted_weeks,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # 14. Mettre à jour le cycle en base
    await db.training_cycles.update_one(
        {"user_id": user_id},
        {"$set": {
            "last_generated_week": week,
            "current_plan": week_plan,
            "vma": estimated_vma,
            "vo2max": vo2max,
            "adjusted_weeks": adjusted_weeks,
            "updated_at": datetime.now(timezone.utc)
        }}
    )
    
    # 15. Stocker en cache
    _plan_cache[cache_key] = (result, time.time())
    _cleanup_cache(_plan_cache)
    
    latency = (time.time() - start) * 1000
    _update_latency(latency)
    
    return result


def _deterministic_plan(context: dict, phase: str, target_load: int, goal: str, sessions_per_week: int = None, personalized_paces: dict = None) -> dict:
    """Génère un plan déterministe de secours avec allures personnalisées basées sur la VMA."""
    
    # Volume actuel de l'athlète (basé sur les 4 dernières semaines)
    current_weekly_km = context.get("weekly_km", 30)
    
    # Volumes minimum RECOMMANDÉS (basés sur données réelles d'entraînement)
    goal_configs = {
        "5K": {"min": 15, "max": 45, "sessions": 3, "long_min": 8, "long_max": 10},
        "10K": {"min": 20, "max": 60, "sessions": 3, "long_min": 10, "long_max": 14},
        "SEMI": {"min": 30, "max": 80, "sessions": 3, "long_min": 16, "long_max": 18},
        "MARATHON": {"min": 40, "max": 120, "sessions": 4, "long_min": 28, "long_max": 32},
        "ULTRA": {"min": 50, "max": 150, "sessions": 5, "long_min": 35, "long_max": 45},
    }
    
    config = goal_configs.get(goal, goal_configs["SEMI"])
    
    # Utiliser le nombre de séances spécifié ou celui par défaut
    num_sessions = sessions_per_week if sessions_per_week in [3, 4, 5, 6] else config["sessions"]
    num_rest_days = 7 - num_sessions
    
    # Volume minimum = max(volume actuel, minimum recommandé)
    volume_min = max(current_weekly_km, config["min"])
    
    # Calcul du volume cible: +7% progressif
    target_km = max(volume_min, min(config["max"], round(current_weekly_km * 1.07)))
    
    # Multiplicateur de phase
    phase_multipliers = {"build": 1.0, "deload": 0.7, "intensification": 1.05, "taper": 0.5, "race": 0.3}
    target_km = round(target_km * phase_multipliers.get(phase, 1.0))
    
    # Sortie longue proportionnelle
    long_ratio = (target_km - config["min"]) / (config["max"] - config["min"]) if config["max"] > config["min"] else 0.5
    long_run = round(config["long_min"] + long_ratio * (config["long_max"] - config["long_min"]))
    long_run = max(config["long_min"], min(config["long_max"], long_run))
    
    # Répartition du reste du volume
    remaining = target_km - long_run
    easy_km = round(remaining * 0.35)
    tempo_km = round(remaining * 0.25)
    seuil_km = round(remaining * 0.22)
    recup_km = remaining - easy_km - tempo_km - seuil_km
    
    # Allures personnalisées (basées sur VMA) ou valeurs par défaut
    if personalized_paces:
        paces = personalized_paces
    else:
        paces = {"z1": "6:30-7:00", "z2": "5:45-6:15", "z3": "5:15-5:30", "z4": "4:45-5:00", "z5": "4:15-4:30", "semi": "5:00-5:15", "marathon": "5:15-5:30"}
    
    hr = {"z1": "120-135", "z2": "135-150", "z3": "150-165", "z4": "165-175", "z5": "175-185"}
    
    # Templates par phase - adapté à l'objectif
    if phase == "deload":
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements recommandés", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": f"{easy_km*6}min", "details": f"{easy_km} km • {paces['z1']}/km • FC {hr['z1']} bpm • Zone 1-2", "intensity": "easy", "estimated_tss": easy_km*5, "distance_km": easy_km},
            {"day": "Mercredi", "type": "Récupération", "duration": f"{recup_km*7}min", "details": f"{recup_km} km • {paces['z1']}/km • FC {hr['z1']} bpm • Très léger", "intensity": "easy", "estimated_tss": recup_km*5, "distance_km": recup_km},
            {"day": "Jeudi", "type": "Endurance", "duration": f"{easy_km*6}min", "details": f"{easy_km} km • {paces['z2']}/km • FC {hr['z2']} bpm", "intensity": "easy", "estimated_tss": easy_km*5, "distance_km": easy_km},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération • Marche légère possible", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Endurance", "duration": f"{tempo_km*6}min", "details": f"{tempo_km} km progressif • {paces['z2']}/km → {paces['z3']}/km", "intensity": "easy", "estimated_tss": tempo_km*6, "distance_km": tempo_km},
            {"day": "Dimanche", "type": "Sortie longue", "duration": f"{long_run*6}min", "details": f"{long_run} km • {paces['z2']}/km • FC {hr['z2']} bpm • Sortie calme", "intensity": "moderate", "estimated_tss": long_run*6, "distance_km": long_run},
        ]
    elif phase == "taper":
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Hydratation ++", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "30min", "details": f"{recup_km} km + 4×100m • {paces['z2']}/km • FC {hr['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": recup_km + 0.5},
            {"day": "Mercredi", "type": "Récupération", "duration": "20min", "details": f"{recup_km-1} km • {paces['z1']}/km • FC {hr['z1']} bpm", "intensity": "easy", "estimated_tss": 15, "distance_km": max(3, recup_km-1)},
            {"day": "Jeudi", "type": "Tempo court", "duration": "25min", "details": f"{recup_km} km dont 2 km allure course • {paces['semi']}/km • FC {hr['z3']} bpm", "intensity": "moderate", "estimated_tss": 35, "distance_km": recup_km},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Repos total • Préparation équipement", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Activation", "duration": "20min", "details": f"3 km + 3×200m • {paces['z2']}/km", "intensity": "easy", "estimated_tss": 25, "distance_km": 3.6},
            {"day": "Dimanche", "type": "Repos", "duration": "0min", "details": "VEILLE DE COURSE • Repos, glucides", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    elif phase == "race":
        race_km = {"5K": 5, "10K": 10, "SEMI": 21.1, "MARATHON": 42.2, "ULTRA": 50}.get(goal, 21.1)
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération totale", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Activation", "duration": "20min", "details": f"3 km • {paces['z1']}/km • FC {hr['z1']} bpm", "intensity": "easy", "estimated_tss": 15, "distance_km": 3},
            {"day": "Mercredi", "type": "Récupération", "duration": "15min", "details": f"2.5 km • {paces['z1']}/km • FC {hr['z1']} bpm", "intensity": "easy", "estimated_tss": 12, "distance_km": 2.5},
            {"day": "Jeudi", "type": "Activation", "duration": "15min", "details": f"2 km + 2×100m • {paces['z1']}/km", "intensity": "easy", "estimated_tss": 10, "distance_km": 2.2},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Repos complet", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Repos", "duration": "0min", "details": "VEILLE • Glucides", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Dimanche", "type": "COURSE", "duration": "Variable", "details": f"🏆 {goal} ({race_km} km) • Objectif: {paces.get('semi')}/km", "intensity": "race", "estimated_tss": int(race_km * 7), "distance_km": race_km},
        ]
    else:  # build, intensification - Plan standard adapté à l'objectif
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements recommandés", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": f"{easy_km*6}min", "details": f"{easy_km} km • {paces['z2']}/km • FC {hr['z2']} bpm • Zone 2 stricte", "intensity": "easy", "estimated_tss": easy_km*6, "distance_km": easy_km},
            {"day": "Mercredi", "type": "Seuil", "duration": f"{seuil_km*5}min", "details": f"{seuil_km} km dont 20min à {paces['z4']}/km • FC {hr['z4']} bpm • Récup 2min", "intensity": "hard", "estimated_tss": seuil_km*8, "distance_km": seuil_km},
            {"day": "Jeudi", "type": "Récupération", "duration": f"{recup_km*7}min", "details": f"{recup_km} km • {paces['z1']}/km • FC <135 bpm • Footing léger", "intensity": "easy", "estimated_tss": recup_km*5, "distance_km": recup_km},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération • Cross-training possible (vélo, natation)", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Tempo", "duration": f"{tempo_km*5}min", "details": f"{tempo_km} km dont 25min à {paces['semi']}/km • FC {hr['z3']} bpm", "intensity": "moderate", "estimated_tss": tempo_km*7, "distance_km": tempo_km},
            {"day": "Dimanche", "type": "Sortie longue", "duration": f"{long_run*5}min", "details": f"{long_run} km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr['z2']}→{hr['z3']} bpm", "intensity": "moderate", "estimated_tss": long_run*6, "distance_km": long_run},
        ]
    
    total_tss = sum(s["estimated_tss"] for s in sessions)
    total_km = sum(s.get("distance_km", 0) for s in sessions)
    
    return {
        "focus": phase,
        "planned_load": target_load,
        "weekly_km": round(total_km, 1),
        "sessions": sessions,
        "total_tss": total_tss,
        "advice": get_phase_description(phase).get("advice", f"Focus sur la préparation {goal}. Respecte les allures cibles !")
    }


# ============================================================
# CACHE & UTILS
# ============================================================

def clear_cache() -> dict:
    """Vide les caches."""
    global _workout_cache, _weekly_cache, _plan_cache
    result = {
        "cleared_workout": len(_workout_cache),
        "cleared_weekly": len(_weekly_cache),
        "cleared_plan": len(_plan_cache)
    }
    _workout_cache = {}
    _weekly_cache = {}
    _plan_cache = {}
    return result


def get_cache_stats() -> dict:
    """Retourne les statistiques du cache."""
    return {
        "workout_cache_size": len(_workout_cache),
        "weekly_cache_size": len(_weekly_cache),
        "plan_cache_size": len(_plan_cache),
        "max_size": MAX_CACHE_SIZE,
        "ttl_seconds": CACHE_TTL_SECONDS
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "analyze_workout",
    "weekly_review", 
    "chat_response",
    "generate_dynamic_training_plan",
    "clear_cache",
    "get_cache_stats",
    "get_metrics",
    "reset_metrics"
]
