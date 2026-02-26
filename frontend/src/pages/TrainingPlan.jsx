import { useState, useEffect } from "react";
import { useLanguage } from "@/context/LanguageContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { 
  Target, Calendar, TrendingUp, RefreshCw, CheckCircle2, 
  AlertTriangle, Zap, Clock, Activity, ChevronRight
} from "lucide-react";
import { toast } from "sonner";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const USER_ID = "default";

const GOAL_OPTIONS = [
  { value: "5K", label: "5 km", weeks: 6 },
  { value: "10K", label: "10 km", weeks: 8 },
  { value: "SEMI", label: "Semi-Marathon", weeks: 12 },
  { value: "MARATHON", label: "Marathon", weeks: 16 },
  { value: "ULTRA", label: "Ultra-Trail", weeks: 20 },
];

// Couleurs correspondant au design de l'app
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
  tempo: {
    bg: "linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%)",
    border: "#fb923c",
    text: "#9a3412",
    badge: "#fb923c",
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
  rest: {
    bg: "linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)",
    border: "#6366f1",
    text: "#c7d2fe",
    badge: "#4f46e5",
    badgeText: "#ffffff"
  },
  easy: {
    bg: "linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%)",
    border: "#34d399",
    text: "#065f46",
    badge: "#10b981",
    badgeText: "#ffffff"
  },
  moderate: {
    bg: "linear-gradient(135deg, #fed7aa 0%, #fdba74 100%)",
    border: "#f97316",
    text: "#9a3412",
    badge: "#f97316",
    badgeText: "#ffffff"
  },
  hard: {
    bg: "linear-gradient(135deg, #fecaca 0%, #fca5a5 100%)",
    border: "#ef4444",
    text: "#991b1b",
    badge: "#ef4444",
    badgeText: "#ffffff"
  },
  race: {
    bg: "linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%)",
    border: "#8b5cf6",
    text: "#5b21b6",
    badge: "#8b5cf6",
    badgeText: "#ffffff"
  },
};

const PHASE_INFO = {
  build: { color: "#3b82f6", name: "Construction" },
  deload: { color: "#22c55e", name: "Récupération" },
  intensification: { color: "#f97316", name: "Intensification" },
  taper: { color: "#8b5cf6", name: "Affûtage" },
  race: { color: "#ef4444", name: "Compétition" },
};

// Map session type to style key
const getSessionStyleKey = (type, intensity) => {
  const typeLower = type?.toLowerCase() || "";
  
  if (typeLower.includes("repos") || typeLower === "rest") return "repos";
  if (typeLower.includes("endurance") || typeLower.includes("easy")) return "endurance";
  if (typeLower.includes("seuil") || typeLower.includes("threshold")) return "seuil";
  if (typeLower.includes("récup") || typeLower.includes("recup") || typeLower.includes("recovery")) return "recuperation";
  if (typeLower.includes("tempo")) return "tempo";
  if (typeLower.includes("sortie longue") || typeLower.includes("long")) return "sortie_longue";
  if (typeLower.includes("fractionn") || typeLower.includes("interval")) return "fractionne";
  
  // Fallback to intensity
  return intensity || "easy";
};

export default function TrainingPlan() {
  const { t, lang } = useLanguage();
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [settingGoal, setSettingGoal] = useState(false);

  const fetchPlan = async () => {
    try {
      const res = await axios.get(`${API}/training/plan`, {
        headers: { "X-User-Id": USER_ID }
      });
      setPlan(res.data);
    } catch (err) {
      console.error("Error fetching plan:", err);
      toast.error(lang === "fr" ? "Erreur de chargement" : "Loading error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlan();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const res = await axios.post(`${API}/training/refresh`, {}, {
        headers: { "X-User-Id": USER_ID }
      });
      setPlan(res.data);
      toast.success(lang === "fr" ? "Plan mis à jour" : "Plan updated");
    } catch (err) {
      toast.error(lang === "fr" ? "Erreur" : "Error");
    } finally {
      setRefreshing(false);
    }
  };

  const handleSetGoal = async (goal) => {
    setSettingGoal(true);
    try {
      await axios.post(`${API}/training/set-goal?goal=${goal}`, {}, {
        headers: { "X-User-Id": USER_ID }
      });
      toast.success(lang === "fr" ? `Objectif ${goal} défini` : `Goal ${goal} set`);
      fetchPlan();
    } catch (err) {
      toast.error(lang === "fr" ? "Erreur" : "Error");
    } finally {
      setSettingGoal(false);
    }
  };

  if (loading) {
    return (
      <div className="p-4 space-y-4" style={{ background: "var(--bg-primary)", minHeight: "100vh" }}>
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-3 grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  const context = plan?.context || {};
  const sessions = plan?.plan?.sessions || [];
  const phaseInfo = plan?.phase_info || {};
  const currentPhase = PHASE_INFO[plan?.phase] || { color: "#64748b", name: plan?.phase };

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }} data-testid="training-plan-page">
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold uppercase tracking-tight text-white">
            {lang === "fr" ? "Plan d'Entraînement" : "Training Plan"}
          </h1>
          <p className="text-sm font-mono" style={{ color: "var(--text-tertiary)" }}>
            {lang === "fr" ? "Semaine" : "Week"} {plan?.week || 1} / {plan?.goal_config?.cycle_weeks || 12} 
            {" • "}
            <span className="capitalize">{currentPhase.name}</span>
          </p>
        </div>
        <Button 
          variant="outline" 
          size="sm" 
          onClick={handleRefresh}
          disabled={refreshing}
          className="border-slate-600 text-slate-300 hover:bg-slate-700"
          data-testid="refresh-plan-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
          {lang === "fr" ? "Actualiser" : "Refresh"}
        </Button>
      </div>

      {/* Objectif */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center gap-2 mb-2">
          <Target className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
          <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
            {lang === "fr" ? "Objectif" : "Goal"}
          </span>
        </div>
        <div className="text-2xl font-bold text-white">{plan?.goal || "SEMI"}</div>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {plan?.goal_config?.description || "Semi-marathon"}
        </p>
      </div>

      {/* Phase */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center gap-2 mb-2">
          <Calendar className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
          <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>Phase</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{ background: currentPhase.color }} />
          <span className="text-lg font-semibold text-white capitalize">{currentPhase.name}</span>
        </div>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          {phaseInfo.focus || "Volume en endurance fondamentale (Z1-Z2)"}
        </p>
      </div>

      {/* ACWR & TSB en ligne */}
      <div className="grid grid-cols-2 gap-3">
        {/* ACWR */}
        <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>ACWR</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold text-white">{context.acwr?.toFixed(2) || "1.00"}</span>
            {context.acwr <= 1.3 && context.acwr >= 0.8 && (
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            )}
          </div>
          <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            {lang === "fr" ? "Zone optimale" : "Optimal zone"}
          </p>
        </div>

        {/* TSB */}
        <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>TSB</span>
          </div>
          <span className={`text-2xl font-bold ${context.tsb > 0 ? "text-emerald-400" : "text-white"}`}>
            {context.tsb?.toFixed(1) || "-5.0"}
          </span>
          <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            {context.tsb > 0 
              ? (lang === "fr" ? "Fraîcheur" : "Fresh") 
              : (lang === "fr" ? "Fatigue" : "Fatigue")}
          </p>
        </div>
      </div>

      {/* Sélection d'objectif */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center gap-2 mb-3">
          <Target className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
          <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
            {lang === "fr" ? "Changer d'objectif" : "Change Goal"}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {GOAL_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleSetGoal(opt.value)}
              disabled={settingGoal}
              className={`px-3 py-2 rounded-full text-sm font-medium transition-all ${
                plan?.goal === opt.value 
                  ? "text-white" 
                  : "text-slate-400 hover:text-white"
              }`}
              style={{
                background: plan?.goal === opt.value ? "#8b5cf6" : "var(--bg-secondary)",
                border: `1px solid ${plan?.goal === opt.value ? "#8b5cf6" : "var(--border-color)"}`
              }}
              data-testid={`goal-btn-${opt.value}`}
            >
              {opt.label}
              <span className="ml-1 opacity-60">({opt.weeks}s)</span>
            </button>
          ))}
        </div>
      </div>

      {/* SÉANCES DE LA SEMAINE */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
              {lang === "fr" ? "Séances de la semaine" : "Weekly Sessions"}
            </span>
          </div>
          <span 
            className="px-2 py-1 rounded text-xs font-mono font-semibold"
            style={{ background: "var(--bg-secondary)", color: "var(--text-secondary)" }}
          >
            {plan?.plan?.total_tss || 235} TSS
          </span>
        </div>

        <div className="space-y-2">
          {sessions.map((session, idx) => {
            const styleKey = getSessionStyleKey(session.type, session.intensity);
            const style = SESSION_STYLES[styleKey] || SESSION_STYLES.easy;
            const isRest = styleKey === "repos" || styleKey === "rest";
            const distance = session.distance_km || 0;
            
            return (
              <div
                key={idx}
                className="flex items-stretch gap-0 rounded-xl overflow-hidden transition-all"
                style={{
                  background: style.bg,
                }}
                data-testid={`session-${session.day}`}
              >
                {/* Barre colorée latérale */}
                <div 
                  className="w-1.5 shrink-0"
                  style={{ background: style.border }}
                />
                
                {/* Jour */}
                <div 
                  className="w-24 py-3 px-3 flex items-center shrink-0"
                  style={{ background: "rgba(0,0,0,0.1)" }}
                >
                  <span 
                    className="text-xs font-bold uppercase tracking-wide"
                    style={{ color: style.text }}
                  >
                    {session.day}
                  </span>
                </div>
                
                {/* Contenu principal */}
                <div className="flex-1 py-3 px-3 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span 
                      className="font-bold text-base"
                      style={{ color: style.text }}
                    >
                      {session.type}
                    </span>
                    {session.duration && session.duration !== "0min" && (
                      <span 
                        className="text-xs flex items-center gap-1 opacity-80"
                        style={{ color: style.text }}
                      >
                        <Clock className="w-3 h-3" />
                        {session.duration}
                      </span>
                    )}
                    {distance > 0 && (
                      <span 
                        className="text-xs font-semibold px-1.5 py-0.5 rounded"
                        style={{ 
                          background: "rgba(0,0,0,0.15)",
                          color: style.text 
                        }}
                      >
                        {distance} km
                      </span>
                    )}
                  </div>
                  <p 
                    className="text-xs leading-relaxed"
                    style={{ color: style.text, opacity: 0.85 }}
                  >
                    {session.details}
                  </p>
                </div>
                
                {/* TSS Badge */}
                <div className="py-3 px-3 flex items-center shrink-0">
                  <div 
                    className="px-2.5 py-1.5 rounded-full text-xs font-bold"
                    style={{ 
                      background: style.badge,
                      color: style.badgeText
                    }}
                  >
                    {session.estimated_tss} TSS
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Conseil du coach */}
      {plan?.plan?.advice && (
        <div 
          className="card-modern p-4" 
          style={{ 
            background: "linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%)", 
            border: "1px solid rgba(139, 92, 246, 0.3)", 
            borderRadius: "16px" 
          }}
        >
          <div className="flex gap-3">
            <div 
              className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center"
              style={{ background: "rgba(139, 92, 246, 0.2)" }}
            >
              <Activity className="w-5 h-5" style={{ color: "#8b5cf6" }} />
            </div>
            <div>
              <p className="text-xs font-mono uppercase mb-1" style={{ color: "var(--text-tertiary)" }}>
                {lang === "fr" ? "Conseil du coach" : "Coach advice"}
              </p>
              <p className="text-sm text-white">{plan.plan.advice}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
