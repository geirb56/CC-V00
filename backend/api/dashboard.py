import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request
from typing import Optional

from database import db
from models import DashboardInsightResponse
from api.deps import auth_user, auth_user_optional, SUBSCRIPTION_TIERS, get_message_limit
from api.workouts import get_mock_workouts
from analysis_engine import generate_dashboard_insight

logger = logging.getLogger(__name__)

router = APIRouter()

DASHBOARD_INSIGHT_PROMPT_EN = """You are a calm, experienced running coach.
Generate ONE coaching sentence for the dashboard.

WEEK DATA: {week_data}
MONTH DATA: {month_data}

Rules:
- ONE sentence only, max 15 words
- Speak like a real coach, not a report
- Reassure and guide
- No numbers, no stats, no jargon
- The user should feel: "Ok, I understand. I know what to do."

Good examples:
- "Quiet week with just one run, makes sense for a restart."
- "Body is ready for a second easy outing."
- "Consistency matters more than intensity right now."

Bad (forbidden):
- "Volume analysis shows moderate load compared to baseline."
- Any mention of zones, bpm, or technical terms

100% ENGLISH only."""

DASHBOARD_INSIGHT_PROMPT_FR = """Tu es un coach running calme et experimente.
Genere UNE phrase de coaching pour le dashboard.

DONNEES SEMAINE: {week_data}
DONNEES MOIS: {month_data}

Regles:
- UNE seule phrase, max 15 mots
- Parle comme un vrai coach, pas comme un rapport
- Rassure et guide
- Pas de chiffres, pas de stats, pas de jargon
- L'utilisateur doit se dire: "Ok, je comprends. Je sais quoi faire."

Bons exemples:
- "Semaine tranquille avec une seule sortie, coherent pour une reprise."
- "Le corps est pret pour une deuxieme sortie facile."
- "La regularite compte plus que l'intensite pour l'instant."

Mauvais (interdit):
- "Analyse du volume montrant une charge moderee par rapport a la baseline."
- Toute mention de zones, bpm, ou termes techniques

100% FRANCAIS uniquement."""


def calculate_recovery_score(workouts: list, language: str = "en") -> dict:
    """Calculate recovery score based on recent training load, intensity, and rest days"""
    today = datetime.now(timezone.utc).date()
    
    # Get workouts from last 7 days
    recent_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            if (today - w_date).days <= 7:
                recent_workouts.append((w, w_date))
        except (ValueError, TypeError):
            continue
    
    # Get baseline (previous 7-14 days) for comparison
    baseline_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            days_ago = (today - w_date).days
            if 7 < days_ago <= 14:
                baseline_workouts.append(w)
        except (ValueError, TypeError):
            continue
    
    # Calculate factors
    # 1. Days since last workout (more rest = higher recovery)
    if recent_workouts:
        last_workout_date = max(w_date for _, w_date in recent_workouts)
        days_since_last = (today - last_workout_date).days
    else:
        days_since_last = 7  # No recent workouts = well rested
    
    # 2. Load comparison (current vs baseline)
    current_load = sum(w.get("distance_km", 0) for w, _ in recent_workouts)
    baseline_load = sum(w.get("distance_km", 0) for w in baseline_workouts)
    
    if baseline_load > 0:
        load_ratio = current_load / baseline_load
    else:
        load_ratio = 1.0 if current_load == 0 else 1.5
    
    # 3. Intensity (hard sessions in last 3 days)
    hard_sessions_recent = 0
    for w, w_date in recent_workouts:
        if (today - w_date).days <= 3:
            zones = w.get("effort_zone_distribution", {})
            if zones:
                hard_pct = zones.get("z4", 0) + zones.get("z5", 0)
                if hard_pct >= 25:
                    hard_sessions_recent += 1
    
    # 4. Session spread (better if spread across days)
    unique_days = len(set(w_date for _, w_date in recent_workouts))
    
    # Calculate score (0-100)
    score = 100
    
    # Penalize if workout was today or yesterday
    if days_since_last == 0:
        score -= 25
    elif days_since_last == 1:
        score -= 15
    elif days_since_last >= 3:
        score += 5  # Bonus for extra rest
    
    # Penalize high load ratio
    if load_ratio > 1.3:
        score -= 20
    elif load_ratio > 1.15:
        score -= 10
    elif load_ratio < 0.7:
        score += 10  # Low load = more recovery
    
    # Penalize hard sessions
    score -= hard_sessions_recent * 15
    
    # Penalize clustered sessions
    if len(recent_workouts) > 0 and unique_days < len(recent_workouts):
        score -= 10  # Multiple sessions on same day
    
    # Clamp score
    score = max(20, min(100, score))
    
    # Determine status and coach phrase
    if score >= 75:
        status = "ready"
        if language == "fr":
            phrase = "Corps repose, pret pour une seance intense si tu veux."
        else:
            phrase = "Body is rested, ready for an intense session if you want."
    elif score >= 50:
        status = "moderate"
        if language == "fr":
            phrase = "Recuperation correcte, privilegie une seance facile."
        else:
            phrase = "Decent recovery, favor an easy session."
    else:
        status = "low"
        if language == "fr":
            phrase = "Fatigue accumulee, une journee de repos serait ideale."
        else:
            phrase = "Accumulated fatigue, a rest day would be ideal."
    
    return {
        "score": score,
        "status": status,
        "phrase": phrase,
        "days_since_last_workout": days_since_last
    }


def calculate_week_stats(workouts: list) -> dict:
    """Calculate current week statistics"""
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    
    week_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            if week_start <= w_date <= today:
                week_workouts.append(w)
        except (ValueError, TypeError):
            continue
    
    total_km = sum(w.get("distance_km", 0) for w in week_workouts)
    sessions = len(week_workouts)
    
    # Load signal based on volume vs typical week
    if total_km > 80:
        load_signal = "high"
    elif total_km > 40:
        load_signal = "balanced"
    else:
        load_signal = "low"
    
    return {
        "sessions": sessions,
        "volume_km": round(total_km, 1),
        "load_signal": load_signal
    }


def calculate_month_stats(workouts: list) -> dict:
    """Calculate last 30 days statistics"""
    today = datetime.now(timezone.utc).date()
    month_start = today - timedelta(days=30)
    prev_month_start = today - timedelta(days=60)
    
    current_month = []
    prev_month = []
    
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date()
            if month_start <= w_date <= today:
                current_month.append(w)
            elif prev_month_start <= w_date < month_start:
                prev_month.append(w)
        except (ValueError, TypeError):
            continue
    
    current_km = sum(w.get("distance_km", 0) for w in current_month)
    prev_km = sum(w.get("distance_km", 0) for w in prev_month)
    
    # Active weeks (weeks with at least one workout)
    active_weeks = len(set(
        datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00").split("T")[0]).date().isocalendar()[1]
        for w in current_month if w.get("date")
    ))
    
    # Trend
    if prev_km > 0:
        change = (current_km - prev_km) / prev_km * 100
        if change > 15:
            trend = "up"
        elif change < -15:
            trend = "down"
        else:
            trend = "stable"
    else:
        trend = "up" if current_km > 0 else "stable"
    
    return {
        "volume_km": round(current_km, 1),
        "active_weeks": active_weeks,
        "trend": trend
    }


# Dashboard insight cache (5 minutes TTL)
_dashboard_cache = {}
DASHBOARD_CACHE_TTL = 300  # 5 minutes in seconds


@router.get("/dashboard/insight")
async def get_dashboard_insight(language: str = "en", user_id: str = "default"):
    """Get dashboard coach insight with week and month summaries and recovery score - NO LLM"""
    
    # Check cache first
    cache_key = f"{user_id}_{language}"
    now = datetime.now(timezone.utc).timestamp()
    
    if cache_key in _dashboard_cache:
        cached_data, cached_time = _dashboard_cache[cache_key]
        if now - cached_time < DASHBOARD_CACHE_TTL:
            logger.info(f"Dashboard insight cache hit for {cache_key}")
            return cached_data
    
    # Get workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(200)
    if not all_workouts:
        all_workouts = get_mock_workouts()
    
    # Calculate stats
    week_stats = calculate_week_stats(all_workouts)
    month_stats = calculate_month_stats(all_workouts)
    
    # Calculate recovery score
    recovery_score = calculate_recovery_score(all_workouts, language)
    
    # Generate insight using local engine (NO LLM)
    coach_insight = generate_dashboard_insight(
        week_stats=week_stats,
        month_stats=month_stats,
        recovery_score=recovery_score.get("score") if recovery_score else None,
        language=language
    )
    
    result = DashboardInsightResponse(
        coach_insight=coach_insight,
        week=week_stats,
        month=month_stats,
        recovery_score=recovery_score
    )
    
    # Store in cache
    _dashboard_cache[cache_key] = (result, now)
    logger.info(f"Dashboard insight cached for {cache_key}")
    
    return result
