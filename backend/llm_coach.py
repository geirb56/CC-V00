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

SYSTEM_PROMPT_COACH = """Tu es CardioCoach, un coach running personnel expert et bienveillant.

🎯 TON RÔLE:
Tu réponds aux questions de l'athlète sur son entraînement comme un vrai coach personnel.
Tu as accès à TOUTES ses données d'entraînement réelles: historique complet des séances, plan d'entraînement, VMA, prédictions de course, métriques de forme.

📊 DONNÉES DISPONIBLES:
- Historique COMPLET des séances (28 derniers jours avec distance, durée, allure, FC)
- Plan d'entraînement de la semaine (objectif, séances planifiées)
- VMA estimée et prédictions de temps de course
- Métriques de forme: ACWR (ratio charge aiguë/chronique), TSB (fraîcheur)
- Objectif actuel (5K, 10K, Semi, Marathon, Ultra)

💬 STYLE DE RÉPONSE:
1. Sois direct et concis (3-5 phrases max sauf si analyse détaillée demandée)
2. Utilise les données réelles pour personnaliser ta réponse
3. Donne des conseils actionnables basés sur les séances passées
4. Reste motivant et positif, même pour les critiques
5. Si tu ne sais pas, dis-le honnêtement

🏃 EXPERTISE:
- Plans d'entraînement (5K, 10K, semi, marathon, ultra)
- Gestion de la charge et récupération
- Zones cardiaques et allures cibles
- Prévention des blessures
- Nutrition et hydratation basiques
- Progression et périodisation
- Analyse des performances et prédictions

⚠️ IMPORTANT:
- Réponds TOUJOURS dans la langue de l'utilisateur (FR ou EN)
- Ne fais pas de listes à puces sauf si demandé
- Parle comme un coach humain, pas comme un rapport
- Réfère-toi aux séances spécifiques quand c'est pertinent"""

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
    """Enrichit la réponse chat avec GPT-4o-mini.
    
    Le contexte inclut:
    - Stats 7j et 28j (km, sessions)
    - Métriques fitness (ACWR, TSB)
    - TOUTES les séances des 28 derniers jours
    - Plan d'entraînement actuel
    - VMA estimée et prédictions de course
    - Objectif actuel
    """
    language = context.get("language", "fr")
    
    # Formater le contexte de manière lisible
    stats_7 = context.get("stats_7j", {})
    stats_28 = context.get("stats_28j", {})
    fitness = context.get("fitness", {})
    all_sessions = context.get("all_sessions", "")
    training_plan = context.get("training_plan", "")
    current_goal = context.get("current_goal", "Non défini")
    vma = context.get("vma", "")
    predictions = context.get("predictions", "")
    workout = context.get("workout_detail")
    
    context_text = f"""📊 DONNÉES COMPLÈTES DE L'ATHLÈTE:

🎯 OBJECTIF ACTUEL: {current_goal}

⚡ PERFORMANCE:
- {vma}
- Prédictions: {predictions}

📈 CETTE SEMAINE (7j):
- Volume: {stats_7.get('km', 0)} km
- Séances: {stats_7.get('sessions', 0)}

📅 CE MOIS (28j):
- Volume: {stats_28.get('km', 0)} km  
- Séances: {stats_28.get('sessions', 0)}

💪 ÉTAT DE FORME:
- ACWR: {fitness.get('acwr', 1.0)} ({fitness.get('acwr_status', 'ok')})
- TSB: {fitness.get('tsb', 0)} ({fitness.get('tsb_status', 'normal')})

📋 PLAN D'ENTRAÎNEMENT:
{training_plan if training_plan else "Aucun plan actif"}

🏃 HISTORIQUE COMPLET DES SÉANCES (28 derniers jours):
{all_sessions}"""

    # Ajouter les détails de la séance si disponibles
    if workout:
        zones = workout.get('zones', {})
        zones_str = ""
        if zones:
            zones_str = f"Z1:{zones.get('z1',0)}% Z2:{zones.get('z2',0)}% Z3:{zones.get('z3',0)}% Z4:{zones.get('z4',0)}% Z5:{zones.get('z5',0)}%"
        
        context_text += f"""

🔍 SÉANCE EN COURS D'ANALYSE:
- Nom: {workout.get('name', 'N/A')}
- Distance: {workout.get('distance_km', 0):.1f} km
- Durée: {workout.get('duration_min', 0):.0f} min
- FC moyenne: {workout.get('avg_hr', 'N/A')} bpm
- FC max: {workout.get('max_hr', 'N/A')} bpm
- Zones: {zones_str}"""

    # Formater l'historique de conversation
    history_text = ""
    if conversation_history:
        for msg in conversation_history[-4:]:  # 4 derniers messages max
            role = "Athlète" if msg.get("role") == "user" else "Coach"
            content = msg.get("content", "")[:200]  # Tronquer si trop long
            history_text += f"{role}: {content}\n"
    
    prompt = f"""{context_text}

💬 HISTORIQUE CONVERSATION:
{history_text if history_text else "(Nouvelle conversation)"}

❓ QUESTION DE L'ATHLÈTE: {user_message}

Réponds en {language.upper()} comme un coach personnel bienveillant et expert. Utilise les données ci-dessus pour personnaliser ta réponse."""

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
    user_id: str = "unknown",
    sessions_per_week: int = None,
    personalized_paces: Dict = None
) -> Tuple[Optional[Dict], bool, Dict]:
    """
    Génère un plan de semaine d'entraînement structuré avec allures personnalisées.
    
    Args:
        context: Données de fitness (CTL, ATL, TSB, ACWR, weekly_km, vma, vo2max, paces)
        phase: Phase actuelle (build, deload, intensification, taper, race)
        target_load: Charge cible en TSS
        goal: Objectif (5K, 10K, SEMI, MARATHON, ULTRA)
        user_id: ID utilisateur
        sessions_per_week: Nombre de séances par semaine (3, 4, 5, 6)
        personalized_paces: Allures personnalisées basées sur la VMA (z1, z2, z3, z4, z5, marathon, semi)
        
    Returns:
        (plan_dict, success, metadata)
    """
    # Volume actuel de l'athlète (basé sur les 4 dernières semaines)
    current_weekly_km = context.get('weekly_km', 30)
    
    # Distance de course par objectif (en km)
    race_distances = {
        "5K": 5,
        "10K": 10,
        "SEMI": 21.1,
        "MARATHON": 42.2,
        "ULTRA": 60,
    }
    race_km = race_distances.get(goal, 21.1)
    
    # Volumes minimum RECOMMANDÉS (basés sur données réelles d'entraînement)
    # Source: recommandations coaching pour finir sans souffrir
    goal_configs = {
        "5K": {"min": 15, "max": 45, "sessions": 3, "long_min": 8, "long_max": 10},
        "10K": {"min": 20, "max": 60, "sessions": 3, "long_min": 10, "long_max": 14},
        "SEMI": {"min": 30, "max": 80, "sessions": 3, "long_min": 16, "long_max": 18},
        "MARATHON": {"min": 40, "max": 120, "sessions": 4, "long_min": 28, "long_max": 32},
        "ULTRA": {"min": 50, "max": 150, "sessions": 5, "long_min": 35, "long_max": 45},
    }
    
    config = goal_configs.get(goal, goal_configs["SEMI"])
    
    # Nombre de séances (utilisateur ou défaut)
    target_sessions = sessions_per_week if sessions_per_week in [3, 4, 5, 6] else config["sessions"]
    num_rest_days = 7 - target_sessions
    
    # Volume minimum = max(volume actuel, minimum recommandé pour l'objectif)
    volume_min = max(current_weekly_km, config["min"])
    volume_max = config["max"]
    
    # Calcul du volume cible: +7% progressif, limité entre min et max
    progression_factor = 1.07
    target_km_raw = current_weekly_km * progression_factor
    target_km = max(volume_min, min(volume_max, round(target_km_raw)))
    
    # Sortie longue = proportionnelle au volume, entre long_min et long_max
    long_ratio = (target_km - config["min"]) / (config["max"] - config["min"]) if config["max"] > config["min"] else 0.5
    target_long_run = round(config["long_min"] + long_ratio * (config["long_max"] - config["long_min"]))
    target_long_run = max(config["long_min"], min(config["long_max"], target_long_run))
    
    # Générer les jours de repos et course selon le nombre de séances
    if target_sessions == 3:
        rest_days = ["Lundi", "Mercredi", "Vendredi", "Samedi"]
        run_days_config = [
            ("Mardi", "Endurance", "easy"),
            ("Jeudi", "Seuil", "hard"),
            ("Dimanche", "Sortie longue", "moderate")
        ]
    elif target_sessions == 4:
        rest_days = ["Lundi", "Mercredi", "Vendredi"]
        run_days_config = [
            ("Mardi", "Endurance", "easy"),
            ("Jeudi", "Seuil", "hard"),
            ("Samedi", "Tempo", "moderate"),
            ("Dimanche", "Sortie longue", "moderate")
        ]
    elif target_sessions == 5:
        rest_days = ["Lundi", "Vendredi"]
        run_days_config = [
            ("Mardi", "Endurance", "easy"),
            ("Mercredi", "Seuil", "hard"),
            ("Jeudi", "Récupération", "easy"),
            ("Samedi", "Tempo", "moderate"),
            ("Dimanche", "Sortie longue", "moderate")
        ]
    else:  # 6 séances
        rest_days = ["Vendredi"]
        run_days_config = [
            ("Lundi", "Récupération", "easy"),
            ("Mardi", "Endurance", "easy"),
            ("Mercredi", "Seuil", "hard"),
            ("Jeudi", "Récupération", "easy"),
            ("Samedi", "Tempo", "moderate"),
            ("Dimanche", "Sortie longue", "moderate")
        ]
    
    # Utiliser les allures personnalisées ou des valeurs par défaut
    paces = personalized_paces or context.get('paces', {})
    z1_pace = paces.get('z1', '6:30-7:00')
    z2_pace = paces.get('z2', '5:45-6:15')
    z3_pace = paces.get('z3', '5:15-5:30')
    z4_pace = paces.get('z4', '4:45-5:00')
    z5_pace = paces.get('z5', '4:15-4:30')
    semi_pace = paces.get('semi', '5:00-5:15')
    marathon_pace = paces.get('marathon', '5:15-5:30')
    
    # VMA et VO2MAX de l'athlète
    vma = context.get('vma', 'Non calculée')
    vo2max = context.get('vo2max', 'Non calculé')
    
    prompt = f"""Tu es un coach running expert élite.

Objectif : {goal} ({race_km} km)
Phase : {phase}
Charge cible : {target_load}

Données athlète :
CTL: {context.get('ctl', 40)}
ATL: {context.get('atl', 45)}
TSB: {context.get('tsb', -5)}
ACWR: {round(context.get('acwr', 1.0), 2)}
Volume hebdo ACTUEL: {current_weekly_km} km
VMA estimée: {vma} km/h
VO2MAX: {vo2max}

PARAMÈTRES DU PLAN :
- Nombre de séances demandé: {target_sessions} courses + {num_rest_days} repos
- Volume cible: {target_km} km
- Sortie longue: {target_long_run} km
- Jours de repos: {', '.join(rest_days)}

RÈGLES :
1. 2 jours de repos (Lundi et Vendredi recommandés)
2. {target_sessions} séances de course
3. weekly_km = {target_km} km
4. Sortie longue dimanche: {target_long_run} km
5. Details: distance • allure • FC cible

ZONES D'ALLURE PERSONNALISÉES (basées sur la VMA de l'athlète) :
- Z1 (récup): {z1_pace}/km, FC 120-135
- Z2 (endurance): {z2_pace}/km, FC 135-150
- Z3 (tempo): {z3_pace}/km, FC 150-165
- Z4 (seuil): {z4_pace}/km, FC 165-175
- Z5 (VMA): {z5_pace}/km, FC 175-185
- Allure marathon: {marathon_pace}/km
- Allure semi: {semi_pace}/km

IMPORTANT: Utilise OBLIGATOIREMENT les allures personnalisées ci-dessus dans les détails des séances.

JSON uniquement :

{{
  "focus": "{phase}",
  "planned_load": {target_load},
  "weekly_km": {target_km},
  "sessions": [
    {{"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète", "intensity": "rest", "estimated_tss": 0, "distance_km": 0}},
    {{"day": "Mardi", "type": "Endurance", "duration": "50min", "details": "8 km • {z2_pace}/km • FC 135-150 bpm • Zone 2", "intensity": "easy", "estimated_tss": 50, "distance_km": 8}},
    {{"day": "Mercredi", "type": "Seuil", "duration": "40min", "details": "7 km dont 20min à {z4_pace}/km • FC 165-175 bpm", "intensity": "hard", "estimated_tss": 55, "distance_km": 7}},
    {{"day": "Jeudi", "type": "Récupération", "duration": "30min", "details": "5 km • {z1_pace}/km • FC <135 bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 5}},
    {{"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération", "intensity": "rest", "estimated_tss": 0, "distance_km": 0}},
    {{"day": "Samedi", "type": "Tempo", "duration": "45min", "details": "8 km dont 25min à {semi_pace}/km • FC 150-165 bpm", "intensity": "moderate", "estimated_tss": 60, "distance_km": 8}},
    {{"day": "Dimanche", "type": "Sortie longue", "duration": "90min", "details": "{target_long_run} km progressif • {z2_pace}→{z3_pace}/km • FC 135-165 bpm", "intensity": "moderate", "estimated_tss": 100, "distance_km": {target_long_run}}}
  ],
  "total_tss": 290,
  "advice": "Volume: {current_weekly_km} km → {target_km} km. Min recommandé {goal}: {config['min']} km. Sortie longue: {target_long_run} km."
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
