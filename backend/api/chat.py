from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
import logging
import uuid
from datetime import datetime, timezone

from database import db
from models import CoachRequest, CoachResponse, Message, ConversationMessage, ChatRequest, ChatResponse
from api.deps import auth_user, auth_user_optional, get_message_limit, SUBSCRIPTION_TIERS
from coach_service import chat_response as coach_chat_response, get_cache_stats, clear_cache, get_metrics as get_coach_metrics, reset_metrics as reset_coach_metrics
from llm_coach import LLM_MODEL, enrich_chat_response
from chat_engine import generate_chat_response, check_message_limit, get_remaining_messages
from api.workouts import get_mock_workouts

router = APIRouter()
logger = logging.getLogger(__name__)


def build_chat_context(workouts: list, user_goal: dict = None) -> dict:
    """
    Construit le contexte utilisateur pour le chat coach (LLM ou templates).
    # LLM serveur uniquement – pas d'exécution client-side
    """
    from datetime import timedelta
    
    context = {
        "km_semaine": 0,
        "nb_seances": 0,
        "allure": "N/A",
        "cadence": 0,
        "zones": {},
        "ratio": 1.0,
        "recent_workouts": [],
        "rag_tips": [],
    }
    
    if not workouts:
        return context
    
    # Filtrer les workouts de la semaine
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    
    week_workouts = []
    for w in workouts:
        try:
            w_date = datetime.fromisoformat(w.get("date", "").replace("Z", "+00:00")).date()
            if w_date >= week_start:
                week_workouts.append(w)
        except (ValueError, TypeError, AttributeError):
            pass
    
    # Stats de la semaine
    context["km_semaine"] = round(sum(w.get("distance_km", 0) for w in week_workouts), 1)
    context["nb_seances"] = len(week_workouts)
    
    # Allure moyenne
    total_time = sum(w.get("duration_minutes", 0) for w in week_workouts)
    total_km = context["km_semaine"]
    if total_km > 0 and total_time > 0:
        pace_min = total_time / total_km
        context["allure"] = f"{int(pace_min)}:{int((pace_min % 1) * 60):02d}"
    
    # Cadence moyenne
    cadences = [w.get("average_cadence", 0) for w in week_workouts if w.get("average_cadence")]
    if cadences:
        context["cadence"] = round(sum(cadences) / len(cadences))
    
    # Zones moyennes
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    for w in week_workouts:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z, pct in zones.items():
                if z in zone_totals:
                    zone_totals[z] += pct
            zone_count += 1
    
    if zone_count > 0:
        context["zones"] = {z: round(v / zone_count) for z, v in zone_totals.items()}
    
    # Ratio charge (simplifié)
    prev_week_km = sum(
        w.get("distance_km", 0) for w in workouts
        if (datetime.fromisoformat(w.get("date", "2000-01-01").replace("Z", "+00:00")).date() 
            >= week_start - timedelta(days=7))
        and (datetime.fromisoformat(w.get("date", "2000-01-01").replace("Z", "+00:00")).date() 
             < week_start)
    )
    if prev_week_km > 0:
        context["ratio"] = round(context["km_semaine"] / prev_week_km, 2)
    
    # Workouts récents (5 derniers)
    context["recent_workouts"] = [
        {
            "name": w.get("name", "Run"),
            "distance_km": w.get("distance_km", 0),
            "duration_min": w.get("duration_minutes", 0),
            "date": w.get("date", ""),
        }
        for w in workouts[:5]
    ]
    
    # Goal
    if user_goal:
        context["objectif_nom"] = user_goal.get("race_name", "")
        context["jours_course"] = user_goal.get("days_until", None)
    
    return context


@router.post("/chat/send", response_model=ChatResponse)
async def send_chat_message(request: ChatRequest):
    """Send a message to the chat coach (with tier-based limits)"""
    
    user_id = request.user_id
    
    # Get subscription status
    subscription = await db.subscriptions.find_one(
        {"user_id": user_id},
        {"_id": 0}
    )
    
    # Determine tier and limits
    tier = "free"
    tier_config = SUBSCRIPTION_TIERS["free"]
    
    if subscription and subscription.get("status") == "active":
        # Check expiration
        expires_at = subscription.get("expires_at")
        if expires_at:
            try:
                exp_date = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_date >= datetime.now(timezone.utc):
                    tier = subscription.get("tier", "starter")
                    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS["starter"])
            except (ValueError, TypeError):
                pass

    messages_limit = tier_config.get("messages_limit", 10)
    is_unlimited = tier_config.get("unlimited", False)

    # Get message count for current month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    message_count = await db.chat_messages.count_documents({
        "user_id": user_id,
        "role": "user",
        "timestamp": {"$gte": month_start.isoformat()}
    })
    
    # Check limit (soft limit for unlimited tier)
    if message_count >= messages_limit:
        if is_unlimited and message_count < 200:  # Hard cap for fair-use
            pass  # Allow but warn
        else:
            tier_name = tier_config.get("name", "Gratuit")
            raise HTTPException(
                status_code=429,
                detail=f"Tu as atteint ta limite de {messages_limit} messages ce mois-ci ({tier_name}). Passe au palier supérieur pour continuer ! 😊"
            )
    
    # Get user's recent workouts for context
    workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(50)
    if not workouts:
        workouts = get_mock_workouts()
    
    # Get user goal
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Generate response using local chat engine (NO LLM) - fallback mode
    # Note: If client uses WebLLM, it sends use_local_llm=True and we just store the message
    # LLM serveur uniquement – pas d'exécution client-side
    response_text = ""
    suggestions = []
    category = ""
    used_llm = False
    llm_metadata = {}
    
    if request.use_local_llm:
        # Client is using WebLLM, we just need to store messages and track count
        response_text = ""  # Client will generate this
    else:
        # Construire le contexte pour le LLM/RAG
        language = (request.language or "en").lower()
        if language not in ("en", "fr"):
            language = "en"
        context = build_chat_context(workouts, user_goal)
        context["language"] = language
        
        # Récupérer l'historique de conversation récent
        recent_messages = await db.chat_messages.find(
            {"user_id": user_id},
            {"_id": 0, "role": 1, "content": 1}
        ).sort("timestamp", -1).limit(8).to_list(8)
        recent_messages.reverse()  # Ordre chronologique
        
        # Cascade LLM → Templates via coach_service
        response_text, used_llm, llm_metadata = await coach_chat_response(
            message=request.message,
            context=context,
            history=recent_messages,
            user_id=user_id,
            workouts=workouts,
            user_goal=user_goal
        )
        
        if isinstance(llm_metadata, dict):
            suggestions = llm_metadata.get("suggestions", [])
        
        # Fallback suggestions in user language if LLM gave none
        if used_llm and not suggestions:
            allure = context.get("allure", "6:00")
            if language == "fr":
                suggestions = [
                    "Comment équilibrer mes zones d'entraînement ?",
                    f"Comment améliorer mon allure de {allure}/km ?",
                    "Quels exercices de renforcement faire ?",
                    "Comment travailler plus en endurance fondamentale ?",
                ]
            else:
                suggestions = [
                    "How do I balance my training zones?",
                    f"How can I improve my {allure}/km pace?",
                    "What strength exercises should I do?",
                    "How to train more in base endurance?",
                ]
    
    # Store user message
    user_msg_id = str(uuid.uuid4())
    await db.chat_messages.insert_one({
        "id": user_msg_id,
        "user_id": user_id,
        "role": "user",
        "content": request.message,
        "timestamp": now.isoformat()
    })
    
    # Store assistant response only if generated server-side
    assistant_msg_id = str(uuid.uuid4())
    if response_text:
        await db.chat_messages.insert_one({
            "id": assistant_msg_id,
            "user_id": user_id,
            "role": "assistant",
            "content": response_text,
            "suggestions": suggestions,  # Store suggestions too
            "timestamp": now.isoformat()
        })
    
    messages_remaining = max(0, messages_limit - message_count - 1) if not is_unlimited else 999
    
    source = f"Emergent LLM ({LLM_MODEL})" if used_llm else "Templates Python"
    duration_info = f" en {llm_metadata.get('duration_sec', 0)}s" if used_llm else ""
    logger.info(f"Chat message processed for user {user_id} (tier={tier}, source={source}{duration_info}). Remaining: {messages_remaining}")
    
    return ChatResponse(
        response=response_text,
        message_id=assistant_msg_id,
        messages_remaining=messages_remaining,
        messages_limit=messages_limit,
        is_unlimited=is_unlimited,
        suggestions=suggestions,
        category=category
    )


@router.post("/chat/store-response")
async def store_chat_response(user_id: str, message_id: str, response: str):
    """Store a response generated by client-side WebLLM"""
    await db.chat_messages.insert_one({
        "id": message_id,
        "user_id": user_id,
        "role": "assistant",
        "content": response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "webllm"
    })
    return {"success": True}


@router.get("/chat/history")
async def get_chat_history(user_id: str = "default", limit: int = 50):
    """Get chat history for a user"""
    
    messages = await db.chat_messages.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    # Reverse to chronological order
    messages.reverse()
    
    return messages


@router.delete("/chat/history")
async def clear_chat_history(user_id: str = "default"):
    """Clear chat history for a user"""
    
    result = await db.chat_messages.delete_many({"user_id": user_id})
    
    logger.info(f"Chat history cleared for user {user_id}: {result.deleted_count} messages")
    
    return {"success": True, "deleted_count": result.deleted_count}


@router.get("/cache/stats")
async def get_coach_cache_stats():
    """Get coach service cache statistics"""
    return get_cache_stats()


@router.delete("/cache/clear")
async def clear_coach_cache():
    """Clear all coach service caches"""
    result = clear_cache()
    logger.info(f"Cache cleared: {result}")
    return {"success": True, **result}


@router.get("/metrics")
async def get_service_metrics():
    """Get coach service metrics (LLM success rate, latency, etc.)"""
    return {
        "coach": get_coach_metrics(),
        "cache": get_cache_stats()
    }


@router.delete("/metrics/reset")
async def reset_service_metrics():
    """Reset coach service metrics"""
    old_metrics = reset_coach_metrics()
    logger.info(f"Metrics reset. Previous: {old_metrics}")
    return {"success": True, "previous": old_metrics}
