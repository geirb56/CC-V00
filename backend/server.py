from fastapi import FastAPI, APIRouter, HTTPException, Query, Request, Depends, Header
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import logging
import random
import secrets
import hashlib
import base64
import httpx
import time
from collections import defaultdict
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone, timedelta

# Import the analysis engine (NO LLM dependencies)
from analysis_engine import (
    generate_session_analysis,
    generate_weekly_review,
    generate_dashboard_insight,
    calculate_intensity_level,
    format_duration,
    format_pace
)

# Import the chat engine (NO LLM dependencies)
from chat_engine import (
    generate_chat_response,
    check_message_limit,
    get_remaining_messages
)

# Import LLM coach module (GPT-4o-mini)
from llm_coach import LLM_MODEL, LLM_PROVIDER, generate_cycle_week

# Import coach service (stratégie cascade)
from coach_service import (
    analyze_workout as coach_analyze_workout,
    weekly_review as coach_weekly_review,
    chat_response as coach_chat_response,
    generate_dynamic_training_plan,
    get_cache_stats,
    clear_cache,
    get_metrics as get_coach_metrics,
    reset_metrics as reset_coach_metrics
)

# Import RAG engine for enriched analyses
from rag_engine import (
    generate_dashboard_rag,
    generate_weekly_review_rag,
    generate_workout_analysis_rag
)

# Import training engine for periodization
from training_engine import (
    GOAL_CONFIG,
    compute_week_number,
    compute_acwr,
    determine_phase,
    get_phase_description,
    build_training_context,
    generate_week_recommendation
)

# Import Stripe integration
from emergentintegrations.payments.stripe.checkout import (
    StripeCheckout, 
    CheckoutSessionResponse, 
    CheckoutStatusResponse, 
    CheckoutSessionRequest
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Stripe configuration
STRIPE_API_KEY = os.environ.get('STRIPE_API_KEY', '')

# Subscription tiers configuration
SUBSCRIPTION_TIERS = {
    "free": {
        "name": "Gratuit",
        "price_monthly": 0,
        "price_annual": 0,
        "messages_limit": 10,
        "description": "Découverte"
    },
    "starter": {
        "name": "Starter",
        "price_monthly": 4.99,
        "price_annual": 49.99,
        "messages_limit": 25,
        "description": "Pour débuter"
    },
    "confort": {
        "name": "Confort",
        "price_monthly": 5.99,
        "price_annual": 59.99,
        "messages_limit": 50,
        "description": "Usage régulier"
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 9.99,
        "price_annual": 99.99,
        "messages_limit": 150,  # Soft limit (fair-use)
        "unlimited": True,
        "description": "Illimité"
    }
}

def get_message_limit(tier: str) -> int:
    """Get message limit for a subscription tier"""
    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS["free"])
    return tier_config.get("messages_limit", 10)

# Garmin OAuth Configuration (placeholder - replace with real credentials)
GARMIN_CLIENT_ID = os.environ.get('GARMIN_CLIENT_ID', '')
GARMIN_CLIENT_SECRET = os.environ.get('GARMIN_CLIENT_SECRET', '')
GARMIN_REDIRECT_URI = os.environ.get('GARMIN_REDIRECT_URI', '')

# Strava OAuth Configuration
STRAVA_CLIENT_ID = os.environ.get('STRAVA_CLIENT_ID', '')
STRAVA_CLIENT_SECRET = os.environ.get('STRAVA_CLIENT_SECRET', '')
STRAVA_REDIRECT_URI = os.environ.get('STRAVA_REDIRECT_URI', '')

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Create the main app
app = FastAPI()

# GZip compression for responses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ========== RATE LIMITER ==========

class RateLimiter:
    """Simple in-memory rate limiter"""

    def __init__(self, requests_per_minute: int = 60, burst_limit: int = 10):
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self._last_global_cleanup: float = time.time()

    def _cleanup(self, user_id: str) -> None:
        """Remove old requests outside the window for this user"""
        now = time.time()
        cutoff = now - 60  # 1 minute window
        self.requests[user_id] = [t for t in self.requests[user_id] if t > cutoff]
        # Remove the key entirely when empty to prevent unbounded growth
        if not self.requests[user_id]:
            del self.requests[user_id]

    def _global_cleanup(self) -> None:
        """Periodically purge stale user entries (every 5 minutes)"""
        now = time.time()
        if now - self._last_global_cleanup < 300:
            return
        self._last_global_cleanup = now
        cutoff = now - 60
        stale = [uid for uid, ts in self.requests.items() if not ts or ts[-1] <= cutoff]
        for uid in stale:
            del self.requests[uid]

    def is_limited(self, user_id: str) -> bool:
        """Check if user is rate limited"""
        self._global_cleanup()
        self._cleanup(user_id)

        now = time.time()
        recent = self.requests.get(user_id, [])

        # Check burst (10 requests in last 2 seconds)
        burst_cutoff = now - 2
        burst_count = sum(1 for t in recent if t > burst_cutoff)
        if burst_count >= self.burst_limit:
            return True

        # Check rate (60 requests per minute)
        if len(recent) >= self.requests_per_minute:
            return True

        return False

    def record(self, user_id: str) -> None:
        """Record a request"""
        self.requests[user_id].append(time.time())

    def get_stats(self, user_id: str) -> dict:
        """Get rate limit stats for user"""
        self._cleanup(user_id)
        recent = self.requests.get(user_id, [])
        return {
            "requests_last_minute": len(recent),
            "limit": self.requests_per_minute,
            "remaining": max(0, self.requests_per_minute - len(recent))
        }


# Initialize rate limiter
rate_limiter = RateLimiter(requests_per_minute=60, burst_limit=10)

# Endpoints exempt from rate limiting
RATE_LIMIT_EXEMPT = {"/api/cache/stats", "/api/strava/callback", "/api/webhooks/strava"}


def get_user_id_from_request(request: Request) -> str:
    """Extract user_id from request"""
    # Try query param first
    user_id = request.query_params.get("user_id")
    if user_id:
        return user_id
    
    # Fallback to IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ========== AUTH DEPENDENCY ==========

security = HTTPBearer(auto_error=False)

async def auth_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
) -> dict:
    """
    Dépendance d'authentification flexible.
    
    Ordre de priorité:
    1. Bearer token (JWT à implémenter)
    2. Header X-User-Id
    3. Query param user_id
    4. Fallback "default"
    """
    user_id = None
    
    # 1. Bearer token (placeholder pour JWT)
    if credentials and credentials.credentials:
        token = credentials.credentials
        # TODO: Valider JWT et extraire user_id
        # Pour l'instant, on utilise le token comme user_id si pas de JWT
        if token.startswith("user_"):
            user_id = token
    
    # 2. Header X-User-Id
    if not user_id and x_user_id:
        user_id = x_user_id
    
    # 3. Query param
    if not user_id:
        user_id = request.query_params.get("user_id")
    
    # 4. Fallback
    if not user_id:
        user_id = "default"
    
    return {"id": user_id, "authenticated": bool(credentials)}


async def auth_user_optional(request: Request) -> dict:
    """Version optionnelle - ne lève jamais d'erreur"""
    user_id = request.query_params.get("user_id", "default")
    return {"id": user_id, "authenticated": False}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware"""
    # Skip exempt endpoints
    if request.url.path in RATE_LIMIT_EXEMPT:
        return await call_next(request)
    
    # Skip non-API requests
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    
    user_id = get_user_id_from_request(request)
    
    if rate_limiter.is_limited(user_id):
        logger.warning(f"[RateLimit] User {user_id} exceeded rate limit")
        return JSONResponse(
            status_code=429,
            content={
                "error": "Too many requests",
                "retry_after": 60,
                **rate_limiter.get_stats(user_id)
            }
        )
    
    rate_limiter.record(user_id)
    return await call_next(request)


# ========== MODELS ==========

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


# OAuth state stores backed by MongoDB for cross-process reliability


# ========== GARMIN OAUTH HELPERS ==========

def generate_pkce_pair() -> tuple:
    """Generate PKCE code verifier and code challenge"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge


def get_garmin_auth_url(code_challenge: str, state: str) -> str:
    """Generate Garmin Connect authorization URL"""
    params = {
        "client_id": GARMIN_CLIENT_ID,
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": GARMIN_REDIRECT_URI,
        "state": state,
        "scope": "activity_export"
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://connect.garmin.com/oauthConfirm?{query}"


async def exchange_garmin_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://connectapi.garmin.com/oauth-service/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": GARMIN_CLIENT_ID,
                "client_secret": GARMIN_CLIENT_SECRET,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": GARMIN_REDIRECT_URI
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        return response.json()


async def fetch_garmin_activities(access_token: str, start_date: str = None) -> list:
    """Fetch activities from Garmin Connect API"""
    async with httpx.AsyncClient() as client:
        params = {"limit": 100}
        if start_date:
            params["start"] = start_date
        
        response = await client.get(
            "https://apis.garmin.com/wellness-api/rest/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params
        )
        response.raise_for_status()
        return response.json()


def convert_garmin_to_workout(garmin_activity: dict, user_id: str = "default") -> dict:
    """Convert Garmin activity to CardioCoach workout format"""
    # Map Garmin activity types to our types
    activity_type_map = {
        "running": "run",
        "cycling": "cycle",
        "indoor_cycling": "cycle",
        "trail_running": "run",
        "treadmill_running": "run",
        "virtual_ride": "cycle",
        "road_biking": "cycle",
        "mountain_biking": "cycle",
    }
    
    garmin_type = garmin_activity.get("activityType", "").lower()
    workout_type = activity_type_map.get(garmin_type, None)
    
    # Only import running and cycling
    if not workout_type:
        return None
    
    # Extract metrics with graceful fallback for missing data
    duration_seconds = garmin_activity.get("duration", 0)
    distance_meters = garmin_activity.get("distance", 0)
    avg_hr = garmin_activity.get("averageHR")
    max_hr = garmin_activity.get("maxHR")
    calories = garmin_activity.get("calories")
    elevation = garmin_activity.get("elevationGain")
    
    # Calculate pace/speed
    avg_pace = None
    avg_speed = None
    if distance_meters and duration_seconds:
        if workout_type == "run":
            # Pace in min/km
            avg_pace = (duration_seconds / 60) / (distance_meters / 1000) if distance_meters > 0 else None
        else:
            # Speed in km/h
            avg_speed = (distance_meters / 1000) / (duration_seconds / 3600) if duration_seconds > 0 else None
    
    # Extract heart rate zones if available
    hr_zones = garmin_activity.get("heartRateZones")
    effort_distribution = None
    if hr_zones and isinstance(hr_zones, list) and len(hr_zones) >= 5:
        total_time = sum(z.get("secsInZone", 0) for z in hr_zones[:5])
        if total_time > 0:
            effort_distribution = {
                f"z{i+1}": round((hr_zones[i].get("secsInZone", 0) / total_time) * 100)
                for i in range(5)
            }
    
    # Build workout object
    start_time = garmin_activity.get("startTimeLocal") or garmin_activity.get("startTimeGMT")
    if start_time:
        try:
            if isinstance(start_time, (int, float)):
                date_obj = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)
            else:
                date_obj = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            date_str = date_obj.strftime("%Y-%m-%d")
        except (ValueError, TypeError, AttributeError):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build workout object
    workout = {
        "id": f"garmin_{garmin_activity.get('activityId', uuid.uuid4())}",
        "type": workout_type,
        "name": garmin_activity.get("activityName", f"{workout_type.title()} Workout"),
        "date": date_str,
        "duration_minutes": round(duration_seconds / 60) if duration_seconds else 0,
        "distance_km": round(distance_meters / 1000, 2) if distance_meters else 0,
        "data_source": "garmin",
        "garmin_activity_id": str(garmin_activity.get("activityId")),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Add optional fields only if present (graceful handling)
    if avg_hr:
        workout["avg_heart_rate"] = int(avg_hr)
    if max_hr:
        workout["max_heart_rate"] = int(max_hr)
    if avg_pace:
        workout["avg_pace_min_km"] = round(avg_pace, 2)
    if avg_speed:
        workout["avg_speed_kmh"] = round(avg_speed, 1)
    if calories:
        workout["calories"] = int(calories)
    if elevation:
        workout["elevation_gain_m"] = int(elevation)
    if effort_distribution:
        workout["effort_zone_distribution"] = effort_distribution
    
    return workout


# ========== STRAVA INTEGRATION HELPERS ==========

async def exchange_strava_code(code: str) -> dict:
    """Exchange authorization code for Strava access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/api/v3/oauth/token",
            data={
                "client_id": STRAVA_CLIENT_ID,
                "client_secret": STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code"
            }
        )
        response.raise_for_status()
        return response.json()


async def refresh_strava_token(refresh_token: str) -> dict:
    """Refresh Strava access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/api/v3/oauth/token",
            data={
                "client_id": STRAVA_CLIENT_ID,
                "client_secret": STRAVA_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
        )
        response.raise_for_status()
        return response.json()


async def fetch_strava_activities(access_token: str, per_page: int = 100, max_pages: int = 3) -> list:
    """Fetch activities from Strava API (up to max_pages * per_page activities)"""
    all_activities = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, max_pages + 1):
            response = await client.get(
                "https://www.strava.com/api/v3/athlete/activities",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"per_page": per_page, "page": page}
            )
            response.raise_for_status()
            activities = response.json()
            
            if not activities:
                break  # No more activities
            
            all_activities.extend(activities)
            
            if len(activities) < per_page:
                break  # Last page
    
    logger.info(f"Fetched {len(all_activities)} activities from Strava")
    return all_activities


async def fetch_strava_activity_streams(access_token: str, activity_id: str) -> dict:
    """Fetch detailed streams (HR, pace, cadence) for a specific activity"""
    streams_data = {}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch HR, velocity, cadence, altitude streams
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "keys": "heartrate,velocity_smooth,cadence,altitude,time,distance,grade_smooth",
                    "key_by_type": "true"
                }
            )
            
            if response.status_code == 200:
                streams = response.json()
                streams_data = streams
            else:
                logger.warning(f"Failed to fetch streams for activity {activity_id}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error fetching streams for activity {activity_id}: {e}")
    
    return streams_data


async def fetch_strava_activity_laps(access_token: str, activity_id: str) -> list:
    """Fetch lap data for a specific activity (splits per km)"""
    laps_data = []
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}/laps",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 200:
                laps_data = response.json()
            else:
                logger.warning(f"Failed to fetch laps for activity {activity_id}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error fetching laps for activity {activity_id}: {e}")
    
    return laps_data


def process_strava_laps(laps: list) -> list:
    """Convert Strava laps to anonymized split data"""
    splits = []
    for i, lap in enumerate(laps, 1):
        distance_km = lap.get("distance", 0) / 1000
        elapsed_time = lap.get("elapsed_time", 0)  # seconds
        moving_time = lap.get("moving_time", elapsed_time)
        avg_speed = lap.get("average_speed", 0)  # m/s
        avg_hr = lap.get("average_heartrate")
        max_hr = lap.get("max_heartrate")
        avg_cadence = lap.get("average_cadence")
        elevation_gain = lap.get("total_elevation_gain", 0)
        
        # Calculate pace min/km
        if avg_speed > 0:
            pace_min_km = (1000 / avg_speed) / 60
            pace_str = f"{int(pace_min_km)}:{int((pace_min_km % 1) * 60):02d}"
        else:
            pace_min_km = None
            pace_str = "N/A"
        
        splits.append({
            "lap_num": i,
            "distance_km": round(distance_km, 2),
            "elapsed_time_sec": elapsed_time,
            "moving_time_sec": moving_time,
            "pace_min_km": round(pace_min_km, 2) if pace_min_km else None,
            "pace_str": pace_str,
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "avg_cadence": int(avg_cadence * 2) if avg_cadence else None,  # Strava returns half cadence
            "elevation_gain": elevation_gain
        })
    
    return splits


def process_strava_streams(streams_data: dict, distance_km: float) -> dict:
    """Process streams into per-km detailed data"""
    detailed_data = {
        "hr_data": [],
        "cadence_data": [],
        "pace_data": [],
        "altitude_data": [],
        "km_splits": []
    }
    
    if not streams_data:
        return detailed_data
    
    # Extract raw streams
    hr_stream = streams_data.get("heartrate", {}).get("data", [])
    cadence_stream = streams_data.get("cadence", {}).get("data", [])
    velocity_stream = streams_data.get("velocity_smooth", {}).get("data", [])
    altitude_stream = streams_data.get("altitude", {}).get("data", [])
    distance_stream = streams_data.get("distance", {}).get("data", [])
    time_stream = streams_data.get("time", {}).get("data", [])
    
    # Store raw data (sampled for storage efficiency)
    sample_rate = max(1, len(hr_stream) // 200)  # Max 200 points
    detailed_data["hr_data"] = hr_stream[::sample_rate] if hr_stream else []
    detailed_data["cadence_data"] = [c * 2 if c else None for c in cadence_stream[::sample_rate]] if cadence_stream else []
    detailed_data["altitude_data"] = altitude_stream[::sample_rate] if altitude_stream else []
    
    # Convert velocity to pace (min/km)
    if velocity_stream:
        pace_data = []
        for v in velocity_stream[::sample_rate]:
            if v and v > 0:
                pace_min_km = (1000 / v) / 60
                pace_data.append(round(pace_min_km, 2))
            else:
                pace_data.append(None)
        detailed_data["pace_data"] = pace_data
    
    # Calculate per-km splits from streams
    if distance_stream and time_stream and velocity_stream:
        km_splits = []
        current_km = 1
        km_start_idx = 0
        
        for i, dist in enumerate(distance_stream):
            dist_km = dist / 1000
            if dist_km >= current_km:
                # Calculate stats for this km
                km_hr = hr_stream[km_start_idx:i] if hr_stream else []
                km_cadence = cadence_stream[km_start_idx:i] if cadence_stream else []
                km_velocity = velocity_stream[km_start_idx:i] if velocity_stream else []
                km_time = time_stream[i] - time_stream[km_start_idx] if time_stream else 0
                
                avg_hr = sum([h for h in km_hr if h]) / len([h for h in km_hr if h]) if km_hr else None
                avg_cadence = sum([c for c in km_cadence if c]) / len([c for c in km_cadence if c]) if km_cadence else None
                avg_velocity = sum([v for v in km_velocity if v]) / len([v for v in km_velocity if v]) if km_velocity else None
                
                if avg_velocity and avg_velocity > 0:
                    pace_min_km = (1000 / avg_velocity) / 60
                    pace_str = f"{int(pace_min_km)}:{int((pace_min_km % 1) * 60):02d}"
                else:
                    pace_min_km = None
                    pace_str = "N/A"
                
                km_splits.append({
                    "km": current_km,
                    "time_sec": km_time,
                    "pace_min_km": round(pace_min_km, 2) if pace_min_km else None,
                    "pace_str": pace_str,
                    "avg_hr": round(avg_hr) if avg_hr else None,
                    "avg_cadence": round(avg_cadence * 2) if avg_cadence else None,
                })
                
                current_km += 1
                km_start_idx = i
        
        detailed_data["km_splits"] = km_splits
    
    return detailed_data


async def fetch_strava_activity_zones(access_token: str, activity_id: str) -> dict:
    """Fetch heart rate zones distribution for a specific activity"""
    zones_data = {}
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}/zones",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if response.status_code == 200:
                zones = response.json()
                zones_data = zones
            else:
                logger.warning(f"Failed to fetch zones for activity {activity_id}: {response.status_code}")
    except Exception as e:
        logger.warning(f"Error fetching zones for activity {activity_id}: {e}")
    
    return zones_data


def calculate_hr_zones_from_stream(hr_stream: list, max_hr: int = None) -> dict:
    """Calculate time spent in each HR zone from stream data"""
    if not hr_stream or not max_hr:
        return None
    
    # Standard 5-zone model based on % of max HR
    # Z1: 50-60%, Z2: 60-70%, Z3: 70-80%, Z4: 80-90%, Z5: 90-100%
    zone_thresholds = [
        (0.50, 0.60, "z1"),
        (0.60, 0.70, "z2"),
        (0.70, 0.80, "z3"),
        (0.80, 0.90, "z4"),
        (0.90, 1.00, "z5"),
    ]
    
    zone_counts = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    total_points = len(hr_stream)
    
    for hr in hr_stream:
        if hr is None:
            continue
        hr_pct = hr / max_hr
        
        for low, high, zone in zone_thresholds:
            if low <= hr_pct < high:
                zone_counts[zone] += 1
                break
        else:
            # Above 100% max HR
            if hr_pct >= 1.0:
                zone_counts["z5"] += 1
    
    # Convert to percentages
    if total_points > 0:
        zone_distribution = {
            zone: round((count / total_points) * 100)
            for zone, count in zone_counts.items()
        }
    else:
        zone_distribution = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    
    return zone_distribution


def calculate_pace_stats_from_stream(velocity_stream: list, time_stream: list = None) -> dict:
    """Calculate detailed pace statistics from velocity stream (for running)"""
    if not velocity_stream:
        return None
    
    # Filter out zero/null values
    valid_velocities = [v for v in velocity_stream if v and v > 0]
    
    if not valid_velocities:
        return None
    
    # Convert m/s to min/km
    def ms_to_pace(v):
        if v <= 0:
            return None
        km_per_sec = v / 1000
        if km_per_sec <= 0:
            return None
        return 1 / (km_per_sec * 60)  # min/km
    
    paces = [ms_to_pace(v) for v in valid_velocities if ms_to_pace(v)]
    
    if not paces:
        return None
    
    avg_pace = sum(paces) / len(paces)
    min_pace = min(paces)  # Fastest
    max_pace = max(paces)  # Slowest
    
    # Calculate pace variability (standard deviation)
    variance = sum((p - avg_pace) ** 2 for p in paces) / len(paces)
    std_dev = variance ** 0.5
    
    return {
        "avg_pace_min_km": round(avg_pace, 2),
        "best_pace_min_km": round(min_pace, 2),
        "slowest_pace_min_km": round(max_pace, 2),
        "pace_variability": round(std_dev, 2)
    }


def convert_strava_to_workout(strava_activity: dict, streams_data: dict = None, zones_data: dict = None) -> dict:
    """Convert Strava activity to CardioCoach workout format with detailed HR and pace data"""
    # Map Strava activity types to our types
    activity_type_map = {
        "run": "run",
        "ride": "cycle",
        "virtualrun": "run",
        "virtualride": "cycle",
        "trailrun": "run",
        "mountainbikeride": "cycle",
        "gravelride": "cycle",
        "ebikeride": "cycle",
    }
    
    strava_type = strava_activity.get("type", "").lower()
    workout_type = activity_type_map.get(strava_type, None)
    
    # Only import running and cycling
    if not workout_type:
        return None
    
    # Extract metrics with graceful fallback for missing data
    elapsed_time = strava_activity.get("elapsed_time", 0)  # in seconds
    moving_time = strava_activity.get("moving_time", elapsed_time)  # in seconds
    distance = strava_activity.get("distance", 0)  # in meters
    avg_hr = strava_activity.get("average_heartrate")
    max_hr = strava_activity.get("max_heartrate")
    elevation = strava_activity.get("total_elevation_gain")
    calories = strava_activity.get("calories")
    avg_speed = strava_activity.get("average_speed", 0)  # in m/s
    max_speed = strava_activity.get("max_speed", 0)  # in m/s
    avg_cadence = strava_activity.get("average_cadence")
    
    # Calculate pace (for runs) or speed (for rides)
    avg_pace_min_km = None
    best_pace_min_km = None
    avg_speed_kmh = None
    max_speed_kmh = None
    
    if avg_speed and avg_speed > 0:
        if workout_type == "run":
            # Convert m/s to min/km
            speed_km_per_min = (avg_speed * 60) / 1000
            if speed_km_per_min > 0:
                avg_pace_min_km = round(1 / speed_km_per_min, 2)
            # Best pace from max speed
            if max_speed and max_speed > 0:
                max_speed_km_per_min = (max_speed * 60) / 1000
                if max_speed_km_per_min > 0:
                    best_pace_min_km = round(1 / max_speed_km_per_min, 2)
        else:
            # Convert m/s to km/h
            avg_speed_kmh = round(avg_speed * 3.6, 1)
            if max_speed:
                max_speed_kmh = round(max_speed * 3.6, 1)
    
    # Parse start time
    start_date = strava_activity.get("start_date_local") or strava_activity.get("start_date")
    if start_date:
        try:
            date_obj = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            date_str = date_obj.strftime("%Y-%m-%d")
        except (ValueError, TypeError, AttributeError):
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Build workout object
    workout = {
        "id": f"strava_{strava_activity.get('id', uuid.uuid4())}",
        "type": workout_type,
        "name": strava_activity.get("name", f"{workout_type.title()} Workout"),
        "date": date_str,
        "duration_minutes": round(elapsed_time / 60) if elapsed_time else 0,
        "moving_time_minutes": round(moving_time / 60) if moving_time else 0,
        "distance_km": round(distance / 1000, 2) if distance else 0,
        "data_source": "strava",
        "strava_activity_id": str(strava_activity.get("id")),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Heart rate data
    if avg_hr:
        workout["avg_heart_rate"] = int(avg_hr)
    if max_hr:
        workout["max_heart_rate"] = int(max_hr)
    
    # Calculate HR zones - PRIORITY: Use Strava's zone data first (uses athlete's configured max HR)
    # Fallback to our calculation if Strava zones not available
    hr_zones = None
    
    # 1. First try Strava's own zone distribution (most accurate, uses athlete settings)
    if zones_data:
        for zone_info in zones_data:
            if zone_info.get("type") == "heartrate":
                distribution_buckets = zone_info.get("distribution_buckets", [])
                if distribution_buckets:
                    total_time = sum(b.get("time", 0) for b in distribution_buckets)
                    if total_time > 0:
                        hr_zones = {}
                        for i, bucket in enumerate(distribution_buckets[:5]):
                            zone_key = f"z{i+1}"
                            hr_zones[zone_key] = round((bucket.get("time", 0) / total_time) * 100)
                        logger.debug(f"Using Strava zones for {workout.get('name', 'workout')}")
    
    # 2. Fallback: Calculate from HR stream using estimated max HR (220 - age, default 185)
    if not hr_zones and streams_data and "heartrate" in streams_data:
        hr_stream = streams_data["heartrate"].get("data", [])
        if hr_stream:
            # Use athlete's theoretical max HR (not session max!)
            # Default to 185 bpm if not configured (typical for ~35 year old)
            athlete_max_hr = 185  # TODO: Get from user settings
            hr_zones = calculate_hr_zones_from_stream(hr_stream, athlete_max_hr)
            logger.debug(f"Calculated zones from stream for {workout.get('name', 'workout')}")
    
    if hr_zones:
        workout["effort_zone_distribution"] = hr_zones
    
    # Pace data (running)
    if workout_type == "run":
        if avg_pace_min_km:
            workout["avg_pace_min_km"] = avg_pace_min_km
        if best_pace_min_km:
            workout["best_pace_min_km"] = best_pace_min_km
        
        # Detailed pace stats from streams
        if streams_data and "velocity_smooth" in streams_data:
            velocity_stream = streams_data["velocity_smooth"].get("data", [])
            pace_stats = calculate_pace_stats_from_stream(velocity_stream)
            if pace_stats:
                workout["pace_stats"] = pace_stats
        
        # Cadence (steps per minute, Strava gives half - one foot)
        if avg_cadence:
            workout["avg_cadence_spm"] = int(avg_cadence * 2)  # Convert to full steps
    
    # Speed data (cycling)
    if workout_type == "cycle":
        if avg_speed_kmh:
            workout["avg_speed_kmh"] = avg_speed_kmh
        if max_speed_kmh:
            workout["max_speed_kmh"] = max_speed_kmh
        if avg_cadence:
            workout["avg_cadence_rpm"] = int(avg_cadence)
    
    # Elevation and calories
    if calories:
        workout["calories"] = int(calories)
    if elevation:
        workout["elevation_gain_m"] = int(elevation)
    
    return workout


def enrich_workout_with_detailed_data(workout: dict, streams_data: dict, laps_data: list) -> dict:
    """Enrich workout with detailed Strava data (splits, HR/cadence/pace per km)"""
    if not workout:
        return workout
    
    distance_km = workout.get("distance_km", 0)
    expected_km_count = int(distance_km) + (1 if distance_km % 1 > 0.3 else 0)  # Ex: 6.7km = 7 splits
    
    # Process streams FIRST to get accurate km_splits
    km_splits = []
    if streams_data:
        detailed = process_strava_streams(streams_data, distance_km)
        
        # Store km splits from streams (accurate per-km data)
        if detailed.get("km_splits"):
            km_splits = detailed["km_splits"]
            workout["km_splits"] = km_splits
        
        # Store sampled data for RAG retrieval
        if detailed.get("hr_data"):
            workout["hr_stream_sample"] = detailed["hr_data"][:50]  # First 50 points
            # HR analysis
            hr_data = [h for h in detailed["hr_data"] if h]
            if hr_data:
                workout["hr_analysis"] = {
                    "min_hr": min(hr_data),
                    "max_hr": max(hr_data),
                    "avg_hr": round(sum(hr_data) / len(hr_data)),
                    "hr_drift": round(sum(hr_data[-10:]) / 10 - sum(hr_data[:10]) / 10) if len(hr_data) >= 20 else 0,
                }
        
        if detailed.get("cadence_data"):
            workout["cadence_stream_sample"] = detailed["cadence_data"][:50]
            cadence_data = [c for c in detailed["cadence_data"] if c]
            if cadence_data:
                workout["cadence_analysis"] = {
                    "min_cadence": min(cadence_data),
                    "max_cadence": max(cadence_data),
                    "avg_cadence": round(sum(cadence_data) / len(cadence_data)),
                    "cadence_stability": round(100 - (max(cadence_data) - min(cadence_data)) / 2, 1),
                }
        
        if detailed.get("altitude_data"):
            alt_data = [a for a in detailed["altitude_data"] if a is not None]
            if alt_data:
                workout["elevation_analysis"] = {
                    "min_altitude": round(min(alt_data)),
                    "max_altitude": round(max(alt_data)),
                    "total_climb": round(sum(max(0, alt_data[i] - alt_data[i-1]) for i in range(1, len(alt_data)))),
                    "total_descent": round(sum(max(0, alt_data[i-1] - alt_data[i]) for i in range(1, len(alt_data)))),
                }
    
    # Use km_splits for split analysis (accurate per-km) OR fall back to laps if close to expected
    use_km_splits = len(km_splits) > 0 and abs(len(km_splits) - expected_km_count) <= 2
    
    if use_km_splits:
        # Use km_splits from streams (more accurate)
        splits = []
        for i, ks in enumerate(km_splits):
            splits.append({
                "lap_num": i + 1,
                "pace_min_km": ks.get("pace_min", 0),
                "pace_str": ks.get("pace_str", "N/A"),
                "avg_hr": ks.get("avg_hr"),
                "avg_cadence": ks.get("avg_cadence"),
            })
        workout["splits"] = splits
        
        # Analyze km splits
        paces = [s["pace_min_km"] for s in splits if s.get("pace_min_km") and s["pace_min_km"] > 0]
        if paces:
            fastest_split = min(paces)
            slowest_split = max(paces)
            
            # Find fastest and slowest km
            fastest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == fastest_split), None)
            slowest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == slowest_split), None)
            
            workout["split_analysis"] = {
                "fastest_split_pace": round(fastest_split, 2),
                "slowest_split_pace": round(slowest_split, 2),
                "fastest_km": fastest_km,
                "slowest_km": slowest_km,
                "pace_drop": round(slowest_split - fastest_split, 2),
                "consistency_score": round(max(0, 100 - (slowest_split - fastest_split) * 10), 1),
                "negative_split": paces[-1] < paces[0] if len(paces) >= 2 else False,
                "total_splits": len(splits)
            }
    elif laps_data and abs(len(laps_data) - expected_km_count) <= 2:
        # Fall back to laps ONLY if they match expected km count (likely auto-lap per km)
        splits = process_strava_laps(laps_data)
        workout["splits"] = splits
        
        if splits:
            paces = [s["pace_min_km"] for s in splits if s.get("pace_min_km")]
            if paces:
                fastest_split = min(paces)
                slowest_split = max(paces)
                
                fastest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == fastest_split), None)
                slowest_km = next((s["lap_num"] for s in splits if s.get("pace_min_km") == slowest_split), None)
                
                workout["split_analysis"] = {
                    "fastest_split_pace": round(fastest_split, 2),
                    "slowest_split_pace": round(slowest_split, 2),
                    "fastest_km": fastest_km,
                    "slowest_km": slowest_km,
                    "pace_drop": round(slowest_split - fastest_split, 2),
                    "consistency_score": round(max(0, 100 - (slowest_split - fastest_split) * 10), 1),
                    "negative_split": paces[-1] < paces[0] if len(paces) >= 2 else False,
                    "total_splits": len(splits)
                }
    else:
        # No valid splits data - clear any invalid analysis
        workout["splits"] = []
        workout["split_analysis"] = {}
    
    return workout


# ========== CARDIOCOACH SYSTEM PROMPTS ==========

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


# ========== MOCK DATA FOR DEMO ==========

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


# ========== ROUTES ==========

@api_router.get("/")
async def root():
    return {"message": "CardioCoach API"}


@api_router.get("/workouts", response_model=List[dict])
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


@api_router.get("/workouts/{workout_id}")
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


@api_router.post("/workouts", response_model=Workout)
async def create_workout(workout: WorkoutCreate, user_id: str = "default"):
    """Create a new workout"""
    workout_obj = Workout(**workout.model_dump())
    doc = workout_obj.model_dump()
    doc["user_id"] = user_id
    await db.workouts.insert_one(doc)
    return workout_obj


# ========== VMA / VO2MAX ESTIMATION ==========

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


@api_router.get("/user/vma-estimate")
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


# ========== DASHBOARD INSIGHT (DECISION ASSISTANT) ==========

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


class DashboardInsightResponse(BaseModel):
    coach_insight: str
    week: dict
    month: dict
    recovery_score: Optional[dict] = None  # New: recovery score


# ========== RECOVERY SCORE CALCULATION ==========

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


# ========== USER GOALS ==========

# Distance types with km values
DISTANCE_TYPES = {
    "5k": 5.0,
    "10k": 10.0,
    "semi": 21.1,
    "marathon": 42.195,
    "ultra": 50.0  # Default for ultra, actual distance in event_name
}


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


@api_router.get("/user/goal")
async def get_user_goal(user_id: str = "default"):
    """Get user's current goal"""
    goal = await db.user_goals.find_one({"user_id": user_id}, {"_id": 0})
    return goal


@api_router.post("/user/goal")
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


@api_router.delete("/user/goal")
async def delete_user_goal(user_id: str = "default"):
    """Delete user's goal"""
    result = await db.user_goals.delete_many({"user_id": user_id})
    return {"deleted": result.deleted_count > 0}


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


@api_router.get("/dashboard/insight")
async def get_dashboard_insight(language: str = "fr", user_id: str = "default"):
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


@api_router.get("/stats")
async def get_stats():
    """Get training statistics"""
    workouts = await db.workouts.find({}, {"_id": 0}).to_list(100)
    if not workouts:
        workouts = get_mock_workouts()
    
    total_distance = sum(w.get("distance_km", 0) for w in workouts)
    total_duration = sum(w.get("duration_minutes", 0) for w in workouts)
    
    hr_values = [w.get("avg_heart_rate") for w in workouts if w.get("avg_heart_rate")]
    avg_hr = sum(hr_values) / len(hr_values) if hr_values else None
    
    # Count by type
    by_type = {}
    for w in workouts:
        t = w.get("type", "other")
        by_type[t] = by_type.get(t, 0) + 1
    
    # Weekly summary (simplified)
    weekly = []
    from collections import defaultdict
    week_data = defaultdict(lambda: {"distance": 0, "duration": 0, "count": 0})
    for w in workouts:
        date_str = w.get("date", "")[:10]
        week_data[date_str]["distance"] += w.get("distance_km", 0)
        week_data[date_str]["duration"] += w.get("duration_minutes", 0)
        week_data[date_str]["count"] += 1
    
    for date, data in sorted(week_data.items()):
        weekly.append({"date": date, **data})
    
    return {
        "total_workouts": len(workouts),
        "total_distance_km": round(total_distance, 1),
        "total_duration_minutes": total_duration,
        "avg_heart_rate": round(avg_hr, 1) if avg_hr else None,
        "workouts_by_type": by_type,
        "weekly_summary": weekly[-7:]  # Last 7 days
    }


@api_router.post("/coach/analyze", response_model=CoachResponse)
async def analyze_with_coach(request: CoachRequest):
    """Get analysis from CardioCoach - 100% LOCAL ENGINE, NO LLM
    
    Note: Conversational Q&A is disabled. Use specific workout analysis instead.
    """
    user_id = request.user_id or "default"
    language = request.language or "fr"
    
    # If workout is specified, generate analysis using local engine
    if request.workout_id:
        # Get all workouts for baseline
        all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(100)
        if not all_workouts:
            all_workouts = get_mock_workouts()
        
        workout = await db.workouts.find_one({"id": request.workout_id}, {"_id": 0})
        if not workout:
            workout = next((w for w in all_workouts if w["id"] == request.workout_id), None)
        
        if workout:
            baseline = calculate_baseline_metrics(all_workouts, workout, days=14)
            analysis = generate_session_analysis(workout, baseline, language)
            
            response_text = f"{analysis['summary']}\n\n{analysis['execution']}\n\n{analysis['meaning']}\n\n{analysis['advice']}"
            
            # Store in conversation history
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
    
    # No workout specified - provide general guidance
    all_workouts = await db.workouts.find({}, {"_id": 0}).sort("date", -1).to_list(50)
    if not all_workouts:
        all_workouts = get_mock_workouts()
    
    # Get week stats for context
    week_stats = calculate_week_stats(all_workouts)
    month_stats = calculate_month_stats(all_workouts)
    recovery = calculate_recovery_score(all_workouts, language)
    
    # Generate dashboard-style insight
    insight = generate_dashboard_insight(
        week_stats=week_stats,
        month_stats=month_stats,
        recovery_score=recovery.get("score") if recovery else None,
        language=language
    )
    
    response_text = insight
    if recovery:
        response_text += f"\n\n{recovery.get('phrase', '')}"
    
    msg_id = str(uuid.uuid4())
    return CoachResponse(response=response_text, message_id=msg_id)


@api_router.get("/coach/history")
async def get_conversation_history(user_id: str = "default", limit: int = 50):
    """Get conversation history for a user"""
    messages = await db.conversations.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(limit)
    return messages


@api_router.delete("/coach/history")
async def clear_conversation_history(user_id: str = "default"):
    """Clear conversation history for a user"""
    result = await db.conversations.delete_many({"user_id": user_id})
    return {"deleted_count": result.deleted_count}


@api_router.get("/messages")
async def get_messages(limit: int = 20):
    """Get recent coach messages (legacy endpoint)"""
    messages = await db.conversations.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return messages


@api_router.post("/coach/guidance", response_model=GuidanceResponse)
async def get_adaptive_guidance(request: GuidanceRequest):
    """Generate adaptive training guidance based on recent workouts - 100% LOCAL ENGINE"""
    
    language = request.language or "fr"
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


@api_router.get("/coach/guidance/latest")
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


# ========== WEEKLY REVIEW (BILAN DE LA SEMAINE) ==========

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


@api_router.get("/coach/digest")
async def get_weekly_review(user_id: str = "default", language: str = "fr"):
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


@api_router.get("/coach/digest/latest")
async def get_latest_digest(user_id: str = "default"):
    """Get the most recent digest for a user"""
    digest = await db.digests.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("generated_at", -1)]
    )
    return digest


@api_router.get("/coach/digest/history")
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


# ========== RAG-ENRICHED ENDPOINTS ==========

@api_router.get("/rag/dashboard")
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


@api_router.get("/rag/weekly-review")
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


@api_router.get("/rag/workout/{workout_id}")
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


# ========== MOBILE-FIRST WORKOUT ANALYSIS ==========

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


class MobileAnalysisResponse(BaseModel):
    workout_id: str
    coach_summary: str
    intensity: dict
    load: dict
    session_type: dict
    insight: Optional[str] = None
    guidance: Optional[str] = None


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


@api_router.get("/coach/workout-analysis/{workout_id}")
async def get_mobile_workout_analysis(workout_id: str, language: str = "fr", user_id: str = "default"):
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


# ========== DETAILED ANALYSIS (CARD-BASED MOBILE) ==========

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


@api_router.get("/coach/detailed-analysis/{workout_id}")
async def get_detailed_analysis(workout_id: str, language: str = "fr", user_id: str = "default"):
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


# ========== GARMIN INTEGRATION ENDPOINTS (DORMANT - NOT USER-FACING) ==========

@api_router.get("/garmin/status")
async def get_garmin_status(user_id: str = "default"):
    """Get Garmin connection status for a user (DORMANT)"""
    # Check if user has Garmin token
    token = await db.garmin_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return GarminConnectionStatus(connected=False, last_sync=None, workout_count=0)
    
    # Get last sync time and workout count
    sync_info = await db.sync_history.find_one(
        {"user_id": user_id, "source": "garmin"},
        {"_id": 0},
        sort=[("synced_at", -1)]
    )
    
    workout_count = await db.workouts.count_documents({
        "data_source": "garmin",
        "user_id": user_id
    })
    
    return GarminConnectionStatus(
        connected=True,
        last_sync=sync_info.get("synced_at") if sync_info else None,
        workout_count=workout_count
    )


@api_router.get("/garmin/authorize")
async def garmin_authorize():
    """Initiate Garmin OAuth flow (DORMANT)"""
    if not GARMIN_CLIENT_ID or not GARMIN_CLIENT_SECRET:
        raise HTTPException(
            status_code=503, 
            detail="Garmin integration not configured. Please add GARMIN_CLIENT_ID and GARMIN_CLIENT_SECRET to environment."
        )
    
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()

    # Store PKCE pair in DB (cross-process safe), expires in 10 minutes
    await db.oauth_states.update_one(
        {"state": state},
        {"$set": {
            "state": state,
            "code_verifier": code_verifier,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)
        }},
        upsert=True
    )

    auth_url = get_garmin_auth_url(code_challenge, state)
    return {"authorization_url": auth_url, "state": state}


@api_router.get("/garmin/callback")
async def garmin_callback(code: str, state: str):
    """Handle Garmin OAuth callback (DORMANT)"""
    pkce_entry = await db.oauth_states.find_one_and_delete({"state": state})
    if not pkce_entry:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    code_verifier = pkce_entry["code_verifier"]
    
    try:
        # Exchange code for tokens
        token_data = await exchange_garmin_code(code, code_verifier)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        user_id = "default"  # In production, get from session
        
        # Store token
        await db.garmin_tokens.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                "created_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        
        logger.info(f"Garmin connected for user: {user_id}")
        
        # Redirect back to frontend settings
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?garmin=connected")
    
    except Exception as e:
        logger.error(f"Garmin OAuth error: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?garmin=error")


@api_router.post("/garmin/sync", response_model=GarminSyncResult)
async def sync_garmin_activities(user_id: str = "default"):
    """Sync activities from Garmin Connect (DORMANT)"""
    # Get token
    token = await db.garmin_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return GarminSyncResult(success=False, synced_count=0, message="Not connected to Garmin")
    
    access_token = token.get("access_token")
    
    # Check if token is expired
    expires_at = token.get("expires_at")
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at < datetime.now(timezone.utc):
            return GarminSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
    
    try:
        # Fetch activities from Garmin
        activities = await fetch_garmin_activities(access_token)
        
        synced_count = 0
        for garmin_activity in activities:
            workout = convert_garmin_to_workout(garmin_activity)
            
            if workout:
                # Check if already exists
                existing = await db.workouts.find_one({"id": workout["id"]})
                if not existing:
                    await db.workouts.insert_one(workout)
                    synced_count += 1
        
        # Record sync history
        await db.sync_history.insert_one({
            "user_id": user_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "synced_count": synced_count,
            "source": "garmin"
        })
        
        logger.info(f"Garmin sync complete: {synced_count} workouts for user {user_id}")
        
        return GarminSyncResult(success=True, synced_count=synced_count, message=f"Synced {synced_count} workouts")
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Garmin API error: {e}")
        if e.response.status_code == 401:
            return GarminSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
        return GarminSyncResult(success=False, synced_count=0, message="Failed to fetch activities")
    except Exception as e:
        logger.error(f"Garmin sync error: {e}")
        return GarminSyncResult(success=False, synced_count=0, message="Sync failed")


@api_router.delete("/garmin/disconnect")
async def disconnect_garmin(user_id: str = "default"):
    """Disconnect Garmin account (DORMANT)"""
    await db.garmin_tokens.delete_one({"user_id": user_id})
    logger.info(f"Garmin disconnected for user: {user_id}")
    return {"success": True, "message": "Garmin disconnected"}


# ========== STRAVA INTEGRATION ENDPOINTS (ACTIVE) ==========

class StravaConnectionStatus(BaseModel):
    connected: bool
    last_sync: Optional[str] = None
    workout_count: int = 0


class StravaSyncResult(BaseModel):
    success: bool
    synced_count: int
    message: str


# strava_oauth_store moved to MongoDB (see /strava/authorize endpoint)


@api_router.get("/strava/status")
async def get_strava_status(user_id: str = "default"):
    """Get Strava connection status for a user"""
    # Check if user has Strava token
    token = await db.strava_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return StravaConnectionStatus(connected=False, last_sync=None, workout_count=0)
    
    # Get last sync time
    sync_info = await db.sync_history.find_one(
        {"user_id": user_id, "source": "strava"},
        {"_id": 0},
        sort=[("synced_at", -1)]
    )
    
    # Count imported Strava workouts
    workout_count = await db.workouts.count_documents({
        "data_source": "strava",
        "user_id": user_id
    })
    
    return StravaConnectionStatus(
        connected=True,
        last_sync=sync_info.get("synced_at") if sync_info else None,
        workout_count=workout_count
    )


@api_router.get("/strava/authorize")
async def strava_authorize(user_id: str = "default"):
    """Initiate Strava OAuth flow"""
    if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET:
        raise HTTPException(
            status_code=503, 
            detail="Data sync not configured. Please contact the administrator."
        )
    
    # Generate state for security
    state = secrets.token_urlsafe(32)

    # Store state with user_id in DB (cross-process safe), expires in 10 minutes
    await db.oauth_states.update_one(
        {"state": state},
        {"$set": {
            "state": state,
            "user_id": user_id,
            "provider": "strava",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)
        }},
        upsert=True
    )
    
    # Build Strava authorization URL
    redirect_uri = STRAVA_REDIRECT_URI or f"{FRONTEND_URL}/settings"
    scope = "read,activity:read_all"
    
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scope}"
        f"&state={state}"
    )
    
    return {"authorization_url": auth_url, "state": state}


@api_router.get("/strava/callback")
async def strava_callback(code: str, state: str, scope: str = None):
    """Handle Strava OAuth callback"""
    state_entry = await db.oauth_states.find_one_and_delete({"state": state, "provider": "strava"})
    if not state_entry:
        logger.warning(f"Invalid state parameter received: {state}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=error&reason=invalid_state")

    user_id = state_entry["user_id"]
    
    try:
        # Exchange code for tokens
        token_data = await exchange_strava_code(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_at = token_data.get("expires_at")  # Strava returns Unix timestamp
        athlete_info = token_data.get("athlete", {})
        
        # Store token
        await db.strava_tokens.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "athlete_id": athlete_info.get("id"),
                "created_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        
        logger.info(f"Strava connected for user: {user_id}, athlete: {athlete_info.get('id')}")
        
        # Redirect back to frontend settings
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=connected")
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Strava OAuth HTTP error: {e.response.status_code} - {e.response.text}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=error&reason=token_exchange_failed")
    except Exception as e:
        logger.error(f"Strava OAuth error: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/settings?strava=error&reason=unknown")


@api_router.post("/strava/sync", response_model=StravaSyncResult)
async def sync_strava_activities(user_id: str = "default", fetch_details: bool = True):
    """Sync activities from Strava with detailed HR/pace/splits data for RAG"""
    # Get token
    token = await db.strava_tokens.find_one({"user_id": user_id}, {"_id": 0})
    
    if not token:
        return StravaSyncResult(success=False, synced_count=0, message="Not connected to Strava")
    
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_at = token.get("expires_at")
    
    # Check if token is expired and refresh if needed
    if expires_at:
        if isinstance(expires_at, (int, float)):
            token_expired = expires_at < datetime.now(timezone.utc).timestamp()
        else:
            token_expired = False
            
        if token_expired and refresh_token:
            try:
                # Refresh the token
                new_token_data = await refresh_strava_token(refresh_token)
                access_token = new_token_data.get("access_token")
                
                # Update stored token
                await db.strava_tokens.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "access_token": new_token_data.get("access_token"),
                        "refresh_token": new_token_data.get("refresh_token"),
                        "expires_at": new_token_data.get("expires_at")
                    }}
                )
                logger.info(f"Strava token refreshed for user: {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh Strava token: {e}")
                return StravaSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
    
    try:
        # Fetch activities from Strava
        activities = await fetch_strava_activities(access_token, per_page=100)
        
        synced_count = 0
        detailed_count = 0
        
        for idx, strava_activity in enumerate(activities):
            activity_id = strava_activity.get("id")
            
            # Fetch detailed data for recent activities (first 50 for better RAG)
            streams_data = None
            zones_data = None
            laps_data = None
            
            if fetch_details and idx < 50 and activity_id:
                # Fetch laps (splits) for all activities
                laps_data = await fetch_strava_activity_laps(access_token, str(activity_id))
                
                # Fetch streams and zones for activities with HR data
                if strava_activity.get("has_heartrate") or strava_activity.get("average_heartrate"):
                    streams_data = await fetch_strava_activity_streams(access_token, str(activity_id))
                    zones_data = await fetch_strava_activity_zones(access_token, str(activity_id))
                
                if streams_data or zones_data or laps_data:
                    detailed_count += 1
            
            # Convert base workout
            workout = convert_strava_to_workout(strava_activity, streams_data, zones_data)
            
            if workout:
                # Enrich with detailed data (splits, HR analysis, cadence analysis)
                workout = enrich_workout_with_detailed_data(workout, streams_data, laps_data)
                
                # Check if already exists
                existing = await db.workouts.find_one({"id": workout["id"]})
                if not existing:
                    await db.workouts.insert_one(workout)
                    synced_count += 1
                else:
                    # Update existing workout with new detailed data
                    update_fields = {}
                    
                    # Basic fields
                    for field in ["effort_zone_distribution", "pace_stats", "best_pace_min_km", "avg_cadence_spm"]:
                        if workout.get(field):
                            update_fields[field] = workout[field]
                    
                    # Detailed data for RAG
                    for field in ["splits", "split_analysis", "km_splits", "hr_analysis", 
                                  "cadence_analysis", "elevation_analysis", 
                                  "hr_stream_sample", "cadence_stream_sample"]:
                        if workout.get(field):
                            update_fields[field] = workout[field]
                    
                    if update_fields:
                        await db.workouts.update_one(
                            {"id": workout["id"]},
                            {"$set": update_fields}
                        )
        
        # Record sync history
        await db.sync_history.insert_one({
            "user_id": user_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "synced_count": synced_count,
            "detailed_count": detailed_count,
            "source": "strava"
        })
        
        logger.info(f"Strava sync complete: {synced_count} new workouts, {detailed_count} with detailed data for user {user_id}")
        
        message = f"Synced {synced_count} workouts"
        if detailed_count > 0:
            message += f" ({detailed_count} with detailed HR/pace data)"
        
        return StravaSyncResult(success=True, synced_count=synced_count, message=message)
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Strava API error: {e.response.status_code} - {e.response.text}")
        if e.response.status_code == 401:
            return StravaSyncResult(success=False, synced_count=0, message="Token expired. Please reconnect.")
        return StravaSyncResult(success=False, synced_count=0, message="Failed to fetch activities")
    except Exception as e:
        logger.error(f"Strava sync error: {e}")
        return StravaSyncResult(success=False, synced_count=0, message="Sync failed")


@api_router.delete("/strava/disconnect")
async def disconnect_strava(user_id: str = "default"):
    """Disconnect Strava account"""
    await db.strava_tokens.delete_one({"user_id": user_id})
    logger.info(f"Strava disconnected for user: {user_id}")
    return {"success": True, "message": "Strava disconnected"}


# ========== STRAVA WEBHOOKS (REAL-TIME SYNC) ==========

# Webhook verify token (should be stored in env in production)
STRAVA_WEBHOOK_VERIFY_TOKEN = os.environ.get("STRAVA_WEBHOOK_VERIFY_TOKEN", "cardiocoach_webhook_secret_2024")

class WebhookSubscriptionRequest(BaseModel):
    callback_url: str


class WebhookSubscriptionResponse(BaseModel):
    success: bool
    subscription_id: Optional[int] = None
    message: str


@api_router.get("/webhooks/strava")
async def strava_webhook_verify(
    request: Request,
):
    """
    Handle Strava webhook verification (GET request).
    Strava sends: hub.mode=subscribe, hub.verify_token, hub.challenge
    We must return: {"hub.challenge": <challenge_value>}
    """
    params = dict(request.query_params)
    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")
    
    logger.info(f"Strava webhook verification: mode={hub_mode}, token={hub_verify_token}, challenge={hub_challenge}")
    
    if hub_mode == "subscribe" and hub_verify_token == STRAVA_WEBHOOK_VERIFY_TOKEN:
        logger.info("✅ Strava webhook verification successful")
        return {"hub.challenge": hub_challenge}
    else:
        logger.warning(f"❌ Strava webhook verification failed: invalid token or mode")
        raise HTTPException(status_code=403, detail="Verification failed")


@api_router.post("/webhooks/strava")
async def strava_webhook_event(request: Request):
    """
    Handle Strava webhook events (POST request).
    Strava sends events for activity create/update/delete, athlete update/deauthorize.
    """
    try:
        event = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook event: {e}")
        return {"status": "error", "message": "Invalid JSON"}
    
    object_type = event.get("object_type")  # "activity" or "athlete"
    aspect_type = event.get("aspect_type")  # "create", "update", "delete"
    object_id = event.get("object_id")  # activity_id or athlete_id
    owner_id = event.get("owner_id")  # athlete_id (owner of the object)
    subscription_id = event.get("subscription_id")
    event_time = event.get("event_time")
    updates = event.get("updates", {})  # For update events, contains changed fields
    
    logger.info(f"📩 Strava webhook event: type={object_type}, aspect={aspect_type}, object_id={object_id}, owner_id={owner_id}")
    
    # Handle athlete deauthorization
    if object_type == "athlete" and aspect_type == "update" and updates.get("authorized") == "false":
        logger.info(f"🔒 Athlete {owner_id} deauthorized - removing tokens")
        await db.strava_tokens.delete_one({"athlete_id": owner_id})
        return {"status": "ok", "action": "deauthorized"}
    
    # Handle activity events
    if object_type == "activity":
        if aspect_type in ["create", "update"]:
            # Process the activity asynchronously
            try:
                result = await process_strava_webhook_activity(owner_id, object_id, aspect_type)
                return {"status": "ok", "action": result}
            except Exception as e:
                logger.error(f"Error processing activity {object_id}: {e}")
                return {"status": "error", "message": str(e)}
        
        elif aspect_type == "delete":
            # Delete the activity from our database
            logger.info(f"🗑️ Deleting activity {object_id} from webhook")
            await db.workouts.delete_one({"id": f"strava_{object_id}"})
            return {"status": "ok", "action": "deleted"}
    
    # Acknowledge other events
    return {"status": "ok", "action": "ignored"}


async def process_strava_webhook_activity(athlete_id: int, activity_id: int, aspect_type: str) -> str:
    """
    Process a Strava activity event from webhook.
    1. Find the user by athlete_id
    2. Refresh token if needed
    3. Fetch the activity details
    4. Store/update in database
    """
    logger.info(f"🔄 Processing webhook activity {activity_id} for athlete {athlete_id} ({aspect_type})")
    
    # Find user by athlete_id
    token_doc = await db.strava_tokens.find_one({"athlete_id": athlete_id}, {"_id": 0})
    
    if not token_doc:
        logger.warning(f"No token found for athlete {athlete_id}")
        return "no_user_found"
    
    user_id = token_doc.get("user_id")
    access_token = token_doc.get("access_token")
    refresh_token = token_doc.get("refresh_token")
    expires_at = token_doc.get("expires_at")
    
    # Check if token is expired and refresh if needed
    if expires_at:
        current_time = datetime.now(timezone.utc).timestamp()
        if isinstance(expires_at, (int, float)) and expires_at < current_time:
            logger.info(f"Token expired for user {user_id}, refreshing...")
            try:
                new_token_data = await refresh_strava_token(refresh_token)
                access_token = new_token_data.get("access_token")
                
                # Update token in database
                await db.strava_tokens.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "access_token": new_token_data.get("access_token"),
                        "refresh_token": new_token_data.get("refresh_token", refresh_token),
                        "expires_at": new_token_data.get("expires_at")
                    }}
                )
                logger.info(f"✅ Token refreshed for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh token for user {user_id}: {e}")
                return "token_refresh_failed"
    
    # Fetch the activity from Strava
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{activity_id}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            strava_activity = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to fetch activity {activity_id}: {e.response.status_code}")
        return f"fetch_failed_{e.response.status_code}"
    except Exception as e:
        logger.error(f"Error fetching activity {activity_id}: {e}")
        return "fetch_error"
    
    # Convert and store the activity
    workout = convert_strava_to_workout(strava_activity, user_id)
    
    # Fetch additional details (streams, laps) for RAG enrichment
    try:
        streams_data = await fetch_strava_activity_streams(access_token, str(activity_id))
        laps_data = await fetch_strava_activity_laps(access_token, str(activity_id))
        
        # Enrich workout with detailed data
        workout = enrich_workout_with_detailed_data(workout, streams_data, laps_data)
        logger.info(f"✅ Enriched activity {activity_id} with streams and laps data")
    except Exception as e:
        logger.warning(f"Could not fetch detailed data for activity {activity_id}: {e}")
    
    # Upsert the workout
    await db.workouts.update_one(
        {"id": workout["id"]},
        {"$set": workout},
        upsert=True
    )
    
    logger.info(f"✅ Activity {activity_id} synced for user {user_id}: {workout.get('name', 'Untitled')}")
    
    # Store sync event for debugging
    await db.webhook_events.insert_one({
        "event_type": "activity_sync",
        "activity_id": activity_id,
        "athlete_id": athlete_id,
        "user_id": user_id,
        "aspect_type": aspect_type,
        "workout_name": workout.get("name"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return "synced"


@api_router.post("/strava/webhook/subscribe", response_model=WebhookSubscriptionResponse)
async def create_strava_webhook_subscription(req: WebhookSubscriptionRequest):
    """
    Create a Strava webhook subscription (admin endpoint).
    This should be called once to register the webhook with Strava.
    """
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return WebhookSubscriptionResponse(
            success=False,
            message="Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET"
        )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://www.strava.com/api/v3/push_subscriptions",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "callback_url": req.callback_url,
                    "verify_token": STRAVA_WEBHOOK_VERIFY_TOKEN
                }
            )
            
            if response.status_code == 201:
                data = response.json()
                subscription_id = data.get("id")
                
                # Store subscription info
                await db.strava_webhook_subscriptions.update_one(
                    {"type": "main"},
                    {"$set": {
                        "subscription_id": subscription_id,
                        "callback_url": req.callback_url,
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }},
                    upsert=True
                )
                
                logger.info(f"✅ Strava webhook subscription created: {subscription_id}")
                return WebhookSubscriptionResponse(
                    success=True,
                    subscription_id=subscription_id,
                    message="Webhook subscription created successfully"
                )
            else:
                error_msg = response.text
                logger.error(f"Failed to create webhook subscription: {response.status_code} - {error_msg}")
                return WebhookSubscriptionResponse(
                    success=False,
                    message=f"Failed: {error_msg}"
                )
    except Exception as e:
        logger.error(f"Error creating webhook subscription: {e}")
        return WebhookSubscriptionResponse(
            success=False,
            message=str(e)
        )


@api_router.get("/strava/webhook/status")
async def get_strava_webhook_status():
    """Get current Strava webhook subscription status"""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return {"status": "error", "message": "Missing credentials"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://www.strava.com/api/v3/push_subscriptions",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            
            if response.status_code == 200:
                subscriptions = response.json()
                
                # Get recent webhook events from our DB
                recent_events = await db.webhook_events.find(
                    {},
                    {"_id": 0}
                ).sort("timestamp", -1).limit(10).to_list(10)
                
                return {
                    "status": "ok",
                    "subscriptions": subscriptions,
                    "recent_events": recent_events,
                    "verify_token_configured": bool(STRAVA_WEBHOOK_VERIFY_TOKEN)
                }
            else:
                return {
                    "status": "error",
                    "message": response.text
                }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@api_router.delete("/strava/webhook/unsubscribe/{subscription_id}")
async def delete_strava_webhook_subscription(subscription_id: int):
    """Delete a Strava webhook subscription"""
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"https://www.strava.com/api/v3/push_subscriptions/{subscription_id}",
                params={
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            
            if response.status_code == 204:
                await db.strava_webhook_subscriptions.delete_one({"subscription_id": subscription_id})
                logger.info(f"✅ Webhook subscription {subscription_id} deleted")
                return {"success": True, "message": "Subscription deleted"}
            else:
                return {"success": False, "message": response.text}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ========== PREMIUM SUBSCRIPTION (STRIPE) ==========

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


# ========== TRAINING ENDPOINTS ==========

@api_router.post("/training/set-goal")
async def set_training_goal(
    goal: str = Query(..., description="10K | SEMI | MARATHON"),
    user: dict = Depends(auth_user)
):
    """
    Définit l'objectif principal du cycle.
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        return {"error": "Invalid goal"}
    
    goal_upper = goal.upper()
    
    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "goal": goal_upper,
            "start_date": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    logger.info(f"[Training] Goal set for user {user['id']}: {goal_upper}")
    
    return {"status": "updated", "goal": goal_upper}


@api_router.get("/training/plan")
async def get_training_plan_v2(user: dict = Depends(auth_user)):
    """
    Génère ou met à jour le plan d'entraînement dynamique
    selon les dernières données fitness.
    """
    return await generate_dynamic_training_plan(db, user["id"])


@api_router.post("/training/refresh")
async def refresh_training_plan(sessions: int = None, user: dict = Depends(auth_user)):
    """
    Force le recalcul complet du plan
    (après sync Strava par exemple).
    sessions: nombre de séances souhaitées (3, 4, 5, 6)
    """
    # Vider le cache pour cet utilisateur
    from coach_service import _plan_cache
    keys_to_remove = [k for k in _plan_cache if user["id"] in k]
    for k in keys_to_remove:
        del _plan_cache[k]
    
    # Sauvegarder le nombre de séances si spécifié
    if sessions and sessions in [3, 4, 5, 6]:
        await db.training_prefs.update_one(
            {"user_id": user["id"]},
            {"$set": {"sessions_per_week": sessions}},
            upsert=True
        )
    
    return await generate_dynamic_training_plan(db, user["id"], sessions_override=sessions)


@api_router.delete("/training/goal")
async def delete_training_goal(user_id: str = "default"):
    """Supprime l'objectif d'entraînement"""
    
    result = await db.training_goals.delete_one({"user_id": user_id})
    await db.training_context.delete_one({"user_id": user_id})
    await db.training_cycles.delete_one({"user_id": user_id})
    
    return {
        "success": result.deleted_count > 0,
        "message": "Objectif supprimé" if result.deleted_count > 0 else "Aucun objectif trouvé"
    }


@api_router.get("/training-plan")
async def get_training_plan(user: dict = Depends(auth_user)):
    """
    Récupère le plan d'entraînement dynamique pour l'utilisateur.
    Génère automatiquement les séances via LLM basé sur le cycle.
    """
    return await generate_dynamic_training_plan(db, user["id"])


@api_router.post("/training-plan/set-goal")
async def set_training_plan_goal(goal: str, user: dict = Depends(auth_user)):
    """
    Définit l'objectif d'entraînement (10K, SEMI, MARATHON, etc.)
    """
    if goal.upper() not in ["5K", "10K", "SEMI", "MARATHON", "ULTRA"]:
        return {"error": "Invalid goal"}
    
    goal_upper = goal.upper()
    config = GOAL_CONFIG[goal_upper]
    
    await db.training_cycles.update_one(
        {"user_id": user["id"]},
        {"$set": {
            "goal": goal_upper,
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    
    logger.info(f"[Training] Goal updated for user {user['id']}: {goal_upper}")
    
    return {
        "status": "updated",
        "goal": goal_upper,
        "cycle_weeks": config["cycle_weeks"],
        "description": config["description"]
    }


# Garder l'ancien endpoint pour compatibilité
@api_router.get("/training/dynamic-plan")
async def get_dynamic_training_plan_legacy(user_id: str = "default"):
    """Legacy endpoint - utiliser /training-plan à la place"""
    return await generate_dynamic_training_plan(db, user_id)


@api_router.get("/training/goals")
async def get_available_goals():
    """Liste les types d'objectifs disponibles"""
    return {
        "goals": [
            {
                "type": goal_type,
                "description": config["description"],
                "cycle_weeks": config["cycle_weeks"],
                "long_run_ratio": config["long_run_ratio"],
                "intensity_pct": config["intensity_pct"]
            }
            for goal_type, config in GOAL_CONFIG.items()
        ]
    }


@api_router.get("/training/metrics")
async def get_training_metrics(user: dict = Depends(auth_user)):
    """
    Retourne les métriques d'entraînement: ACWR, TSB, charge, monotonie.
    Utilisé par le Dashboard pour afficher l'état de forme.
    """
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    # Récupérer les activités Strava
    activities_7 = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    activities_28 = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(300)
    
    # Fallback sur workouts manuels si pas de Strava
    if not activities_28:
        activities_7 = await db.workouts.find({
            "date": {"$gte": seven_days_ago.isoformat()}
        }).to_list(100)
        activities_28 = await db.workouts.find({
            "date": {"$gte": twenty_eight_days_ago.isoformat()}
        }).to_list(300)
    
    # Calculer les charges (en km, simplifié)
    def get_distance(a):
        dist = a.get("distance", 0)
        if dist > 1000:  # Strava retourne en mètres
            return dist / 1000
        return a.get("distance_km", dist)
    
    load_7 = sum(get_distance(a) for a in activities_7)
    load_28 = sum(get_distance(a) for a in activities_28)
    
    # ACWR
    chronic_avg = load_28 / 4 if load_28 > 0 else 1
    acwr = round(load_7 / chronic_avg, 2) if chronic_avg > 0 else 1.0
    
    # TSB simplifié (basé sur la différence entre charge récente et moyenne)
    # CTL = moyenne mobile sur 42 jours (approximé par 28j/4*6)
    # ATL = moyenne mobile sur 7 jours
    ctl = load_28 / 4  # Approximation fitness
    atl = load_7  # Fatigue récente
    tsb = round(ctl - atl, 1)
    
    # Calculer la monotonie (7 derniers jours)
    daily_loads = []
    for i in range(7):
        day = (today - timedelta(days=i)).date()
        day_load = 0
        for a in activities_7:
            try:
                a_date_str = a.get("start_date_local", a.get("date", ""))
                if a_date_str:
                    a_date = datetime.fromisoformat(a_date_str.replace("Z", "+00:00")).date()
                    if a_date == day:
                        day_load += get_distance(a)
            except:
                pass
        daily_loads.append(day_load)
    
    # Monotonie = moyenne / écart-type
    if daily_loads and len(daily_loads) >= 2:
        avg_load = sum(daily_loads) / len(daily_loads)
        variance = sum((x - avg_load) ** 2 for x in daily_loads) / len(daily_loads)
        std = variance ** 0.5
        monotony = round(avg_load / std, 2) if std > 0 else 0
    else:
        monotony = 0
    
    # Strain = Load * Monotony
    strain = round(load_7 * monotony, 0) if monotony > 0 else 0
    
    # Interpréter ACWR
    if acwr < 0.8:
        acwr_status = "low"
        acwr_label = "Sous-entraînement"
    elif acwr <= 1.3:
        acwr_status = "optimal"
        acwr_label = "Zone optimale"
    elif acwr <= 1.5:
        acwr_status = "warning"
        acwr_label = "Zone à risque"
    else:
        acwr_status = "danger"
        acwr_label = "Danger"
    
    # Interpréter TSB
    if tsb > 10:
        tsb_status = "fresh"
        tsb_label = "Très frais"
    elif tsb > 0:
        tsb_status = "ready"
        tsb_label = "Prêt"
    elif tsb > -10:
        tsb_status = "training"
        tsb_label = "En charge"
    else:
        tsb_status = "fatigued"
        tsb_label = "Fatigué"
    
    return {
        "acwr": acwr,
        "acwr_status": acwr_status,
        "acwr_label": acwr_label,
        "tsb": tsb,
        "tsb_status": tsb_status,
        "tsb_label": tsb_label,
        "load_7": round(load_7, 1),
        "load_28": round(load_28, 1),
        "monotony": monotony,
        "strain": strain,
        "ctl": round(ctl, 1),
        "atl": round(atl, 1)
    }


@api_router.get("/training/race-predictions")
async def get_race_predictions(user: dict = Depends(auth_user)):
    """
    Prédit les temps de course pour 5K, 10K, Semi, Marathon, Ultra
    basé sur le profil d'entraînement de l'athlète.
    """
    today = datetime.now(timezone.utc)
    sixty_days_ago = today - timedelta(days=60)
    
    # Récupérer les activités des 60 derniers jours
    activities = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": sixty_days_ago.isoformat()}
    }).to_list(500)
    
    if not activities:
        activities = await db.workouts.find({
            "date": {"$gte": sixty_days_ago.isoformat()}
        }).to_list(500)
    
    if not activities:
        return {
            "has_data": False,
            "message": "Pas assez de données pour prédire. Continue à t'entraîner !",
            "predictions": []
        }
    
    # Extraire les métriques clés
    def get_distance(a):
        dist = a.get("distance", 0)
        if dist > 1000:
            return dist / 1000
        return a.get("distance_km", dist)
    
    def get_duration_minutes(a):
        """Retourne la durée en minutes"""
        # Strava: moving_time en secondes
        moving_time = a.get("moving_time", 0)
        if moving_time > 0:
            return moving_time / 60
        # Fallback: elapsed_time
        elapsed = a.get("elapsed_time", 0)
        if elapsed > 0:
            return elapsed / 60
        # Fallback: duration_minutes
        return a.get("duration_minutes", 0)
    
    def get_pace(a):
        # Pace en min/km
        pace = a.get("avg_pace_min_km")
        if pace:
            return pace
        # Calculer depuis vitesse moyenne (m/s)
        speed = a.get("average_speed", 0)
        if speed > 0:
            return (1000 / speed) / 60
        # Calculer depuis distance/durée
        dist = get_distance(a)
        duration_min = get_duration_minutes(a)
        if dist > 0 and duration_min > 0:
            return duration_min / dist
        return None
    
    # Collecter les données
    total_km = 0
    total_sessions = 0
    paces = []
    long_runs = []  # Sorties > 15km
    vma_efforts = []  # Efforts >= 6 min pour calcul VMA
    distances = []
    
    MIN_VMA_DURATION = 6  # Minutes minimum pour calcul VMA
    
    for a in activities:
        dist = get_distance(a)
        pace = get_pace(a)
        duration_min = get_duration_minutes(a)
        
        if dist > 0:
            total_km += dist
            total_sessions += 1
            distances.append(dist)
            
            if pace and 3 < pace < 10:  # Pace réaliste
                paces.append(pace)
                
                # Pour la VMA : effort >= 6 minutes ET allure rapide (< 5:30/km)
                if duration_min >= MIN_VMA_DURATION and pace < 5.5:
                    vma_efforts.append({
                        "distance": dist, 
                        "pace": pace, 
                        "duration": duration_min,
                        "speed_kmh": 60 / pace
                    })
                
                if dist >= 15:  # Sortie longue
                    long_runs.append({"distance": dist, "pace": pace})
    
    if not paces:
        return {
            "has_data": False,
            "message": "Pas assez de données d'allure. Assure-toi que tes séances ont des données GPS.",
            "predictions": []
        }
    
    # Calculer les métriques de base
    weekly_km = total_km / 8.5  # ~60 jours = 8.5 semaines
    avg_pace = sum(paces) / len(paces)
    best_pace = min(paces) if paces else avg_pace
    max_long_run = max(distances) if distances else 0
    
    # Estimer la VMA (Vitesse Maximale Aérobie)
    # Basé sur les efforts >= 6 minutes (physiologiquement représentatif)
    vma_method = "estimated"
    
    if vma_efforts:
        # Prendre le meilleur effort de >= 6 minutes
        best_vma_effort = max(vma_efforts, key=lambda x: x["speed_kmh"])
        best_sustained_speed = best_vma_effort["speed_kmh"]
        
        # La VMA est environ 5-10% au-dessus de l'allure soutenue sur 6+ min
        # Plus l'effort est long, plus on est proche de la VMA
        duration = best_vma_effort["duration"]
        if duration >= 20:
            # Effort long (20+ min) = environ 85% VMA → VMA = vitesse / 0.85
            estimated_vma = best_sustained_speed / 0.85
        elif duration >= 12:
            # Effort moyen (12-20 min) = environ 90% VMA
            estimated_vma = best_sustained_speed / 0.90
        else:
            # Effort court (6-12 min) = environ 95% VMA
            estimated_vma = best_sustained_speed / 0.95
        
        vma_method = f"effort_{int(duration)}min"
    else:
        # Pas d'effort rapide >= 6 min, estimation depuis allure moyenne
        # L'allure moyenne d'endurance est environ 70% VMA
        avg_speed_kmh = 60 / avg_pace
        estimated_vma = avg_speed_kmh / 0.70
        vma_method = "from_avg_pace"
    
    # Prédictions basées sur VMA et volume
    predictions = []
    
    # Facteurs de prédiction par distance
    race_configs = [
        {
            "distance": "5K",
            "km": 5,
            "vma_pct": 0.95,  # 5K = ~95% VMA
            "min_weekly_km": 15,
            "min_long_run": 8,
            "description": "5 kilomètres"
        },
        {
            "distance": "10K",
            "km": 10,
            "vma_pct": 0.90,  # 10K = ~90% VMA
            "min_weekly_km": 25,
            "min_long_run": 12,
            "description": "10 kilomètres"
        },
        {
            "distance": "Semi",
            "km": 21.1,
            "vma_pct": 0.82,  # Semi = ~82% VMA
            "min_weekly_km": 35,
            "min_long_run": 18,
            "description": "Semi-marathon"
        },
        {
            "distance": "Marathon",
            "km": 42.195,
            "vma_pct": 0.75,  # Marathon = ~75% VMA
            "min_weekly_km": 50,
            "min_long_run": 30,
            "description": "Marathon"
        },
        {
            "distance": "Ultra",
            "km": 50,
            "vma_pct": 0.65,  # Ultra = ~65% VMA
            "min_weekly_km": 70,
            "min_long_run": 35,
            "description": "Ultra-trail (50km)"
        }
    ]
    
    for config in race_configs:
        # Vitesse de course prédite
        race_speed = estimated_vma * config["vma_pct"]
        race_pace = 60 / race_speed  # min/km
        
        # Temps prédit
        predicted_minutes = config["km"] * race_pace
        
        # Ajuster selon le volume d'entraînement
        volume_factor = min(1.0, weekly_km / config["min_weekly_km"])
        if volume_factor < 0.7:
            # Volume insuffisant = temps plus lent
            predicted_minutes *= (1 + (1 - volume_factor) * 0.15)
        
        # Ajuster selon sortie longue max
        endurance_factor = min(1.0, max_long_run / config["min_long_run"])
        if endurance_factor < 0.8 and config["km"] > 10:
            predicted_minutes *= (1 + (1 - endurance_factor) * 0.10)
        
        # Formater le temps
        hours = int(predicted_minutes // 60)
        mins = int(predicted_minutes % 60)
        secs = int((predicted_minutes % 1) * 60)
        
        if hours > 0:
            time_str = f"{hours}h{mins:02d}"
            time_range = f"{hours}h{max(0,mins-3):02d} - {hours}h{mins+5:02d}"
        else:
            time_str = f"{mins}:{secs:02d}"
            time_range = f"{max(0,mins-2)}:{secs:02d} - {mins+3}:{secs:02d}"
        
        # Évaluer la capacité
        readiness_score = (volume_factor * 0.5 + endurance_factor * 0.5) * 100
        
        if readiness_score >= 80:
            readiness = "ready"
            readiness_label = "Prêt"
            readiness_color = "#22c55e"
        elif readiness_score >= 60:
            readiness = "possible"
            readiness_label = "Possible"
            readiness_color = "#f59e0b"
        elif readiness_score >= 40:
            readiness = "challenging"
            readiness_label = "Ambitieux"
            readiness_color = "#f97316"
        else:
            readiness = "not_ready"
            readiness_label = "Pas prêt"
            readiness_color = "#ef4444"
        
        # Allure prédite formatée
        pace_mins = int(race_pace)
        pace_secs = int((race_pace % 1) * 60)
        pace_str = f"{pace_mins}:{pace_secs:02d}/km"
        
        predictions.append({
            "distance": config["distance"],
            "distance_km": config["km"],
            "description": config["description"],
            "predicted_time": time_str,
            "predicted_range": time_range,
            "predicted_pace": pace_str,
            "readiness": readiness,
            "readiness_label": readiness_label,
            "readiness_color": readiness_color,
            "readiness_score": round(readiness_score),
            "volume_factor": round(volume_factor * 100),
            "endurance_factor": round(endurance_factor * 100)
        })
    
    return {
        "has_data": True,
        "athlete_profile": {
            "weekly_km": round(weekly_km, 1),
            "avg_pace": f"{int(avg_pace)}:{int((avg_pace % 1) * 60):02d}/km",
            "best_pace": f"{int(best_pace)}:{int((best_pace % 1) * 60):02d}/km",
            "max_long_run": round(max_long_run, 1),
            "estimated_vma": round(estimated_vma, 1),
            "total_sessions_60d": total_sessions
        },
        "predictions": predictions
    }


@api_router.get("/training/full-cycle")
async def get_full_training_cycle(user: dict = Depends(auth_user)):
    """
    Retourne l'aperçu complet du cycle d'entraînement avec toutes les semaines.
    Chaque semaine inclut: numéro, phase, volume cible, type de séances.
    """
    # Récupérer le cycle utilisateur
    cycle = await db.training_cycles.find_one({"user_id": user["id"]})
    
    if not cycle:
        # Créer un cycle par défaut
        default_cycle = {
            "user_id": user["id"],
            "goal": "SEMI",
            "start_date": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc)
        }
        await db.training_cycles.insert_one(default_cycle)
        cycle = await db.training_cycles.find_one({"user_id": user["id"]})
    
    goal = cycle.get("goal", "SEMI")
    config = GOAL_CONFIG.get(goal, GOAL_CONFIG["SEMI"])
    total_weeks = config["cycle_weeks"]
    
    # Récupérer les préférences de séances
    prefs = await db.training_prefs.find_one({"user_id": user["id"]})
    sessions_per_week = prefs.get("sessions_per_week", 4) if prefs else 4
    
    # Calculer la semaine actuelle
    start_date = cycle.get("start_date")
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    current_week = compute_week_number(start_date.date() if isinstance(start_date, datetime) else start_date)
    
    # Récupérer le volume actuel de l'athlète (basé sur les 28 derniers jours)
    today = datetime.now(timezone.utc)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_28 = await db.strava_activities.find({
        "user_id": user["id"],
        "start_date_local": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(200)
    
    # Si pas de données Strava, essayer les workouts manuels
    if not workouts_28:
        workouts_28 = await db.workouts.find({
            "date": {"$gte": twenty_eight_days_ago.isoformat()}
        }).to_list(200)
    
    km_28 = sum(w.get("distance", w.get("distance_km", 0) * 1000) / 1000 for w in workouts_28)
    base_weekly_km = km_28 / 4 if km_28 > 0 else 25  # Volume hebdo de base
    
    # Générer l'aperçu de toutes les semaines
    weeks_overview = []
    
    for week_num in range(1, total_weeks + 1):
        phase = determine_phase(week_num, total_weeks)
        phase_info = get_phase_description(phase, "fr")
        
        # Calculer le volume cible selon la phase et la progression
        progression_factor = 1 + (week_num / total_weeks) * 0.3  # +30% max sur le cycle
        
        if phase == "build":
            volume_factor = 1.0 * progression_factor
        elif phase == "deload":
            volume_factor = 0.7  # -30% en décharge
        elif phase == "intensification":
            volume_factor = 1.1 * progression_factor
        elif phase == "taper":
            # Réduction progressive: -40% à -60%
            weeks_to_race = total_weeks - week_num
            volume_factor = 0.6 - (0.1 * (2 - weeks_to_race))
        elif phase == "race":
            volume_factor = 0.3  # Très peu de volume
        else:
            volume_factor = 1.0
        
        target_km = round(base_weekly_km * volume_factor)
        
        # Types de séances selon la phase
        if phase == "build":
            session_types = ["Endurance", "Endurance", "Sortie longue"] if sessions_per_week <= 3 else ["Endurance", "Endurance", "Fartlek", "Sortie longue"]
        elif phase == "deload":
            session_types = ["Récupération", "Endurance facile", "Endurance courte"]
        elif phase == "intensification":
            session_types = ["Endurance", "Seuil/Tempo", "Fractionné", "Sortie longue"]
        elif phase == "taper":
            session_types = ["Endurance facile", "Rappel vitesse", "Footing"]
        elif phase == "race":
            session_types = ["Activation", "COURSE"]
        else:
            session_types = ["Endurance", "Sortie longue"]
        
        weeks_overview.append({
            "week": week_num,
            "phase": phase,
            "phase_name": phase_info.get("name", phase),
            "phase_focus": phase_info.get("focus", ""),
            "target_km": target_km,
            "sessions": sessions_per_week if phase not in ["taper", "race"] else min(3, sessions_per_week),
            "session_types": session_types[:sessions_per_week],
            "is_current": week_num == current_week,
            "is_completed": week_num < current_week,
            "intensity_pct": phase_info.get("intensity_pct", 15)
        })
    
    return {
        "goal": goal,
        "goal_description": config["description"],
        "total_weeks": total_weeks,
        "current_week": current_week,
        "start_date": start_date.isoformat() if start_date else None,
        "sessions_per_week": sessions_per_week,
        "base_weekly_km": round(base_weekly_km),
        "weeks": weeks_overview
    }


@api_router.get("/training/week-plan")
async def get_week_plan(user_id: str = "default"):
    """
    Génère un plan d'entraînement détaillé pour la semaine via LLM.
    Utilise le contexte d'entraînement et l'objectif défini.
    """
    # Récupérer l'objectif
    goal = await db.training_goals.find_one({"user_id": user_id}, {"_id": 0})
    
    if not goal:
        raise HTTPException(status_code=400, detail="Aucun objectif défini. Utilisez /api/training/set-goal d'abord.")
    
    # Récupérer les données récentes pour le contexte
    today = datetime.now(timezone.utc)
    seven_days_ago = today - timedelta(days=7)
    twenty_eight_days_ago = today - timedelta(days=28)
    
    workouts_7 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": seven_days_ago.isoformat()}
    }).to_list(100)
    
    workouts_28 = await db.workouts.find({
        "user_id": user_id,
        "date": {"$gte": twenty_eight_days_ago.isoformat()}
    }).to_list(100)
    
    # Calculer les métriques
    km_7 = sum(w.get("distance_km", 0) or 0 for w in workouts_7)
    km_28 = sum(w.get("distance_km", 0) or 0 for w in workouts_28)
    load_7 = km_7 * 10
    load_28 = km_28 * 10
    
    # Construire le contexte
    context = {
        "ctl": load_28 / 4 if load_28 > 0 else 30,
        "atl": load_7 if load_7 > 0 else 35,
        "tsb": (load_28 / 4 - load_7) if load_28 > 0 else -5,
        "acwr": (load_7 / (load_28 / 4)) if load_28 > 0 else 1.0,
        "weekly_km": km_28 / 4 if km_28 > 0 else 20
    }
    
    # Calculer la phase
    start_date = goal["start_date"]
    cycle_weeks = goal["cycle_weeks"]
    
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    
    if today < start_date:
        current_week = 0
    else:
        delta_days = (today - start_date).days
        current_week = min(delta_days // 7 + 1, cycle_weeks + 1)
    
    phase = determine_phase(current_week, cycle_weeks)
    
    # Calculer la charge cible
    from training_engine import determine_target_load
    target_load = determine_target_load(context, phase)
    
    # Générer le plan via LLM
    plan, success, metadata = await generate_cycle_week(
        context=context,
        phase=phase,
        target_load=target_load,
        goal=goal["goal_type"],
        user_id=user_id
    )
    
    if not success or not plan:
        # Fallback: plan générique basé sur la phase
        plan = _generate_fallback_week_plan(context, phase, target_load, goal["goal_type"])
    
    return {
        "goal": {
            "type": goal["goal_type"],
            "name": goal["event_name"],
            "event_date": goal["event_date"].isoformat() if isinstance(goal["event_date"], datetime) else goal["event_date"]
        },
        "current_week": current_week,
        "total_weeks": cycle_weeks,
        "phase": phase,
        "context": context,
        "plan": plan,
        "generated_by": "llm" if success else "fallback",
        "metadata": metadata
    }


def _generate_fallback_week_plan(context: dict, phase: str, target_load: int, goal: str) -> dict:
    """Génère un plan de secours basé sur des templates."""
    weekly_km = context.get("weekly_km", 30)
    
    # Ajuster selon la phase
    phase_multipliers = {
        "build": 1.0,
        "deload": 0.7,
        "intensification": 1.05,
        "taper": 0.6,
        "race": 0.25
    }
    adjusted_km = weekly_km * phase_multipliers.get(phase, 1.0)
    
    # Allures de référence (à personnaliser selon le profil utilisateur)
    # Format: allure en min:sec/km
    paces = {
        "z1": "6:30-7:00",  # Récupération
        "z2": "5:45-6:15",  # Endurance fondamentale
        "z3": "5:15-5:30",  # Tempo / Allure marathon
        "z4": "4:45-5:00",  # Seuil
        "z5": "4:15-4:30",  # VMA
        "semi": "5:00-5:15", # Allure semi-marathon
        "10k": "4:40-4:55",  # Allure 10K
    }
    
    # FC cibles (à personnaliser selon FC max utilisateur ~185 bpm)
    hr_zones = {
        "z1": "120-135",
        "z2": "135-150", 
        "z3": "150-165",
        "z4": "165-175",
        "z5": "175-185",
    }
    
    # Templates par phase avec détails enrichis
    if phase == "deload":
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements ou yoga", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "30min", "details": f"5 km • {paces['z1']}/km • FC {hr_zones['z1']} bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 5},
            {"day": "Mercredi", "type": "Repos", "duration": "0min", "details": "Récupération active • Marche ou natation légère", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Jeudi", "type": "Endurance", "duration": "35min", "details": f"6 km • {paces['z2']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": 6},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Sommeil prioritaire", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Endurance", "duration": "40min", "details": f"7 km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 35, "distance_km": 7},
            {"day": "Dimanche", "type": "Repos", "duration": "0min", "details": "Récupération complète • Prépare la semaine suivante", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    elif phase == "taper":
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Hydratation ++", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "30min", "details": f"5 km + 4×100m vite • {paces['z2']}/km puis sprint • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 30, "distance_km": 5.5},
            {"day": "Mercredi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Préparation mentale", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Jeudi", "type": "Tempo court", "duration": "25min", "details": f"4 km dont 2 km à allure course • {paces['semi']}/km • FC {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": 35, "distance_km": 4},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Repos total • Dernière préparation équipement", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Activation", "duration": "20min", "details": f"3 km + 3×200m allure course • {paces['z2']}/km • FC {hr_zones['z2']} bpm", "intensity": "easy", "estimated_tss": 25, "distance_km": 3.6},
            {"day": "Dimanche", "type": "Repos", "duration": "0min", "details": "VEILLE DE COURSE • Repos total, alimentation glucides", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
        ]
    else:  # build, intensification
        sessions = [
            {"day": "Lundi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Étirements recommandés", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Mardi", "type": "Endurance", "duration": "50min", "details": f"8 km • {paces['z2']}/km • FC {hr_zones['z2']} bpm • Zone 2 stricte", "intensity": "easy", "estimated_tss": 50, "distance_km": 8},
            {"day": "Mercredi", "type": "Seuil", "duration": "40min", "details": f"7 km dont 20min à {paces['z4']}/km • FC {hr_zones['z4']} bpm • Récup 2min entre blocs", "intensity": "hard", "estimated_tss": 55, "distance_km": 7},
            {"day": "Jeudi", "type": "Récupération", "duration": "30min", "details": f"5 km très léger • {paces['z1']}/km • FC <{hr_zones['z1'].split('-')[1]} bpm max", "intensity": "easy", "estimated_tss": 25, "distance_km": 5},
            {"day": "Vendredi", "type": "Repos", "duration": "0min", "details": "Récupération complète • Cross-training possible (vélo, natation)", "intensity": "rest", "estimated_tss": 0, "distance_km": 0},
            {"day": "Samedi", "type": "Tempo", "duration": "45min", "details": f"8 km dont 25min à {paces['semi']}/km • FC {hr_zones['z3']} bpm • Allure semi-marathon", "intensity": "moderate", "estimated_tss": 60, "distance_km": 8},
            {"day": "Dimanche", "type": "Sortie longue", "duration": "70min", "details": f"12 km progressif • {paces['z2']}/km → {paces['z3']}/km • FC {hr_zones['z2']} → {hr_zones['z3']} bpm", "intensity": "moderate", "estimated_tss": 45, "distance_km": 12},
        ]
    
    total_tss = sum(s["estimated_tss"] for s in sessions)
    total_km = sum(s.get("distance_km", 0) for s in sessions)
    
    return {
        "focus": phase,
        "planned_load": target_load,
        "weekly_km": round(total_km, 1),
        "sessions": sessions,
        "total_tss": total_tss,
        "advice": get_phase_description(phase).get("advice", "Continue sur ta lancée !")
    }


@api_router.get("/subscription/tiers")
async def get_subscription_tiers():
    """Get all available subscription tiers"""
    tiers = []
    for tier_id, config in SUBSCRIPTION_TIERS.items():
        tiers.append(SubscriptionTierInfo(
            id=tier_id,
            name=config["name"],
            price_monthly=config["price_monthly"],
            price_annual=config["price_annual"],
            messages_limit=config["messages_limit"],
            unlimited=config.get("unlimited", False),
            description=config["description"]
        ))
    return tiers


@api_router.get("/subscription/status")
async def get_subscription_status(user_id: str = "default"):
    """Check user's subscription status"""
    
    # Check subscription in DB
    subscription = await db.subscriptions.find_one(
        {"user_id": user_id},
        {"_id": 0}
    )
    
    # Default to free tier
    tier = "free"
    tier_config = SUBSCRIPTION_TIERS["free"]
    is_premium = False
    billing_period = None
    expires_at = None
    subscription_id = None
    
    if subscription and subscription.get("status") == "active":
        expires_at = subscription.get("expires_at")
        
        # Check if subscription is still valid
        if expires_at:
            try:
                exp_date = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if exp_date < datetime.now(timezone.utc):
                    # Subscription expired - revert to free
                    await db.subscriptions.update_one(
                        {"user_id": user_id},
                        {"$set": {"status": "expired"}}
                    )
                else:
                    # Active subscription
                    tier = subscription.get("tier", "starter")
                    tier_config = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS["starter"])
                    is_premium = True
                    billing_period = subscription.get("billing_period", "monthly")
                    subscription_id = subscription.get("subscription_id")
            except (ValueError, TypeError):
                pass

    # Get message count for current month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    message_count = await db.chat_messages.count_documents({
        "user_id": user_id,
        "role": "user",
        "timestamp": {"$gte": month_start.isoformat()}
    })

    messages_limit = tier_config.get("messages_limit", 10)
    is_unlimited = tier_config.get("unlimited", False)
    
    return SubscriptionStatusResponse(
        tier=tier,
        tier_name=tier_config["name"],
        is_premium=is_premium,
        subscription_id=subscription_id,
        billing_period=billing_period,
        expires_at=expires_at,
        messages_used=message_count,
        messages_limit=messages_limit,
        messages_remaining=max(0, messages_limit - message_count) if not is_unlimited else 999,
        is_unlimited=is_unlimited
    )


# Keep old endpoint for backward compatibility
@api_router.get("/premium/status")
async def get_premium_status(user_id: str = "default"):
    """Check if user has active premium subscription (backward compat)"""
    status = await get_subscription_status(user_id)
    return {
        "is_premium": status.is_premium or status.tier != "free",
        "subscription_id": status.subscription_id,
        "expires_at": status.expires_at,
        "messages_used": status.messages_used,
        "messages_remaining": status.messages_remaining,
        "tier": status.tier,
        "tier_name": status.tier_name,
        "messages_limit": status.messages_limit,
        "is_unlimited": status.is_unlimited
    }


@api_router.post("/subscription/checkout", response_model=CreateCheckoutResponse)
async def create_subscription_checkout(request: CreateCheckoutRequest, http_request: Request, user_id: str = "default"):
    """Create Stripe checkout session for subscription"""
    
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    # Validate tier
    if request.tier not in ["starter", "confort", "pro"]:
        raise HTTPException(status_code=400, detail="Invalid subscription tier")
    
    tier_config = SUBSCRIPTION_TIERS[request.tier]
    
    # Get price based on billing period
    if request.billing_period == "annual":
        amount = tier_config["price_annual"]
    else:
        amount = tier_config["price_monthly"]
    
    # Build URLs
    success_url = f"{request.origin_url}/settings?session_id={{CHECKOUT_SESSION_ID}}&subscription=success"
    cancel_url = f"{request.origin_url}/settings?subscription=cancelled"
    
    # Initialize Stripe
    webhook_url = f"{str(http_request.base_url)}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    # Create checkout session
    checkout_request = CheckoutSessionRequest(
        amount=amount,
        currency="eur",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
            "product": f"cardiocoach_{request.tier}",
            "tier": request.tier,
            "billing_period": request.billing_period,
            "type": "subscription"
        }
    )
    
    try:
        session = await stripe_checkout.create_checkout_session(checkout_request)
        
        # Record transaction as pending
        await db.payment_transactions.insert_one({
            "session_id": session.session_id,
            "user_id": user_id,
            "amount": amount,
            "currency": "eur",
            "tier": request.tier,
            "billing_period": request.billing_period,
            "status": "pending",
            "product": f"cardiocoach_{request.tier}",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Checkout session created for user {user_id}: {request.tier} ({request.billing_period})")
        
        return CreateCheckoutResponse(
            checkout_url=session.url,
            session_id=session.session_id
        )
    
    except Exception as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create checkout: {str(e)}")


# Keep old endpoint for backward compatibility
@api_router.post("/premium/checkout", response_model=CreateCheckoutResponse)
async def create_premium_checkout_compat(request: CreateCheckoutRequest, http_request: Request, user_id: str = "default"):
    """Create Stripe checkout session (backward compat)"""
    # Convert old request to new format - default to starter monthly
    new_request = CreateCheckoutRequest(
        origin_url=request.origin_url,
        tier=getattr(request, 'tier', 'starter'),
        billing_period=getattr(request, 'billing_period', 'monthly')
    )
    return await create_subscription_checkout(new_request, http_request, user_id)


@api_router.get("/subscription/checkout/status/{session_id}")
async def check_subscription_status(session_id: str, http_request: Request, user_id: str = "default"):
    """Check status of a checkout session and activate subscription if paid"""
    
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    # Check if already processed
    existing = await db.payment_transactions.find_one({"session_id": session_id})
    if existing and existing.get("status") == "completed":
        return {"status": "completed", "message": "Already processed"}
    
    # Initialize Stripe
    webhook_url = f"{str(http_request.base_url)}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    try:
        status = await stripe_checkout.get_checkout_status(session_id)
        
        if status.payment_status == "paid":
            # Get tier and billing from transaction
            transaction = await db.payment_transactions.find_one({"session_id": session_id})
            actual_user_id = transaction.get("user_id", user_id) if transaction else user_id
            tier = transaction.get("tier", "starter") if transaction else "starter"
            billing_period = transaction.get("billing_period", "monthly") if transaction else "monthly"
            
            # Update transaction
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {
                    "status": "completed",
                    "payment_status": status.payment_status,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            # Calculate expiration (30 days for monthly, 365 for annual)
            days = 365 if billing_period == "annual" else 30
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            
            # Create/update subscription
            await db.subscriptions.update_one(
                {"user_id": actual_user_id},
                {"$set": {
                    "user_id": actual_user_id,
                    "subscription_id": session_id,
                    "tier": tier,
                    "billing_period": billing_period,
                    "status": "active",
                    "amount": transaction.get("amount") if transaction else 0,
                    "currency": "eur",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": expires_at
                }},
                upsert=True
            )
            
            tier_name = SUBSCRIPTION_TIERS.get(tier, {}).get("name", "Starter")
            logger.info(f"Subscription activated for user {actual_user_id}: {tier} ({billing_period})")
            
            return {
                "status": "completed",
                "payment_status": status.payment_status,
                "tier": tier,
                "message": f"Abonnement {tier_name} activé ! Bienvenue dans CardioCoach."
            }
        
        elif status.payment_status == "unpaid":
            return {"status": "pending", "payment_status": status.payment_status}
        
        else:
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"status": status.payment_status}}
            )
            return {"status": status.status, "payment_status": status.payment_status}
    
    except Exception as e:
        logger.error(f"Checkout status error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check status: {str(e)}")


# Backward compat endpoint
@api_router.get("/premium/checkout/status/{session_id}")
async def check_checkout_status_compat(session_id: str, http_request: Request, user_id: str = "default"):
    """Check checkout status (backward compat)"""
    return await check_subscription_status(session_id, http_request, user_id)


@api_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    body = await request.body()
    signature = request.headers.get("Stripe-Signature")
    
    webhook_url = f"{str(request.base_url)}api/webhook/stripe"
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    try:
        webhook_response = await stripe_checkout.handle_webhook(body, signature)
        
        logger.info(f"Stripe webhook: {webhook_response.event_type} - {webhook_response.session_id}")
        
        if webhook_response.payment_status == "paid":
            # Activate premium (same logic as checkout status)
            user_id = webhook_response.metadata.get("user_id", "default")
            
            await db.payment_transactions.update_one(
                {"session_id": webhook_response.session_id},
                {"$set": {
                    "status": "completed",
                    "payment_status": "paid",
                    "webhook_event": webhook_response.event_type,
                    "completed_at": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            await db.subscriptions.update_one(
                {"user_id": user_id},
                {"$set": {
                    "status": "active",
                    "expires_at": expires_at
                }},
                upsert=True
            )
        
        return {"received": True}
    
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")


# ========== CHAT COACH (PREMIUM ONLY) ==========

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

@api_router.post("/chat/send", response_model=ChatResponse)
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
        context = build_chat_context(workouts, user_goal)
        
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
        
        # Générer des suggestions si LLM utilisé et pas de suggestions
        if used_llm and not suggestions:
            suggestions = [
                "Comment équilibrer mes zones d'entraînement ?",
                f"Comment améliorer mon allure de {context.get('allure', '6:00')}/km ?",
                "Quels exercices de renforcement faire ?",
                "Comment travailler plus en endurance fondamentale ?"
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


@api_router.post("/chat/store-response")
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


@api_router.get("/chat/history")
async def get_chat_history(user_id: str = "default", limit: int = 50):
    """Get chat history for a user"""
    
    messages = await db.chat_messages.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    # Reverse to chronological order
    messages.reverse()
    
    return messages


@api_router.delete("/chat/history")
async def clear_chat_history(user_id: str = "default"):
    """Clear chat history for a user"""
    
    result = await db.chat_messages.delete_many({"user_id": user_id})
    
    logger.info(f"Chat history cleared for user {user_id}: {result.deleted_count} messages")
    
    return {"success": True, "deleted_count": result.deleted_count}


@api_router.get("/cache/stats")
async def get_coach_cache_stats():
    """Get coach service cache statistics"""
    return get_cache_stats()


@api_router.delete("/cache/clear")
async def clear_coach_cache():
    """Clear all coach service caches"""
    result = clear_cache()
    logger.info(f"Cache cleared: {result}")
    return {"success": True, **result}


@api_router.get("/metrics")
async def get_service_metrics():
    """Get coach service metrics (LLM success rate, latency, etc.)"""
    return {
        "coach": get_coach_metrics(),
        "cache": get_cache_stats()
    }


@api_router.delete("/metrics/reset")
async def reset_service_metrics():
    """Reset coach service metrics"""
    old_metrics = reset_coach_metrics()
    logger.info(f"Metrics reset. Previous: {old_metrics}")
    return {"success": True, "previous": old_metrics}


# Include the router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def create_db_indexes():
    """Create MongoDB indexes for common query patterns"""
    try:
        # Workouts: filter + sort by user and date
        await db.workouts.create_index([("user_id", 1), ("date", -1)])
        await db.workouts.create_index([("id", 1)], sparse=True)
        # Conversations / chat messages
        await db.conversations.create_index([("user_id", 1), ("timestamp", 1)])
        await db.chat_messages.create_index([("user_id", 1), ("timestamp", 1)])
        # OAuth state store: auto-expire after TTL (expires_at stored as datetime)
        await db.oauth_states.create_index("state", unique=True)
        await db.oauth_states.create_index("expires_at", expireAfterSeconds=0)
        # Subscriptions / tokens
        await db.subscriptions.create_index("user_id", sparse=True)
        await db.strava_tokens.create_index("user_id", sparse=True)
        await db.garmin_tokens.create_index("user_id", sparse=True)
        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning(f"Could not create some MongoDB indexes: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
