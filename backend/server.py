from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Dict

from database import db, client
from subscription_manager import (
    get_user_subscription,
    is_route_protected,
    SubscriptionStatus,
)

from api.workouts import router as workouts_router
from api.training import router as training_router
from api.coach import router as coach_router
from api.chat import router as chat_router
from api.rag import router as rag_router
from api.strava import router as strava_router
from api.subscription import router as subscription_router
from api.dashboard import router as dashboard_router

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create the main app
app = FastAPI()

# GZip compression for responses > 1KB
app.add_middleware(GZipMiddleware, minimum_size=1000)


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


@app.middleware("http")
async def subscription_middleware(request: Request, call_next):
    """Middleware de vérification d'abonnement.

    Bloque l'accès aux routes protégées pour les utilisateurs 'free'.
    Les utilisateurs 'trial', 'early_adopter' et 'premium' ont accès complet.
    """
    path = request.url.path

    # Skip non-API requests
    if not path.startswith("/api"):
        return await call_next(request)

    # Skip public routes (subscription, auth, health, etc.)
    if not is_route_protected(path):
        return await call_next(request)

    # Get user ID
    user_id = get_user_id_from_request(request)

    try:
        # Get subscription status
        subscription = await get_user_subscription(db, user_id)
        status = subscription.get("status", SubscriptionStatus.FREE)

        # Check if user has access
        if status == SubscriptionStatus.FREE:
            logger.info(f"[Subscription] Blocked {path} for FREE user {user_id}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "subscription_required",
                    "message": "Abonnement requis pour accéder à cette fonctionnalité",
                    "message_en": "Subscription required to access this feature",
                    "status": status,
                    "upgrade_url": "/subscription"
                }
            )

        # Store subscription in request state for later use
        request.state.subscription = subscription

    except Exception as e:
        logger.error(f"[Subscription] Error checking subscription: {e}")
        # En cas d'erreur, on laisse passer (fail open)

    return await call_next(request)


# Include all routers
app.include_router(workouts_router, prefix="/api")
app.include_router(training_router, prefix="/api")
app.include_router(coach_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(rag_router, prefix="/api")
app.include_router(strava_router, prefix="/api")
app.include_router(subscription_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")

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
