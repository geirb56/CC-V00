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
  Check,
  X,
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
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

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

// Couleurs pour les séances (même style que TrainingPlan)
const SESSION_STYLES = {
  repos: {
    bg: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
    border: "#6366f1",
    text: "#c7d2fe",
    badge: "#4f46e5",
    badgeText: "#ffffff"
  },
  endurance: {
    bg: "linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%)",
    border: "#34d399",
    text: "#065f46",
    badge: "#10b981",
    badgeText: "#ffffff"
  },
  seuil: {
    bg: "linear-gradient(135deg, #fed7aa 0%, #fdba74 100%)",
    border: "#f97316",
    text: "#9a3412",
    badge: "#f97316",
    badgeText: "#ffffff"
  },
  recuperation: {
    bg: "linear-gradient(135deg, #fef9c3 0%, #fef08a 100%)",
    border: "#facc15",
    text: "#854d0e",
    badge: "#eab308",
    badgeText: "#ffffff"
  },
  sortie_longue: {
    bg: "linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%)",
    border: "#ec4899",
    text: "#9d174d",
    badge: "#ec4899",
    badgeText: "#ffffff"
  },
  fractionne: {
    bg: "linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%)",
    border: "#8b5cf6",
    text: "#5b21b6",
    badge: "#8b5cf6",
    badgeText: "#ffffff"
  },
};

const getSessionStyleKey = (type, intensity) => {
  const typeLower = (type && typeof type === "string" ? type : "").toLowerCase();
  
  if (typeLower.includes("repos") || typeLower === "rest") return "repos";
  if (typeLower.includes("endurance") || typeLower === "easy" || typeLower === "short_easy" || typeLower === "easy_run") return "endurance";
  if (typeLower.includes("seuil") || typeLower.includes("threshold") || typeLower === "tempo") return "seuil";
  if (typeLower.includes("récup") || typeLower.includes("recup") || typeLower === "recovery" || typeLower === "activation") return "recuperation";
  if (typeLower.includes("sortie longue") || typeLower === "long_run" || typeLower.includes("long")) return "sortie_longue";
  if (typeLower.includes("fractionn") || typeLower.includes("interval") || typeLower === "fartlek" || typeLower === "speed_reminder" || typeLower === "race") return "fractionne";
  
  return intensity || "endurance";
};

// SessionCard component for displaying a session with colors
function SessionCard({ session, isGrayed = false, fatigueColor = null }) {
  if (!session) return null;

  const styleKey = getSessionStyleKey(session.type, session.intensity);
  const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
  const isRest = styleKey === "repos";

  const borderColor = fatigueColor
    ? (fatigueColor === "green" ? "#10b981" : fatigueColor === "yellow" ? "#f59e0b" : "#ef4444")
    : style.border;

  return (
    <div
      className={`flex items-center gap-2 p-3 rounded-lg ${isGrayed ? "opacity-50" : ""}`}
      style={{
        background: style.bg,
        border: `2px solid ${borderColor}`
      }}
    >
      <div
        className="w-1 h-10 rounded-full shrink-0"
        style={{ background: borderColor }}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-bold" style={{ color: style.text }}>
            {session.type}
          </span>
          <span className="text-xs" style={{ color: style.text, opacity: 0.8 }}>
            {session.duration}
          </span>
        </div>
        {!isRest && session.details && (
          <span className="text-xs block" style={{ color: style.text, opacity: 0.7 }}>
            {session.details}
          </span>
        )}
      </div>
      <span
        className="px-2 py-1 rounded-full text-xs font-bold shrink-0"
        style={{ background: style.badge, color: style.badgeText }}
      >
        {session.estimated_tss || 0} TSS
      </span>
    </div>
  );
}

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
  const [loading, setLoading] = useState(true);
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  const [sessionFeedback, setSessionFeedback] = useState({});
  const { t, lang } = useLanguage();
  const { unitSystem } = useUnitSystem();
  const fetchedRef = useRef(false);
  const lastLangRef = useRef(lang);

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
      const [insightRes, workoutsRes, ragRes, todayRes, metricsRes] = await Promise.all([
        axios.get(`${API}/dashboard/insight?language=${lang}`),
        axios.get(`${API}/workouts`),
        axios.get(`${API}/rag/dashboard`).catch(() => ({ data: null })),
        axios.get(`${API}/training/today`, { headers: { "X-User-Id": "default" } }).catch(() => ({ data: null })),
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
      
      // Utiliser la réponse de /api/training/today (avec adaptation)
      if (todayRes.data?.status === "success") {
        setTodaySession(todayRes.data);
      }
    } catch (error) {
      console.error("Failed to fetch data:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (day, status) => {
    setFeedbackSubmitting(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      await axios.post(
        `${API}/training/feedback`,
        null,
        {
          params: { date: today, workout_id: day, status },
          headers: { "X-User-Id": "default" }
        }
      );

      setSessionFeedback(prev => ({ ...prev, [day]: status }));
      toast.success(t("trainingPlanExtended.feedbackSaved") || "Feedback enregistré");
      
      // Refresh today's session
      const todayRes = await axios.get(`${API}/training/today`, { headers: { "X-User-Id": "default" } });
      if (todayRes.data?.status === "success") {
        setTodaySession(todayRes.data);
      }
    } catch (err) {
      console.error("Error submitting feedback:", err);
      toast.error(t("common.error") || "Erreur");
    } finally {
      setFeedbackSubmitting(false);
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

      {/* TODAY'S SESSION - Interactive with Adaptation */}
      <div 
        className="today-workout-card animate-in" 
        style={{ 
          animationDelay: "150ms",
          border: todaySession?.fatigue ? `2px solid ${
            todaySession.fatigue.fatigue_status === "green" ? "#10b981" :
            todaySession.fatigue.fatigue_status === "yellow" ? "#f59e0b" : "#ef4444"
          }` : undefined
        }} 
        data-testid="today-workout-card"
      >
        <div className="flex items-center justify-between mb-3">
          <p className="today-label">{t("dashboard.todayLabel")}</p>
          {todaySession?.fatigue && (
            <span
              className="px-3 py-1 rounded-full text-xs font-bold"
              style={{
                background: todaySession.fatigue.fatigue_status === "green" ? "#10b98120" :
                           todaySession.fatigue.fatigue_status === "yellow" ? "#f59e0b20" : "#ef444420",
                color: todaySession.fatigue.fatigue_status === "green" ? "#10b981" :
                       todaySession.fatigue.fatigue_status === "yellow" ? "#f59e0b" : "#ef4444"
              }}
            >
              {todaySession.fatigue.recommendation || "RUN HARD"}
            </span>
          )}
        </div>

        {todaySession?.status === "success" ? (
          <>
            {/* Adaptation notice */}
            {todaySession.adaptation_applied && (
              <div
                className="p-2 rounded-lg text-xs mb-3"
                style={{
                  background: "rgba(249, 115, 22, 0.1)",
                  border: "1px solid rgba(249, 115, 22, 0.3)",
                  color: "#fb923c"
                }}
              >
                <strong>{t("trainingPlanExtended.adaptedBecause") || "Adapté :"}</strong> {todaySession.adaptation_reason}
              </div>
            )}

            {/* Display with SessionCard */}
            {todaySession.adaptation_applied ? (
              <div className="space-y-3">
                {/* Original Session (grayed out) */}
                <div>
                  <div className="text-[10px] font-mono uppercase mb-1" style={{ color: "var(--text-tertiary)" }}>
                    {t("trainingPlanExtended.originalSession") || "Séance originale"}
                  </div>
                  <SessionCard session={todaySession.planned_session} isGrayed={true} />
                </div>

                {/* Adaptive Session (highlighted) */}
                <div>
                  <div className="text-[10px] font-mono uppercase mb-1" style={{ color: "var(--text-secondary)" }}>
                    {t("trainingPlanExtended.adaptiveSession") || "Séance adaptative"}
                  </div>
                  <SessionCard
                    session={todaySession.adaptive_session}
                    fatigueColor={todaySession.fatigue?.recommendation_color}
                  />
                </div>
              </div>
            ) : (
              <SessionCard session={todaySession.planned_session} />
            )}

            {/* Feedback Buttons */}
            <div className="flex gap-2 mt-3">
              <Button
                size="sm"
                onClick={() => handleFeedback(todaySession.day, "done")}
                disabled={feedbackSubmitting || sessionFeedback[todaySession.day] === "done"}
                className={`flex-1 ${
                  sessionFeedback[todaySession.day] === "done"
                    ? "bg-green-600 text-white"
                    : "bg-slate-700 text-slate-200 hover:bg-green-600"
                }`}
              >
                <Check className="w-4 h-4 mr-1" />
                {t("trainingPlanExtended.feedbackDone") || "Réalisé"}
              </Button>
              <Button
                size="sm"
                onClick={() => handleFeedback(todaySession.day, "missed")}
                disabled={feedbackSubmitting || sessionFeedback[todaySession.day] === "missed"}
                className={`flex-1 ${
                  sessionFeedback[todaySession.day] === "missed"
                    ? "bg-red-600 text-white"
                    : "bg-slate-700 text-slate-200 hover:bg-red-600"
                }`}
              >
                <X className="w-4 h-4 mr-1" />
                {t("trainingPlanExtended.feedbackMissed") || "Manqué"}
              </Button>
            </div>
          </>
        ) : (
          <>
            <h3 className="today-title" style={{ color: "var(--text-secondary)" }}>
              {t("dashboard.todayNoSessionTitle")}
            </h3>
            <p className="today-meta" style={{ opacity: 0.7 }}>
              {t("dashboard.todayNoSessionSubtitle")}
            </p>
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
            
            // Calculate Run Readiness Score from fatigue_ratio
            const fatigueRatio = m.fatigue_ratio ?? 1.0;
            const runReadinessScore = Math.max(20, Math.min(100, Math.round(120 - (fatigueRatio * 25))));
            
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
                  
                  {/* Run Readiness Score - Big Display */}
                  <div className="flex items-center gap-4">
                    <div className="flex flex-col items-center">
                      <span 
                        className="text-6xl font-black"
                        style={{ color: recStyle.accent }}
                      >
                        {runReadinessScore}
                      </span>
                      <span className="text-xs uppercase tracking-wider mt-1" style={{ color: "var(--text-tertiary)" }}>
                        {t("dashboard.readinessScore") || "Run Readiness"}
                      </span>
                    </div>
                    <div className="h-16 w-px" style={{ background: `${recStyle.accent}40` }} />
                    <div className="flex items-center gap-2">
                      <span className="text-3xl">{cardioData?.recommendation_emoji}</span>
                      <span className="text-2xl font-black tracking-tight" style={{ color: recStyle.accent }}>
                        {cardioData?.recommendation || "—"}
                      </span>
                    </div>
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
                      icon={TrendingUp}
                      label={t("dashboard.currentForm")}
                      value={recovery?.score || 75}
                      unit="pts"
                      status={recovery?.score >= 75 ? "green" : recovery?.score >= 50 ? "yellow" : "red"}
                      detail={recovery?.status === "ready" ? t("dashboard.formReady") || "Prêt" : recovery?.status === "ok" ? t("dashboard.formOk") || "OK" : t("dashboard.formTired") || "Fatigué"}
                    />
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
