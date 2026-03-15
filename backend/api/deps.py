import os
from fastapi import Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

security = HTTPBearer(auto_error=False)

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
