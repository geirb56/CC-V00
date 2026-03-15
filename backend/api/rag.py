from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging
from datetime import datetime, timezone, timedelta

from database import db
from api.deps import auth_user
from api.workouts import get_mock_workouts
from rag_engine import generate_dashboard_rag, generate_weekly_review_rag, generate_workout_analysis_rag
from coach_service import analyze_workout as coach_analyze_workout, weekly_review as coach_weekly_review

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/rag/dashboard")
async def get_rag_dashboard(user_id: str = "default"):
    """Get RAG-enriched dashboard summary"""
    # Fetch workouts - use same logic as /api/workouts (no user_id filter since data has None)
    # This matches the main workouts endpoint behavior
    workouts = await db.workouts.find(
        {},  # No filter - workouts in DB have user_id=None
        {"_id": 0}
    ).sort("date", -1).limit(100).to_list(length=100)
    
    # Fetch previous bilans
    bilans = await db.digests.find(
        {},  # No filter for consistency
        {"_id": 0}
    ).sort("generated_at", -1).limit(8).to_list(length=8)
    
    # Fetch user goal
    user_goal = await db.user_goals.find_one({}, {"_id": 0})
    
    # Generate RAG-enriched summary
    result = generate_dashboard_rag(workouts, bilans, user_goal)
    
    return {
        "rag_summary": result["summary"],
        "metrics": result["metrics"],
        "points_forts": result["points_forts"],
        "points_ameliorer": result["points_ameliorer"],
        "tips": result["tips"],
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/rag/weekly-review")
async def get_rag_weekly_review(user_id: str = "default"):
    """Get RAG-enriched weekly review with GPT-4o-mini enhancement"""
    # Fetch workouts
    workouts = await db.workouts.find(
        {},
        {"_id": 0}
    ).sort("date", -1).limit(50).to_list(length=50)
    
    # Fetch previous bilans
    bilans = await db.digests.find(
        {},
        {"_id": 0}
    ).sort("generated_at", -1).limit(8).to_list(length=8)
    
    # Fetch user goal
    user_goal = await db.user_goals.find_one({}, {"_id": 0})
    
    # Generate RAG-enriched review (calculs 100% Python local)
    result = generate_weekly_review_rag(workouts, bilans, user_goal)
    
    # Enrichissement via coach_service (cascade LLM → déterministe)
    enriched_summary, used_llm = await coach_weekly_review(
        rag_result=result,
        user_id=user_id
    )
    
    return {
        "rag_summary": enriched_summary,
        "metrics": result["metrics"],
        "comparison": result["comparison"],
        "points_forts": result["points_forts"],
        "points_ameliorer": result["points_ameliorer"],
        "tips": result["tips"],
        "enriched_by_llm": used_llm,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


@router.get("/rag/workout/{workout_id}")
async def get_rag_workout_analysis(workout_id: str, user_id: str = "default"):
    """Get RAG-enriched workout analysis with GPT-4o-mini enhancement"""
    # Fetch the workout
    workout = await db.workouts.find_one(
        {"id": workout_id},
        {"_id": 0}
    )
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    # Fetch all workouts for comparison
    all_workouts = await db.workouts.find(
        {},
        {"_id": 0}
    ).sort("date", -1).limit(100).to_list(length=100)
    
    # Fetch user goal
    user_goal = await db.user_goals.find_one({}, {"_id": 0})
    
    # Generate RAG-enriched analysis (calculs 100% Python local)
    result = generate_workout_analysis_rag(workout, all_workouts, user_goal)
    
    # Enrichissement via coach_service (cascade LLM → déterministe)
    enriched_summary, used_llm = await coach_analyze_workout(
        workout=workout,
        rag_result=result,
        user_id=user_id
    )
    
    return {
        "rag_summary": enriched_summary,
        "workout": result["workout"],
        "comparison": result["comparison"],
        "points_forts": result["points_forts"],
        "points_ameliorer": result["points_ameliorer"],
        "tips": result["tips"],
        "rag_sources": result.get("rag_sources", {}),
        "enriched_by_llm": used_llm,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
