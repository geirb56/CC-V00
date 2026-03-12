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
7. ✅ Navigation avec 5 onglets (Accueil, Plan, Progression, Coach, Réglages)
8. ✅ Coach IA conversationnel (GPT-4o-mini)
9. ✅ Prédictions de course avec VMA
10. ✅ Système d'abonnement (trial/free/early_adopter)
11. ✅ Intégration Stripe pour les paiements
12. ✅ **Plan d'entraînement dynamique avec allures personnalisées basées sur la VMA**

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

### 2026-03-12 (Session actuelle)
- **Plan d'entraînement dynamique avec VMA**:
  - Allures personnalisées (Z1-Z5, marathon, semi) calculées à partir de la VMA
  - VMA estimée via moyenne glissante sur 6 semaines d'entraînement
  - Score de préparation (readiness_score: 0-100) basé sur volume (60%) et forme (40%)
  - Adaptation de la durée de préparation selon le niveau:
    - Avancé (≥90%): -25% semaines
    - Normal (≥70%): durée standard
    - Progressif (≥50%): +25% semaines
    - Débutant (<50%): +50% semaines
  - Zones d'allure: Z1 (65-70% VMA), Z2 (75-80%), Z3 (82-87%), Z4 (88-93%), Z5 (95-100%)
  - Affichage des allures personnalisées dans les détails des séances
  - Tests complets: 20/20 backend + 12/12 frontend passés

### 2026-03-07 (Session précédente)
- **Intégration Stripe complète pour Early Adopter**:
  - Frontend: `Paywall.jsx` et `Settings.jsx` appellent l'endpoint Stripe Checkout
  - Backend: `/api/subscription/early-adopter/checkout` crée une session Stripe (4.99€)
  - Backend: `/api/webhook/stripe/early-adopter` reçoit la confirmation de paiement
  - Backend: `/api/subscription/verify-checkout/{session_id}` active le statut early_adopter
  - Tests complets: 18/18 backend + 15/15 frontend passés

- **Déplacement des sélecteurs vers Réglages**:
  - Nouvelle section "Plan d'entraînement" dans Settings.jsx
  - Sélecteur d'objectif (5K, 10K, Semi-Marathon, Marathon, Ultra-Trail)
  - Sélecteur de séances par semaine (3, 4, 5, 6)

- **Création de la page Progression**:
  - Ajout de l'onglet "Progression" dans la navigation (5 onglets total)
  - Graphique VO2MAX sur 12 mois avec moyenne glissante 6 semaines
  - Prédictions de course par distance

### Sessions précédentes
- **Système d'abonnement** (trial/free/early_adopter) avec middleware de protection
- **Coach IA conversationnel** avec GPT-4o-mini et contexte utilisateur enrichi
- **Métriques ACWR/TSB** sur le dashboard
- **Analyse des séances** avec graphiques pace/km
- **Plan multi-semaines** avec vue complète du cycle

## Key Files
- `/app/backend/coach_service.py` - **generate_dynamic_training_plan()** avec calcul VMA et allures
- `/app/backend/llm_coach.py` - **generate_cycle_week()** avec allures personnalisées dans le prompt
- `/app/frontend/src/pages/TrainingPlan.jsx` - Affichage des séances avec détails d'allure
- `/app/frontend/src/pages/Progress.jsx` - Graphique VO2MAX et prédictions
- `/app/backend/server.py` - API endpoints (7000+ lignes)
- `/app/backend/subscription_manager.py` - Logique métier abonnements

## Key API Endpoints
- `GET /api/training/plan` - Plan avec VMA, allures personnalisées, readiness_score
- `POST /api/training/refresh` - Régénérer le plan avec nouvelles allures
- `GET /api/training/full-cycle` - Aperçu complet du cycle multi-semaines
- `GET /api/training/vma-history` - Historique VO2MAX sur 12 mois
- `GET /api/training/race-predictions` - Prédictions basées sur VMA 6 semaines
- `POST /api/coach/v2/chat` - Chat conversationnel IA
- `POST /api/subscription/early-adopter/checkout` - Session Stripe

## Prioritized Backlog
### P0 (Critical)
- ✅ Plan d'entraînement dynamique avec allures personnalisées

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
