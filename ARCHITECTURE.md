# CardioCoach — Architecture de l'application

## Vue d'ensemble

**CardioCoach** est une application de coaching sportif personnalisé pour les sports d'endurance (course à pied, vélo). Elle synchronise les données Strava de l'athlète et génère des plans d'entraînement adaptatifs pilotés par l'IA.

```
┌─────────────────────────────────────────────────────┐
│                    Utilisateur                       │
│            (navigateur / PWA mobile)                 │
└──────────────────────┬──────────────────────────────┘
                       │  HTTP / REST
┌──────────────────────▼──────────────────────────────┐
│              Frontend (React + Tailwind)             │
│              Port 3000  –  /frontend                 │
└──────────────────────┬──────────────────────────────┘
                       │  Axios
┌──────────────────────▼──────────────────────────────┐
│             Backend (FastAPI + Python)               │
│              Port 8001  –  /backend                  │
│  ┌────────────┐ ┌───────────┐ ┌──────────────────┐  │
│  │ coach_     │ │ training_ │ │ subscription_    │  │
│  │ service.py │ │ engine.py │ │ manager.py       │  │
│  └────────────┘ └───────────┘ └──────────────────┘  │
│  ┌────────────┐ ┌───────────┐ ┌──────────────────┐  │
│  │ llm_coach. │ │ rag_      │ │ analysis_        │  │
│  │ py         │ │ engine.py │ │ engine.py        │  │
│  └────────────┘ └───────────┘ └──────────────────┘  │
│  ┌────────────┐                                      │
│  │ chat_      │                                      │
│  │ engine.py  │                                      │
│  └────────────┘                                      │
└──────────────────────┬──────────────────────────────┘
                       │
      ┌────────────────┼────────────────────┐
      │                │                    │
┌─────▼──────┐  ┌──────▼──────┐  ┌─────────▼────────┐
│  MongoDB   │  │  Strava API  │  │  OpenAI / Stripe │
│ (Motor)    │  │  (OAuth 2)   │  │  (LLM + Paiement)│
└────────────┘  └─────────────┘  └──────────────────┘
```

---

## Structure des répertoires

```
CC-V00/
├── backend/                   # API Python (FastAPI)
│   ├── server.py              # Point d'entrée principal — tous les endpoints REST
│   ├── coach_service.py       # Orchestration coaching (cache + cascade LLM)
│   ├── llm_coach.py           # Appels GPT-4o-mini (analyses, plans, chat)
│   ├── analysis_engine.py     # Analyses déterministes sans LLM
│   ├── training_engine.py     # Périodisation, ACWR, TSB, phases
│   ├── rag_engine.py          # RAG déterministe (enrichissement contexte)
│   ├── chat_engine.py         # Chat 100 % Python (sans LLM, hors-ligne)
│   ├── subscription_manager.py# Logique métier abonnements
│   ├── knowledge_base.json    # Base de connaissances statique (running)
│   ├── requirements.txt       # Dépendances Python
│   ├── docs/
│   │   └── LLM_OLLAMA.md      # Documentation Ollama (LLM local optionnel)
│   └── tests/                 # Tests unitaires backend (pytest)
│       ├── conftest.py
│       ├── test_coach_conversational.py
│       ├── test_dashboard_insight.py
│       ├── test_detailed_analysis.py
│       ├── test_enhanced_goal.py
│       ├── test_mobile_workout_analysis.py
│       ├── test_new_features.py
│       ├── test_rag_endpoints.py
│       ├── test_rag_enrichment.py
│       ├── test_strava_integration.py
│       ├── test_subscription.py
│       ├── test_subscription_chat.py
│       ├── test_training_plan_vma.py
│       ├── test_weekly_digest.py
│       └── test_weekly_review.py
│
├── frontend/                  # Application React (Create React App + CRACO)
│   ├── public/
│   │   ├── index.html         # Shell HTML
│   │   ├── manifest.json      # Manifeste PWA
│   │   ├── sw.js              # Service Worker (mode hors-ligne)
│   │   ├── offline.html       # Page hors-ligne PWA
│   │   └── icons/             # Icônes PWA (72 → 512 px)
│   ├── src/
│   │   ├── index.js           # Point d'entrée React
│   │   ├── App.js             # Routing principal (React Router)
│   │   ├── pages/             # Pages / vues principales
│   │   │   ├── Dashboard.jsx  # Tableau de bord (métriques, séance du jour)
│   │   │   ├── TrainingPlan.jsx # Plan d'entraînement multi-semaines
│   │   │   ├── Progress.jsx   # Graphique VO2max & prédictions de course
│   │   │   ├── Coach.jsx      # Chat IA conversationnel
│   │   │   ├── WorkoutDetail.jsx  # Détail d'une séance
│   │   │   ├── DetailedAnalysis.jsx # Analyse détaillée avec graphiques
│   │   │   ├── Guidance.jsx   # Conseils et recommandations
│   │   │   ├── Digest.jsx     # Bilan hebdomadaire
│   │   │   ├── Settings.jsx   # Réglages (objectif, séances/semaine)
│   │   │   └── Subscription.jsx # Gestion de l'abonnement
│   │   ├── components/        # Composants réutilisables
│   │   │   ├── Layout.jsx     # Mise en page + navigation (5 onglets)
│   │   │   ├── ChatCoach.jsx  # Interface de chat
│   │   │   ├── CoachMessage.jsx # Bulle de message coach
│   │   │   ├── GoalSection.jsx # Sélecteur d'objectif
│   │   │   ├── MetricCard.jsx # Carte d'une métrique
│   │   │   ├── WorkoutCard.jsx # Carte d'une séance
│   │   │   ├── RecoveryGauge.jsx # Jauge de récupération
│   │   │   ├── RAGSummary.jsx # Résumé enrichi par RAG
│   │   │   ├── StravaConnection.jsx # Connexion Strava OAuth
│   │   │   ├── Paywall.jsx    # Écran payant (abonnement)
│   │   │   ├── PremiumBadge.jsx # Badge abonné
│   │   │   ├── LanguageSelector.jsx # Sélecteur FR / EN
│   │   │   ├── LoadingSpinner.jsx # Indicateur de chargement
│   │   │   ├── IOSPWAHint.jsx # Hint installation PWA iOS
│   │   │   └── ui/            # Bibliothèque shadcn/ui (composants génériques)
│   │   ├── context/           # Contextes React globaux
│   │   │   ├── LanguageContext.jsx   # Langue (FR / EN)
│   │   │   ├── SubscriptionContext.jsx # État de l'abonnement
│   │   │   └── UnitContext.jsx       # Unités (km / miles)
│   │   ├── hooks/             # Hooks personnalisés
│   │   │   ├── useWorkouts.js # Chargement des séances
│   │   │   ├── useSettings.js # Persistance des réglages
│   │   │   ├── useAutoSync.js # Synchronisation automatique Strava
│   │   │   └── use-toast.js   # Notifications (toast)
│   │   ├── lib/
│   │   │   ├── i18n.js        # Traductions FR / EN
│   │   │   └── utils.js       # Utilitaires Tailwind (cn)
│   │   ├── utils/
│   │   │   ├── constants.js   # Constantes (API_URL, etc.)
│   │   │   ├── units.js       # Conversion d'unités
│   │   │   └── workoutHelpers.js # Helpers de calcul séances
│   │   └── styles/
│   │       └── theme-modern.css # Thème visuel
│   ├── package.json           # Dépendances JS
│   ├── tailwind.config.js     # Configuration Tailwind CSS
│   ├── craco.config.js        # Surcharge Create React App
│   └── plugins/               # Plugins Webpack internes
│       ├── health-check/      # Endpoint de santé dev
│       └── visual-edits/      # Métadonnées d'édition visuelle
│
├── tests/                     # Tests end-to-end (Playwright)
│   ├── e2e/
│   │   ├── paywall.spec.ts
│   │   ├── subscription.spec.ts
│   │   └── training-plan-vma.spec.ts
│   ├── fixtures/helpers.ts
│   └── playwright.config.ts
│
├── memory/
│   └── PRD.md                 # Product Requirements Document
├── config.py                  # Configuration globale partagée
├── design_guidelines.json     # Charte graphique
└── test_reports/              # Rapports de tests générés
```

---

## Backend — Modules clés

### `server.py` — Routeur principal
Point d'entrée FastAPI. Contient l'ensemble des endpoints REST et le middleware d'authentification/abonnement. Délègue la logique métier aux modules spécialisés.

**Principaux groupes d'endpoints :**

| Préfixe | Rôle |
|---|---|
| `/api/strava/*` | OAuth Strava, synchronisation des activités |
| `/api/training/*` | Plan d'entraînement, VMA, historique, cycle |
| `/api/coach/v2/chat` | Chat conversationnel IA |
| `/api/dashboard/*` | Métriques de forme (ACWR, TSB, insight) |
| `/api/workout/*` | Analyse d'une séance |
| `/api/subscription/*` | Gestion de l'abonnement, checkout Stripe |
| `/api/webhook/stripe/*` | Webhook de confirmation de paiement |
| `/api/rag/*` | Endpoints enrichis par RAG |

### `coach_service.py` — Orchestration coaching
Applique une stratégie en cascade :
1. **Cache** (0 ms) — résultats déjà calculés
2. **Analyse déterministe** via `rag_engine` (< 1 s)
3. **Enrichissement LLM** via `llm_coach` (~ 500 ms, si clé API configurée)

### `llm_coach.py` — Interface GPT-4o-mini
Appels au modèle GPT-4o-mini via la clé `EMERGENT_LLM_KEY`. Génère les analyses personnalisées, le bilan hebdomadaire et le plan d'entraînement. Si la clé n'est pas configurée, retourne `(None, False, metadata)` sans erreur.

### `analysis_engine.py` — Analyses déterministes
Calculs 100 % Python, sans appel externe. Détermine l'intensité d'une séance, formate les métriques, génère des textes de coaching à partir de templates variés. Priorité aux données de fréquence cardiaque quand elles sont disponibles.

### `training_engine.py` — Périodisation
Calcule :
- **ACWR** (Acute:Chronic Workload Ratio) — ratio de charge aiguë/chronique
- **TSB** (Training Stress Balance) — fraîcheur de l'athlète
- **Phase** du cycle (Build, Intensification, Taper, Race)
- **VMA** estimée (moyenne glissante 6 semaines)
- **Allures cibles** par zone (Z1 → Z5, marathon, semi)

### `rag_engine.py` — RAG déterministe
Enrichit les réponses avec des données contextuelles issues de `knowledge_base.json` (conseils running, nutrition, récupération). Aucun appel LLM, totalement déterministe.

### `chat_engine.py` — Chat hors-ligne
Répond aux messages de l'utilisateur sans LLM, en utilisant la classification par mots-clés et des templates de réponses variés. Garantit une expérience fluide même sans connexion API.

### `subscription_manager.py` — Abonnements
Gère les statuts : `trial` (7 jours) → `free` (limité) → `early_adopter` (4,99 €/mois). Expose `has_feature_access()` pour protéger les fonctionnalités premium.

---

## Frontend — Organisation

### Navigation (5 onglets)
| Route | Page | Onglet |
|---|---|---|
| `/` | `Dashboard.jsx` | 🏠 Accueil |
| `/training` | `TrainingPlan.jsx` | 📅 Plan |
| `/progress` | `Progress.jsx` | 📈 Progression |
| `/coach` | `Coach.jsx` | 💬 Coach |
| `/settings` | `Settings.jsx` | ⚙️ Réglages |

### Contextes globaux
- **LanguageContext** — langue de l'interface (FR / EN)
- **SubscriptionContext** — statut de l'abonnement, accès aux fonctionnalités
- **UnitContext** — système de mesure (km / miles)

---

## Stack technique

| Couche | Technologie |
|---|---|
| Frontend | React 19, React Router 7, Tailwind CSS 3, shadcn/ui, Recharts |
| Backend | Python 3, FastAPI, Uvicorn, Motor (MongoDB async) |
| Base de données | MongoDB |
| IA / LLM | GPT-4o-mini via `emergentintegrations` (clé `EMERGENT_LLM_KEY`) |
| Intégration sport | Strava OAuth 2.0 |
| Paiement | Stripe Checkout (via `emergentintegrations`) |
| Tests backend | pytest |
| Tests E2E | Playwright (TypeScript) |
| PWA | Service Worker, manifest.json, mode hors-ligne |

---

## Système d'abonnement

```
Inscription
    │
    ▼
[trial]  ──── 7 jours accès complet ────►  [free]  (fonctionnalités limitées)
                                                │
                                                │  Paiement Stripe (4,99 €/mois)
                                                ▼
                                      [early_adopter]  (accès complet à vie)
```

Les fonctionnalités protégées (plan d'entraînement, analyse de séances, sync Strava) sont bloquées pour le statut `free` ; un paywall s'affiche alors via `Paywall.jsx`.

---

## Flux de données principal

```
1. L'utilisateur connecte son compte Strava (OAuth 2.0)
2. Le backend récupère les activités via l'API Strava et les stocke en MongoDB
3. Au chargement du Dashboard, le backend calcule ACWR, TSB et l'insight du jour
4. Sur la page Plan, coach_service génère le plan hebdomadaire :
   a. Estimation de la VMA à partir des 6 dernières semaines
   b. Calcul des allures cibles (Z1–Z5) à partir de la VMA
   c. Génération du plan par GPT-4o-mini (ou fallback déterministe)
5. Sur la page Coach, les messages sont traités par :
   a. chat_engine (déterministe, hors-ligne) → réponse immédiate
   b. llm_coach (GPT-4o-mini) → enrichissement si clé API disponible
6. Les paiements Early Adopter passent par Stripe Checkout, confirmés via webhook
```
