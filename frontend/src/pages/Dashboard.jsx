import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { useLanguage } from "@/context/LanguageContext";
import { 
  TrendingUp,
  ChevronRight,
  Bike,
  Zap,
  Flame,
  Play,
  RefreshCw,
  Loader2,
  Heart,
  Timer,
  Activity
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Workout type configuration
const WORKOUT_TYPES = {
  fractionne: { 
    label: "Fractionné", 
    color: "#8b5cf6",
    bgClass: "workout-icon fractionne",
    icon: Zap
  },
  endurance: { 
    label: "Endurance", 
    color: "#3b82f6",
    bgClass: "workout-icon endurance",
    icon: Activity
  },
  seuil: { 
    label: "Seuil", 
    color: "#f97316",
    bgClass: "workout-icon seuil",
    icon: Flame
  },
  recuperation: { 
    label: "Récupération", 
    color: "#14b8a6",
    bgClass: "workout-icon recuperation",
    icon: Heart
  },
  run: { 
    label: "Course", 
    color: "#3b82f6",
    bgClass: "workout-icon endurance",
    icon: Activity
  },
  cycle: { 
    label: "Vélo", 
    color: "#f97316",
    bgClass: "workout-icon seuil",
    icon: Bike
  }
};

const formatDuration = (minutes) => {
  if (!minutes) return "--";
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) return `${hrs}h${mins.toString().padStart(2, '0')}`;
  return `${mins}min`;
};

const formatPace = (paceMinKm) => {
  if (!paceMinKm) return "--";
  const mins = Math.floor(paceMinKm);
  const secs = Math.round((paceMinKm - mins) * 60);
  return `${mins}:${secs.toString().padStart(2, '0')}/km`;
};

const getRelativeDate = (dateStr, lang) => {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  
  if (date.toDateString() === today.toDateString()) {
    return lang === "fr" ? "Aujourd'hui" : "Today";
  }
  if (date.toDateString() === yesterday.toDateString()) {
    return lang === "fr" ? "Hier" : "Yesterday";
  }
  return date.toLocaleDateString(lang === "fr" ? "fr-FR" : "en-US", { 
    day: "numeric", 
    month: "short" 
  });
};

// Circular Gauge Component
function CircularGauge({ value, max = 100, size = 64 }) {
  const strokeWidth = 5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const progress = (value / max) * circumference;

  return (
    <div className="circular-gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className="gauge-bg"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          className="gauge-progress"
        />
      </svg>
      <div className="gauge-text">{value}%</div>
    </div>
  );
}

// Mini Line Chart Component
function MiniLineChart({ data = [] }) {
  if (!data.length) return null;
  
  const width = 280;
  const height = 60;
  const padding = 10;
  
  const maxVal = Math.max(...data);
  const minVal = Math.min(...data);
  const range = maxVal - minVal || 1;
  
  const points = data.map((val, i) => {
    const x = padding + (i / (data.length - 1)) * (width - 2 * padding);
    const y = height - padding - ((val - minVal) / range) * (height - 2 * padding);
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg width={width} height={height} className="mt-2">
      <defs>
        <linearGradient id="lineGradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="var(--accent-violet)" stopOpacity="0.3" />
          <stop offset="100%" stopColor="var(--accent-violet)" />
        </linearGradient>
      </defs>
      <polyline
        points={points}
        fill="none"
        stroke="url(#lineGradient)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Dashboard() {
  const [insight, setInsight] = useState(null);
  const [workouts, setWorkouts] = useState([]);
  const [todaySession, setTodaySession] = useState(null);
  const [loading, setLoading] = useState(true);
  const { t, lang } = useLanguage();
  const fetchedRef = useRef(false);
  const lastLangRef = useRef(lang);

  // Mapping des jours FR vers index
  const dayMapping = {
    "Lundi": 1, "Mardi": 2, "Mercredi": 3, "Jeudi": 4,
    "Vendredi": 5, "Samedi": 6, "Dimanche": 0
  };

  useEffect(() => {
    if (fetchedRef.current && lastLangRef.current === lang) {
      return;
    }
    fetchedRef.current = true;
    lastLangRef.current = lang;
    fetchData();
  }, [lang]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [insightRes, workoutsRes, ragRes, planRes] = await Promise.all([
        axios.get(`${API}/dashboard/insight?language=${lang}`),
        axios.get(`${API}/workouts`),
        axios.get(`${API}/rag/dashboard`).catch(() => ({ data: null })),
        axios.get(`${API}/training/plan`, { headers: { "X-User-Id": "default" } }).catch(() => ({ data: null }))
      ]);
      setInsight(insightRes.data);
      setWorkouts(workoutsRes.data);
      if (ragRes.data) {
        setInsight(prev => ({ ...prev, rag: ragRes.data }));
      }
      
      // Trouver la séance du jour
      if (planRes.data?.plan?.sessions) {
        const todayIndex = new Date().getDay(); // 0=Dimanche, 1=Lundi...
        const sessions = planRes.data.plan.sessions;
        const todayPlan = sessions.find(s => dayMapping[s.day] === todayIndex);
        setTodaySession(todayPlan);
      }
    } catch (error) {
      console.error("Failed to fetch data:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: "var(--accent-violet)" }} />
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          {lang === "fr" ? "Chargement..." : "Loading..."}
        </p>
      </div>
    );
  }

  const recovery = insight?.recovery_score;
  const weekStats = insight?.week || { sessions: 0, volume_km: 0 };
  const monthStats = insight?.month || { volume_km: 0 };
  
  // Mock data for the chart (would come from real data)
  const chartData = [45, 48, 42, 50, 55, 58, 62, 68];
  
  // Calculate weekly progress
  const weeklyKmTarget = 80;
  const weeklyProgress = Math.min(100, Math.round((weekStats.volume_km / weeklyKmTarget) * 100));
  
  // Calories (mock - would come from real data)
  const calories = Math.round(weekStats.volume_km * 65);
  const caloriesTarget = 5000;

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }}>
      
      {/* FORME ACTUELLE - Form Score Card */}
      <div className="form-score-card p-4 animate-in">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
              {lang === "fr" ? "Forme actuelle" : "Current Form"}
            </p>
            <div className="flex items-baseline">
              <span className="form-score-value">{recovery?.score || 75}</span>
              <span className="form-score-unit">pts</span>
            </div>
            <p className="form-score-change mt-1">
              ↑ +3 {lang === "fr" ? "cette semaine" : "this week"}
            </p>
          </div>
          <CircularGauge value={recovery?.score || 75} />
        </div>
        <MiniLineChart data={chartData} />
      </div>

      {/* METRICS ROW - Cette semaine & Calories */}
      <div className="grid grid-cols-2 gap-3">
        {/* Cette semaine */}
        <div className="metric-card-modern animate-in" style={{ animationDelay: "50ms" }}>
          <div className="metric-label">
            <Zap className="w-4 h-4" style={{ color: "var(--accent-violet)" }} />
            <span>{lang === "fr" ? "Cette semaine" : "This week"}</span>
          </div>
          <div className="flex items-baseline">
            <span className="metric-value">{weekStats.volume_km || 0}</span>
            <span className="metric-unit">km</span>
          </div>
          <div className="metric-progress-bar">
            <div 
              className="metric-progress-fill" 
              style={{ width: `${weeklyProgress}%` }}
            />
          </div>
        </div>

        {/* Calories */}
        <div className="metric-card-modern animate-in" style={{ animationDelay: "100ms" }}>
          <div className="metric-label">
            <Flame className="w-4 h-4" style={{ color: "var(--accent-pink)" }} />
            <span>Calories</span>
          </div>
          <div className="flex items-baseline">
            <span className="metric-value">{calories.toLocaleString()}</span>
          </div>
          <p className="metric-objective">
            Objectif: {caloriesTarget.toLocaleString()}
          </p>
        </div>
      </div>

      {/* TODAY'S WORKOUT */}
      <div className="today-workout-card animate-in" style={{ animationDelay: "150ms" }} data-testid="today-workout-card">
        <p className="today-label">{lang === "fr" ? "AUJOURD'HUI" : "TODAY"}</p>
        {todaySession ? (
          todaySession.type?.toLowerCase().includes("repos") || todaySession.type?.toLowerCase() === "rest" ? (
            // Jour de repos
            <>
              <h3 className="today-title" style={{ color: "var(--text-secondary)" }}>
                {lang === "fr" ? "Jour de repos" : "Rest Day"}
              </h3>
              <p className="today-meta" style={{ opacity: 0.7 }}>
                {todaySession.details || (lang === "fr" ? "Récupération active ou repos complet" : "Active recovery or complete rest")}
              </p>
              <div className="today-details">
                <span style={{ color: "var(--accent-teal)" }}>
                  {lang === "fr" ? "Profite de ta récup' 💪" : "Enjoy your recovery 💪"}
                </span>
              </div>
            </>
          ) : (
            // Séance d'entraînement
            <>
              <h3 className="today-title">{todaySession.type}</h3>
              <p className="today-meta">
                {todaySession.duration && todaySession.duration !== "0min" && `${todaySession.duration}`}
                {todaySession.distance_km > 0 && ` • ${todaySession.distance_km} km`}
                {todaySession.target_pace && ` • Cible: ${todaySession.target_pace}`}
              </p>
              <div className="today-details">
                <span>{todaySession.details}</span>
              </div>
              <div className="play-button">
                <Play className="w-5 h-5" fill="white" />
              </div>
            </>
          )
        ) : (
          // Aucun plan disponible
          <>
            <h3 className="today-title" style={{ color: "var(--text-secondary)" }}>
              {lang === "fr" ? "Pas de séance planifiée" : "No session planned"}
            </h3>
            <p className="today-meta" style={{ opacity: 0.7 }}>
              {lang === "fr" ? "Génère ton plan dans l'onglet Plan" : "Generate your plan in the Plan tab"}
            </p>
            <Link to="/plan" className="play-button" style={{ textDecoration: "none" }}>
              <ChevronRight className="w-5 h-5" />
            </Link>
          </>
        )}
      </div>

      {/* DERNIÈRES SORTIES */}
      <div className="animate-in" style={{ animationDelay: "200ms" }}>
        <h2 className="section-header">
          {lang === "fr" ? "DERNIÈRES SORTIES" : "RECENT WORKOUTS"}
        </h2>
        
        <div className="space-y-2">
          {workouts.slice(0, 5).map((workout, index) => {
            // Better workout type detection
            const workoutName = workout.name?.toLowerCase() || "";
            const notes = workout.notes?.toLowerCase() || "";
            const avgHR = workout.avg_heart_rate || 0;
            
            let workoutType = "endurance"; // default
            
            if (workoutName.includes("interval") || notes.includes("interval") || workoutName.includes("fractionn")) {
              workoutType = "fractionne";
            } else if (workoutName.includes("recup") || notes.includes("recup") || workoutName.includes("easy") || workoutName.includes("recovery")) {
              workoutType = "recuperation";
            } else if (avgHR > 165 || workoutName.includes("tempo") || workoutName.includes("seuil") || workoutName.includes("threshold")) {
              workoutType = "seuil";
            } else if (workout.type === "cycle") {
              workoutType = "cycle";
            }
            
            const typeConfig = WORKOUT_TYPES[workoutType] || WORKOUT_TYPES.endurance;
            const TypeIcon = typeConfig.icon;
            
            return (
              <Link
                key={workout.id}
                to={`/workout/${workout.id}`}
                className="workout-list-item animate-in"
                style={{ animationDelay: `${250 + index * 50}ms` }}
              >
                <div 
                  className="workout-icon"
                  style={{ 
                    background: `${typeConfig.color}20`,
                    color: typeConfig.color
                  }}
                >
                  <TypeIcon className="w-5 h-5" />
                </div>
                
                <div className="workout-info">
                  <p className="workout-type-name">{typeConfig.label}</p>
                  <div className="workout-stats">
                    <span>{workout.distance_km?.toFixed(1)} km</span>
                    <span className="dot" />
                    <span>{formatPace(workout.avg_pace_min_km)}</span>
                    {workout.avg_heart_rate && (
                      <>
                        <span className="dot" />
                        <span>FC {workout.avg_heart_rate}</span>
                      </>
                    )}
                  </div>
                </div>
                
                <span className="workout-date">
                  {getRelativeDate(workout.date, lang)}
                </span>
                
                <ChevronRight className="workout-arrow w-4 h-4" />
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
