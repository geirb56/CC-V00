import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from typing import List, Optional

from database import db
from models import (
    Workout, WorkoutCreate, VMAEstimationResponse,
    UserGoal, UserGoalCreate, TrainingStats
)
from api.deps import auth_user, auth_user_optional, SUBSCRIPTION_TIERS, get_message_limit

logger = logging.getLogger(__name__)

router = APIRouter()

# Distance types with km values
DISTANCE_TYPES = {
    "5k": 5.0,
    "10k": 10.0,
    "semi": 21.1,
    "marathon": 42.195,
    "ultra": 50.0  # Default for ultra, actual distance in event_name
}


def get_mock_workouts():
    """Generate mock workout data for demonstration with recent dates"""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()
    
    return [
        {
            "id": "w001",
            "type": "run",
            "name": "Morning Easy Run",
            "date": (today - timedelta(days=0)).isoformat(),
            "duration_minutes": 45,
            "distance_km": 8.2,
            "avg_heart_rate": 142,
            "max_heart_rate": 158,
            "avg_pace_min_km": 5.49,
            "elevation_gain_m": 85,
            "calories": 520,
            "effort_zone_distribution": {"z1": 15, "z2": 55, "z3": 25, "z4": 5, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w002",
            "type": "cycle",
            "name": "Tempo Ride",
            "date": (today - timedelta(days=1)).isoformat(),
            "duration_minutes": 90,
            "distance_km": 42.5,
            "avg_heart_rate": 155,
            "max_heart_rate": 172,
            "avg_speed_kmh": 28.3,
            "elevation_gain_m": 320,
            "calories": 1180,
            "effort_zone_distribution": {"z1": 5, "z2": 25, "z3": 45, "z4": 20, "z5": 5},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w003",
            "type": "run",
            "name": "Interval Session",
            "date": (today - timedelta(days=2)).isoformat(),
            "duration_minutes": 52,
            "distance_km": 10.1,
            "avg_heart_rate": 162,
            "max_heart_rate": 185,
            "avg_pace_min_km": 5.15,
            "elevation_gain_m": 45,
            "calories": 680,
            "effort_zone_distribution": {"z1": 10, "z2": 20, "z3": 25, "z4": 30, "z5": 15},
            "notes": "5x1000m @ threshold",
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w004",
            "type": "run",
            "name": "Long Run",
            "date": (today - timedelta(days=3)).isoformat(),
            "duration_minutes": 105,
            "distance_km": 18.5,
            "avg_heart_rate": 138,
            "max_heart_rate": 155,
            "avg_pace_min_km": 5.68,
            "elevation_gain_m": 180,
            "calories": 1350,
            "effort_zone_distribution": {"z1": 20, "z2": 65, "z3": 15, "z4": 0, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w005",
            "type": "cycle",
            "name": "Recovery Spin",
            "date": (today - timedelta(days=4)).isoformat(),
            "duration_minutes": 45,
            "distance_km": 18.0,
            "avg_heart_rate": 118,
            "max_heart_rate": 132,
            "avg_speed_kmh": 24.0,
            "elevation_gain_m": 50,
            "calories": 380,
            "effort_zone_distribution": {"z1": 60, "z2": 35, "z3": 5, "z4": 0, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w006",
            "type": "run",
            "name": "Hill Repeats",
            "date": (today - timedelta(days=5)).isoformat(),
            "duration_minutes": 48,
            "distance_km": 8.8,
            "avg_heart_rate": 158,
            "max_heart_rate": 178,
            "avg_pace_min_km": 5.45,
            "elevation_gain_m": 280,
            "calories": 620,
            "effort_zone_distribution": {"z1": 10, "z2": 25, "z3": 30, "z4": 25, "z5": 10},
            "notes": "8x200m hill sprints",
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w007",
            "type": "cycle",
            "name": "Endurance Base",
            "date": (today - timedelta(days=6)).isoformat(),
            "duration_minutes": 120,
            "distance_km": 55.0,
            "avg_heart_rate": 135,
            "max_heart_rate": 152,
            "avg_speed_kmh": 27.5,
            "elevation_gain_m": 420,
            "calories": 1520,
            "effort_zone_distribution": {"z1": 15, "z2": 60, "z3": 20, "z4": 5, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        # Baseline week (days 7-13)
        {
            "id": "w008",
            "type": "run",
            "name": "Recovery Run",
            "date": (today - timedelta(days=8)).isoformat(),
            "duration_minutes": 35,
            "distance_km": 6.0,
            "avg_heart_rate": 135,
            "max_heart_rate": 148,
            "avg_pace_min_km": 5.83,
            "elevation_gain_m": 40,
            "calories": 380,
            "effort_zone_distribution": {"z1": 25, "z2": 60, "z3": 15, "z4": 0, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w009",
            "type": "cycle",
            "name": "Steady Ride",
            "date": (today - timedelta(days=9)).isoformat(),
            "duration_minutes": 75,
            "distance_km": 35.0,
            "avg_heart_rate": 140,
            "max_heart_rate": 158,
            "avg_speed_kmh": 28.0,
            "elevation_gain_m": 250,
            "calories": 950,
            "effort_zone_distribution": {"z1": 10, "z2": 50, "z3": 30, "z4": 10, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w010",
            "type": "run",
            "name": "Tempo Run",
            "date": (today - timedelta(days=10)).isoformat(),
            "duration_minutes": 50,
            "distance_km": 10.0,
            "avg_heart_rate": 155,
            "max_heart_rate": 170,
            "avg_pace_min_km": 5.0,
            "elevation_gain_m": 60,
            "calories": 620,
            "effort_zone_distribution": {"z1": 5, "z2": 30, "z3": 45, "z4": 15, "z5": 5},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w011",
            "type": "run",
            "name": "Easy Run",
            "date": (today - timedelta(days=12)).isoformat(),
            "duration_minutes": 40,
            "distance_km": 7.5,
            "avg_heart_rate": 140,
            "max_heart_rate": 155,
            "avg_pace_min_km": 5.33,
            "elevation_gain_m": 50,
            "calories": 450,
            "effort_zone_distribution": {"z1": 20, "z2": 55, "z3": 20, "z4": 5, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "id": "w012",
            "type": "cycle",
            "name": "Long Ride",
            "date": (today - timedelta(days=13)).isoformat(),
            "duration_minutes": 150,
            "distance_km": 70.0,
            "avg_heart_rate": 132,
            "max_heart_rate": 155,
            "avg_speed_kmh": 28.0,
            "elevation_gain_m": 550,
            "calories": 1850,
            "effort_zone_distribution": {"z1": 20, "z2": 60, "z3": 15, "z4": 5, "z5": 0},
            "notes": None,
            "data_source": "manual",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]


def estimate_vma_from_race(distance_km: float, time_minutes: int) -> dict:
    """Estimate VMA from race performance using VDOT tables (Jack Daniels)"""
    if distance_km <= 0 or time_minutes <= 0:
        return None
    
    # Calculate pace in min/km
    pace_min_km = time_minutes / distance_km
    
    # Simplified VDOT estimation based on pace
    # These are approximations from Jack Daniels' tables
    speed_kmh = 60 / pace_min_km  # Convert pace to km/h
    
    # VMA is approximately the speed you can sustain for 4-7 minutes
    # From race performance, we estimate VMA based on distance
    # Longer distances = lower % of VMA
    vma_percentage = {
        5: 0.95,      # 5km ≈ 95% VMA
        10: 0.90,     # 10km ≈ 90% VMA
        21.1: 0.85,   # Semi ≈ 85% VMA
        42.195: 0.80  # Marathon ≈ 80% VMA
    }
    
    # Find closest distance
    closest_dist = min(vma_percentage.keys(), key=lambda x: abs(x - distance_km))
    pct = vma_percentage[closest_dist]
    
    vma_kmh = speed_kmh / pct
    vo2max = vma_kmh * 3.5  # Standard formula: VO2max ≈ VMA × 3.5
    
    return {
        "vma_kmh": round(vma_kmh, 1),
        "vo2max": round(vo2max, 1),
        "method": "race_performance",
        "confidence": "high" if distance_km >= 5 else "medium"
    }


def estimate_vma_from_workouts(workouts: list) -> dict:
    """Estimate VMA from training data (Z5 efforts)"""
    
    # Filter running workouts with HR zones
    running_workouts = [
        w for w in workouts 
        if w.get("type") == "run" and w.get("effort_zone_distribution")
    ]
    
    if len(running_workouts) < 3:
        return {
            "has_sufficient_data": False,
            "reason": "need_more_workouts",
            "count": len(running_workouts)
        }
    
    # Analyze Z5 efforts
    z5_efforts = []
    z4_efforts = []
    
    for w in running_workouts:
        zones = w.get("effort_zone_distribution", {})
        z5_pct = zones.get("z5", 0) or 0
        z4_pct = zones.get("z4", 0) or 0
        duration = w.get("duration_minutes", 0)
        
        # Z5 time in minutes
        z5_time = (z5_pct / 100) * duration
        z4_time = (z4_pct / 100) * duration
        
        # Best pace as proxy for VMA effort
        best_pace = w.get("best_pace_min_km")
        avg_pace = w.get("avg_pace_min_km")
        
        if z5_time >= 2 and best_pace:  # At least 2 min in Z5
            z5_efforts.append({
                "workout": w.get("name"),
                "date": w.get("date"),
                "z5_time_min": z5_time,
                "best_pace": best_pace,
                "avg_pace": avg_pace
            })
        
        if z4_time >= 5 and avg_pace:  # At least 5 min in Z4
            z4_efforts.append({
                "workout": w.get("name"),
                "date": w.get("date"),
                "z4_time_min": z4_time,
                "avg_pace": avg_pace
            })
    
    # Priority 1: Use Z5 efforts (most reliable)
    if len(z5_efforts) >= 2:
        # Take best paces from Z5 efforts
        best_paces = [e["best_pace"] for e in z5_efforts if e["best_pace"]]
        if best_paces:
            # VMA ≈ best pace in Z5 (slightly faster)
            avg_best_pace = sum(best_paces) / len(best_paces)
            vma_kmh = 60 / avg_best_pace  # Convert min/km to km/h
            vo2max = vma_kmh * 3.5
            
            return {
                "has_sufficient_data": True,
                "vma_kmh": round(vma_kmh, 1),
                "vo2max": round(vo2max, 1),
                "method": "z5_efforts",
                "confidence": "medium",
                "sample_count": len(z5_efforts),
                "efforts": z5_efforts[:3]  # Return top 3 for reference
            }
    
    # Priority 2: Use Z4 efforts (less reliable)
    if len(z4_efforts) >= 3:
        avg_paces = [e["avg_pace"] for e in z4_efforts if e["avg_pace"]]
        if avg_paces:
            # Z4 pace ≈ 85-90% VMA, so VMA ≈ Z4 pace / 0.87
            avg_z4_pace = sum(avg_paces) / len(avg_paces)
            z4_speed = 60 / avg_z4_pace
            vma_kmh = z4_speed / 0.87
            vo2max = vma_kmh * 3.5
            
            return {
                "has_sufficient_data": True,
                "vma_kmh": round(vma_kmh, 1),
                "vo2max": round(vo2max, 1),
                "method": "z4_extrapolation",
                "confidence": "low",
                "sample_count": len(z4_efforts),
                "warning": "Estimation basée sur Z4 uniquement - moins fiable"
            }
    
    # Not enough high-intensity data
    return {
        "has_sufficient_data": False,
        "reason": "need_high_intensity",
        "z5_count": len(z5_efforts),
        "z4_count": len(z4_efforts)
    }


def calculate_training_zones(vma_kmh: float, language: str = "en") -> dict:
    """Calculate training zones based on VMA"""
    
    def kmh_to_pace(speed_kmh):
        if speed_kmh <= 0:
            return None
        pace = 60 / speed_kmh
        mins = int(pace)
        secs = int((pace - mins) * 60)
        return f"{mins}:{secs:02d}"
    
    zones = {
        "z1": {
            "name": "Recovery" if language == "en" else "Récupération",
            "pct_vma": "60-65%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.60)} - {kmh_to_pace(vma_kmh * 0.65)}"
        },
        "z2": {
            "name": "Endurance" if language == "en" else "Endurance",
            "pct_vma": "65-75%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.65)} - {kmh_to_pace(vma_kmh * 0.75)}"
        },
        "z3": {
            "name": "Tempo" if language == "en" else "Tempo",
            "pct_vma": "75-85%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.75)} - {kmh_to_pace(vma_kmh * 0.85)}"
        },
        "z4": {
            "name": "Threshold" if language == "en" else "Seuil",
            "pct_vma": "85-95%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.85)} - {kmh_to_pace(vma_kmh * 0.95)}"
        },
        "z5": {
            "name": "VMA/VO2max",
            "pct_vma": "95-105%",
            "pace_range": f"{kmh_to_pace(vma_kmh * 0.95)} - {kmh_to_pace(vma_kmh * 1.05)}"
        }
    }
    
    return zones


def calculate_target_pace(distance_km: float, target_time_minutes: int) -> str:
    """Calculate target pace in min/km format"""
    if distance_km <= 0 or target_time_minutes <= 0:
        return None
    pace_minutes = target_time_minutes / distance_km
    pace_min = int(pace_minutes)
    pace_sec = int((pace_minutes - pace_min) * 60)
    return f"{pace_min}:{pace_sec:02d}"


def format_target_time(minutes: int) -> str:
    """Format target time as Xh:MM"""
    if not minutes:
        return None
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h{mins:02d}"
    return f"{mins}min"


# ========== ROUTES ==========

@router.get("/")
async def root():
    return {"message": "CardioCoach API"}


@router.get("/workouts", response_model=List[dict])
async def get_workouts(user_id: str = "default"):
    """Get all workouts for a user, sorted by date descending"""
    # Search for workouts with user_id OR without user_id (Strava imports)
    workouts = await db.workouts.find(
        {"$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}]}, 
        {"_id": 0}
    ).sort("date", -1).to_list(200)
    if not workouts:
        workouts = get_mock_workouts()
    return workouts


@router.get("/workouts/{workout_id}")
async def get_workout(workout_id: str, user_id: str = "default"):
    """Get a specific workout by ID"""
    # Search with or without user_id
    workout = await db.workouts.find_one(
        {"id": workout_id, "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}]}, 
        {"_id": 0}
    )
    if not workout:
        # Check mock data
        mock = get_mock_workouts()
        workout = next((w for w in mock if w["id"] == workout_id), None)
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    return workout


@router.post("/workouts", response_model=Workout)
async def create_workout(workout: WorkoutCreate, user_id: str = "default"):
    """Create a new workout"""
    workout_obj = Workout(**workout.model_dump())
    doc = workout_obj.model_dump()
    doc["user_id"] = user_id
    await db.workouts.insert_one(doc)
    return workout_obj


@router.get("/user/vma-estimate")
async def get_vma_estimate(user_id: str = "default", language: str = "en"):
    """Estimate VMA and VO2max from user data"""
    
    # Check if user has a goal (race performance to use)
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Get all running workouts
    all_workouts = await db.workouts.find(
        {"type": "run"}, 
        {"_id": 0}
    ).sort("date", -1).to_list(100)
    
    if not all_workouts:
        return VMAEstimationResponse(
            has_sufficient_data=False,
            confidence="insufficient",
            confidence_score=0,
            message="Données insuffisantes. Aucune séance de course enregistrée." if language == "fr" else "Insufficient data. No running workouts recorded.",
            recommendations=[
                "Synchronise tes séances Strava" if language == "fr" else "Sync your Strava workouts",
                "Fais quelques sorties avec cardiofréquencemètre" if language == "fr" else "Do some runs with heart rate monitor"
            ]
        )
    
    result = None
    data_source = None
    
    # Priority 1: Use goal race performance if it's a past event or use target
    if user_goal and user_goal.get("target_time_minutes") and user_goal.get("distance_km"):
        race_estimate = estimate_vma_from_race(
            user_goal["distance_km"],
            user_goal["target_time_minutes"]
        )
        if race_estimate:
            result = race_estimate
            data_source = f"Objectif: {user_goal['event_name']}" if language == "fr" else f"Goal: {user_goal['event_name']}"
    
    # Priority 2: Analyze workout data
    if not result:
        workout_estimate = estimate_vma_from_workouts(all_workouts)
        
        if not workout_estimate.get("has_sufficient_data"):
            reason = workout_estimate.get("reason")
            
            if reason == "need_more_workouts":
                msg = f"Données insuffisantes. Seulement {workout_estimate.get('count')} séances avec données cardio." if language == "fr" else f"Insufficient data. Only {workout_estimate.get('count')} workouts with HR data."
                recs = [
                    "Continue à synchroniser tes séances" if language == "fr" else "Keep syncing your workouts",
                    "Au moins 3 séances avec cardiofréquencemètre nécessaires" if language == "fr" else "At least 3 workouts with HR monitor needed"
                ]
            else:  # need_high_intensity
                msg = f"Données insuffisantes. Pas assez d'efforts intenses (Z4/Z5) pour estimer la VMA." if language == "fr" else f"Insufficient data. Not enough high-intensity efforts (Z4/Z5) to estimate VMA."
                recs = [
                    "Fais une séance de fractionné ou un test VMA" if language == "fr" else "Do an interval session or VMA test",
                    f"Séances Z5 trouvées: {workout_estimate.get('z5_count', 0)}, Z4: {workout_estimate.get('z4_count', 0)}"
                ]
            
            return VMAEstimationResponse(
                has_sufficient_data=False,
                confidence="insufficient",
                confidence_score=0,
                message=msg,
                recommendations=recs
            )
        
        result = workout_estimate
        method = result.get("method")
        if method == "z5_efforts":
            data_source = f"Analyse de {result.get('sample_count')} efforts Z5" if language == "fr" else f"Analysis of {result.get('sample_count')} Z5 efforts"
        else:
            data_source = f"Extrapolation depuis {result.get('sample_count')} séances Z4" if language == "fr" else f"Extrapolation from {result.get('sample_count')} Z4 sessions"
    
    # Calculate training zones
    vma_kmh = result["vma_kmh"]
    vo2max = result["vo2max"]
    training_zones = calculate_training_zones(vma_kmh, language)
    
    # Confidence mapping
    confidence = result.get("confidence", "medium")
    confidence_scores = {"high": 5, "medium": 3, "low": 2}
    confidence_score = confidence_scores.get(confidence, 1)
    
    # Build message
    if confidence == "high":
        msg = f"VMA estimée avec bonne fiabilité depuis ton objectif de course." if language == "fr" else "VMA estimated with good reliability from your race goal."
    elif confidence == "medium":
        msg = f"VMA estimée depuis tes efforts intenses. Fiabilité correcte." if language == "fr" else "VMA estimated from your intense efforts. Decent reliability."
    else:
        msg = f"VMA estimée par extrapolation. Fiabilité limitée - un test VMA serait plus précis." if language == "fr" else "VMA estimated by extrapolation. Limited reliability - a VMA test would be more accurate."
    
    # Recommendations based on VMA
    if language == "fr":
        recs = [
            f"Endurance fondamentale: {training_zones['z2']['pace_range']}/km",
            f"Allure seuil (tempo): {training_zones['z4']['pace_range']}/km",
            f"Fractionné VMA: {training_zones['z5']['pace_range']}/km"
        ]
    else:
        recs = [
            f"Easy/endurance pace: {training_zones['z2']['pace_range']}/km",
            f"Threshold (tempo) pace: {training_zones['z4']['pace_range']}/km",
            f"VMA intervals: {training_zones['z5']['pace_range']}/km"
        ]
    
    return VMAEstimationResponse(
        has_sufficient_data=True,
        confidence=confidence,
        confidence_score=confidence_score,
        vma_kmh=vma_kmh,
        vo2max=vo2max,
        data_source=data_source,
        training_zones=training_zones,
        message=msg,
        recommendations=recs
    )


@router.get("/user/goal")
async def get_user_goal(user_id: str = "default"):
    """Get user's current goal"""
    goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    return goal


@router.post("/user/goal")
async def set_user_goal(goal: UserGoalCreate, user_id: str = "default"):
    """Set user's goal (event with date, distance, target time)"""
    # Delete existing goal
    await db.user_goals.delete_many({"user_id": user_id})
    
    # Get distance in km
    distance_km = DISTANCE_TYPES.get(goal.distance_type, 42.195)
    
    # Calculate target pace if time provided
    target_pace = None
    if goal.target_time_minutes:
        target_pace = calculate_target_pace(distance_km, goal.target_time_minutes)
    
    # Create new goal
    goal_obj = UserGoal(
        user_id=user_id,
        event_name=goal.event_name,
        event_date=goal.event_date,
        distance_type=goal.distance_type,
        distance_km=distance_km,
        target_time_minutes=goal.target_time_minutes,
        target_pace=target_pace
    )
    doc = goal_obj.model_dump()
    await db.user_goals.insert_one(doc)
    
    # Return without _id
    doc.pop("_id", None)
    
    logger.info(f"Goal set for user {user_id}: {goal.event_name} ({goal.distance_type}) on {goal.event_date}, target: {goal.target_time_minutes}min")
    return {"success": True, "goal": doc}


@router.delete("/user/goal")
async def delete_user_goal(user_id: str = "default"):
    """Delete user's goal"""
    result = await db.user_goals.delete_many({"user_id": user_id})
    return {"deleted": result.deleted_count > 0}


@router.get("/stats")
async def get_stats():
    """Get training statistics with proper 7-day and 30-day calculations"""
    from datetime import datetime, timedelta
    from collections import defaultdict
    
    # Get all workouts
    workouts = await db.workouts.find({}, {"_id": 0}).to_list(500)
    
    # Also check Strava activities
    strava_activities = await db.strava_activities.find({}, {"_id": 0}).to_list(500)
    
    # Merge both sources
    all_activities = []
    
    for w in workouts:
        date_str = w.get("date", "")[:10]
        if date_str:
            all_activities.append({
                "date": date_str,
                "distance_km": w.get("distance_km", 0),
                "duration_minutes": w.get("duration_minutes", 0),
                "avg_heart_rate": w.get("avg_heart_rate"),
                "type": w.get("type", "run")
            })
    
    for a in strava_activities:
        date_str = a.get("start_date_local", "")[:10]
        dist = a.get("distance", 0)
        if dist > 1000:
            dist = dist / 1000
        duration = a.get("moving_time", 0)
        if duration > 100:
            duration = duration / 60
        if date_str:
            all_activities.append({
                "date": date_str,
                "distance_km": dist,
                "duration_minutes": duration,
                "avg_heart_rate": a.get("average_heartrate"),
                "type": a.get("type", "run").lower()
            })
    
    if not all_activities:
        all_activities = [{
            "date": (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"),
            "distance_km": 8 + (i % 5),
            "duration_minutes": 45 + (i % 20),
            "avg_heart_rate": 140,
            "type": "run"
        } for i in range(10)]
    
    # Calculate date boundaries
    today = datetime.now().date()
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)
    
    # Filter activities by period
    last_7_days = []
    last_30_days = []
    
    for a in all_activities:
        try:
            activity_date = datetime.strptime(a["date"], "%Y-%m-%d").date()
            if activity_date >= seven_days_ago:
                last_7_days.append(a)
            if activity_date >= thirty_days_ago:
                last_30_days.append(a)
        except:
            continue
    
    # Calculate 7-day stats
    km_7_days = sum(a.get("distance_km", 0) for a in last_7_days)
    sessions_7_days = len(last_7_days)
    
    # Calculate 30-day stats
    km_30_days = sum(a.get("distance_km", 0) for a in last_30_days)
    sessions_30_days = len(last_30_days)
    
    # Total stats
    total_distance = sum(a.get("distance_km", 0) for a in all_activities)
    total_duration = sum(a.get("duration_minutes", 0) for a in all_activities)
    
    hr_values = [a.get("avg_heart_rate") for a in all_activities if a.get("avg_heart_rate")]
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else None
    
    # Count by type
    by_type = {}
    for a in all_activities:
        t = a.get("type", "other")
        by_type[t] = by_type.get(t, 0) + 1
    
    # Daily breakdown for last 7 days
    daily_data = defaultdict(lambda: {"distance": 0, "duration": 0, "count": 0})
    for a in last_7_days:
        date_str = a.get("date", "")
        daily_data[date_str]["distance"] += a.get("distance_km", 0)
        daily_data[date_str]["duration"] += a.get("duration_minutes", 0)
        daily_data[date_str]["count"] += 1
    
    weekly_summary = []
    for date, data in sorted(daily_data.items()):
        weekly_summary.append({"date": date, **data})
    
    return {
        "total_workouts": len(all_activities),
        "total_distance_km": round(total_distance, 1),
        "total_duration_minutes": int(total_duration),
        "avg_heart_rate": round(avg_hr, 1) if avg_hr else None,
        "workouts_by_type": by_type,
        "weekly_summary": weekly_summary,
        # New fields for precise calculations
        "sessions_7_days": sessions_7_days,
        "km_7_days": round(km_7_days, 1),
        "sessions_30_days": sessions_30_days,
        "km_30_days": round(km_30_days, 1)
    }
