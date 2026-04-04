"""
CardioCoach - LLM Coach Module (GPT-4o-mini)

This module handles the enrichment of coach texts via GPT-4o-mini.
Training data is sent directly to the LLM to
generate personalized and motivating analyses.

Flow:
1. Receive training data
2. Send to GPT-4o-mini for text generation
3. Error returned if API is not available
"""

import os
import time
import json
import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configuration
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
LLM_MODEL = "gpt-4.1-mini"
LLM_PROVIDER = "openai"
LLM_TIMEOUT = 15


# ============================================================
# SYSTEM PROMPTS
# ============================================================

SYSTEM_PROMPT_COACH = """You are CardioCoach, an expert and caring personal running coach.

🎯 YOUR ROLE:
You answer the athlete's questions about their training like a real personal coach.
You have access to ALL their real training data: complete session history, training plan, VO2max, race predictions, fitness metrics.

📊 AVAILABLE DATA:
- COMPLETE session history (last 28 days with distance, duration, pace, HR)
- Weekly training plan (goal, planned sessions)
- Estimated VO2max and race time predictions
- Fitness metrics: ACWR (acute/chronic workload ratio), TSB (freshness)
- Current goal (5K, 10K, Half, Marathon, Ultra)

💬 RESPONSE STYLE:
1. Be direct and concise (3-5 sentences max unless detailed analysis requested)
2. Use real data to personalize your response
3. Give actionable advice based on past sessions
4. Stay motivating and positive, even for critiques
5. If you don't know, say so honestly

🏃 EXPERTISE:
- Training plans (5K, 10K, half, marathon, ultra)
- Load management and recovery
- Heart rate zones and target paces
- Injury prevention
- Basic nutrition and hydration
- Progression and periodization
- Performance analysis and predictions

⚠️ IMPORTANT:
- ALWAYS respond in the user's language (FR or EN)
- Don't use bullet points unless requested
- Speak like a human coach, not like a report
- Refer to specific sessions when relevant"""

SYSTEM_PROMPT_BILAN = """You are a running coach providing a weekly review.

Review structure:
1. Positive intro (congratulate consistency or effort)
2. Analysis of key metrics (explain simply)
3. Strengths (max 2)
4. Area to improve (max 1, framed positively)
5. Advice for next week
6. Motivating follow-up question

Be encouraging even if stats are average. Max 6-8 sentences."""

SYSTEM_PROMPT_SEANCE = """You are a running coach analyzing a session.

Structure:
1. Positive reaction to the effort
2. Simple data analysis (pace, HR, consistency)
3. Session highlight
4. Advice for next run
5. Motivating follow-up (optional)

Be concrete and encouraging. Max 4-5 sentences."""

SYSTEM_PROMPT_PLAN = """You are an elite running coach specialized in periodization.
Respond ONLY in valid JSON, without text before or after."""


# ============================================================
# ENRICHMENT FUNCTIONS
# ============================================================

async def enrich_chat_response(
    user_message: str,
    context: Dict,
    conversation_history: List[Dict],
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches chat response with GPT-4o-mini.

    Context includes:
    - 7-day and 28-day stats (km, sessions)
    - Fitness metrics (ACWR, TSB)
    - ALL sessions from last 28 days
    - Current training plan
    - Estimated VO2max and race predictions
    - Current goal
    """
    language = context.get("language", "fr")

    # Format context in readable format
    stats_7 = context.get("stats_7j", {})
    stats_28 = context.get("stats_28j", {})
    fitness = context.get("fitness", {})
    all_sessions = context.get("all_sessions", "")
    training_plan = context.get("training_plan", "")
    current_goal = context.get("current_goal", "Not set")
    vma = context.get("vma", "")
    predictions = context.get("predictions", "")
    workout = context.get("workout_detail")

    context_text = f"""📊 COMPLETE ATHLETE DATA:

🎯 CURRENT GOAL: {current_goal}

⚡ PERFORMANCE:
- {vma}
- Predictions: {predictions}

📈 THIS WEEK (7d):
- Volume: {stats_7.get('km', 0)} km
- Sessions: {stats_7.get('sessions', 0)}

📅 THIS MONTH (28d):
- Volume: {stats_28.get('km', 0)} km
- Sessions: {stats_28.get('sessions', 0)}

💪 FITNESS STATUS:
- ACWR: {fitness.get('acwr', 1.0)} ({fitness.get('acwr_status', 'ok')})
- TSB: {fitness.get('tsb', 0)} ({fitness.get('tsb_status', 'normal')})

📋 TRAINING PLAN:
{training_plan if training_plan else "No active plan"}

🏃 COMPLETE SESSION HISTORY (last 28 days):
{all_sessions}"""

    # Add workout details if available
    if workout:
        zones = workout.get('zones', {})
        zones_str = ""
        if zones:
            zones_str = f"Z1:{zones.get('z1',0)}% Z2:{zones.get('z2',0)}% Z3:{zones.get('z3',0)}% Z4:{zones.get('z4',0)}% Z5:{zones.get('z5',0)}%"

        context_text += f"""

🔍 SESSION BEING ANALYZED:
- Name: {workout.get('name', 'N/A')}
- Distance: {workout.get('distance_km', 0):.1f} km
- Duration: {workout.get('duration_min', 0):.0f} min
- Avg HR: {workout.get('avg_hr', 'N/A')} bpm
- Max HR: {workout.get('max_hr', 'N/A')} bpm
- Zones: {zones_str}"""

    # Format conversation history
    history_text = ""
    if conversation_history:
        for msg in conversation_history[-4:]:  # last 4 messages max
            role = "Athlete" if msg.get("role") == "user" else "Coach"
            content = msg.get("content", "")[:200]  # Truncate if too long
            history_text += f"{role}: {content}\n"

    prompt = f"""{context_text}

💬 CONVERSATION HISTORY:
{history_text if history_text else "(New conversation)"}

❓ ATHLETE'S QUESTION: {user_message}

Respond in {language.upper()} as a caring and expert personal coach. Use the data above to personalize your response."""

    return await _call_gpt(SYSTEM_PROMPT_COACH, prompt, user_id, "chat")


async def enrich_weekly_review(
    stats: Dict,
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches weekly review with GPT-4o-mini."""
    prompt = f"""WEEKLY STATS:
{_format_context(stats)}

Generate a motivating and personalized weekly review based on this data."""

    return await _call_gpt(SYSTEM_PROMPT_BILAN, prompt, user_id, "bilan")


async def enrich_workout_analysis(
    workout: Dict,
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enriches workout analysis with GPT-4o-mini."""
    prompt = f"""SESSION DATA:
{_format_context(workout)}

Analyze this session as a caring running coach."""

    return await _call_gpt(SYSTEM_PROMPT_SEANCE, prompt, user_id, "seance")


async def generate_cycle_week(
    context: Dict,
    phase: str,
    target_load: int,
    goal: str,
    user_id: str = "unknown",
    sessions_per_week: int = None,
    personalized_paces: Dict = None
) -> Tuple[Optional[Dict], bool, Dict]:
    """
    Generates a structured weekly training plan with personalized paces.

    Args:
        context: Fitness data (CTL, ATL, TSB, ACWR, weekly_km, vma, vo2max, paces)
        phase: Current phase (build, deload, intensification, taper, race)
        target_load: Target load in TSS
        goal: Goal (5K, 10K, SEMI, MARATHON, ULTRA)
        user_id: User ID
        sessions_per_week: Number of sessions per week (3, 4, 5, 6)
        personalized_paces: Personalized paces based on VO2max (z1, z2, z3, z4, z5, marathon, half)

    Returns:
        (plan_dict, success, metadata)
    """
    # Athlete's current volume (based on last 4 weeks)
    current_weekly_km = context.get('weekly_km', 30)

    # Race distance by goal (in km)
    race_distances = {
        "5K": 5,
        "10K": 10,
        "SEMI": 21.1,
        "MARATHON": 42.2,
        "ULTRA": 60,
    }
    race_km = race_distances.get(goal, 21.1)

    # RECOMMENDED minimum volumes (based on real training data)
    # Source: coaching recommendations to finish without struggling
    goal_configs = {
        "5K": {"min": 15, "max": 45, "sessions": 3, "long_min": 8, "long_max": 10},
        "10K": {"min": 20, "max": 60, "sessions": 3, "long_min": 10, "long_max": 14},
        "SEMI": {"min": 30, "max": 80, "sessions": 3, "long_min": 16, "long_max": 18},
        "MARATHON": {"min": 40, "max": 120, "sessions": 4, "long_min": 28, "long_max": 32},
        "ULTRA": {"min": 50, "max": 150, "sessions": 5, "long_min": 35, "long_max": 45},
    }

    config = goal_configs.get(goal, goal_configs["SEMI"])

    # Number of sessions (user or default)
    target_sessions = sessions_per_week if sessions_per_week in [3, 4, 5, 6] else config["sessions"]
    num_rest_days = 7 - target_sessions

    # Minimum volume = max(current volume, minimum recommended for goal)
    volume_min = max(current_weekly_km, config["min"])
    volume_max = config["max"]

    # Target volume calculation: +7% progressive, limited between min and max
    progression_factor = 1.07
    target_km_raw = current_weekly_km * progression_factor
    target_km = max(volume_min, min(volume_max, round(target_km_raw)))

    # Long run = proportional to volume, between long_min and long_max
    long_ratio = (target_km - config["min"]) / (config["max"] - config["min"]) if config["max"] > config["min"] else 0.5
    target_long_run = round(config["long_min"] + long_ratio * (config["long_max"] - config["long_min"]))
    target_long_run = max(config["long_min"], min(config["long_max"], target_long_run))

    # Generate rest and run days according to number of sessions
    if target_sessions == 3:
        rest_days = ["Monday", "Wednesday", "Friday", "Saturday"]
        run_days_config = [
            ("Tuesday", "Endurance", "easy"),
            ("Thursday", "Threshold", "hard"),
            ("Sunday", "Long run", "moderate")
        ]
    elif target_sessions == 4:
        rest_days = ["Monday", "Wednesday", "Friday"]
        run_days_config = [
            ("Tuesday", "Endurance", "easy"),
            ("Thursday", "Threshold", "hard"),
            ("Saturday", "Tempo", "moderate"),
            ("Sunday", "Long run", "moderate")
        ]
    elif target_sessions == 5:
        rest_days = ["Monday", "Friday"]
        run_days_config = [
            ("Tuesday", "Endurance", "easy"),
            ("Wednesday", "Threshold", "hard"),
            ("Thursday", "Recovery", "easy"),
            ("Saturday", "Tempo", "moderate"),
            ("Sunday", "Long run", "moderate")
        ]
    else:  # 6 sessions
        rest_days = ["Friday"]
        run_days_config = [
            ("Monday", "Recovery", "easy"),
            ("Tuesday", "Endurance", "easy"),
            ("Wednesday", "Threshold", "hard"),
            ("Thursday", "Recovery", "easy"),
            ("Saturday", "Tempo", "moderate"),
            ("Sunday", "Long run", "moderate")
        ]

    # Use personalized paces or default values
    paces = personalized_paces or context.get('paces', {})
    z1_pace = paces.get('z1', '6:30-7:00')
    z2_pace = paces.get('z2', '5:45-6:15')
    z3_pace = paces.get('z3', '5:15-5:30')
    z4_pace = paces.get('z4', '4:45-5:00')
    z5_pace = paces.get('z5', '4:15-4:30')
    semi_pace = paces.get('semi', '5:00-5:15')
    marathon_pace = paces.get('marathon', '5:15-5:30')

    # Helper function to calculate distance from duration and pace
    def calc_distance_from_duration(duration_min: int, pace_range: str) -> float:
        """
        Calculate distance (km) from duration (min) and pace range (e.g., '6:30-7:00').
        Uses the slower pace (second value) for conservative estimate.
        """
        try:
            # Extract the slower pace (second value in range)
            pace_str = pace_range.split('-')[-1].strip()
            parts = pace_str.replace('/km', '').split(':')
            pace_min = int(parts[0]) + int(parts[1]) / 60
            distance = duration_min / pace_min
            return round(distance, 1)
        except (ValueError, IndexError, TypeError):
            # Fallback: assume 6:00/km pace
            return round(duration_min / 6.0, 1)

    # Pre-calculate distances based on durations and paces
    recovery_30min_dist = calc_distance_from_duration(30, z1_pace)
    endurance_50min_dist = calc_distance_from_duration(50, z2_pace)
    threshold_40min_dist = calc_distance_from_duration(40, z3_pace)  # Mix of paces, use z3 average
    tempo_45min_dist = calc_distance_from_duration(45, z3_pace)

    # Athlete's VO2max and VO2MAX
    vma = context.get('vma', 'Not calculated')
    vo2max = context.get('vo2max', 'Not calculated')

    prompt = f"""You are an elite running coach.

Goal: {goal} ({race_km} km)
Phase: {phase}
Target load: {target_load}

Athlete data:
CTL: {context.get('ctl', 40)}
ATL: {context.get('atl', 45)}
TSB: {context.get('tsb', -5)}
ACWR: {round(context.get('acwr', 1.0), 2)}
CURRENT weekly volume: {current_weekly_km} km
Estimated VO2max: {vma} km/h
VO2MAX: {vo2max}

PLAN PARAMETERS:
- Requested number of sessions: {target_sessions} runs + {num_rest_days} rest
- Target volume: {target_km} km
- Long run: {target_long_run} km
- Rest days: {', '.join(rest_days)}

RULES:
1. 2 rest days (Monday and Friday recommended)
2. {target_sessions} running sessions
3. weekly_km = {target_km} km
4. Long run Sunday: {target_long_run} km
5. Details: distance • pace • target HR
6. CRITICAL: distance_km MUST be calculated from duration and pace: distance = duration / pace
   Example: 30min at 7:00/km pace = 30/7 = 4.3 km (NOT 5 km!)

PERSONALIZED PACE ZONES (based on athlete's VO2max):
- Z1 (recovery): {z1_pace}/km, HR 120-135
- Z2 (endurance): {z2_pace}/km, HR 135-150
- Z3 (tempo): {z3_pace}/km, HR 150-165
- Z4 (threshold): {z4_pace}/km, HR 165-175
- Z5 (VO2max): {z5_pace}/km, HR 175-185
- Marathon pace: {marathon_pace}/km
- Half marathon pace: {semi_pace}/km

IMPORTANT: MUST use the personalized paces above in session details.

JSON only:

{{
  "focus": "{phase}",
  "planned_load": {target_load},
  "weekly_km": {target_km},
  "sessions": [
    {{"day": "Monday", "type": "Rest", "duration": "0min", "details": "Complete recovery", "intensity": "rest", "estimated_tss": 0, "distance_km": 0}},
    {{"day": "Tuesday", "type": "Endurance", "duration": "50min", "details": "{endurance_50min_dist} km • {z2_pace}/km • HR 135-150 bpm • Zone 2", "intensity": "easy", "estimated_tss": 50, "distance_km": {endurance_50min_dist}}},
    {{"day": "Wednesday", "type": "Threshold", "duration": "40min", "details": "{threshold_40min_dist} km including 20min at {z4_pace}/km • HR 165-175 bpm", "intensity": "hard", "estimated_tss": 55, "distance_km": {threshold_40min_dist}}},
    {{"day": "Thursday", "type": "Recovery", "duration": "30min", "details": "{recovery_30min_dist} km • {z1_pace}/km • HR 120-135 bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": {recovery_30min_dist}}},
    {{"day": "Friday", "type": "Rest", "duration": "0min", "details": "Recovery", "intensity": "rest", "estimated_tss": 0, "distance_km": 0}},
    {{"day": "Saturday", "type": "Tempo", "duration": "45min", "details": "{tempo_45min_dist} km including 25min at {semi_pace}/km • HR 150-165 bpm", "intensity": "moderate", "estimated_tss": 60, "distance_km": {tempo_45min_dist}}},
    {{"day": "Sunday", "type": "Long run", "duration": "90min", "details": "{target_long_run} km progressive • {z2_pace}→{z3_pace}/km • HR 135-165 bpm", "intensity": "moderate", "estimated_tss": 100, "distance_km": {target_long_run}}}
  ],
  "total_tss": 290,
  "advice": "Volume: {current_weekly_km} km → {target_km} km. Recommended min for {goal}: {config['min']} km. Long run: {target_long_run} km."
}}"""

    start_time = time.time()
    metadata = {
        "model": LLM_MODEL,
        "provider": LLM_PROVIDER,
        "context_type": "cycle_week",
        "duration_sec": 0,
        "success": False
    }
    
    if not EMERGENT_LLM_KEY or not EMERGENT_LLM_KEY.startswith("sk-emergent"):
        logger.warning("[LLM] Emergent LLM Key not configured")
        return None, False, metadata

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        session_id = f"cardiocoach_plan_{user_id}_{int(time.time())}"

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=SYSTEM_PROMPT_PLAN
        ).with_model(LLM_PROVIDER, LLM_MODEL)

        response = await asyncio.wait_for(
            chat.send_message(UserMessage(text=prompt)),
            timeout=LLM_TIMEOUT
        )

        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)

        # Parse JSON
        response_text = str(response).strip()

        # Clean if markdown
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        plan = json.loads(response_text)

        # Post-process: Fix pace in details to match duration/distance
        def fix_session_details(session):
            """Recalculate pace from duration and distance, update details if needed."""
            duration_str = session.get("duration", "0min")
            distance = session.get("distance_km", 0)
            details = session.get("details", "")
            
            if distance > 0 and "min" in duration_str:
                try:
                    duration = int(duration_str.replace("min", ""))
                    if duration > 0:
                        # Calculate actual pace
                        pace_min = duration / distance
                        pace_mins = int(pace_min)
                        pace_secs = int((pace_min % 1) * 60)
                        actual_pace = f"{pace_mins}:{pace_secs:02d}/km"
                        
                        # Replace first pace pattern (X:XX-X:XX/km or X:XX/km) with actual pace
                        import re
                        pace_pattern = r'\d+:\d+-\d+:\d+/km|\d+:\d+/km'
                        if re.search(pace_pattern, details):
                            # Only replace if the calculated pace differs significantly
                            details = re.sub(pace_pattern, actual_pace, details, count=1)
                            session["details"] = details
                except (ValueError, ZeroDivisionError):
                    pass
            return session

        # Apply fix to all sessions
        if "sessions" in plan:
            plan["sessions"] = [fix_session_details(s) for s in plan["sessions"]]

        # Calculate total TSS volume
        total_tss = sum(s.get("estimated_tss", 0) for s in plan.get("sessions", []))
        plan["total_tss"] = total_tss

        # Calculate total KM volume (LLM correction)
        total_km = sum(s.get("distance_km", 0) or 0 for s in plan.get("sessions", []))
        plan["weekly_km"] = round(total_km, 1)

        metadata["success"] = True
        logger.info(f"[LLM] ✅ Weekly plan generated in {elapsed:.2f}s (TSS: {total_tss}, KM: {total_km})")

        return plan, True, metadata

    except json.JSONDecodeError as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ JSON parsing error: {e}")
        return None, False, metadata

    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.warning(f"[LLM] ⏱️ Plan timeout after {elapsed:.2f}s")
        return None, False, metadata

    except Exception as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ Plan error: {e}")
        return None, False, metadata


# ============================================================
# INTERNAL FUNCTIONS
# ============================================================

async def _call_gpt(
    system_prompt: str,
    user_prompt: str,
    user_id: str,
    context_type: str
) -> Tuple[Optional[str], bool, Dict]:
    """Call GPT-4o-mini via Emergent LLM Key"""

    start_time = time.time()
    metadata = {
        "model": LLM_MODEL,
        "provider": LLM_PROVIDER,
        "context_type": context_type,
        "duration_sec": 0,
        "success": False
    }

    if not EMERGENT_LLM_KEY or not EMERGENT_LLM_KEY.startswith("sk-emergent"):
        logger.warning("[LLM] Emergent LLM Key not configured")
        return None, False, metadata
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        session_id = f"cardiocoach_{context_type}_{user_id}_{int(time.time())}"
        
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=system_prompt
        ).with_model(LLM_PROVIDER, LLM_MODEL)
        
        response = await asyncio.wait_for(
            chat.send_message(UserMessage(text=user_prompt)),
            timeout=LLM_TIMEOUT
        )
        
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        metadata["success"] = True
        response_text = _clean_response(str(response))

        if response_text:
            logger.info(f"[LLM] ✅ {context_type} enriched in {elapsed:.2f}s")
            return response_text, True, metadata
        else:
            logger.warning(f"[LLM] Empty response for {context_type}")
            return None, False, metadata

    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.warning(f"[LLM] ⏱️ Timeout after {elapsed:.2f}s")
        return None, False, metadata

    except Exception as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ Error: {e}")
        return None, False, metadata


def _format_context(data: Dict) -> str:
    """Formats data into readable text for LLM"""
    lines = []
    for key, value in data.items():
        if value is not None and value != "" and value != {} and value != []:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "No data"


def _format_history(history: List[Dict]) -> str:
    """Formats conversation history"""
    if not history:
        return "Start of conversation"

    lines = []
    for msg in history[-4:]:
        role = "User" if msg.get("role") == "user" else "Coach"
        content = msg.get("content", "")[:150]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _clean_response(response: str) -> str:
    """Cleans GPT response"""
    if not response:
        return ""

    response = response.strip()
    if response.startswith('"') and response.endswith('"'):
        response = response[1:-1]

    if len(response) > 700:
        response = response[:700]
        last_period = max(response.rfind("."), response.rfind("!"), response.rfind("?"))
        if last_period > 400:
            response = response[:last_period + 1]

    return response.strip()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "enrich_chat_response",
    "enrich_weekly_review", 
    "enrich_workout_analysis",
    "generate_cycle_week",
    "LLM_MODEL",
    "LLM_PROVIDER"
]
