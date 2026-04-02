# CardioCoach - Product Requirements Document

## Original Problem Statement
CardioCoach is a full-stack AI-powered sports coaching app for endurance athletes (running, cycling). It features dynamic training plans, VMA/VO2MAX estimations, race predictions, readiness scores (Terra API integration), conversational AI coach, subscription paywalls, and multilingual support (EN/FR/ES).

## User Personas
- **Endurance Athletes**: Runners and cyclists looking for personalized training plans
- **Goal-Oriented Users**: Athletes training for specific races (5K, 10K, Semi, Marathon)

## Core Requirements
1. Dashboard with physiological data visualization
2. Training plan generation and tracking
3. VMA/VO2MAX estimation and history
4. Race time predictions based on fitness level
5. AI Coach for conversational guidance
6. Subscription management (with DEMO_MODE for testing)
7. Multilingual support (EN/FR/ES)

## Architecture
```
/app/
├── backend/
│   ├── api/                 # API routers (dashboard.py, mock_runner.py)
│   ├── engine/              # Physiological engines (readiness, training load)
│   ├── services/            # Orchestration layer (adaptation_engine.py)
│   ├── demo_mode.py         # Paywall bypass patch
│   ├── server.py            # Main FastAPI app
│   ├── terra_integration.py # Wearables integration
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/      # UI Components (Layout, LanguageSelector)
│   │   ├── context/         # React Contexts (Language, Subscription)
│   │   ├── lib/             # Utilities (i18n.js)
│   │   ├── pages/           # Pages (Dashboard, Progress, TrainingPlan, Coach)
│   │   ├── config.js        # Environment config loader
│   │   └── App.js
│   ├── package.json
│   └── tailwind.config.js
```

## Key API Endpoints
- `GET /api/dashboard` - Main dashboard data
- `GET /api/mock-runner` - Dynamic fallback demo data
- `GET /api/mock-runner/vma-history` - VMA history mock data
- `GET /api/mock-runner/race-predictions` - Race predictions mock data
- `GET /api/training/vma-history` - Real VMA history
- `GET /api/training/race-predictions` - Real race predictions

## 3rd Party Integrations
- **Terra API**: Wearable data aggregation (requires user API key)
- **Stripe**: Payments (requires API key, currently bypassed via DEMO_MODE)
- **OpenAI GPT-4o-mini**: AI Coach via LiteLLM (uses Emergent LLM Key)

## Tech Stack
- Frontend: React 19, Tailwind CSS, Shadcn UI, i18n
- Backend: FastAPI, Python, MongoDB
- External: Terra API

---

# Changelog

## 2025-04-02
- **Fixed Dashboard translations**: Added 16 new i18n keys for metrics section (todaysMetrics, hrvDeviation, restingHR, etc.) in EN/FR/ES
- **Fixed Coach LLM chat**: Added missing `EMERGENT_LLM_KEY` to backend .env - chat now works with GPT-4.1-mini
- Fixed rate limiting (burst 10→30, requests/min 60→120) for SPA parallel API calls
- VMA and Race Predictions now display correctly in Progress tab using mock fallback data
- Git pull successful - repo already up to date with PR #38

## Previous Session
- Translated entire codebase from French to English
- Removed Strava & Garmin integrations, transitioned to Terra API
- Cleaned up ~5000 lines of dead code
- Added mock_runner.py for dynamic fallback demo data
- Added DEMO_MODE to bypass subscription paywalls
- Added Spanish (ES) translation support
- Fixed "Domain: undefined" API errors via config.js

---

# Roadmap

## P0 (Critical) - Completed
- ✅ VMA/Race Predictions display in Progress tab
- ✅ Demo mode with mock data
- ✅ Multilingual support (EN/FR/ES)

## P1 (High Priority) - Backlog
- Real Terra API integration (requires user API key)
- Stripe payment integration (requires API key)
- User authentication system

## P2 (Nice to Have)
- Custom training plan editor
- Social sharing of achievements
- Export data to CSV/PDF
