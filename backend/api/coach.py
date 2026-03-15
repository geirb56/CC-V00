from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List, Dict
import logging
import uuid
from datetime import datetime, timezone, timedelta

from database import db
from models import CoachRequest, CoachResponse, GuidanceRequest, GuidanceResponse, WeeklyReviewResponse, MobileAnalysisResponse, DetailedAnalysisResponse
from api.deps import auth_user, auth_user_optional, SUBSCRIPTION_TIERS, get_message_limit
from api.workouts import get_mock_workouts
from analysis_engine import generate_session_analysis, generate_weekly_review, generate_dashboard_insight, calculate_intensity_level, format_duration, format_pace
from coach_service import analyze_workout as coach_analyze_workout, weekly_review as coach_weekly_review, chat_response as coach_chat_response, generate_dynamic_training_plan, get_cache_stats, clear_cache, get_metrics as get_coach_metrics, reset_metrics as reset_coach_metrics
from llm_coach import LLM_MODEL, LLM_PROVIDER, generate_cycle_week
from rag_engine import generate_dashboard_rag, generate_weekly_review_rag, generate_workout_analysis_rag

router = APIRouter()
logger = logging.getLogger(__name__)

CARDIOCOACH_SYSTEM_EN = """You are CardioCoach, a mobile-first personal sports coach.
You answer user questions directly, like a human coach whispering in their ear.

THIS IS NOT A REPORT. THIS IS A CONVERSATION.

RESPONSE FORMAT (MANDATORY):

1) DIRECT ANSWER (required)
- 1 to 2 sentences maximum
- Directly answers the question
- Simple language
Example: "Your recent load is generally moderate, but quite irregular."

2) QUICK CONTEXT (optional)
- 1 to 3 bullet points maximum
- Each bullet = one key piece of information
- No unnecessary numbers
- No sub-sections
Example:
- Your last three runs were all at similar intensity
- Volume is slightly up from last week

3) COACH TIP (required)
- ONE single recommendation
- Clear, concrete, immediately actionable
Example: "Try to keep truly easy sessions between your harder outings."

STRICT STYLE RULES (FORBIDDEN):
- NO stars (*, **, ****)
- NO markdown
- NO titles or headers
- NO numbering (1., 2., etc.)
- NO sections like "physiological", "trend", "reading"
- NO walls of text
- NO artificial emphasis
- NO academic or medical tone

TONE:
- Calm
- Confident
- Caring
- Precise but simple
- Like a coach speaking in the user's ear

GOLDEN RULE:
If your response looks like a report or written analysis, it is WRONG and must be simplified.

100% ENGLISH. No French words allowed."""

CARDIOCOACH_SYSTEM_FR = """Tu es CardioCoach, un coach sportif personnel mobile-first.
Tu reponds directement aux questions de l'utilisateur, comme un coach humain qui parle a son oreille.

CECI N'EST PAS UN RAPPORT. C'EST UNE CONVERSATION.

FORMAT DE REPONSE (OBLIGATOIRE):

1) REPONSE DIRECTE (obligatoire)
- 1 a 2 phrases maximum
- Repond directement a la question
- Langage simple
Exemple: "Ta charge recente est globalement moderee, mais assez irreguliere."

2) CONTEXTE RAPIDE (optionnel)
- 1 a 3 puces maximum
- Chaque puce = une information cle
- Pas de chiffres inutiles
- Pas de sous-sections
Exemple:
- Tes trois dernieres sorties etaient toutes a intensite similaire
- Le volume est legerement en hausse par rapport a la semaine derniere

3) CONSEIL COACH (obligatoire)
- UNE seule recommandation
- Claire, concrete, immediatement applicable
Exemple: "Essaie de garder des seances vraiment faciles entre les sorties plus intenses."

REGLES DE STYLE STRICTES (INTERDITS):
- AUCUNE etoile (*, **, ****)
- AUCUN markdown
- AUCUN titre
- AUCUNE numerotation (1., 2., etc.)
- AUCUNE section "physiologique", "tendance", "lecture"
- AUCUN pave de texte
- AUCUNE emphase artificielle
- AUCUN ton academique ou medical

TON:
- Calme
- Confiant
- Bienveillant
- Precis mais simple
- Comme un coach qui parle dans l'oreille de l'utilisateur

REGLE D'OR:
Si ta reponse ressemble a un rapport ou a une analyse ecrite, elle est FAUSSE et doit etre simplifiee.

100% FRANCAIS. Aucun mot anglais autorise."""

DEEP_ANALYSIS_PROMPT_EN = """Provide a deep technical analysis of this workout WITH CONTEXTUAL COMPARISON to the athlete's recent baseline.

You have access to:
- Current workout data
- Baseline metrics from the last 7-14 days (averages and trends)

Structure your analysis:

1. EXECUTION ASSESSMENT
- How well was this session executed?
- Compare to recent baseline: pace/power consistency, heart rate response
- Express in relative terms: "slightly above your recent aerobic average", "in line with baseline", "notably higher than recent sessions"

2. TREND DETECTION
- Based on comparing this workout to baseline:
  - IMPROVING: metrics trending positively (lower HR at same pace, faster times, better efficiency)
  - MAINTAINING: stable performance, consistent with baseline
  - OVERLOAD RISK: signs of accumulated fatigue (elevated HR, declining pace, poor recovery between efforts)
- Be calm and precise. Not alarmist. State observations neutrally.

3. PHYSIOLOGICAL CONTEXT
- Zone distribution vs recent patterns
- Cardiac efficiency relative to baseline
- Any deviation from normal response patterns

4. ACTIONABLE INSIGHT
- One specific recommendation based on where this workout sits relative to recent load
- If load is high: suggest recovery focus
- If maintaining: suggest progression opportunity
- If improving: acknowledge and suggest next challenge

{hidden_insight_instruction}

Tone: Calm, precise, non-alarmist. Use phrases like:
- "slightly elevated compared to your recent baseline"
- "consistent with your 7-day average"
- "this represents a modest increase in training load"
- "your body is responding well to recent training"

Never dramatize. Just observe and advise."""

DEEP_ANALYSIS_PROMPT_FR = """Fournis une analyse technique approfondie de cette seance AVEC COMPARAISON CONTEXTUELLE a la baseline recente de l'athlete.

Tu as acces a:
- Les donnees de la seance actuelle
- Les metriques de reference des 7-14 derniers jours (moyennes et tendances)

Structure ton analyse:

1. EVALUATION DE L'EXECUTION
- Comment cette seance a-t-elle ete executee?
- Compare a la baseline recente: regularite allure/puissance, reponse cardiaque
- Exprime en termes relatifs: "legerement au-dessus de ta moyenne aerobie recente", "en ligne avec la baseline", "notablement plus eleve que les seances recentes"

2. DETECTION DE TENDANCE
- En comparant cette seance a la baseline:
  - PROGRESSION: metriques en amelioration (FC plus basse a meme allure, temps plus rapides, meilleure efficacite)
  - MAINTIEN: performance stable, coherente avec la baseline
  - RISQUE DE SURCHARGE: signes de fatigue accumulee (FC elevee, allure en baisse, mauvaise recuperation entre efforts)
- Sois calme et precis. Pas alarmiste. Enonce les observations de maniere neutre.

3. CONTEXTE PHYSIOLOGIQUE
- Distribution des zones vs patterns recents
- Efficacite cardiaque relative a la baseline
- Toute deviation des patterns de reponse normaux

4. RECOMMANDATION ACTIONNABLE
- Une recommandation specifique basee sur la position de cette seance par rapport a la charge recente
- Si charge elevee: suggere un focus recuperation
- Si maintien: suggere une opportunite de progression
- Si progression: reconnais et suggere le prochain defi

{hidden_insight_instruction}

Ton: Calme, precis, non-alarmiste. Utilise des phrases comme:
- "legerement eleve par rapport a ta baseline recente"
- "coherent avec ta moyenne sur 7 jours"
- "cela represente une augmentation modeste de la charge"
- "ton corps repond bien a l'entrainement recent"

Ne dramatise jamais. Observe et conseille simplement."""

HIDDEN_INSIGHT_EN = """
5. HIDDEN INSIGHT (include this section)
Add one non-obvious observation at the end. Something a less experienced coach might miss.

Focus areas (pick ONE that applies):
- Effort distribution anomaly: unusual zone transitions, split behavior patterns
- Pacing stability: drift patterns, negative/positive split tendencies
- Efficiency signals: pace-to-HR ratio changes, power economy shifts
- Fatigue fingerprints: late-session degradation, recovery interval quality
- Aerobic signature: threshold proximity patterns, sustainable effort markers

Rules:
- Variable length: sometimes just one sentence, sometimes 2-3 sentences
- No motivation ("great job", "keep it up")
- No alarms ("warning", "danger", "concerning")
- No medical terms
- State it as a quiet observation, like thinking out loud
- Use phrases like: "Worth noting...", "Something subtle here...", "An interesting pattern...", "One detail stands out..."

The goal is to sound like a thoughtful coach who notices things others don't."""

HIDDEN_INSIGHT_FR = """
5. OBSERVATION DISCRETE (inclure cette section)
Ajoute une observation non-evidente a la fin. Quelque chose qu'un coach moins experimente pourrait manquer.

Axes d'attention (choisis UN qui s'applique):
- Anomalie de distribution d'effort: transitions de zones inhabituelles, patterns de splits
- Stabilite d'allure: patterns de derive, tendances splits negatifs/positifs
- Signaux d'efficacite: changements du ratio allure/FC, evolution de l'economie de puissance
- Empreintes de fatigue: degradation en fin de seance, qualite des intervalles de recuperation
- Signature aerobie: patterns de proximite au seuil, marqueurs d'effort soutenable

Regles:
- Longueur variable: parfois une seule phrase, parfois 2-3 phrases
- Pas de motivation ("bravo", "continue comme ca")
- Pas d'alarmes ("attention", "danger", "preoccupant")
- Pas de termes medicaux
- Enonce-le comme une observation tranquille, comme une reflexion a voix haute
- Utilise des phrases comme: "A noter...", "Quelque chose de subtil ici...", "Un pattern interessant...", "Un detail ressort..."

L'objectif est de sonner comme un coach reflechi qui remarque des choses que d'autres ne voient pas."""

NO_HIDDEN_INSIGHT = ""

# ========== ADAPTIVE GUIDANCE PROMPTS ==========

ADAPTIVE_GUIDANCE_PROMPT_EN = """Based on the athlete's recent training data, provide adaptive training guidance.

You have access to:
- Recent workouts (last 7-14 days)
- Training load summary (volume, intensity distribution, workout types)

Generate SHORT-TERM guidance (not a rigid plan):

1. CURRENT STATUS
Assess the athlete's current state in ONE of these terms:
- "MAINTAIN" - training is balanced, continue current approach
- "ADJUST" - minor tweaks needed based on recent patterns
- "HOLD STEADY" - consolidate recent work before adding more

Explain in 1-2 sentences why.

2. SUGGESTED SESSIONS (max 3)
Provide up to 3 suggested next sessions. For each:
- Type: run/cycle/recovery
- Focus: what this session targets (aerobic base, speed, recovery, threshold, etc.)
- Duration/Distance: approximate
- Intensity: easy/moderate/hard or zone guidance
- Rationale: ONE sentence explaining "why this helps now" based on recent data

Format each suggestion as:
SESSION 1: [Type] - [Focus]
- Duration: [X min] or Distance: [X km]
- Intensity: [level]
- Why now: [brief rationale tied to recent training]

3. GUIDANCE NOTE (optional)
If relevant, add one brief observation about pacing, recovery, or load management.

Rules:
- No rigid schedules or fixed weekly plans
- Suggestions are guidance, not obligations
- Max 3 sessions ahead
- Calm, technical tone
- No motivation ("you've got this", "great work")
- No medical language
- No alarms or warnings
- Each suggestion must have a clear "why this helps now" rationale

The goal is to help the athlete train better without cognitive overload."""

ADAPTIVE_GUIDANCE_PROMPT_FR = """En fonction des donnees d'entrainement recentes de l'athlete, fournis des recommandations adaptatives.

Tu as acces a:
- Les seances recentes (7-14 derniers jours)
- Resume de la charge (volume, distribution d'intensite, types de seances)

Genere des recommandations A COURT TERME (pas un plan rigide):

1. STATUT ACTUEL
Evalue l'etat actuel de l'athlete avec UN de ces termes:
- "MAINTENIR" - l'entrainement est equilibre, continuer l'approche actuelle
- "AJUSTER" - petits ajustements necessaires selon les patterns recents
- "CONSOLIDER" - consolider le travail recent avant d'en ajouter

Explique en 1-2 phrases pourquoi.

2. SEANCES SUGGEREES (max 3)
Propose jusqu'a 3 prochaines seances. Pour chacune:
- Type: course/velo/recuperation
- Focus: ce que cette seance cible (base aerobie, vitesse, recuperation, seuil, etc.)
- Duree/Distance: approximative
- Intensite: facile/moderee/difficile ou zones
- Justification: UNE phrase expliquant "pourquoi maintenant" basee sur les donnees recentes

Formate chaque suggestion ainsi:
SEANCE 1: [Type] - [Focus]
- Duree: [X min] ou Distance: [X km]
- Intensite: [niveau]
- Pourquoi maintenant: [breve justification liee a l'entrainement recent]

3. NOTE DE GUIDANCE (optionnel)
Si pertinent, ajoute une breve observation sur l'allure, la recuperation ou la gestion de charge.

Regles:
- Pas de plannings rigides ou plans hebdomadaires fixes
- Les suggestions sont des recommandations, pas des obligations
- Max 3 seances a venir
- Ton calme et technique
- Pas de motivation ("tu vas y arriver", "super travail")
- Pas de langage medical
- Pas d'alarmes ou avertissements
- Chaque suggestion doit avoir une justification claire "pourquoi maintenant"

L'objectif est d'aider l'athlete a mieux s'entrainer sans surcharge cognitive."""


def get_system_prompt(language: str) -> str:
    """Get the appropriate system prompt based on language"""
    if language == "fr":
        return CARDIOCOACH_SYSTEM_FR
    return CARDIOCOACH_SYSTEM_EN


def calculate_baseline_metrics(workouts: List[dict], current_workout: dict, days: int = 14) -> dict:
    """Calculate baseline metrics from recent workouts for contextual comparison"""
    from datetime import datetime, timedelta
    
    current_date = datetime.fromisoformat(current_workout.get("date", "").replace("Z", "+00:00").split("T")[0])
    cutoff_date = current_date - timedelta(days=days)
    current_type = current_workout.get("type")
    
    # Filter workouts: same type, within date range, excluding current
    baseline_workouts = [
        w for w in workouts
        if w.get("type") == current_type
        and w.get("id") != current_workout.get("id")
        and w.get("date")
    ]
    
    # Filter by date
    filtered = []
    for w in baseline_workouts:
        try:
            w_date = datetime.fromisoformat(w["date"].replace("Z", "+00:00").split("T")[0])
            if cutoff_date <= w_date < current_date:
                filtered.append(w)
        except (ValueError, TypeError):
            continue
    
    if not filtered:
        return None
    
    # Calculate averages
    def safe_avg(values):
        valid = [v for v in values if v is not None]
        return round(sum(valid) / len(valid), 2) if valid else None
    
    baseline = {
        "period_days": days,
        "workout_count": len(filtered),
        "workout_type": current_type,
        "avg_distance_km": safe_avg([w.get("distance_km") for w in filtered]),
        "avg_duration_minutes": safe_avg([w.get("duration_minutes") for w in filtered]),
        "avg_heart_rate": safe_avg([w.get("avg_heart_rate") for w in filtered]),
        "avg_max_heart_rate": safe_avg([w.get("max_heart_rate") for w in filtered]),
    }
    
    # Type-specific metrics
    if current_type == "run":
        baseline["avg_pace_min_km"] = safe_avg([w.get("avg_pace_min_km") for w in filtered])
    elif current_type == "cycle":
        baseline["avg_speed_kmh"] = safe_avg([w.get("avg_speed_kmh") for w in filtered])
    
    # Calculate zone distribution averages
    zone_totals = {"z1": [], "z2": [], "z3": [], "z4": [], "z5": []}
    for w in filtered:
        zones = w.get("effort_zone_distribution", {})
        for z in zone_totals:
            if z in zones:
                zone_totals[z].append(zones[z])
    
    baseline["avg_zone_distribution"] = {
        z: safe_avg(vals) for z, vals in zone_totals.items() if vals
    }
    
    # Calculate load metrics
    total_volume = sum(w.get("distance_km", 0) for w in filtered)
    total_time = sum(w.get("duration_minutes", 0) for w in filtered)
    baseline["total_volume_km"] = round(total_volume, 1)
    baseline["total_time_minutes"] = total_time
    baseline["weekly_avg_distance"] = round(total_volume / (days / 7), 1) if days > 0 else 0
    
    # Compare current workout to baseline
    current_hr = current_workout.get("avg_heart_rate")
    current_dist = current_workout.get("distance_km")
    current_dur = current_workout.get("duration_minutes")
    
    comparison = {}
    if baseline["avg_heart_rate"] and current_hr:
        hr_diff = current_hr - baseline["avg_heart_rate"]
        hr_pct = (hr_diff / baseline["avg_heart_rate"]) * 100
        comparison["heart_rate_vs_baseline"] = {
            "difference_bpm": round(hr_diff, 1),
            "percentage": round(hr_pct, 1),
            "status": "elevated" if hr_pct > 5 else "reduced" if hr_pct < -5 else "normal"
        }
    
    if baseline["avg_distance_km"] and current_dist:
        dist_diff = current_dist - baseline["avg_distance_km"]
        dist_pct = (dist_diff / baseline["avg_distance_km"]) * 100
        comparison["distance_vs_baseline"] = {
            "difference_km": round(dist_diff, 1),
            "percentage": round(dist_pct, 1),
            "status": "longer" if dist_pct > 15 else "shorter" if dist_pct < -15 else "typical"
        }
    
    if current_type == "run" and baseline.get("avg_pace_min_km"):
        current_pace = current_workout.get("avg_pace_min_km")
        if current_pace:
            pace_diff = current_pace - baseline["avg_pace_min_km"]
            comparison["pace_vs_baseline"] = {
                "difference_min_km": round(pace_diff, 2),
                "status": "slower" if pace_diff > 0.15 else "faster" if pace_diff < -0.15 else "consistent"
            }
    
    baseline["comparison"] = comparison
    
    return baseline


WEEKLY_REVIEW_PROMPT_EN = """You are a calm, experienced professional coach giving a weekly review.
The user should understand their week in under 1 minute and know what to do next week.

CURRENT WEEK DATA: {training_data}
PREVIOUS WEEK DATA: {baseline_data}
{goal_context}
{followup_context}

KEY METRICS TO USE IN YOUR ANALYSIS:
- HR Zone distribution: Aggregate Z1-Z5 percentages show training intensity balance
  (Ideal polarized: 80% easy Z1-Z2, 20% hard Z4-Z5)
- Average cadence: Running efficiency indicator (optimal 170-180 spm)
- Pace consistency: Low variability = steady runs, high = intervals or terrain

Respond in JSON format only:
{{
  "coach_summary": "<ONE sentence maximum. Include zone insight if relevant. Example: 'Good volume with mostly easy effort - classic endurance building week.'>",
  "coach_reading": "<2 to 3 sentences ONLY. Interpret zones and intensity balance. Example: 'You spent 70% in Z4 this week which is high intensity. Consider adding more Z2 runs for recovery. Cadence averaged 165, try shorter steps for efficiency.'>",
  "recommendations": [
    "<1 to 2 clear recommendations based on zone analysis. ACTION-oriented. Example: 'Add a pure Z2 recovery run (conversational pace)'>",
    "<Example: 'Work on cadence: aim for 170+ spm on easy runs'>"
  ],
  "recommendations_followup": "<ONLY if previous recommendations exist: ONE sentence about how the user followed (or not) last week's advice. Be factual, not judgmental. Leave empty string if no previous recommendations.>"
}}

TRANSLATE zones naturally: Z1-Z2="easy/recovery", Z3="moderate", Z4="hard/tempo", Z5="max effort"
FORBIDDEN: Raw percentages without context, markdown, report language
REQUIRED: Interpret data into simple coaching insights. Calm, confident, professional.

100% ENGLISH only. No French words."""

WEEKLY_REVIEW_PROMPT_FR = """Tu es un coach professionnel calme et experimente qui fait un bilan hebdomadaire.
L'utilisateur doit comprendre sa semaine en moins d'1 minute et savoir quoi faire la semaine prochaine.

DONNEES SEMAINE EN COURS: {training_data}
DONNEES SEMAINE PRECEDENTE: {baseline_data}
{goal_context}
{followup_context}

METRIQUES CLES POUR TON ANALYSE:
- Repartition zones FC: Agregation Z1-Z5 montre l'equilibre d'intensite
  (Ideal polarise: 80% facile Z1-Z2, 20% dur Z4-Z5)
- Cadence moyenne: Indicateur d'efficacite (optimal 170-180 ppm)
- Regularite allure: Basse variabilite = sorties regulieres, haute = intervalles ou terrain

Reponds en format JSON uniquement:
{{
  "coach_summary": "<UNE phrase maximum. Inclus insight zones si pertinent. Exemple: 'Bon volume avec effort surtout facile - semaine classique de construction.'>",
  "coach_reading": "<2 a 3 phrases UNIQUEMENT. Interprete zones et equilibre intensite. Exemple: 'Tu as passe 70% en Z4 cette semaine, intensite elevee. Ajoute des sorties Z2 pour recuperer. Cadence moyenne 165, essaie des foulees plus courtes.'>",
  "recommendations": [
    "<1 a 2 recommandations claires basees sur analyse zones. Orientees ACTION. Exemple: 'Ajouter une sortie pure Z2 (allure conversation)'>",
    "<Exemple: 'Travailler la cadence: viser 170+ ppm sur sorties faciles'>"
  ],
  "recommendations_followup": "<UNIQUEMENT si recommandations precedentes existent: UNE phrase sur comment l'utilisateur a suivi (ou non) les conseils. Factuel, pas moralisateur. Vide si pas de recommandations precedentes.>"
}}

TRADUIRE les zones naturellement: Z1-Z2="facile/recup", Z3="modere", Z4="soutenu/tempo", Z5="effort max"
INTERDIT: Pourcentages bruts sans contexte, markdown, langage de rapport
OBLIGATOIRE: Interprete les donnees en coaching simple. Calme, confiant, professionnel.

100% FRANCAIS uniquement. Aucun mot anglais."""


def calculate_review_metrics(workouts: List[dict], baseline_workouts: List[dict]) -> tuple:
    """Calculate metrics and comparison for weekly review"""
    if not workouts:
        metrics = {
            "total_sessions": 0,
            "total_distance_km": 0,
            "total_duration_min": 0,
        }
        comparison = {
            "sessions_diff": 0,
            "distance_diff_km": 0,
            "distance_diff_pct": 0,
            "duration_diff_min": 0,
        }
        return metrics, comparison
    
    # Current week metrics
    total_distance = sum(w.get("distance_km", 0) for w in workouts)
    total_duration = sum(w.get("duration_minutes", 0) for w in workouts)
    
    metrics = {
        "total_sessions": len(workouts),
        "total_distance_km": round(total_distance, 1),
        "total_duration_min": total_duration,
    }
    
    # Baseline comparison
    baseline_sessions = len(baseline_workouts) if baseline_workouts else 0
    baseline_distance = sum(w.get("distance_km", 0) for w in baseline_workouts) if baseline_workouts else 0
    baseline_duration = sum(w.get("duration_minutes", 0) for w in baseline_workouts) if baseline_workouts else 0
    
    # Calculate differences
    distance_diff_pct = 0
    if baseline_distance > 0:
        distance_diff_pct = round(((total_distance - baseline_distance) / baseline_distance) * 100)
    elif total_distance > 0:
        distance_diff_pct = 100
    
    comparison = {
        "sessions_diff": len(workouts) - baseline_sessions,
        "distance_diff_km": round(total_distance - baseline_distance, 1),
        "distance_diff_pct": distance_diff_pct,
        "duration_diff_min": total_duration - baseline_duration,
    }
    
    return metrics, comparison


def generate_review_signals(workouts: List[dict], baseline_workouts: List[dict]) -> List[dict]:
    """Generate visual signal indicators for weekly review - CARTE 2"""
    signals = []
    
    # Calculate volume change
    current_km = sum(w.get("distance_km", 0) for w in workouts)
    baseline_km = sum(w.get("distance_km", 0) for w in baseline_workouts) if baseline_workouts else 0
    
    if baseline_km > 0:
        volume_change = round(((current_km - baseline_km) / baseline_km) * 100)
    else:
        volume_change = 100 if current_km > 0 else 0
    
    # Volume signal
    if volume_change > 15:
        signals.append({"key": "load", "status": "up", "value": f"+{volume_change}%"})
    elif volume_change < -15:
        signals.append({"key": "load", "status": "down", "value": f"{volume_change}%"})
    else:
        signals.append({"key": "load", "status": "stable", "value": f"{volume_change:+}%" if volume_change != 0 else "="})
    
    # Intensity signal based on zone distribution
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    for w in workouts:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z, pct in zones.items():
                if z in zone_totals:
                    zone_totals[z] += pct
            zone_count += 1
    
    if zone_count > 0:
        avg_zones = {z: v / zone_count for z, v in zone_totals.items()}
        easy_pct = avg_zones.get("z1", 0) + avg_zones.get("z2", 0)
        hard_pct = avg_zones.get("z4", 0) + avg_zones.get("z5", 0)
        
        if easy_pct >= 70:
            signals.append({"key": "intensity", "status": "easy", "value": None})
        elif hard_pct >= 30:
            signals.append({"key": "intensity", "status": "hard", "value": None})
        else:
            signals.append({"key": "intensity", "status": "balanced", "value": None})
    else:
        signals.append({"key": "intensity", "status": "balanced", "value": None})
    
    # Regularity signal (sessions spread across days)
    unique_days = len(set(w.get("date", "")[:10] for w in workouts))
    regularity_pct = min(100, round((unique_days / 7) * 100)) if workouts else 0
    
    if regularity_pct >= 60:
        signals.append({"key": "consistency", "status": "high", "value": f"{regularity_pct}%"})
    elif regularity_pct >= 30:
        signals.append({"key": "consistency", "status": "moderate", "value": f"{regularity_pct}%"})
    else:
        signals.append({"key": "consistency", "status": "low", "value": f"{regularity_pct}%"})
    
    return signals


MOBILE_ANALYSIS_PROMPT_EN = """You are a calm running coach giving quick feedback on a workout.

WORKOUT DATA:
{workout_data}

RECENT HABITS (baseline):
{baseline_data}

KEY METRICS TO ANALYZE:
- HR Zones: Time distribution across Z1-Z5 (Z1-Z2 = easy, Z3 = moderate, Z4-Z5 = hard)
- Pace: Average vs best pace, variability (low = steady, high = variable effort)
- Cadence: Steps per minute (optimal running: 170-180 spm)
- Compare this session to recent habits

Respond in JSON:
{{
  "coach_summary": "<ONE sentence, max 15 words. Like a coach talking. Use HR zones insight. Example: 'Mostly in Z4, a solid tempo run with good rhythm.'>",
  "insight": "<Max 2 short sentences. Interpret the data simply. Example: 'You spent 65% in Z4 which shows sustained effort. Cadence at 165 is slightly low.'>",
  "guidance": "<ONE calm suggestion based on zones/pace or null. Example: 'Next time, try more Z2 time to balance the week.'>"
}}

FORBIDDEN: raw numbers without context, markdown, "baseline", "distribution", report language
TRANSLATE zones to feelings: Z1-Z2="easy/comfortable", Z3="moderate", Z4="hard/tempo", Z5="max effort"
REQUIRED: Speak like a real coach. Reassure. Guide. Keep it simple but informed.

100% ENGLISH only."""

MOBILE_ANALYSIS_PROMPT_FR = """Tu es un coach running calme qui donne un retour rapide sur une seance.

DONNEES SEANCE:
{workout_data}

HABITUDES RECENTES (baseline):
{baseline_data}

METRIQUES CLES A ANALYSER:
- Zones FC: Repartition Z1-Z5 (Z1-Z2 = facile, Z3 = modere, Z4-Z5 = soutenu)
- Allure: Moyenne vs meilleure, variabilite (basse = regulier, haute = effort variable)
- Cadence: Pas par minute (optimal course: 170-180 ppm)
- Compare cette seance aux habitudes recentes

Reponds en JSON:
{{
  "coach_summary": "<UNE phrase, max 15 mots. Comme un coach qui parle. Utilise les zones. Exemple: 'Surtout en Z4, une belle sortie tempo avec bon rythme.'>",
  "insight": "<Max 2 phrases courtes. Interprete les donnees simplement. Exemple: 'Tu as passe 65% en Z4, effort soutenu. Cadence a 165, un peu basse.'>",
  "guidance": "<UNE suggestion calme basee sur zones/allure ou null. Exemple: 'Prochaine fois, plus de temps en Z2 pour equilibrer la semaine.'>"
}}

INTERDIT: chiffres bruts sans contexte, markdown, "baseline", "distribution", langage de rapport
TRADUIRE les zones en sensations: Z1-Z2="facile/confortable", Z3="modere", Z4="soutenu/tempo", Z5="effort max"
OBLIGATOIRE: Parle comme un vrai coach. Rassure. Guide. Simple mais informe.

100% FRANCAIS uniquement."""


def calculate_mobile_signals(workout: dict, baseline: dict) -> dict:
    """Calculate signal cards for mobile workout analysis"""
    w_type = workout.get("type", "run")
    
    # Intensity card
    intensity = {
        "pace": None,
        "avg_hr": workout.get("avg_heart_rate"),
        "label": "normal"
    }
    
    if w_type == "run":
        pace = workout.get("avg_pace_min_km")
        if pace:
            mins = int(pace)
            secs = int((pace - mins) * 60)
            intensity["pace"] = f"{mins}:{str(secs).zfill(2)}/km"
    else:
        speed = workout.get("avg_speed_kmh")
        if speed:
            intensity["pace"] = f"{speed:.1f} km/h"
    
    # Compare HR to baseline for intensity label
    hr_score = 0
    if baseline and baseline.get("avg_heart_rate") and workout.get("avg_heart_rate"):
        hr_diff_pct = (workout["avg_heart_rate"] - baseline["avg_heart_rate"]) / baseline["avg_heart_rate"] * 100
        if hr_diff_pct > 5:
            intensity["label"] = "above_usual"
            hr_score = 1
        elif hr_diff_pct < -5:
            intensity["label"] = "below_usual"
            hr_score = -1
    
    # Load card
    distance = workout.get("distance_km", 0)
    duration = workout.get("duration_minutes", 0)
    
    load = {
        "distance_km": round(distance, 1),
        "duration_min": duration,
        "direction": "stable"
    }
    
    load_score = 0
    if baseline and baseline.get("avg_distance_km"):
        dist_diff = (distance - baseline["avg_distance_km"]) / baseline["avg_distance_km"] * 100
        if dist_diff > 15:
            load["direction"] = "up"
            load_score = 1
        elif dist_diff < -15:
            load["direction"] = "down"
            load_score = -1
    
    # Session Type card (Easy / Sustained / Hard)
    # Based on HR intensity + load combined
    combined_score = hr_score + load_score
    
    if combined_score >= 2:
        session_type_label = "hard"
    elif combined_score <= -1:
        session_type_label = "easy"
    elif hr_score == 1 or load_score == 1:
        session_type_label = "sustained"
    else:
        session_type_label = "easy" if hr_score == -1 else "sustained"
    
    # Also check zone distribution if available
    zones = workout.get("effort_zone_distribution", {})
    if zones:
        hard_zones = (zones.get("z4", 0) or 0) + (zones.get("z5", 0) or 0)
        easy_zones = (zones.get("z1", 0) or 0) + (zones.get("z2", 0) or 0)
        
        if hard_zones > 30:
            session_type_label = "hard"
        elif easy_zones > 80:
            session_type_label = "easy"
    
    session_type = {
        "label": session_type_label
    }
    
    return {
        "intensity": intensity,
        "load": load,
        "session_type": session_type
    }


DETAILED_ANALYSIS_PROMPT_EN = """You are a calm running coach giving a detailed debrief.
This is NOT a report. This is a calm conversation with data-informed insights.

WORKOUT DATA:
{workout_data}

RECENT HABITS (baseline):
{baseline_data}

KEY DATA TO INTERPRET:
- HR Zones (z1-z5): z1-z2 = recovery/easy, z3 = aerobic, z4 = tempo/threshold, z5 = VO2max
- Pace: avg vs best shows your range, variability shows steadiness
- Cadence: 170-180 spm is efficient, <165 may indicate overstriding

Structure your response in JSON:

{{
  "header": {{
    "context": "<1 sentence. What happened using zone insight. Example: '65% in Z4 - a solid tempo effort with good rhythm.'>",
    "session_name": "<Short descriptive name based on zones. Example: 'Tempo Run' if mostly Z4, 'Easy Aerobic' if Z1-Z2>"
  }},
  "execution": {{
    "intensity": "<Easy | Moderate | Sustained | High> - based on Z4+Z5 percentage",
    "volume": "<Usual | Longer | One-off peak>",
    "regularity": "<Stable | Variable> - based on pace variability"
  }},
  "meaning": {{
    "text": "<What it means. 2-3 short sentences. Interpret zones and pace. Example: 'Most time in Z4 shows sustained threshold work. Your cadence at 165 is slightly low - small steps help efficiency. Pace variability was high, suggesting uneven terrain or effort.'>"
  }},
  "recovery": {{
    "text": "<What the body needs based on intensity. 1 sentence. Example: 'After that Z4 effort, an easy Z2 day tomorrow helps absorption.'>"
  }},
  "advice": {{
    "text": "<What to do next. 1 calm sentence. Example: 'Next run, aim for more Z2 time to balance this tempo work.'>"
  }},
  "advanced": {{
    "comparisons": "<Technical details for curious users. 2-3 short points about zones/pace/cadence vs baseline.>"
  }}
}}

TRANSLATE zones: Z1-Z2="easy/recovery", Z3="aerobic", Z4="tempo/hard", Z5="max"
FORBIDDEN: raw zone percentages without interpretation, markdown, report language
REQUIRED: Interpret data into actionable coaching. Reassure. Guide.

100% ENGLISH only."""

DETAILED_ANALYSIS_PROMPT_FR = """Tu es un coach running calme qui fait un debrief detaille.
Ceci n'est PAS un rapport. C'est une conversation calme avec des insights bases sur les donnees.

DONNEES SEANCE:
{workout_data}

HABITUDES RECENTES (baseline):
{baseline_data}

DONNEES CLES A INTERPRETER:
- Zones FC (z1-z5): z1-z2 = recup/facile, z3 = aerobie, z4 = tempo/seuil, z5 = VO2max
- Allure: moy vs meilleure montre ta plage, variabilite montre la regularite
- Cadence: 170-180 ppm est efficace, <165 peut indiquer des foulees trop longues

Structure ta reponse en JSON:

{{
  "header": {{
    "context": "<1 phrase. Ce qui s'est passe avec insight zones. Exemple: '65% en Z4 - un bel effort tempo avec bon rythme.'>",
    "session_name": "<Nom court descriptif base sur zones. Exemple: 'Sortie Tempo' si surtout Z4, 'Aerobie Facile' si Z1-Z2>"
  }},
  "execution": {{
    "intensity": "<Facile | Moderee | Soutenue | Haute> - base sur pourcentage Z4+Z5",
    "volume": "<Habituel | Plus long | Pic ponctuel>",
    "regularity": "<Stable | Variable> - base sur variabilite allure"
  }},
  "meaning": {{
    "text": "<Ce que ca signifie. 2-3 phrases courtes. Interprete zones et allure. Exemple: 'Surtout en Z4, travail au seuil soutenu. Ta cadence a 165 est un peu basse - des petits pas aident l'efficacite. Variabilite d'allure elevee, terrain vallonne ou effort irregulier.'>"
  }},
  "recovery": {{
    "text": "<Ce dont le corps a besoin selon l'intensite. 1 phrase. Exemple: 'Apres cet effort Z4, une journee facile en Z2 demain aide l'absorption.'>"
  }},
  "advice": {{
    "text": "<Quoi faire ensuite. 1 phrase calme. Exemple: 'Prochaine sortie, vise plus de temps en Z2 pour equilibrer ce tempo.'>"
  }},
  "advanced": {{
    "comparisons": "<Details techniques pour les curieux. 2-3 points courts sur zones/allure/cadence vs baseline.>"
  }}
}}

TRADUIRE les zones: Z1-Z2="facile/recup", Z3="aerobie", Z4="tempo/soutenu", Z5="max"
INTERDIT: pourcentages bruts sans interpretation, markdown, langage de rapport
OBLIGATOIRE: Interprete les donnees en coaching actionnable. Rassure. Guide.

100% FRANCAIS uniquement."""


@router.post("/coach/analyze", response_model=CoachResponse)
async def analyze_with_coach(request: CoachRequest):
    """Chat Coach conversationnel avec GPT-4o-mini
    
    Le coach a accès à:
    - L'historique des conversations
    - Les données d'entraînement (séances, stats)
    - Le contexte fitness (ACWR, TSB, volume)
    
    Il peut répondre à des questions ouvertes sur l'entraînement.
    """
    from llm_coach import enrich_chat_response
    
    user_id = request.user_id or "default"
    language = request.language or "en"
    user_message = request.message or ""
    
    # 1. Récupérer l'historique des conversations (5 derniers messages)
    conversation_history = await db.conversations.find(
        {"user_id": user_id}
    ).sort("timestamp", -1).limit(5).to_list(5)
    conversation_history = list(reversed(conversation_history))  # Ordre chronologique
    
    # 2. Récupérer les données d'entraînement
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    # Activités Strava
    recent_activities = await db.strava_activities.find({
        "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
        "start_date_local": {"$gte": seven_days_ago.isoformat()}
    }).sort("start_date_local", -1).to_list(20)
    
    all_activities = await db.strava_activities.find({
        "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
        "start_date_local": {"$gte": twenty_eight_days_ago.isoformat()}
    }).sort("start_date_local", -1).to_list(100)
    
    # Fallback sur workouts locaux
    if not all_activities:
        recent_activities = await db.workouts.find({
            "date": {"$gte": seven_days_ago.isoformat()}
        }).sort("date", -1).to_list(20)
        all_activities = await db.workouts.find({
            "date": {"$gte": twenty_eight_days_ago.isoformat()}
        }).sort("date", -1).to_list(100)
    
    # 3. Calculer les métriques de contexte
    def get_distance_km(w):
        dist = w.get("distance", 0)
        if dist > 1000:
            return dist / 1000
        return w.get("distance_km", dist) or 0
    
    km_7 = sum(get_distance_km(w) for w in recent_activities)
    km_28 = sum(get_distance_km(w) for w in all_activities)
    
    # ACWR & TSB
    chronic_avg = km_28 / 4 if km_28 > 0 else 1
    acwr = round(km_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    ctl = km_28 / 4
    atl = km_7
    tsb = round(ctl - atl, 1)
    
    # 4. Préparer le résumé de TOUTES les séances (pas seulement 5)
    all_sessions_summary = []
    for act in all_activities:
        name = act.get("name", "Séance")
        dist = get_distance_km(act)
        duration = act.get("moving_time", act.get("duration_minutes", 0) * 60)
        if duration > 100:
            duration = duration / 60  # Convertir secondes en minutes
        avg_hr = act.get("average_heartrate", act.get("avg_heart_rate"))
        date_str = act.get("start_date_local", act.get("date", ""))[:10]
        avg_pace = ""
        if dist > 0 and duration > 0:
            pace_sec = (duration * 60) / dist
            pace_min = int(pace_sec // 60)
            pace_sec_rem = int(pace_sec % 60)
            avg_pace = f"{pace_min}:{pace_sec_rem:02d}/km"
        
        session_info = f"- {date_str}: {name}, {dist:.1f}km"
        if duration:
            session_info += f", {int(duration)}min"
        if avg_pace:
            session_info += f", {avg_pace}"
        if avg_hr:
            session_info += f", FC {int(avg_hr)}bpm"
        all_sessions_summary.append(session_info)
    
    # 5. Récupérer le plan d'entraînement actuel
    training_plan_summary = ""
    current_goal = "Non défini"
    sessions_per_week = 4
    try:
        plan_data = await db.training_plans.find_one(
            {"user_id": user_id},
            sort=[("created_at", -1)]
        )
        if plan_data:
            current_goal = plan_data.get("goal", "SEMI")
            sessions_per_week = plan_data.get("sessions_per_week", 4)
            sessions = plan_data.get("sessions", [])
            if sessions:
                training_plan_summary = f"Objectif: {current_goal} | {sessions_per_week} séances/semaine\n"
                training_plan_summary += "Planning de la semaine:\n"
                for s in sessions:
                    day = s.get("day", "")
                    stype = s.get("type", "")
                    details = s.get("details", "")
                    dist = s.get("distance_km", 0)
                    training_plan_summary += f"  • {day}: {stype}"
                    if dist > 0:
                        training_plan_summary += f" ({dist}km)"
                    if details and stype != "Repos":
                        training_plan_summary += f" - {details[:60]}"
                    training_plan_summary += "\n"
    except Exception as e:
        logger.warning(f"Could not fetch training plan for coach context: {e}")
    
    # 6. Récupérer la VMA et les prédictions depuis l'endpoint existant
    vma_info = ""
    predictions_summary = ""
    try:
        # Utiliser la même logique que /api/training/race-predictions
        sixty_days_ago = today - timedelta(days=60)
        pred_activities = await db.strava_activities.find({
            "$or": [{"user_id": user_id}, {"user_id": None}, {"user_id": {"$exists": False}}],
            "start_date_local": {"$gte": sixty_days_ago.isoformat()}
        }).to_list(500)
        
        if not pred_activities:
            pred_activities = await db.workouts.find({
                "date": {"$gte": sixty_days_ago.isoformat()}
            }).to_list(500)
        
        if pred_activities:
            # Calculer la VMA avec la méthode correcte
            def get_pred_distance(a):
                dist = a.get("distance", 0)
                if dist > 1000:
                    return dist / 1000
                return a.get("distance_km", dist)
            
            def get_pred_duration(a):
                moving_time = a.get("moving_time", 0)
                if moving_time > 0:
                    return moving_time / 60
                elapsed = a.get("elapsed_time", 0)
                if elapsed > 0:
                    return elapsed / 60
                return a.get("duration_minutes", 0)
            
            def get_pred_pace(a):
                pace = a.get("avg_pace_min_km")
                if pace:
                    return pace
                speed = a.get("average_speed", 0)
                if speed > 0:
                    return (1000 / speed) / 60
                dist = get_pred_distance(a)
                duration_min = get_pred_duration(a)
                if dist > 0 and duration_min > 0:
                    return duration_min / dist
                return None
            
            paces = []
            vma_efforts = []
            MIN_VMA_DURATION = 6
            
            for a in pred_activities:
                dist = get_pred_distance(a)
                pace = get_pred_pace(a)
                duration_min = get_pred_duration(a)
                
                if dist > 0 and pace and 3 < pace < 10:
                    paces.append(pace)
                    # Efforts >= 6 min ET allure rapide (< 5:30/km)
                    if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                        vma_efforts.append({
                            "pace": pace,
                            "duration": duration_min,
                            "speed_kmh": 60 / pace
                        })
            
            if paces:
                avg_pace = sum(paces) / len(paces)
                
                # Calculer VMA avec la méthode correcte
                if vma_efforts:
                    best_vma_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
                    best_sustained_speed = best_vma_effort["speed_kmh"]
                    duration = best_vma_effort["duration"]
                    
                    if duration >= 20:
                        estimated_vma = best_sustained_speed / 0.85
                    elif duration >= 12:
                        estimated_vma = best_sustained_speed / 0.90
                    else:
                        estimated_vma = best_sustained_speed / 0.95
                else:
                    avg_speed_kmh = 60 / avg_pace
                    estimated_vma = avg_speed_kmh / 0.70
                
                estimated_vma = round(estimated_vma, 1)
                vma_info = f"VMA estimée: {estimated_vma} km/h"
                
                # Prédictions basées sur VMA
                pred_5k_speed = estimated_vma * 0.95
                pred_5k_pace = 60 / pred_5k_speed
                time_5k = (pred_5k_pace * 5)
                
                pred_10k_speed = estimated_vma * 0.90
                pred_10k_pace = 60 / pred_10k_speed
                time_10k = (pred_10k_pace * 10)
                
                pred_semi_speed = estimated_vma * 0.82
                pred_semi_pace = 60 / pred_semi_speed
                time_semi = (pred_semi_pace * 21.1)
                h_semi = int(time_semi // 60)
                m_semi = int(time_semi % 60)
                
                pred_marathon_speed = estimated_vma * 0.75
                pred_marathon_pace = 60 / pred_marathon_speed
                time_marathon = (pred_marathon_pace * 42.195)
                h_mar = int(time_marathon // 60)
                m_mar = int(time_marathon % 60)
                
                predictions_summary = f"5K: {int(time_5k)}:{int((time_5k % 1) * 60):02d} | 10K: {int(time_10k)}:{int((time_10k % 1) * 60):02d} | Semi: {h_semi}h{m_semi:02d} | Marathon: {h_mar}h{m_mar:02d}"
                
    except Exception as e:
        logger.warning(f"Could not calculate VMA for coach context: {e}")
        vma_info = "VMA: non calculée"
    
    # 7. Construire le contexte complet
    context = {
        "language": language,
        "stats_7j": {
            "km": round(km_7, 1),
            "sessions": len(recent_activities)
        },
        "stats_28j": {
            "km": round(km_28, 1),
            "sessions": len(all_activities)
        },
        "fitness": {
            "acwr": acwr,
            "acwr_status": "optimal" if 0.8 <= acwr <= 1.3 else "attention",
            "tsb": tsb,
            "tsb_status": "frais" if tsb > 0 else "fatigué" if tsb < -10 else "en charge"
        },
        "all_sessions": "\n".join(all_sessions_summary) if all_sessions_summary else "Aucune séance enregistrée",
        "training_plan": training_plan_summary if training_plan_summary else "Aucun plan d'entraînement actif",
        "current_goal": current_goal,
        "vma": vma_info,
        "predictions": predictions_summary
    }
    
    # 5. Si workout_id spécifié, enrichir le contexte avec les détails de la séance
    if request.workout_id:
        workout = await db.strava_activities.find_one({"id": request.workout_id})
        if not workout:
            workout = await db.workouts.find_one({"id": request.workout_id})
        
        if workout:
            context["workout_detail"] = {
                "name": workout.get("name"),
                "distance_km": get_distance_km(workout),
                "duration_min": workout.get("moving_time", workout.get("duration_minutes", 0) * 60) / 60 if workout.get("moving_time", 0) > 100 else workout.get("duration_minutes", 0),
                "avg_hr": workout.get("average_heartrate", workout.get("avg_heart_rate")),
                "max_hr": workout.get("max_heartrate", workout.get("max_heart_rate")),
                "zones": workout.get("effort_zone_distribution"),
                "km_splits": workout.get("km_splits", [])[:5]  # 5 premiers km
            }
    
    # 6. Stocker le message utilisateur
    user_msg_id = str(uuid.uuid4())
    await db.conversations.insert_one({
        "id": user_msg_id,
        "user_id": user_id,
        "role": "user",
        "content": user_message,
        "workout_id": request.workout_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    # 7. Appeler GPT-4o-mini pour générer la réponse
    llm_response, success, meta = await enrich_chat_response(
        user_message=user_message,
        context=context,
        conversation_history=[{"role": m.get("role"), "content": m.get("content")} for m in conversation_history],
        user_id=user_id
    )
    
    if not success or not llm_response:
        logger.warning(f"LLM chat failed: {meta}")
        raise HTTPException(
            status_code=503,
            detail="Le service de coaching IA n'est pas disponible actuellement." if language == "fr" else "The AI coaching service is currently unavailable."
        )
    
    response_text = llm_response
    
    # 8. Stocker la réponse assistant
    msg_id = str(uuid.uuid4())
    await db.conversations.insert_one({
        "id": msg_id,
        "user_id": user_id,
        "role": "assistant",
        "content": response_text,
        "workout_id": request.workout_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return CoachResponse(response=response_text, message_id=msg_id)


@router.get("/coach/history")
async def get_conversation_history(user_id: str = "default", limit: int = 50):
    """Get conversation history for a user"""
    messages = await db.conversations.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(limit)
    return messages


@router.delete("/coach/history")
async def clear_conversation_history(user_id: str = "default"):
    """Clear conversation history for a user"""
    result = await db.conversations.delete_many({"user_id": user_id})
    return {"deleted_count": result.deleted_count}


@router.get("/messages")
async def get_messages(limit: int = 20):
    """Get recent coach messages (legacy endpoint)"""
    messages = await db.conversations.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return messages


@router.post("/coach/guidance", response_model=GuidanceResponse)
async def get_adaptive_guidance(request: GuidanceRequest):
    """Generate adaptive training guidance based on recent workouts - 100% LOCAL ENGINE"""
    
    language = request.language or "en"
    user_id = request.user_id or "default"
    
    # Get recent workouts (last 14 days)
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
    if not all_workouts:
        all_workouts = get_mock_workouts()
    
    # Calculate training summary
    today = datetime.now(timezone.utc).date()
    cutoff_14d = today - timedelta(days=14)
    cutoff_7d = today - timedelta(days=7)
    
    recent_14d = []
    recent_7d = []
    
    for w in all_workouts:
        try:
            w_date = datetime.fromisoformat(w["date"].replace("Z", "+00:00").split("T")[0]).date()
            if w_date >= cutoff_14d:
                recent_14d.append(w)
            if w_date >= cutoff_7d:
                recent_7d.append(w)
        except (ValueError, TypeError, KeyError):
            continue
    
    # Use local engine for weekly review
    review = generate_weekly_review(
        workouts=recent_7d,
        previous_week_workouts=[w for w in recent_14d if w not in recent_7d],
        user_goal=None,
        language=language
    )
    
    # Determine status from metrics
    metrics = review.get("metrics", {})
    volume_change = metrics.get("volume_change_pct", 0)
    total_sessions = metrics.get("total_sessions", 0)
    
    # Calculate zone distribution
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    for w in recent_7d:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z, pct in zones.items():
                if z in zone_totals:
                    zone_totals[z] += (pct or 0)
            zone_count += 1
    
    z4_z5_avg = 0
    if zone_count > 0:
        z4_z5_avg = (zone_totals["z4"] + zone_totals["z5"]) / zone_count
    
    # Determine status
    if total_sessions == 0:
        status = "hold_steady"
    elif volume_change > 20 or z4_z5_avg > 35:
        status = "adjust"  # Need to recover
    elif volume_change < -20 or total_sessions < 2:
        status = "hold_steady"  # Build back up
    else:
        status = "maintain"
    
    # Build guidance text
    guidance_parts = [review["summary"]]
    guidance_parts.append(review["meaning"])
    guidance_parts.append(review["advice"])
    
    guidance = "\n\n".join(guidance_parts)
    
    # Store guidance in DB
    await db.guidance.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "status": status,
        "guidance": guidance,
        "language": language,
        "training_summary": {
            "last_7d": {
                "count": len(recent_7d),
                "total_km": round(sum(w.get("distance_km", 0) for w in recent_7d), 1)
            },
            "last_14d": {
                "count": len(recent_14d),
                "total_km": round(sum(w.get("distance_km", 0) for w in recent_14d), 1)
            }
        },
        "generated_at": datetime.now(timezone.utc).isoformat()
    })
    
    logger.info(f"Guidance generated (LOCAL): status={status}, user={user_id}")
    
    return GuidanceResponse(
        status=status,
        guidance=guidance,
        generated_at=datetime.now(timezone.utc).isoformat()
    )


@router.get("/coach/guidance/latest")
async def get_latest_guidance(user_id: str = "default"):
    """Get the most recent guidance for a user"""
    guidance = await db.guidance.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("generated_at", -1)]
    )
    if not guidance:
        return None
    return guidance


@router.get("/coach/digest")
async def get_weekly_review(user_id: str = "default", language: str = "en"):
    """Generate weekly training review (Bilan de la semaine) - 100% LOCAL ENGINE, NO LLM"""
    
    # Get all workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(200)
    if not all_workouts:
        all_workouts = get_mock_workouts()
    
    # Calculate date ranges
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=7)
    baseline_start = today - timedelta(days=14)
    
    # Filter workouts for current week and baseline
    current_week = []
    baseline_week = []
    
    for w in all_workouts:
        try:
            w_date = datetime.fromisoformat(w["date"].replace("Z", "+00:00").split("T")[0]).date()
            if week_start <= w_date <= today:
                current_week.append(w)
            elif baseline_start <= w_date < week_start:
                baseline_week.append(w)
        except (ValueError, TypeError, KeyError):
            continue
    
    # Calculate metrics and comparison (CARTE 3)
    metrics, comparison = calculate_review_metrics(current_week, baseline_week)
    
    # Generate signals (CARTE 2)
    signals = generate_review_signals(current_week, baseline_week)
    
    # Get user goal for context
    user_goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    # Generate review content using LOCAL ENGINE (NO LLM - Strava compliant)
    review = generate_weekly_review(
        workouts=current_week,
        previous_week_workouts=baseline_week,
        user_goal=user_goal,
        language=language
    )
    
    coach_summary = review["summary"]
    coach_reading = review["meaning"]
    recommendations = [review["advice"]]
    recommendations_followup = review.get("recovery", "")
    
    # Store review
    review_id = str(uuid.uuid4())
    await db.digests.insert_one({
        "id": review_id,
        "user_id": user_id,
        "period_start": week_start.isoformat(),
        "period_end": today.isoformat(),
        "coach_summary": coach_summary,
        "coach_reading": coach_reading,
        "recommendations": recommendations,
        "recommendations_followup": recommendations_followup,
        "metrics": metrics,
        "comparison": comparison,
        "signals": signals,
        "user_goal": user_goal,
        "language": language,
        "generated_at": datetime.now(timezone.utc).isoformat()
    })
    
    logger.info(f"Weekly review generated for user {user_id}: {len(current_week)} workouts (LOCAL ENGINE)")
    
    return WeeklyReviewResponse(
        period_start=week_start.isoformat(),
        period_end=today.isoformat(),
        coach_summary=coach_summary,
        coach_reading=coach_reading,
        recommendations=recommendations,
        recommendations_followup=recommendations_followup,
        metrics=metrics,
        comparison=comparison,
        signals=signals,
        user_goal=user_goal,
        generated_at=datetime.now(timezone.utc).isoformat()
    )


@router.get("/coach/digest/latest")
async def get_latest_digest(user_id: str = "default"):
    """Get the most recent digest for a user"""
    digest = await db.digests.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("generated_at", -1)]
    )
    return digest


@router.get("/coach/digest/history")
async def get_digest_history(user_id: str = "default", limit: int = 10, skip: int = 0):
    """Get history of weekly digests for a user"""
    digests = await db.digests.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("generated_at", -1).skip(skip).limit(limit).to_list(length=limit)
    
    total = await db.digests.count_documents({"user_id": user_id})
    
    return {
        "digests": digests,
        "total": total,
        "has_more": skip + len(digests) < total
    }


@router.get("/coach/workout-analysis/{workout_id}")
async def get_mobile_workout_analysis(workout_id: str, language: str = "en", user_id: str = "default"):
    """Get mobile-first workout analysis with coach summary and signals - 100% LOCAL ENGINE"""
    
    # Get all workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
    if not all_workouts:
        all_workouts = get_mock_workouts()
    
    # Find the workout
    workout = await db.workouts.find_one({"id": workout_id}, {"_id": 0})
    if not workout:
        workout = next((w for w in all_workouts if w["id"] == workout_id), None)
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    # Calculate baseline
    baseline = calculate_baseline_metrics(all_workouts, workout, days=14)
    
    # Calculate signal cards
    signals = calculate_mobile_signals(workout, baseline)
    
    # Build workout summary for AI with enriched data
    workout_summary = {
        "type": workout.get("type"),
        "distance_km": workout.get("distance_km"),
        "duration_min": workout.get("duration_minutes"),
        "moving_time_min": workout.get("moving_time_minutes"),
        "avg_hr": workout.get("avg_heart_rate"),
        "max_hr": workout.get("max_heart_rate"),
        "hr_zones": workout.get("effort_zone_distribution"),
        "avg_pace_min_km": workout.get("avg_pace_min_km"),
        "best_pace_min_km": workout.get("best_pace_min_km"),
        "pace_variability": workout.get("pace_stats", {}).get("pace_variability") if workout.get("pace_stats") else None,
        "avg_cadence_spm": workout.get("avg_cadence_spm"),
        "avg_speed_kmh": workout.get("avg_speed_kmh"),
        "max_speed_kmh": workout.get("max_speed_kmh"),
        "elevation_m": workout.get("elevation_gain_m")
    }
    
    baseline_summary = {
        "sessions": baseline.get("workout_count", 0) if baseline else 0,
        "avg_distance": baseline.get("avg_distance_km") if baseline else None,
        "avg_duration": baseline.get("avg_duration_min") if baseline else None,
        "avg_hr": baseline.get("avg_heart_rate") if baseline else None,
        "avg_pace": baseline.get("avg_pace") if baseline else None,
        "avg_cadence": baseline.get("avg_cadence") if baseline else None
    } if baseline else {}
    
    # Generate analysis using LOCAL ENGINE (NO LLM - Strava compliant)
    analysis = generate_session_analysis(workout, baseline, language)
    
    coach_summary = analysis["summary"]
    insight = analysis["meaning"]
    guidance = analysis["advice"]
    
    return MobileAnalysisResponse(
        workout_id=workout_id,
        coach_summary=coach_summary,
        intensity=signals["intensity"],
        load=signals["load"],
        session_type=signals["session_type"],
        insight=insight,
        guidance=guidance
    )


@router.get("/coach/detailed-analysis/{workout_id}")
async def get_detailed_analysis(workout_id: str, language: str = "en", user_id: str = "default"):
    """Get card-based detailed analysis for mobile view - 100% LOCAL ENGINE"""
    
    # Get all workouts
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
    if not all_workouts:
        all_workouts = get_mock_workouts()
    
    # Find the workout
    workout = await db.workouts.find_one({"id": workout_id}, {"_id": 0})
    if not workout:
        workout = next((w for w in all_workouts if w["id"] == workout_id), None)
    
    if not workout:
        raise HTTPException(status_code=404, detail="Workout not found")
    
    # Calculate baseline
    baseline = calculate_baseline_metrics(all_workouts, workout, days=14)
    
    # Generate analysis using LOCAL ENGINE (NO LLM)
    analysis = generate_session_analysis(workout, baseline, language)
    
    # Build header
    session_type = analysis.get("metrics", {}).get("session_type", "moderate")
    intensity_level = analysis.get("metrics", {}).get("intensity_level", "moderate")
    
    session_names = {
        "easy": "Sortie facile" if language == "fr" else "Easy Run",
        "moderate": "Sortie modérée" if language == "fr" else "Moderate Run",
        "hard": "Séance intense" if language == "fr" else "Hard Session",
        "very_hard": "Séance très intense" if language == "fr" else "Very Hard Session",
        "long": "Sortie longue" if language == "fr" else "Long Run",
        "short": "Sortie courte" if language == "fr" else "Short Run"
    }
    
    intensity_labels = {
        "easy": "Facile" if language == "fr" else "Easy",
        "moderate": "Modérée" if language == "fr" else "Moderate",
        "hard": "Soutenue" if language == "fr" else "Sustained",
        "very_hard": "Haute" if language == "fr" else "High"
    }
    
    # Calculate volume comparison
    distance = workout.get("distance_km", 0)
    avg_distance = baseline.get("avg_distance_km", distance) if baseline else distance
    
    if distance > avg_distance * 1.2:
        volume = "Plus long" if language == "fr" else "Longer"
    elif distance < avg_distance * 0.8:
        volume = "Plus court" if language == "fr" else "Shorter"
    else:
        volume = "Habituel" if language == "fr" else "Usual"
    
    # Check pace regularity
    pace_stats = workout.get("pace_stats", {})
    variability = pace_stats.get("pace_variability", 0) if pace_stats else 0
    regularity = "Variable" if variability > 0.5 else "Stable"
    
    header = {
        "context": analysis["summary"],
        "session_name": session_names.get(session_type, workout.get("name", "Séance"))
    }
    
    execution = {
        "intensity": intensity_labels.get(intensity_level, "Modérée"),
        "volume": volume,
        "regularity": regularity
    }
    
    meaning = {"text": analysis["meaning"]}
    recovery = {"text": analysis["recovery"]}
    advice = {"text": analysis["advice"]}
    
    # Build advanced comparisons
    comparison_parts = []
    zones = analysis.get("metrics", {}).get("zones", {})
    if zones:
        easy_pct = zones.get("easy", 0)
        hard_pct = zones.get("hard", 0)
        if language == "fr":
            comparison_parts.append(f"{easy_pct}% du temps en zone facile, {hard_pct}% en zone intense.")
        else:
            comparison_parts.append(f"{easy_pct}% time in easy zone, {hard_pct}% in hard zone.")
    
    if baseline and baseline.get("comparison"):
        hr_comp = baseline["comparison"].get("heart_rate_vs_baseline", {})
        if hr_comp:
            diff = hr_comp.get("difference_bpm", 0)
            if abs(diff) > 3:
                if language == "fr":
                    comparison_parts.append(f"FC {'+' if diff > 0 else ''}{diff:.0f} bpm vs baseline.")
                else:
                    comparison_parts.append(f"HR {'+' if diff > 0 else ''}{diff:.0f} bpm vs baseline.")
    
    advanced = {"comparisons": " ".join(comparison_parts) if comparison_parts else ""}
    
    logger.info(f"Detailed analysis generated (LOCAL) for workout {workout_id}")
    
    return DetailedAnalysisResponse(
        workout_id=workout_id,
        workout_name=workout.get("name", ""),
        workout_date=workout.get("date", ""),
        workout_type=workout.get("type", ""),
        header=header,
        execution=execution,
        meaning=meaning,
        recovery=recovery,
        advice=advice,
        advanced=advanced
    )
