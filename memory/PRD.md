# CardioCoach - Product Requirements Document

## Original Problem Statement
Application de coaching sportif personnalisé pour les sports d'endurance (course à pied, vélo). L'application doit:
- Se connecter à Strava pour récupérer les données d'entraînement réelles de l'utilisateur
- Générer des plans d'entraînement personnalisés et adaptatifs basés sur l'IA (GPT-4o-mini)
- Afficher un tableau de bord avec les métriques de forme, volume d'entraînement et séances planifiées
- Permettre à l'utilisateur de choisir son objectif (5K, 10K, Semi, Marathon, Ultra)
- Adapter le volume et le nombre de séances en fonction du niveau de l'athlète
- Système d'abonnement avec essai gratuit, accès limité et offre Early Adopter

## User Personas
- **Coureur amateur**: Cherche un coach virtuel pour progresser et atteindre ses objectifs de course
- **Cycliste/Triathlete**: Utilise l'app pour le suivi de ses entraînements multi-sports
- **Utilisateur Strava**: Souhaite synchroniser ses données existantes pour un suivi personnalisé

## Core Requirements
1. ✅ Intégration Strava fonctionnelle avec données réelles
2. ✅ Générateur de plan d'entraînement adaptatif (LLM-driven)
3. ✅ Dashboard avec métriques de forme et statistiques hebdomadaires
4. ✅ Sélecteur d'objectif (5K, 10K, Semi, Marathon, Ultra)
5. ✅ Sélecteur du nombre de séances par semaine (3-6)
6. ✅ Affichage de la séance du jour sur le Dashboard
7. ✅ Navigation avec 4 onglets (Accueil, Coach, Plan, Réglages)
8. ✅ Coach IA conversationnel (GPT-4o-mini)
9. ✅ Prédictions de course avec VMA
10. ✅ Système d'abonnement (trial/free/early_adopter)
11. ✅ Intégration Stripe pour les paiements

## Architecture
- **Backend**: FastAPI + MongoDB + LiteLLM (GPT-4o-mini)
- **Frontend**: React + Tailwind CSS + Shadcn/UI
- **Integrations**: Strava OAuth, OpenAI via Emergent LLM Key, Stripe Payments

## Subscription System
- **trial**: 7 jours d'essai gratuit avec accès complet
- **free**: Accès limité après fin d'essai (paywall bloque les fonctionnalités premium)
- **early_adopter**: 4,99€/mois (prix garanti à vie) - Accès complet
- **premium**: Réservé pour le futur

## What's Been Implemented

### 2026-03-07 (Current Session)
- **Intégration Stripe complète pour Early Adopter**:
  - Frontend: `Paywall.jsx` et `Settings.jsx` appellent l'endpoint Stripe Checkout
  - Backend: `/api/subscription/early-adopter/checkout` crée une session Stripe (4.99€)
  - Backend: `/api/webhook/stripe/early-adopter` reçoit la confirmation de paiement
  - Backend: `/api/subscription/verify-checkout/{session_id}` active le statut early_adopter
  - Fix du montant Stripe (float au lieu d'int pour emergentintegrations)
  - Tests complets: 18/18 backend + 15/15 frontend passés

### Previous Sessions
- **Système d'abonnement** (trial/free/early_adopter) avec middleware de protection
- **Coach IA conversationnel** avec GPT-4o-mini et contexte utilisateur
- **Prédictions de course** avec calcul VMA précis
- **Métriques ACWR/TSB** sur le dashboard
- **Analyse des séances** avec graphiques pace/km
- **Navigation simplifiée** (4 onglets)
- **Carte "Aujourd'hui"** sur le Dashboard
- **Plan multi-semaines** avec vue complète du cycle

## Key Files
- `/app/frontend/src/pages/Settings.jsx` - Page paramètres avec section abonnement
- `/app/frontend/src/components/Paywall.jsx` - Composant paywall avec CTA Stripe
- `/app/frontend/src/context/SubscriptionContext.jsx` - Gestion état abonnement
- `/app/backend/server.py` - API endpoints (6600+ lignes)
- `/app/backend/subscription_manager.py` - Logique métier abonnements
- `/app/backend/llm_coach.py` - Coach IA conversationnel

## Key API Endpoints
- `GET /api/subscription/info` - Statut d'abonnement complet
- `POST /api/subscription/early-adopter/checkout` - Créer session Stripe
- `GET /api/subscription/verify-checkout/{session_id}` - Vérifier paiement
- `POST /api/coach/v2/chat` - Chat conversationnel IA
- `GET /api/training/race-predictions` - Prédictions de course
- `GET /api/training/plan` - Plan d'entraînement

## Prioritized Backlog
### P0 (Critical)
- ✅ Intégration Stripe pour abonnement Early Adopter

### P1 (High Priority)
- Aucun item haute priorité en attente

### P2 (Medium Priority)
- Tier "premium" avec fonctionnalités avancées
- Prédictions de course avec temps réels de l'utilisateur (formule de Riegel)
- Refactoring de server.py en modules séparés (/app/backend/routes/)

### P3 (Future/Backlog)
- Historique des plans d'entraînement
- Notifications push pour les rappels de séances
- Export des données au format GPX/TCX
- Mode sombre/clair toggle
- Intégration Garmin Connect
