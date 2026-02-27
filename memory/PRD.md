# CardioCoach - Product Requirements Document

## Original Problem Statement
Application de coaching sportif personnalisé pour les sports d'endurance (course à pied, vélo). L'application doit:
- Se connecter à Strava pour récupérer les données d'entraînement réelles de l'utilisateur
- Générer des plans d'entraînement personnalisés et adaptatifs basés sur l'IA (GPT-4o-mini)
- Afficher un tableau de bord avec les métriques de forme, volume d'entraînement et séances planifiées
- Permettre à l'utilisateur de choisir son objectif (5K, 10K, Semi, Marathon, Ultra)
- Adapter le volume et le nombre de séances en fonction du niveau de l'athlète

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
7. ✅ Navigation avec 5 onglets (Accueil, Analyse, Plan, Abo, Réglages)

## Architecture
- **Backend**: FastAPI + MongoDB + LiteLLM (GPT-4o-mini)
- **Frontend**: React + Tailwind CSS + Shadcn/UI
- **Integrations**: Strava OAuth, OpenAI via Emergent LLM Key

## What's Been Implemented

### 2025-02-27
- **Carte "Aujourd'hui" sur le Dashboard**: Affiche maintenant la séance planifiée du jour actuel
  - Récupère les données du plan d'entraînement via `/api/training/plan`
  - Identifie le jour actuel et trouve la séance correspondante
  - Affiche les jours de repos avec un message approprié ("Jour de repos")
  - Affiche les séances d'entraînement avec type, durée, distance, allure cible et détails

### Sessions précédentes
- Synchronisation avec le repo Git "V2"
- Refonte visuelle complète du Dashboard et de la page Plan
- Correction de l'intégration Strava (données réelles vs mock)
- Plan d'entraînement avec détails (km, allure, FC cible)
- Correction de la logique du plan (volume, jours de repos)
- Volume adaptatif basé sur l'objectif et l'historique de l'athlète
- Intégration des données scientifiques de volume minimum
- Sélecteur du nombre de séances (3, 4, 5, 6)
- Ajout des onglets "Abonnement" et "Paramètres"

## Key Files
- `/app/frontend/src/pages/Dashboard.jsx` - Dashboard principal avec carte "Aujourd'hui"
- `/app/frontend/src/pages/TrainingPlan.jsx` - Page du plan d'entraînement
- `/app/backend/server.py` - API endpoints
- `/app/backend/coach_service.py` - Logique de génération de plan adaptatif
- `/app/backend/llm_coach.py` - Prompts LLM pour la génération de plans

## Key API Endpoints
- `GET /api/workouts` - Récupère les séances de l'utilisateur
- `GET /api/training/plan` - Génère/récupère le plan d'entraînement hebdomadaire
- `POST /api/training/refresh?sessions=N` - Régénère le plan avec N séances
- `GET /api/strava/status` - Statut de connexion Strava

## Prioritized Backlog
### P0 (Critical)
- Aucun item critique en attente

### P1 (High Priority)
- Aucun item haute priorité en attente

### P2 (Medium Priority)
- Page "Abonnement" - Contenu et intégration Stripe
- Page "Paramètres" - Préférences utilisateur

### P3 (Future/Backlog)
- Historique des plans d'entraînement
- Notifications push pour les rappels de séances
- Export des données au format GPX/TCX
- Mode sombre/clair toggle
