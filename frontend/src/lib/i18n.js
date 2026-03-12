export const LANGUAGE_STORAGE_KEY = "cardiocoach_lang";

export const translations = {
  en: {
    // Navigation
    nav: {
      dashboard: "Dashboard",
      training: "Training",
      digest: "Review",
      guidance: "Guidance",
      coach: "Coach",
      progress: "Progress",
      subscription: "Plans",
      settings: "Settings",
      tagline: "Elite Endurance Analysis",
    },
    
    // Dashboard
    dashboard: {
      title: "Dashboard",
      thisWeek: "This Week",
      lastMonth: "Last 30 Days",
      sessions: "Sessions",
      km: "km",
      activeWeeks: "Active Weeks",
      recentWorkouts: "Recent Workouts",
      viewAll: "View All",
      recovery: "Recovery",
      recoveryScore: "Recovery Score",
      load: {
        label: "Load",
        low: "Low",
        balanced: "Balanced",
        high: "High",
      },
      trend: {
        up: "Up",
        stable: "Stable",
        down: "Down",
      },
    },
    
    // Workout types
    workoutTypes: {
      run: "Run",
      cycle: "Cycle",
      swim: "Swim",
    },
    
    // Workout detail
    workout: {
      back: "Back",
      avgHeartRate: "Avg Heart Rate",
      maxHeartRate: "Max Heart Rate",
      avgPace: "Avg Pace",
      avgSpeed: "Avg Speed",
      elevation: "Elevation",
      calories: "Calories",
      effortDistribution: "Effort Distribution",
      notes: "Notes",
      analyzeWithCoach: "Analyze with Coach",
      notFound: "Workout not found.",
      zones: {
        z1: "Z1 Recovery",
        z2: "Z2 Aerobic",
        z3: "Z3 Tempo",
        z4: "Z4 Threshold",
        z5: "Z5 VO2Max",
      },
    },
    
    // Workout Analysis (Mobile)
    analysis: {
      intensity: "Intensity",
      load: "Load",
      type: "Type",
      pace: "Pace",
      speed: "Speed",
      avgHr: "Avg HR",
      hrZones: "Heart Rate Zones",
      coachInsight: "Coach",
      viewDetailedAnalysis: "View detailed analysis",
      askCoach: "Ask the coach",
      load_up: "Higher",
      load_down: "Lower",
      labels: {
        above_usual: "Above usual",
        below_usual: "Below usual",
        normal: "Normal",
      },
      session_types: {
        easy: "Easy",
        sustained: "Sustained",
        hard: "Hard",
      },
    },
    
    // Heart Rate Zones
    zones: {
      recovery: "Recovery",
      endurance: "Endurance",
      tempo: "Tempo",
      threshold: "Threshold",
      max: "VO2max",
      easy: "Easy",
      moderate: "Moderate",
      hard: "Hard",
      dominant_easy: "Easy effort",
      dominant_balanced: "Balanced",
      dominant_hard: "High intensity",
    },
    
    // Detailed Analysis
    detailedAnalysis: {
      title: "Detailed Analysis",
      loading: "Analyzing...",
      execution: "Execution",
      intensity: "Intensity",
      volume: "Volume",
      regularity: "Regularity",
      meaning: "What it means",
      recovery: "Recovery",
      advice: "Coach Advice",
      advanced: "Go further",
      askCoach: "Ask the coach",
    },
    
    // Coach
    coach: {
      title: "Coach",
      subtitle: "Performance Analysis",
      placeholder: "Ask about your training...",
      emptyState: "Ask about your training data. Zone distribution. Pace patterns. Recovery metrics.",
      you: "You",
      suggestions: {
        trainingLoad: "Analyze training load",
        heartRate: "Heart rate patterns",
        paceConsistency: "Pace consistency",
      },
      error: "Analysis failed. Check connection.",
      unavailable: "Unable to process request.",
      analyzing: "Analyzing...",
      thinking: "Thinking...",
      workoutAnalyzed: "Workout analyzed",
      historyClear: "History cleared",
    },
    
    // Progress
    progress: {
      title: "Progress",
      subtitle: "Training Trends",
      totalVolume: "Total Volume",
      kilometers: "kilometers",
      sessions: "Sessions",
      workouts: "workouts",
      byType: "By Type",
      dailyDistance: "Daily Distance",
      allWorkouts: "All Workouts",
      vmaEstimate: "VMA / VO2max Estimate",
      vma: "VMA",
      vo2max: "VO2max",
      confidence: "Confidence",
      dataSource: "Data source",
      trainingZones: "Training Zones",
      insufficientData: "Insufficient Data",
      confidenceLevels: {
        high: "High",
        medium: "Medium",
        low: "Low",
        insufficient: "Insufficient"
      }
    },
    
    // Guidance
    guidance: {
      title: "Guidance",
      subtitle: "Adaptive Training",
      suggestedSessions: "Suggested Sessions",
      disclaimer: "Guidance only. Not a fixed plan.",
      status: {
        maintain: "Maintain",
        adjust: "Adjust",
        hold_steady: "Hold Steady",
      },
    },
    
    // Settings
    settings: {
      title: "Settings",
      subtitle: "Preferences",
      language: "Language",
      languageDesc: "Select your preferred language",
      english: "English",
      french: "French",
      spanish: "Spanish",
      about: "About",
      aboutDesc: "CardioCoach is an elite endurance coaching tool for runners and cyclists. This is not a medical application.",
      version: "Version",
      dataSync: "Data Sync",
      dataSyncDesc: "Connect your fitness account to import workouts automatically",
      connected: "Connected",
      notConnected: "Not connected",
      connect: "Connect Account",
      disconnect: "Disconnect",
      sync: "Sync Now",
      lastSync: "Last sync",
      workouts: "Imported",
      goal: "Training Goal",
      goalDesc: "Set a target event to get personalized recommendations",
      eventName: "Event name",
      eventDate: "Event date",
      distance: "Distance",
      targetTime: "Target time",
      targetTimeDesc: "Leave empty if no specific goal",
      saveGoal: "Save goal",
      deleteGoal: "Delete",
      noGoal: "No goal set",
      goalSaved: "Goal saved",
      goalDeleted: "Goal deleted",
      daysUntil: "days until",
      targetPace: "Target pace",
      distances: {
        "5k": "5 km",
        "10k": "10 km",
        "semi": "Half Marathon",
        "marathon": "Marathon",
        "ultra": "Ultra Trail"
      },
    },
    
    // Weekly Review
    digest: {
      title: "Weekly Review",
      generating: "Generating review...",
      noData: "No training data this week.",
      sessions: "Sessions",
      km: "KM",
      hours: "Hours",
      coachSummary: "Coach Summary",
      coachReading: "Coach Reading",
      recommendations: "Recommendations",
      recommendationsFollowup: "Last week's advice",
      essentialNumbers: "Essential Numbers",
      vsLastWeek: "vs last week",
      askCoach: "Ask the coach",
      goalContext: "Training for",
      signals: {
        load: "Volume",
        intensity: "Intensity",
        consistency: "Regularity",
      },
      intensity: {
        hard: "High",
        easy: "Easy",
        balanced: "Balanced",
      },
      load: {
        up: "Up",
        down: "Down",
        stable: "Stable",
      },
      regularity: {
        high: "Good",
        moderate: "Moderate",
        low: "Low",
      },
    },
    
    // Common
    common: {
      loading: "Loading...",
      error: "Error",
      save: "Save",
      cancel: "Cancel",
    },
    
    // Date formatting
    dateFormat: {
      locale: "en-US",
      weekday: "long",
      month: "short",
      day: "numeric",
      year: "numeric",
    },
  },
  
  fr: {
    // Navigation
    nav: {
      dashboard: "Tableau de bord",
      training: "Entrainement",
      digest: "Bilan",
      guidance: "Recommandations",
      coach: "Coach",
      progress: "Progression",
      subscription: "Abonnement",
      settings: "Parametres",
      tagline: "Analyse Endurance Elite",
    },
    
    // Dashboard
    dashboard: {
      title: "Tableau de bord",
      thisWeek: "Cette semaine",
      lastMonth: "30 derniers jours",
      sessions: "Séances",
      km: "km",
      activeWeeks: "Semaines actives",
      recentWorkouts: "Séances récentes",
      viewAll: "Tout voir",
      recovery: "Recuperation",
      recoveryScore: "Score de recuperation",
      load: {
        label: "Charge",
        low: "Faible",
        balanced: "Équilibrée",
        high: "Élevée",
      },
      trend: {
        up: "Hausse",
        stable: "Stable",
        down: "Baisse",
      },
    },
    
    // Workout types
    workoutTypes: {
      run: "Course",
      cycle: "Velo",
      swim: "Natation",
    },
    
    // Workout detail
    workout: {
      back: "Retour",
      avgHeartRate: "FC Moyenne",
      maxHeartRate: "FC Max",
      avgPace: "Allure Moy",
      avgSpeed: "Vitesse Moy",
      elevation: "Denivele",
      calories: "Calories",
      effortDistribution: "Distribution de l'effort",
      notes: "Notes",
      analyzeWithCoach: "Analyser avec Coach",
      notFound: "Seance introuvable.",
      zones: {
        z1: "Z1 Recuperation",
        z2: "Z2 Aerobie",
        z3: "Z3 Tempo",
        z4: "Z4 Seuil",
        z5: "Z5 VO2Max",
      },
    },
    
    // Workout Analysis (Mobile)
    analysis: {
      intensity: "Intensite",
      load: "Charge",
      type: "Type",
      pace: "Allure",
      speed: "Vitesse",
      avgHr: "FC Moy",
      hrZones: "Zones Cardiaques",
      coachInsight: "Coach",
      viewDetailedAnalysis: "Voir l'analyse detaillee",
      askCoach: "Poser une question au coach",
      load_up: "Elevee",
      load_down: "Reduite",
      labels: {
        above_usual: "Au-dessus habituel",
        below_usual: "En-dessous habituel",
        normal: "Normal",
      },
      session_types: {
        easy: "Facile",
        sustained: "Soutenu",
        hard: "Difficile",
      },
    },
    
    // Heart Rate Zones
    zones: {
      recovery: "Recup",
      endurance: "Endurance",
      tempo: "Tempo",
      threshold: "Seuil",
      max: "VO2max",
      easy: "Facile",
      moderate: "Modere",
      hard: "Intense",
      dominant_easy: "Effort facile",
      dominant_balanced: "Equilibre",
      dominant_hard: "Haute intensite",
    },
    
    // Detailed Analysis
    detailedAnalysis: {
      title: "Analyse Detaillee",
      loading: "Analyse en cours...",
      execution: "Execution",
      intensity: "Intensite",
      volume: "Volume",
      regularity: "Regularite",
      meaning: "Ce que ca signifie",
      recovery: "Recuperation",
      advice: "Conseil Coach",
      advanced: "Pour aller plus loin",
      askCoach: "Poser une question au coach",
    },
    
    // Coach
    coach: {
      title: "Coach",
      subtitle: "Analyse de Performance",
      placeholder: "Posez une question sur votre entrainement...",
      emptyState: "Interrogez vos donnees d'entrainement. Distribution des zones. Patterns d'allure. Metriques de recuperation.",
      you: "Vous",
      suggestions: {
        trainingLoad: "Analyser la charge",
        heartRate: "Patterns cardiaque",
        paceConsistency: "Regularite d'allure",
      },
      error: "Analyse echouee. Verifiez la connexion.",
      unavailable: "Impossible de traiter la demande.",
      analyzing: "Analyse en cours...",
      thinking: "Reflexion...",
      workoutAnalyzed: "Seance analysee",
      historyClear: "Historique efface",
    },
    
    // Progress
    progress: {
      title: "Progression",
      subtitle: "Tendances d'entrainement",
      totalVolume: "Volume Total",
      kilometers: "kilometres",
      sessions: "Seances",
      workouts: "entrainements",
      byType: "Par Type",
      dailyDistance: "Distance Quotidienne",
      allWorkouts: "Toutes les seances",
      vmaEstimate: "Estimation VMA / VO2max",
      vma: "VMA",
      vo2max: "VO2max",
      confidence: "Fiabilite",
      dataSource: "Source des donnees",
      trainingZones: "Zones d'entrainement",
      insufficientData: "Donnees insuffisantes",
      confidenceLevels: {
        high: "Elevee",
        medium: "Correcte",
        low: "Limitee",
        insufficient: "Insuffisante"
      }
    },
    
    // Guidance
    guidance: {
      title: "Recommandations",
      subtitle: "Entrainement Adaptatif",
      suggestedSessions: "Seances Suggerees",
      disclaimer: "Recommandations uniquement. Pas un plan fixe.",
      status: {
        maintain: "Maintenir",
        adjust: "Ajuster",
        hold_steady: "Consolider",
      },
    },
    
    // Settings
    settings: {
      title: "Parametres",
      subtitle: "Preferences",
      language: "Langue",
      languageDesc: "Selectionnez votre langue preferee",
      english: "Anglais",
      french: "Francais",
      spanish: "Espagnol",
      about: "A propos",
      aboutDesc: "CardioCoach est un outil de coaching endurance elite pour coureurs et cyclistes. Ceci n'est pas une application medicale.",
      version: "Version",
      dataSync: "Synchronisation",
      dataSyncDesc: "Connectez votre compte fitness pour importer vos seances automatiquement",
      connected: "Connecte",
      notConnected: "Non connecte",
      connect: "Connecter un compte",
      disconnect: "Deconnecter",
      sync: "Synchroniser",
      lastSync: "Derniere synchro",
      workouts: "Importees",
      goal: "Objectif",
      goalDesc: "Definis un evenement cible pour des recommandations personnalisees",
      eventName: "Nom de l'evenement",
      eventDate: "Date de l'evenement",
      distance: "Distance",
      targetTime: "Temps vise",
      targetTimeDesc: "Laisser vide si pas d'objectif precis",
      saveGoal: "Enregistrer",
      deleteGoal: "Supprimer",
      noGoal: "Aucun objectif defini",
      goalSaved: "Objectif enregistre",
      goalDeleted: "Objectif supprime",
      daysUntil: "jours avant",
      targetPace: "Allure cible",
      distances: {
        "5k": "5 km",
        "10k": "10 km",
        "semi": "Semi-marathon",
        "marathon": "Marathon",
        "ultra": "Ultra Trail"
      },
    },
    
    // Weekly Review (Bilan de la semaine)
    digest: {
      title: "Bilan de la semaine",
      generating: "Generation du bilan...",
      noData: "Aucune donnee cette semaine.",
      sessions: "Seances",
      km: "KM",
      hours: "Heures",
      coachSummary: "Synthese du coach",
      coachReading: "Lecture du coach",
      recommendations: "Preconisations",
      recommendationsFollowup: "Conseil de la semaine derniere",
      essentialNumbers: "Chiffres essentiels",
      vsLastWeek: "vs semaine precedente",
      askCoach: "Poser une question au coach",
      goalContext: "Preparation pour",
      signals: {
        load: "Volume",
        intensity: "Intensite",
        consistency: "Regularite",
      },
      intensity: {
        hard: "Soutenue",
        easy: "Legere",
        balanced: "Equilibree",
      },
      load: {
        up: "Hausse",
        down: "Baisse",
        stable: "Stable",
      },
      regularity: {
        high: "Bonne",
        moderate: "Moyenne",
        low: "Faible",
      },
    },
    
    // Common
    common: {
      loading: "Chargement...",
      error: "Erreur",
      save: "Enregistrer",
      cancel: "Annuler",
    },
    
    // Date formatting
    dateFormat: {
      locale: "fr-FR",
      weekday: "long",
      month: "short",
      day: "numeric",
      year: "numeric",
    },
  },
  
  // Spanish - currently uses English for most strings via fallback,
  // with specific labels for the language settings section.
  es: {
    settings: {
      title: "Settings",
      subtitle: "Preferences",
      language: "Language",
      languageDesc: "Select your preferred language",
      english: "Inglés",
      french: "Francés",
      spanish: "Español",
      about: "About",
      aboutDesc:
        "CardioCoach is an elite endurance coaching tool for runners and cyclists. This is not a medical application.",
      version: "Version",
      dataSync: "Data Sync",
      dataSyncDesc: "Connect your fitness account to import workouts automatically",
      connected: "Connected",
      notConnected: "Not connected",
      connect: "Connect Account",
      disconnect: "Disconnect",
      sync: "Sync Now",
      lastSync: "Last sync",
      workouts: "Imported",
      goal: "Training Goal",
      goalDesc: "Set a target event to get personalized recommendations",
      eventName: "Event name",
      eventDate: "Event date",
      distance: "Distance",
      targetTime: "Target time",
      targetTimeDesc: "Leave empty if no specific goal",
      saveGoal: "Save goal",
      deleteGoal: "Delete",
      noGoal: "No goal set",
      goalSaved: "Goal saved",
      goalDeleted: "Goal deleted",
      daysUntil: "days until",
      targetPace: "Target pace",
      distances: {
        "5k": "5 km",
        "10k": "10 km",
        semi: "Half Marathon",
        marathon: "Marathon",
        ultra: "Ultra Trail",
      },
    },
    common: {
      loading: "Loading...",
      error: "Error",
      save: "Save",
      cancel: "Cancel",
    },
    dateFormat: {
      locale: "en-US",
      weekday: "long",
      month: "short",
      day: "numeric",
      year: "numeric",
    },
  },
};

export const getAppLanguage = () => {
  // 1) User preference (localStorage)
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
      if (stored && translations[stored]) {
        return stored;
      }
    } catch {
      // Ignore storage errors and continue to detection
    }

    // 2) Device / browser language
    const browserLang =
      (window.navigator.language || window.navigator.userLanguage || "").toLowerCase();

    if (browserLang.startsWith("fr")) return "fr";
    if (browserLang.startsWith("es")) return "es";
    if (browserLang.startsWith("en")) return "en";
  }

  // 3) Default to English
  return "en";
};

export const getTranslation = (lang, path) => {
  const keys = path.split(".");
  let result = translations[lang];
  for (const key of keys) {
    if (result && result[key] !== undefined) {
      result = result[key];
    } else {
      // Fallback to English
      result = translations.en;
      for (const k of keys) {
        if (result && result[k] !== undefined) {
          result = result[k];
        } else {
          return path; // Return path if not found
        }
      }
      break;
    }
  }
  return result;
};
