from fastapi import APIRouter, HTTPException, Depends, Request, Query
from typing import Optional
import logging
import os
import json
from datetime import datetime, timezone, timedelta

from database import db
from models import CreateCheckoutRequest, CreateCheckoutResponse, SubscriptionStatusResponse, SubscriptionTierInfo, SubscriptionInfo, ActivateSubscriptionRequest
from api.deps import auth_user, auth_user_optional, SUBSCRIPTION_TIERS
from subscription_manager import get_user_subscription, activate_early_adopter, cancel_subscription, get_trial_days_remaining, get_subscription_display, SubscriptionStatus, FEATURES, EARLY_ADOPTER_PRICE
from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionResponse, CheckoutStatusResponse, CheckoutSessionRequest

router = APIRouter()
logger = logging.getLogger(__name__)

STRIPE_API_KEY = os.environ.get('STRIPE_API_KEY', '')


@router.get("/subscription/tiers")
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


@router.get("/subscription/status")
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
@router.get("/premium/status")
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


@router.post("/subscription/checkout", response_model=CreateCheckoutResponse)
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
@router.post("/premium/checkout", response_model=CreateCheckoutResponse)
async def create_premium_checkout_compat(request: CreateCheckoutRequest, http_request: Request, user_id: str = "default"):
    """Create Stripe checkout session (backward compat)"""
    # Convert old request to new format - default to starter monthly
    new_request = CreateCheckoutRequest(
        origin_url=request.origin_url,
        tier=getattr(request, 'tier', 'starter'),
        billing_period=getattr(request, 'billing_period', 'monthly')
    )
    return await create_subscription_checkout(new_request, http_request, user_id)


@router.get("/subscription/checkout/status/{session_id}")
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
@router.get("/premium/checkout/status/{session_id}")
async def check_checkout_status_compat(session_id: str, http_request: Request, user_id: str = "default"):
    """Check checkout status (backward compat)"""
    return await check_subscription_status(session_id, http_request, user_id)


@router.post("/webhook/stripe")
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


@router.get("/subscription/info")
async def get_subscription_info(user_id: str = "default", language: str = "en"):
    """
    Retrieves complete subscription information for a user.
    
    Returns:
    - status: trial, free, early_adopter, premium
    - display: Localized UI texts
    - features: Accessible features
    - trial_days_remaining: Remaining days if in trial
    """
    subscription = await get_user_subscription(db, user_id)
    status = subscription.get("status", SubscriptionStatus.FREE)
    
    return {
        "user_id": user_id,
        "status": status,
        "display": get_subscription_display(subscription, language),
        "features": FEATURES.get(status, FEATURES[SubscriptionStatus.FREE]),
        "trial_days_remaining": get_trial_days_remaining(subscription),
        "price_locked": subscription.get("price_locked"),
        "stripe_customer_id": subscription.get("stripe_customer_id"),
        "created_at": subscription.get("created_at"),
        "activated_at": subscription.get("activated_at")
    }


@router.post("/subscription/activate-early-adopter")
async def activate_early_adopter_subscription(request: ActivateSubscriptionRequest):
    """
    Active l'abonnement Early Adopter pour un utilisateur.
    Prix garanti à vie: 4.99€/mois
    
    Appelé après un paiement Stripe réussi.
    """
    subscription = await activate_early_adopter(
        db,
        request.user_id,
        request.stripe_customer_id or f"cus_simulated_{request.user_id}",
        request.stripe_subscription_id or f"sub_simulated_{request.user_id}"
    )
    
    return {
        "success": True,
        "status": subscription.get("status"),
        "message": "Abonnement Early Adopter activé ! Prix garanti à vie: 4.99€/mois",
        "subscription": subscription
    }


@router.post("/subscription/cancel")
async def cancel_user_subscription(user_id: str = "default"):
    """
    Annule l'abonnement d'un utilisateur.
    Le statut passe à 'free'.
    """
    subscription = await cancel_subscription(db, user_id)
    
    return {
        "success": True,
        "status": subscription.get("status"),
        "message": "Abonnement annulé"
    }


@router.post("/subscription/simulate-trial-end")
async def simulate_trial_end(user_id: str = "default"):
    """
    [DEV ONLY] Simule la fin de l'essai gratuit pour tester le paywall.
    """
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "trial_end": datetime.now(timezone.utc).isoformat(),
                "status": SubscriptionStatus.FREE
            }
        }
    )
    
    return {
        "success": True,
        "message": "Essai terminé, utilisateur passé en FREE"
    }


@router.post("/subscription/reset-to-trial")
async def reset_to_trial(user_id: str = "default"):
    """
    [DEV ONLY] Remet l'utilisateur en essai gratuit de 7 jours.
    """
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=7)
    
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.TRIAL,
                "trial_start": now.isoformat(),
                "trial_end": trial_end.isoformat(),
                "updated_at": now.isoformat()
            }
        },
        upsert=True
    )
    
    return {
        "success": True,
        "message": f"Essai gratuit réactivé jusqu'au {trial_end.isoformat()}"
    }


@router.get("/subscription/early-adopter-offer")
async def get_early_adopter_offer(language: str = "en"):
    """
    Retourne les détails de l'offre Early Adopter.
    """
    if language == "fr":
        return {
            "title": "Active ton coach running",
            "subtitle": "Ton plan d'entraînement personnalisé est prêt",
            "description": "Active ton abonnement pour y accéder.",
            "offer_name": "Early Adopter",
            "price": EARLY_ADOPTER_PRICE,
            "price_display": f"{EARLY_ADOPTER_PRICE:.2f} € / mois",
            "price_guarantee": "Prix garanti à vie",
            "features": [
                "Plan d'entraînement personnalisé",
                "Adaptation automatique du plan",
                "Analyse intelligente des séances",
                "Coach IA conversationnel",
                "Synchronisation montres/apps",
                "Prédictions de course"
            ],
            "cta_button": "Activer mon coach",
            "trial_cta": "Profite de ton essai gratuit"
        }
    else:
        return {
            "title": "Activate your running coach",
            "subtitle": "Your personalized training plan is ready",
            "description": "Activate your subscription to access it.",
            "offer_name": "Early Adopter",
            "price": EARLY_ADOPTER_PRICE,
            "price_display": f"€{EARLY_ADOPTER_PRICE:.2f} / month",
            "price_guarantee": "Price guaranteed for life",
            "features": [
                "Personalized training plan",
                "Automatic plan adaptation",
                "Smart session analysis",
                "AI conversational coach",
                "Watch/app synchronization",
                "Race predictions"
            ],
            "cta_button": "Activate my coach",
            "trial_cta": "Enjoy your free trial"
        }


@router.post("/subscription/early-adopter/checkout")
async def create_early_adopter_checkout(http_request: Request, user_id: str = "default", origin_url: str = None):
    """
    Crée une session Stripe Checkout pour l'offre Early Adopter.
    Prix: 4.99€/mois, garanti à vie.
    """
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    # Déterminer l'URL d'origine
    if not origin_url:
        origin_url = str(http_request.base_url).rstrip('/')
        # En preview, utiliser l'URL frontend
        if "preview.emergentagent.com" in origin_url:
            origin_url = origin_url.replace("/api", "").rstrip('/')
    
    # URLs de redirection
    success_url = f"{origin_url}/settings?session_id={{CHECKOUT_SESSION_ID}}&subscription=early_adopter_success"
    cancel_url = f"{origin_url}/settings?subscription=cancelled"
    
    # Webhook URL
    webhook_url = f"{str(http_request.base_url).rstrip('/')}/api/webhook/stripe/early-adopter"
    
    # Initialiser Stripe
    stripe_checkout = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)
    
    # Créer la session checkout
    checkout_request = CheckoutSessionRequest(
        amount=float(EARLY_ADOPTER_PRICE),  # En euros (format float requis par Stripe Emergent)
        currency="eur",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "user_id": user_id,
            "product": "cardiocoach_early_adopter",
            "price_locked": str(EARLY_ADOPTER_PRICE),
            "type": "subscription",
            "plan": "early_adopter"
        }
    )
    
    try:
        session = await stripe_checkout.create_checkout_session(checkout_request)
        
        # Enregistrer la transaction en attente
        await db.payment_transactions.insert_one({
            "session_id": session.session_id,
            "user_id": user_id,
            "amount": EARLY_ADOPTER_PRICE,
            "currency": "eur",
            "plan": "early_adopter",
            "status": "pending",
            "product": "cardiocoach_early_adopter",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Early Adopter checkout session created for user {user_id}: {session.session_id}")
        
        return {
            "checkout_url": session.url,
            "session_id": session.session_id
        }
    
    except Exception as e:
        logger.error(f"Early Adopter Stripe checkout error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create checkout: {str(e)}")


@router.post("/webhook/stripe/early-adopter")
async def stripe_early_adopter_webhook(request: Request):
    """
    Webhook Stripe pour les paiements Early Adopter.
    Active l'abonnement une fois le paiement confirmé.
    """
    try:
        payload = await request.body()
        event = json.loads(payload)
        
        event_type = event.get("type", "")
        logger.info(f"Early Adopter webhook received: {event_type}")
        
        if event_type == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            metadata = session.get("metadata", {})
            
            user_id = metadata.get("user_id", "default")
            session_id = session.get("id")
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")
            
            # Activer l'abonnement Early Adopter
            await activate_early_adopter(
                db,
                user_id,
                customer_id or f"cus_{session_id}",
                subscription_id or f"sub_{session_id}"
            )
            
            # Mettre à jour la transaction
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "status": "completed",
                        "stripe_customer_id": customer_id,
                        "stripe_subscription_id": subscription_id,
                        "completed_at": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
            
            logger.info(f"Early Adopter activated for user {user_id}")
        
        return {"received": True}
    
    except Exception as e:
        logger.error(f"Early Adopter webhook error: {e}")
        return {"received": True, "error": str(e)}


@router.get("/subscription/verify-checkout/{session_id}")
async def verify_checkout_session(session_id: str, user_id: str = "default"):
    """
    Vérifie le statut d'une session checkout et active l'abonnement si payé.
    Appelé par le frontend après retour de Stripe.
    """
    try:
        # Vérifier la transaction
        transaction = await db.payment_transactions.find_one({"session_id": session_id})
        
        if not transaction:
            return {"success": False, "error": "Session not found"}
        
        if transaction.get("status") == "completed":
            # Déjà traité
            subscription = await get_user_subscription(db, user_id)
            return {
                "success": True,
                "status": subscription.get("status"),
                "already_processed": True
            }
        
        # Pour les tests, activer directement si la session existe
        # En production, cela serait vérifié via l'API Stripe
        if transaction.get("plan") == "early_adopter":
            await activate_early_adopter(
                db,
                user_id,
                f"cus_{session_id}",
                f"sub_{session_id}"
            )
            
            await db.payment_transactions.update_one(
                {"session_id": session_id},
                {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
            )
            
            return {
                "success": True,
                "status": "early_adopter",
                "message": "Abonnement Early Adopter activé !"
            }
        
        return {"success": False, "error": "Unknown plan"}
    
    except Exception as e:
        logger.error(f"Verify checkout error: {e}")
        return {"success": False, "error": str(e)}
