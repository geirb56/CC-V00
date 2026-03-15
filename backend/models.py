import re
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict


class Workout(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str  # "run", "cycle", "swim"
    name: str
    date: str  # ISO date string
    duration_minutes: int
    distance_km: float
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_min_km: Optional[float] = None  # minutes per km
    avg_speed_kmh: Optional[float] = None
    elevation_gain_m: Optional[int] = None
    calories: Optional[int] = None
    effort_zone_distribution: Optional[dict] = None  # {"z1": 10, "z2": 25, ...}
    notes: Optional[str] = None
    data_source: Optional[str] = "manual"  # "manual", "garmin", etc.
    garmin_activity_id: Optional[str] = None  # For Garmin workouts
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorkoutCreate(BaseModel):
    type: str
    name: str
    date: str
    duration_minutes: int
    distance_km: float
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_min_km: Optional[float] = None
    avg_speed_kmh: Optional[float] = None
    elevation_gain_m: Optional[int] = None
    calories: Optional[int] = None
    effort_zone_distribution: Optional[dict] = None
    notes: Optional[str] = None
    data_source: Optional[str] = "manual"
    garmin_activity_id: Optional[str] = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"run", "cycle", "swim"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v < 0:
            raise ValueError("duration_minutes must be non-negative")
        return v

    @field_validator("distance_km")
    @classmethod
    def validate_distance(cls, v: float) -> float:
        if v < 0:
            raise ValueError("distance_km must be non-negative")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.split("T")[0])
        except (ValueError, AttributeError):
            raise ValueError("date must be a valid ISO date string (YYYY-MM-DD)")
        return v

    @field_validator("notes")
    @classmethod
    def sanitize_notes(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Strip HTML tags to prevent stored XSS
        v = re.sub(r"<[^>]+>", "", v)
        return v[:500]  # Cap length


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CoachRequest(BaseModel):
    message: str
    workout_id: Optional[str] = None
    context: Optional[str] = None  # Additional context like recent stats
    language: Optional[str] = "en"  # "en" or "fr"
    deep_analysis: Optional[bool] = False  # Trigger deep workout analysis
    user_id: Optional[str] = "default"  # For memory persistence


class CoachResponse(BaseModel):
    response: str
    message_id: str


class GuidanceRequest(BaseModel):
    language: Optional[str] = "en"
    user_id: Optional[str] = "default"


class GuidanceResponse(BaseModel):
    status: str  # "maintain", "adjust", "hold_steady"
    guidance: str
    generated_at: str


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    role: str  # "user" or "assistant"
    content: str
    workout_id: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TrainingStats(BaseModel):
    total_workouts: int
    total_distance_km: float
    total_duration_minutes: int
    avg_heart_rate: Optional[float] = None
    workouts_by_type: dict
    weekly_summary: List[dict]


# ========== GARMIN INTEGRATION MODELS ==========

class GarminConnectionStatus(BaseModel):
    connected: bool
    last_sync: Optional[str] = None
    workout_count: int = 0


class GarminSyncResult(BaseModel):
    success: bool
    synced_count: int
    message: str


class VMAEstimationResponse(BaseModel):
    has_sufficient_data: bool
    confidence: str  # "high", "medium", "low", "insufficient"
    confidence_score: int  # 1-5 (5 = very confident)
    vma_kmh: Optional[float] = None
    vo2max: Optional[float] = None
    data_source: Optional[str] = None
    training_zones: Optional[dict] = None
    message: str
    recommendations: Optional[List[str]] = None


class UserGoal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    event_name: str
    event_date: str  # ISO date string
    distance_type: str  # 5k, 10k, semi, marathon, ultra
    distance_km: float  # Actual distance in km
    target_time_minutes: Optional[int] = None  # Target time in minutes
    target_pace: Optional[str] = None  # Calculated pace min/km
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UserGoalCreate(BaseModel):
    event_name: str
    event_date: str
    distance_type: str  # 5k, 10k, semi, marathon, ultra
    target_time_minutes: Optional[int] = None  # Target time in minutes


class DashboardInsightResponse(BaseModel):
    coach_insight: str
    week: dict
    month: dict
    recovery_score: Optional[dict] = None  # New: recovery score


class WeeklyReviewResponse(BaseModel):
    period_start: str
    period_end: str
    coach_summary: str  # 1 phrase max - CARTE 1
    coach_reading: str  # 2-3 phrases - CARTE 4
    recommendations: List[str]  # 1-2 actions - CARTE 5
    recommendations_followup: Optional[str] = None  # Feedback on last week's recommendations
    metrics: dict  # CARTE 3
    comparison: dict  # vs semaine precedente
    signals: List[dict]  # CARTE 2
    user_goal: Optional[dict] = None  # User's event goal
    generated_at: str


class StravaConnectionStatus(BaseModel):
    connected: bool
    last_sync: Optional[str] = None
    workout_count: int = 0


class StravaSyncResult(BaseModel):
    success: bool
    synced_count: int
    message: str


class WebhookSubscriptionRequest(BaseModel):
    callback_url: str


class WebhookSubscriptionResponse(BaseModel):
    success: bool
    subscription_id: Optional[int] = None
    message: str


class SubscriptionStatusResponse(BaseModel):
    tier: str = "free"
    tier_name: str = "Gratuit"
    is_premium: bool = False
    subscription_id: Optional[str] = None
    billing_period: Optional[str] = None  # "monthly" or "annual"
    expires_at: Optional[str] = None
    messages_used: int = 0
    messages_limit: int = 10
    messages_remaining: int = 10
    is_unlimited: bool = False


class CreateCheckoutRequest(BaseModel):
    origin_url: str
    tier: str = "starter"  # starter, confort, pro
    billing_period: str = "monthly"  # monthly, annual


class CreateCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default"
    use_local_llm: bool = False  # True if using WebLLM on client
    language: Optional[str] = "en"  # Response language: "en" or "fr"


class ChatResponse(BaseModel):
    response: str
    message_id: str
    messages_remaining: int
    messages_limit: int
    is_unlimited: bool = False
    suggestions: List[str] = []  # Suggested follow-up questions
    category: str = ""  # Detected intent category


class ChatHistoryItem(BaseModel):
    id: str
    role: str
    content: str
    timestamp: str


class SubscriptionTierInfo(BaseModel):
    id: str
    name: str
    price_monthly: float
    price_annual: float
    messages_limit: int
    unlimited: bool = False
    description: str


# ========== TRAINING MODELS ==========

class TrainingGoalRequest(BaseModel):
    goal_type: str = Field(..., description="Type d'objectif: 5K, 10K, SEMI, MARATHON, ULTRA")
    event_date: str = Field(..., description="Date de l'événement (YYYY-MM-DD)")
    event_name: Optional[str] = Field(None, description="Nom de la course")

class TrainingGoalResponse(BaseModel):
    success: bool
    goal_type: str
    event_name: Optional[str]
    event_date: str
    cycle_weeks: int
    current_week: int
    phase: str
    phase_info: dict

class TrainingPlanResponse(BaseModel):
    goal: Optional[dict]
    current_week: int
    total_weeks: int
    phase: str
    phase_info: dict
    recommendation: dict
    context: dict
    days_until_event: Optional[int]


class MobileAnalysisResponse(BaseModel):
    workout_id: str
    coach_summary: str
    intensity: dict
    load: dict
    session_type: dict
    insight: Optional[str] = None
    guidance: Optional[str] = None


class DetailedAnalysisResponse(BaseModel):
    workout_id: str
    workout_name: str
    workout_date: str
    workout_type: str
    header: dict
    execution: dict
    meaning: dict
    recovery: dict
    advice: dict
    advanced: Optional[dict] = None


# ========== SUBSCRIPTION SYSTEM (Early Adopter) ==========

class SubscriptionInfo(BaseModel):
    """Informations d'abonnement utilisateur"""
    user_id: str
    status: str  # trial, free, early_adopter, premium
    display: Dict
    features: Dict
    trial_days_remaining: Optional[int] = None
    price_locked: Optional[float] = None
    stripe_customer_id: Optional[str] = None


class ActivateSubscriptionRequest(BaseModel):
    """Requête pour activer un abonnement"""
    user_id: str = "default"
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
