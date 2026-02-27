"""
CardioCoach - Module LLM Coach (GPT-4o-mini)

Ce module gère l'enrichissement des textes coach via GPT-4o-mini.
Les données d'entraînement sont envoyées directement au LLM pour
générer des analyses personnalisées et motivantes.

Flux:
1. Réception des données d'entraînement
2. Envoi à GPT-4o-mini pour génération texte
3. Fallback templates Python si erreur
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
# PROMPTS SYSTÈME
# ============================================================

SYSTEM_PROMPT_COACH = """Tu es un coach running expérimenté, empathique et précis. 

Structure de réponse :
1. Positif d'abord (félicite, encourage)
2. Analyse claire et simple des données (explique les chiffres sans jargon)
3. Conseil actionable (allure, cadence, récup, renforcement)
4. Question de relance si pertinent

Focus : allure/km, cadence, zones cardio, récupération, fatigue, plans.
Sois concret, motivant et bienveillant. Max 4-5 phrases."""

SYSTEM_PROMPT_BILAN = """Tu es un coach running qui fait le bilan hebdomadaire.

Structure du bilan :
1. Intro positive (félicite la régularité ou l'effort)
2. Analyse des chiffres clés (explique simplement)
3. Points forts (2 max)
4. Point à améliorer (1 max, formulé positivement)
5. Conseil pour la semaine prochaine
6. Question de relance motivante

Sois encourageant même si les stats sont moyennes. Max 6-8 phrases."""

SYSTEM_PROMPT_SEANCE = """Tu es un coach running qui analyse une séance.


Structure :
1. Réaction positive sur l'effort accompli
2. Analyse simple des données (allure, FC, régularité)
3. Point fort de la séance
4. Conseil pour la prochaine sortie
5. Relance motivante (optionnel)

Sois concret et encourageant. Max 4-5 phrases."""

SYSTEM_PROMPT_PLAN = """Tu es un coach running expert élite spécialisé en périodisation.
Répond UNIQUEMENT en JSON valide, sans texte avant ou après."""


# ============================================================
# FONCTIONS D'ENRICHISSEMENT
# ============================================================

async def enrich_chat_response(
    user_message: str,
    context: Dict,
    conversation_history: List[Dict],
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enrichit la réponse chat avec GPT-4o-mini."""
    prompt = f"""DONNÉES UTILISATEUR:
{_format_context(context)}

HISTORIQUE CONVERSATION:
{_format_history(conversation_history)}

QUESTION: {user_message}

Réponds en tant que coach running motivant."""

    return await _call_gpt(SYSTEM_PROMPT_COACH, prompt, user_id, "chat")


async def enrich_weekly_review(
    stats: Dict,
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enrichit le bilan hebdomadaire avec GPT-4o-mini."""
    prompt = f"""STATS SEMAINE:
{_format_context(stats)}

Génère un bilan hebdomadaire motivant et personnalisé basé sur ces données."""

    return await _call_gpt(SYSTEM_PROMPT_BILAN, prompt, user_id, "bilan")


async def enrich_workout_analysis(
    workout: Dict,
    user_id: str = "unknown"
) -> Tuple[Optional[str], bool, Dict]:
    """Enrichit l'analyse d'une séance avec GPT-4o-mini."""
    prompt = f"""DONNÉES SÉANCE:
{_format_context(workout)}

Analyse cette séance en tant que coach running bienveillant."""

    return await _call_gpt(SYSTEM_PROMPT_SEANCE, prompt, user_id, "seance")


async def generate_cycle_week(
    context: Dict,
    phase: str,
    target_load: int,
    goal: str,
    user_id: str = "unknown"
) -> Tuple[Optional[Dict], bool, Dict]:
    """
    Génère un plan de semaine d'entraînement structuré.
    
    Args:
        context: Données de fitness (CTL, ATL, TSB, ACWR, weekly_km)
        phase: Phase actuelle (build, deload, intensification, taper, race)
        target_load: Charge cible en TSS
        goal: Objectif (5K, 10K, SEMI, MARATHON, ULTRA)
        user_id: ID utilisateur
        
    Returns:
        (plan_dict, success, metadata)
    """
    # Volume cible selon l'objectif ET le niveau actuel de l'athlète
    current_weekly_km = context.get('weekly_km', 30)
    
    # Volumes minimum/maximum par objectif (pour athlète débutant → confirmé)
    goal_volume_ranges = {
        "5K": {"min": 20, "max": 45, "long_pct": 0.33, "sessions": 4},
        "10K": {"min": 30, "max": 60, "long_pct": 0.30, "sessions": 5},
        "SEMI": {"min": 40, "max": 80, "long_pct": 0.35, "sessions": 5},
        "MARATHON": {"min": 50, "max": 120, "long_pct": 0.35, "sessions": 5},
        "ULTRA": {"min": 60, "max": 150, "long_pct": 0.40, "sessions": 5},
    }
    
    goal_range = goal_volume_ranges.get(goal, goal_volume_ranges["SEMI"])
    
    # Calcul du volume cible basé sur le niveau actuel + progressivité (+5-10%)
    progression_factor = 1.07  # +7% par semaine (max recommandé: 10%)
    target_km_raw = current_weekly_km * progression_factor
    
    # Limiter entre min et max selon l'objectif
    target_km = max(goal_range["min"], min(goal_range["max"], round(target_km_raw)))
    
    # Sortie longue = % du volume total
    target_long_run = round(target_km * goal_range["long_pct"])
    target_sessions = goal_range["sessions"]
    
    prompt = f"""Tu es un coach running expert élite.

Objectif : {goal}
Phase : {phase}
Charge cible : {target_load}

Données athlète :
CTL: {context.get('ctl', 40)}
ATL: {context.get('atl', 45)}
TSB: {context.get('tsb', -5)}
ACWR: {round(context.get('acwr', 1.0), 2)}
Volume hebdo ACTUEL: {current_weekly_km} km (basé sur les 4 dernières semaines)

VOLUME CIBLE PERSONNALISÉ POUR {goal} :
- Volume cible: {target_km} km (+7% progressif, limité entre {goal_range["min"]}-{goal_range["max"]} km)
- Sortie longue: {target_long_run} km ({int(goal_range["long_pct"]*100)}% du volume)
- Nombre de séances: {target_sessions} courses + 2 repos

RÈGLES IMPORTANTES :
1. EXACTEMENT 2 jours de repos (Lundi et Vendredi)
2. {target_sessions} séances de course
3. weekly_km doit être {target_km} km (±5%)
4. Sortie longue dimanche: {target_long_run} km
5. Dans "details", TOUJOURS inclure: distance • allure • FC cible

Zones d'allure (VMA ~15 km/h) :
- Z1 Récup: 6:30-7:00/km, FC 120-135
- Z2 Endurance: 5:45-6:15/km, FC 135-150
- Z3 Tempo: 5:15-5:30/km, FC 150-165
- Z4 Seuil: 4:45-5:00/km, FC 165-175
- Z5 VMA: 4:15-4:30/km, FC 175-185

Répond UNIQUEMENT en JSON valide :

{{
  "focus": "{phase}",
  "planned_load": {target_load},
  "weekly_km": {target_km},
  "sessions": [
    {{"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements recommandés", "intensity": "rest", "estimated_tss": 0, "distance_km": 0}},
    {{"day": "Mardi", "type": "Endurance", "duration": "50min", "details": "8 km • 5:45-6:15/km • FC 135-150 bpm • Zone 2", "intensity": "easy", "estimated_tss": 50, "distance_km": 8}},
    {{"day": "Mercredi", "type": "Seuil", "duration": "40min", "details": "7 km dont 20min à 4:45-5:00/km • FC 165-175 bpm", "intensity": "hard", "estimated_tss": 55, "distance_km": 7}},
    {{"day": "Jeudi", "type": "Récupération", "duration": "30min", "details": "5 km • 6:30-7:00/km • FC <135 bpm • Footing léger", "intensity": "easy", "estimated_tss": 25, "distance_km": 5}},
    {{"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération • Cross-training possible", "intensity": "rest", "estimated_tss": 0, "distance_km": 0}},
    {{"day": "Samedi", "type": "Tempo", "duration": "45min", "details": "8 km dont 25min à 5:00-5:15/km • FC 150-165 bpm", "intensity": "moderate", "estimated_tss": 60, "distance_km": 8}},
    {{"day": "Dimanche", "type": "Sortie longue", "duration": "90min", "details": "{target_long_run} km progressif • 5:45→5:30/km • FC 135-165 bpm", "intensity": "moderate", "estimated_tss": 100, "distance_km": {target_long_run}}}
  ],
  "total_tss": 290,
  "advice": "Volume adapté à ton niveau ({current_weekly_km} km → {target_km} km). Sortie longue prioritaire pour {goal}."
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
        logger.warning("[LLM] Emergent LLM Key non configurée")
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
        
        # Parser le JSON
        response_text = str(response).strip()
        
        # Nettoyer si markdown
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        plan = json.loads(response_text)
        
        # Calculer le volume total TSS
        total_tss = sum(s.get("estimated_tss", 0) for s in plan.get("sessions", []))
        plan["total_tss"] = total_tss
        
        # Calculer le volume total KM (correction du LLM)
        total_km = sum(s.get("distance_km", 0) or 0 for s in plan.get("sessions", []))
        plan["weekly_km"] = round(total_km, 1)
        
        metadata["success"] = True
        logger.info(f"[LLM] ✅ Plan semaine généré en {elapsed:.2f}s (TSS: {total_tss}, KM: {total_km})")
        
        return plan, True, metadata
        
    except json.JSONDecodeError as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ Erreur parsing JSON: {e}")
        return None, False, metadata
        
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.warning(f"[LLM] ⏱️ Timeout plan après {elapsed:.2f}s")
        return None, False, metadata
        
    except Exception as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ Erreur plan: {e}")
        return None, False, metadata


# ============================================================
# FONCTIONS INTERNES
# ============================================================

async def _call_gpt(
    system_prompt: str,
    user_prompt: str,
    user_id: str,
    context_type: str
) -> Tuple[Optional[str], bool, Dict]:
    """Appel GPT-4o-mini via Emergent LLM Key"""
    
    start_time = time.time()
    metadata = {
        "model": LLM_MODEL,
        "provider": LLM_PROVIDER,
        "context_type": context_type,
        "duration_sec": 0,
        "success": False
    }
    
    if not EMERGENT_LLM_KEY or not EMERGENT_LLM_KEY.startswith("sk-emergent"):
        logger.warning("[LLM] Emergent LLM Key non configurée")
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
            logger.info(f"[LLM] ✅ {context_type} enrichi en {elapsed:.2f}s")
            return response_text, True, metadata
        else:
            logger.warning(f"[LLM] Réponse vide pour {context_type}")
            return None, False, metadata
            
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.warning(f"[LLM] ⏱️ Timeout après {elapsed:.2f}s")
        return None, False, metadata
        
    except Exception as e:
        elapsed = time.time() - start_time
        metadata["duration_sec"] = round(elapsed, 2)
        logger.error(f"[LLM] ❌ Erreur: {e}")
        return None, False, metadata


def _format_context(data: Dict) -> str:
    """Formate les données en texte lisible pour le LLM"""
    lines = []
    for key, value in data.items():
        if value is not None and value != "" and value != {} and value != []:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "Aucune donnée"


def _format_history(history: List[Dict]) -> str:
    """Formate l'historique de conversation"""
    if not history:
        return "Début de conversation"
    
    lines = []
    for msg in history[-4:]:
        role = "User" if msg.get("role") == "user" else "Coach"
        content = msg.get("content", "")[:150]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _clean_response(response: str) -> str:
    """Nettoie la réponse GPT"""
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
