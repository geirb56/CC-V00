import { useState, useEffect, useRef, useCallback } from "react";
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
  Activity,
  Moon,
  BarChart2,
  CheckCircle,
  AlertTriangle,
  XCircle,
} from "lucide-react";
import {
  BarChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useUnitSystem } from "@/context/UnitContext";
import { formatDistance, formatPace as formatPaceUnits } from "@/utils/units";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;

// ─── Run Recommendation thresholds ──────────────────────────────────────────
const FATIGUE_REST_THRESHOLD = 1.5;
const FATIGUE_EASY_THRESHOLD = 1.2;
const LOAD_OPTIMAL_MIN = 0.8;
const LOAD_OPTIMAL_MAX = 1.3;

const STATUS_COLORS = {
  green: { bg: "#22c55e20", text: "#22c55e", border: "#22c55e40" },
  yellow: { bg: "#f59e0b20", text: "#f59e0b", border: "#f59e0b40" },
  red: { bg: "#ef444420", text: "#ef4444", border: "#ef444440" },
};

const REC_STYLES = {
  green: {
    bg: "linear-gradient(135deg, #052e16 0%, #14532d 100%)",
    accent: "#22c55e",
    button: "#22c55e",
    buttonHover: "#16a34a",
  },
  yellow: {
    bg: "linear-gradient(135deg, #1c1003 0%, #451a03 100%)",
    accent: "#f59e0b",
    button: "#d97706",
    buttonHover: "#b45309",
  },
  red: {
    bg: "linear-gradient(135deg, #1c0202 0%, #450a0a 100%)",
    accent: "#ef4444",
    button: "#ef4444",
    buttonHover: "#dc2626",
  },
};

function StatusIcon({ status, size = 16 }) {
  if (status === "green") return <CheckCircle size={size} color="#22c55e" />;
  if (status === "yellow") return <AlertTriangle size={size} color="#f59e0b" />;
  return <XCircle size={size} color="#ef4444" />;
}

function MetricWidget({ icon: Icon, label, value, unit, status, detail }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.green;
  return (
    <div
      className="flex-shrink-0 rounded-2xl p-4 flex flex-col gap-1"
      style={{ width: 140, background: colors.bg, border: `1px solid ${colors.border}` }}
    >
      <div className="flex items-center justify-between">
        <Icon size={18} color={colors.text} />
        <StatusIcon status={status} size={14} />
      </div>
      <p className="text-xs font-medium mt-1" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </p>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-bold" style={{ color: colors.text }}>
          {value}
        </span>
        {unit && (
          <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            {unit}
          </span>
        )}
      </div>
      {detail && (
        <p className="text-[10px] leading-tight" style={{ color: "var(--text-tertiary)" }}>
          {detail}
        </p>
      )}
    </div>
  );
}

function TrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-xl p-3 text-xs shadow-lg"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border-color)",
        color: "var(--text-primary)",
      }}
    >
      <p className="font-bold mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
        </p>
      ))}
    </div>
  );
}

// Workout type configuration (labels from t("workoutTypes.*"))
const WORKOUT_TYPES = {
  fractionne: { color: "#8b5cf6", bgClass: "workout-icon fractionne", icon: Zap },
  endurance: { color: "#3b82f6", bgClass: "workout-icon endurance", icon: Activity },
  seuil: { color: "#f97316", bgClass: "workout-icon seuil", icon: Flame },
  recuperation: { color: "#14b8a6", bgClass: "workout-icon recuperation", icon: Heart },
  run: { color: "#3b82f6", bgClass: "workout-icon endurance", icon: Activity },
  cycle: { color: "#f97316", bgClass: "workout-icon seuil", icon: Bike },
};

const formatDuration = (minutes) => {
  if (!minutes) return "--";
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) return `${hrs}h${mins.toString().padStart(2, '0')}`;
  return `${mins}min`;
};

const getRelativeDate = (dateStr, t, locale) => {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return t("dashboard.today");
  if (date.toDateString() === yesterday.toDateString()) return t("dashboard.yesterday");
  return date.toLocaleDateString(locale, { day: "numeric", month: "short" });
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
  const [trainingMetrics, setTrainingMetrics] = useState(null);
  const [cardioData, setCardioData] = useState(null);
  const [cardioLoading, setCardioLoading] = useState(true);
  const [cardioError, setCardioError] = useState(null);
  const [runStarted, setRunStarted] = useState(false);
  const [loading, setLoading] = useState(true);
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const fetchedRef = useRef(false);
  const lastLangRef = useRef(lang);

  // Mapping des jours vers index selon la langue
  // The merged object covers all three languages so the lookup works regardless
  // of whether the backend returns English (fallback plan), French (LLM) or Spanish day names.
  const dayMappings = {
    fr: { "Lundi": 1, "Mardi": 2, "Mercredi": 3, "Jeudi": 4, "Vendredi": 5, "Samedi": 6, "Dimanche": 0 },
    en: { "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6, "Sunday": 0 },
    es: { "Lunes": 1, "Martes": 2, "Miércoles": 3, "Jueves": 4, "Viernes": 5, "Sábado": 6, "Domingo": 0 },
  };
  const dayMapping = { ...dayMappings.fr, ...dayMappings.en, ...dayMappings.es };

  useEffect(() => {
    if (fetchedRef.current && lastLangRef.current === lang) {
      return;
    }
    fetchedRef.current = true;
    lastLangRef.current = lang;
    fetchData();
  }, [lang]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchData = async () => {
    setLoading(true);
    try {
      const [insightRes, workoutsRes, ragRes, planRes, metricsRes] = await Promise.all([
        axios.get(`${API}/dashboard/insight?language=${lang}`),
        axios.get(`${API}/workouts`),
        axios.get(`${API}/rag/dashboard`).catch(() => ({ data: null })),
        axios.get(`${API}/training/plan`, { headers: { "X-User-Id": "default" } }).catch(() => ({ data: null })),
        axios.get(`${API}/training/metrics`, { headers: { "X-User-Id": "default" } }).catch(() => ({ data: null }))
      ]);
      setInsight(insightRes.data);
      setWorkouts(workoutsRes.data);
      if (ragRes.data) {
        setInsight(prev => ({ ...prev, rag: ragRes.data }));
      }
      if (metricsRes.data) {
        setTrainingMetrics(metricsRes.data);
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

  const fetchCardioData = useCallback(async () => {
    setCardioLoading(true);
    setCardioError(null);
    try {
      const res = await axios.get(`${API}/cardio-coach?user_id=default`);
      setCardioData(res.data);
    } catch (err) {
      console.error("CardioCoach fetch failed, trying mock API:", err);
      try {
        const mockRes = await axios.get(`${API}/mock-runner`);
        setCardioData(mockRes.data.today);
        setCardioError("Live data unavailable — showing dynamic demo.");
      } catch (mockErr) {
        console.error("Mock API also failed:", mockErr);
        setCardioError("Unable to load data.");
      }
    } finally {
      setCardioLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCardioData();
  }, [fetchCardioData]);

  // ACWR color helper
  const getAcwrColor = (status) => {
    switch(status) {
      case "optimal": return "#22c55e";
      case "low": return "#3b82f6";
      case "warning": return "#f59e0b";
      case "danger": return "#ef4444";
      default: return "#22c55e";
    }
  };

  // TSB color helper
  const getTsbColor = (status) => {
    switch(status) {
      case "fresh": return "#22c55e";
      case "ready": return "#3b82f6";
      case "training": return "#f59e0b";
      case "fatigued": return "#ef4444";
      default: return "#3b82f6";
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: "var(--accent-violet)" }} />
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          {t("common.loading")}
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
  const weeklyKmTarget = trainingMetrics?.load_28 ? Math.round(trainingMetrics.load_28 / 4 * 1.1) : 80;
  const weeklyProgress = Math.min(100, Math.round((weekStats.volume_km / weeklyKmTarget) * 100));

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }}>
      
      {/* FORME ACTUELLE - Form Score Card */}
      <div className="form-score-card p-4 animate-in">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
              {t("dashboard.currentForm")}
            </p>
            <div className="flex items-baseline">
              <span className="form-score-value">{recovery?.score || 75}</span>
              <span className="form-score-unit">pts</span>
            </div>
            <p className="form-score-change mt-1">
              ↑ +3 {t("dashboard.thisWeekCompact")}
            </p>
          </div>
          <CircularGauge value={recovery?.score || 75} />
        </div>
        <MiniLineChart data={chartData} />
      </div>

      {/* METRICS ROW - Cette semaine & ACWR/TSB */}
      <div className="grid grid-cols-2 gap-3">
        {/* Cette semaine */}
        <div className="metric-card-modern animate-in" style={{ animationDelay: "50ms" }}>
          <div className="metric-label">
            <Zap className="w-4 h-4" style={{ color: "var(--accent-violet)" }} />
            <span>{t("dashboard.thisWeek")}</span>
          </div>
          <div className="flex items-baseline">
            <span className="metric-value">
              {formatDistance(weekStats.volume_km || 0, { unitSystem })}
            </span>
          </div>
          <div className="metric-progress-bar">
            <div 
              className="metric-progress-fill" 
              style={{ width: `${weeklyProgress}%` }}
            />
          </div>
        </div>

        {/* Charge 28j */}
        <div className="metric-card-modern animate-in" style={{ animationDelay: "100ms" }}>
          <div className="metric-label">
            <TrendingUp className="w-4 h-4" style={{ color: "var(--accent-pink)" }} />
            <span>{t("dashboard.load28Label")}</span>
          </div>
          <div className="flex items-baseline">
            <span className="metric-value">
              {formatDistance(trainingMetrics?.load_28 || 0, { unitSystem })}
            </span>
          </div>
          <p className="metric-objective">
            {t("dashboard.load28Subtitle")}
          </p>
        </div>
      </div>

      {/* ACWR & TSB ROW */}
      <div className="grid grid-cols-2 gap-3">
        {/* ACWR */}
        <div className="metric-card-modern animate-in" style={{ animationDelay: "120ms" }}>
          <div className="metric-label">
            <Activity className="w-4 h-4" style={{ color: getAcwrColor(trainingMetrics?.acwr_status) }} />
            <span>ACWR</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="metric-value" style={{ color: getAcwrColor(trainingMetrics?.acwr_status) }}>
              {trainingMetrics?.acwr?.toFixed(2) || "1.00"}
            </span>
            {trainingMetrics?.acwr_status === "optimal" && (
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "#22c55e20", color: "#22c55e" }}>✓</span>
            )}
          </div>
          <p className="metric-objective" style={{ color: getAcwrColor(trainingMetrics?.acwr_status) }}>
            {trainingMetrics?.acwr_status ? t(`dashboard.acwr_status.${trainingMetrics.acwr_status}`) : t("dashboard.acwr_status.optimal")}
          </p>
        </div>

        {/* TSB */}
        <div className="metric-card-modern animate-in" style={{ animationDelay: "140ms" }}>
          <div className="metric-label">
            <Heart className="w-4 h-4" style={{ color: getTsbColor(trainingMetrics?.tsb_status) }} />
            <span>TSB</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="metric-value" style={{ color: getTsbColor(trainingMetrics?.tsb_status) }}>
              {trainingMetrics?.tsb?.toFixed(1) || "0.0"}
            </span>
          </div>
          <p className="metric-objective" style={{ color: getTsbColor(trainingMetrics?.tsb_status) }}>
            {trainingMetrics?.tsb_label || t("dashboard.tsb_status.training")}
          </p>
        </div>
      </div>

      {/* TODAY'S WORKOUT */}
      <div className="today-workout-card animate-in" style={{ animationDelay: "150ms" }} data-testid="today-workout-card">
        <p className="today-label">{t("dashboard.todayLabel")}</p>
        {todaySession ? (
          todaySession.type?.toLowerCase().includes("repos") || todaySession.type?.toLowerCase() === "rest" ? (
            <>
              <h3 className="today-title" style={{ color: "var(--text-secondary)" }}>
                {t("dashboard.todayRestTitle")}
              </h3>
              <p className="today-meta" style={{ opacity: 0.7 }}>
                {todaySession.details || t("dashboard.todayRestDescription")}
              </p>
              <div className="today-details">
                <span style={{ color: "var(--accent-teal)" }}>
                  {t("dashboard.todayRestTagline")}
                </span>
              </div>
            </>
          ) : (
            <>
              <h3 className="today-title">{todaySession.type}</h3>
              <p className="today-meta">
                {todaySession.duration && todaySession.duration !== "0min" && `${todaySession.duration}`}
                {todaySession.distance_km > 0 &&
                  ` • ${formatDistance(todaySession.distance_km, { unitSystem })}`}
                {todaySession.target_pace && ` • ${t("dashboard.targetLabel")}: ${todaySession.target_pace}`}
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
              {t("dashboard.todayNoSessionTitle")}
            </h3>
            <p className="today-meta" style={{ opacity: 0.7 }}>
              {t("dashboard.todayNoSessionSubtitle")}
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
          {t("dashboard.recentWorkouts")}
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
                  <p className="workout-type-name">{t(`workoutTypes.${workoutType}`)}</p>
                  <div className="workout-stats">
                    <span>
                      {formatDistance(workout.distance_km || 0, { unitSystem })}
                    </span>
                    <span className="dot" />
                    <span>
                      {formatPaceUnits(
                        (workout.avg_pace_min_km || 0) * 60,
                        { unitSystem }
                      )}
                    </span>
                    {workout.avg_heart_rate && (
                      <>
                        <span className="dot" />
                        <span>{t("dashboard.hrLabel")} {workout.avg_heart_rate}</span>
                      </>
                    )}
                  </div>
                </div>
                
                <span className="workout-date">
                  {getRelativeDate(workout.date, t, lang === "fr" ? "fr-FR" : "en-US")}
                </span>
                
                <ChevronRight className="workout-arrow w-4 h-4" />
              </Link>
            );
          })}
        </div>
      </div>

      {/* ── RUN RECOMMENDATION SECTION ────────────────────────────────────── */}
      <div className="animate-in" style={{ animationDelay: "300ms" }}>
        <h2 className="section-header">{t("dashboard.runReadiness")}</h2>
      </div>

      {cardioLoading ? (
        <div
          className="flex flex-col items-center justify-center py-8 gap-3"
          data-testid="cardio-coach-loading"
        >
          <Loader2
            className="animate-spin"
            size={28}
            style={{ color: "var(--accent-violet)" }}
          />
          <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            {t("dashboard.computingReadiness")}
          </p>
        </div>
      ) : (
        <>
          {cardioError && (
            <div
              className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
              style={{ background: "#f59e0b15", border: "1px solid #f59e0b30", color: "#f59e0b" }}
            >
              <AlertTriangle size={14} />
              <span>{cardioError}</span>
            </div>
          )}

          {/* Decision card */}
          {(() => {
            const m = cardioData?.metrics || {};
            const recStyle = REC_STYLES[cardioData?.recommendation_color] || REC_STYLES.green;
            const history = cardioData?.history || [];
            return (
              <>
                <div
                  className="rounded-2xl p-5 space-y-3"
                  style={{ background: recStyle.bg, border: `1px solid ${recStyle.accent}30` }}
                  data-testid="decision-card"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: recStyle.accent }}>
                      {t("dashboard.todaysRecommendation")}
                    </span>
                    <button
                      onClick={fetchCardioData}
                      className="p-1 rounded-lg opacity-60 hover:opacity-100 transition-opacity"
                      aria-label="Refresh"
                    >
                      <RefreshCw size={14} style={{ color: recStyle.accent }} />
                    </button>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-4xl">{cardioData?.recommendation_emoji}</span>
                    <span className="text-3xl font-black tracking-tight" style={{ color: recStyle.accent }}>
                      {cardioData?.recommendation || "—"}
                    </span>
                  </div>
                  <ul className="space-y-1">
                    {(cardioData?.reasons || []).map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                        <span className="mt-0.5 shrink-0" style={{ color: recStyle.accent }}>›</span>
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Next workout card */}
                <div
                  className="rounded-2xl p-4 flex items-center gap-4"
                  style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}
                  data-testid="next-workout-card"
                >
                  <div
                    className="w-12 h-12 rounded-xl flex items-center justify-center shrink-0"
                    style={{ background: `${recStyle.accent}20`, color: recStyle.accent }}
                  >
                    <Activity size={24} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs uppercase tracking-wider mb-0.5" style={{ color: "var(--text-tertiary)" }}>
                      {t("dashboard.nextWorkout")}
                    </p>
                    <p className="font-bold text-base truncate" style={{ color: "var(--text-primary)" }}>
                      {cardioData?.next_workout?.label || "—"}
                    </p>
                  </div>
                  <Play size={20} style={{ color: recStyle.accent }} />
                </div>

                {/* Metric widgets */}
                <div>
                  <h2 className="text-xs uppercase tracking-widest mb-3 font-semibold" style={{ color: "var(--text-tertiary)" }}>
                    {t("dashboard.todaysMetrics")}
                  </h2>
                  <div
                    className="flex gap-3 overflow-x-auto pb-2 -mx-4 px-4"
                    style={{ scrollbarWidth: "none" }}
                    data-testid="metrics-scroll"
                  >
                    <MetricWidget
                      icon={Heart}
                      label={t("dashboard.hrvDeviation")}
                      value={m.hrv_delta !== undefined ? (m.hrv_delta >= 0 ? `+${m.hrv_delta}` : `${m.hrv_delta}`) : "—"}
                      unit="ms"
                      status={m.hrv_status || "green"}
                      detail={`${t("dashboard.today")} ${m.hrv_today ?? "—"} ms`}
                    />
                    <MetricWidget
                      icon={Moon}
                      label={t("dashboard.restingHR")}
                      value={m.rhr_today ?? "—"}
                      unit="bpm"
                      status={m.rhr_status || "green"}
                      detail={`${t("dashboard.baseline")} ${m.rhr_baseline ?? "—"} bpm`}
                    />
                    <MetricWidget
                      icon={Zap}
                      label={t("dashboard.sleep")}
                      value={m.sleep_hours ?? "—"}
                      unit="h"
                      status={m.sleep_status || "green"}
                      detail={`${m.sleep_efficiency !== undefined ? Math.round(m.sleep_efficiency * 100) : "—"}% ${t("dashboard.efficiency")}`}
                    />
                    <MetricWidget
                      icon={BarChart2}
                      label={t("dashboard.trainingLoad")}
                      value={m.training_load ?? "—"}
                      unit="ACWR"
                      status={m.training_load_status || "green"}
                      detail={m.training_load >= LOAD_OPTIMAL_MIN && m.training_load <= LOAD_OPTIMAL_MAX ? t("dashboard.optimalZone") : t("dashboard.outsideZone")}
                    />
                    <MetricWidget
                      icon={Activity}
                      label={t("dashboard.fatigueRatio")}
                      value={m.fatigue_ratio ?? "—"}
                      unit=""
                      status={m.fatigue_status || "green"}
                      detail={m.fatigue_ratio <= FATIGUE_EASY_THRESHOLD ? t("dashboard.lowFatigue") : m.fatigue_ratio <= FATIGUE_REST_THRESHOLD ? t("dashboard.moderate") : t("dashboard.highFatigue")}
                    />
                  </div>
                </div>

                {/* 7-Day Trend Graph */}
                <div
                  className="rounded-2xl p-4"
                  style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}
                  data-testid="trend-graph"
                >
                  <h2 className="text-xs uppercase tracking-widest mb-4 font-semibold" style={{ color: "var(--text-tertiary)" }}>
                    {t("dashboard.sevenDayTrend")}
                  </h2>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={history} margin={{ top: 5, right: 5, left: -20, bottom: 0 }} barCategoryGap="20%">
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border-color)" vertical={false} />
                      <XAxis dataKey="day" tick={{ fill: "var(--text-tertiary)", fontSize: 10 }} axisLine={false} tickLine={false} />
                      <YAxis yAxisId="left" tick={{ fill: "var(--text-tertiary)", fontSize: 10 }} axisLine={false} tickLine={false} domain={[0, "auto"]} />
                      <YAxis yAxisId="right" orientation="right" tick={{ fill: "var(--text-tertiary)", fontSize: 10 }} axisLine={false} tickLine={false} domain={[0, "auto"]} />
                      <Tooltip content={<TrendTooltip />} />
                      <Legend iconType="circle" iconSize={8} formatter={(v) => (<span style={{ color: "var(--text-secondary)", fontSize: 10 }}>{v}</span>)} />
                      <Bar yAxisId="left" dataKey="training_load" name={t("dashboard.trainingLoadAcwr")} fill="#8b5cf680" radius={[4, 4, 0, 0]} maxBarSize={24} />
                      <Line yAxisId="right" type="monotone" dataKey="fatigue_ratio" name={t("dashboard.fatigueRatio")} stroke="#ec4899" strokeWidth={2} dot={{ r: 3, fill: "#ec4899" }} activeDot={{ r: 5 }} />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="flex gap-4 mt-2 justify-center">
                    <div className="flex items-center gap-1 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                      <div className="w-2 h-2 rounded-full" style={{ background: "#ec4899" }} />
                      <span>{t("dashboard.fatigueRest")} &gt;{FATIGUE_REST_THRESHOLD} → {t("dashboard.rest")}</span>
                    </div>
                    <div className="flex items-center gap-1 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                      <div className="w-2 h-2 rounded-full" style={{ background: "#f59e0b" }} />
                      <span>&gt;{FATIGUE_EASY_THRESHOLD} → {t("dashboard.easy")}</span>
                    </div>
                  </div>
                </div>

                {/* Start Run CTA */}
                <button
                  onClick={() => setRunStarted((v) => !v)}
                  className="w-full py-4 rounded-2xl font-black text-white text-lg tracking-wider uppercase transition-all duration-200 active:scale-95 flex items-center justify-center gap-3 shadow-lg"
                  style={{
                    background: runStarted ? "var(--bg-card)" : `linear-gradient(135deg, ${recStyle.button} 0%, ${recStyle.buttonHover} 100%)`,
                    border: `2px solid ${recStyle.accent}`,
                    color: runStarted ? recStyle.accent : "white",
                    boxShadow: runStarted ? "none" : `0 8px 24px ${recStyle.accent}40`,
                  }}
                  data-testid="start-run-btn"
                >
                  <Play size={22} fill={runStarted ? recStyle.accent : "white"} />
                  {runStarted ? t("dashboard.running") : cardioData?.recommendation === "REST" ? t("dashboard.logRestDay") : t("dashboard.startRun")}
                </button>

                {cardioData?.mock && (
                  <p className="text-center text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                    {t("dashboard.demoDataNotice")}
                  </p>
                )}
              </>
            );
          })()}
        </>
      )}
    </div>
  );
}
