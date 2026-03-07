import { useState, useEffect } from "react";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { 
  Target, Calendar, TrendingUp, RefreshCw, CheckCircle2, 
  Zap, Clock, Activity, ChevronDown, ChevronUp, Play,
  Trophy, Mountain, Timer
} from "lucide-react";
import { toast } from "sonner";
import axios from "axios";
import Paywall from "@/components/Paywall";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const USER_ID = "default";

const GOAL_OPTIONS = [
  { value: "5K", label: "5 km", weeks: 6 },
  { value: "10K", label: "10 km", weeks: 8 },
  { value: "SEMI", label: "Semi-Marathon", weeks: 12 },
  { value: "MARATHON", label: "Marathon", weeks: 16 },
  { value: "ULTRA", label: "Ultra-Trail", weeks: 20 },
];

// Couleurs par phase
const PHASE_COLORS = {
  build: { bg: "#3b82f620", border: "#3b82f6", text: "#3b82f6", name: "Construction" },
  deload: { bg: "#22c55e20", border: "#22c55e", text: "#22c55e", name: "Récupération" },
  intensification: { bg: "#f9731620", border: "#f97316", text: "#f97316", name: "Intensification" },
  taper: { bg: "#8b5cf620", border: "#8b5cf6", text: "#8b5cf6", name: "Affûtage" },
  race: { bg: "#ef444420", border: "#ef4444", text: "#ef4444", name: "Course" },
};

// Couleurs correspondant au design de l'app pour les séances
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
  const typeLower = type?.toLowerCase() || "";
  
  if (typeLower.includes("repos") || typeLower === "rest") return "repos";
  if (typeLower.includes("endurance") || typeLower.includes("easy")) return "endurance";
  if (typeLower.includes("seuil") || typeLower.includes("threshold") || typeLower.includes("tempo")) return "seuil";
  if (typeLower.includes("récup") || typeLower.includes("recup") || typeLower.includes("recovery")) return "recuperation";
  if (typeLower.includes("sortie longue") || typeLower.includes("long")) return "sortie_longue";
  if (typeLower.includes("fractionn") || typeLower.includes("interval") || typeLower.includes("fartlek")) return "fractionne";
  
  return intensity || "endurance";
};

export default function TrainingPlan() {
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading, trialDaysRemaining, isTrial } = useSubscription();
  const [plan, setPlan] = useState(null);
  const [fullCycle, setFullCycle] = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [settingGoal, setSettingGoal] = useState(false);
  const [sessionsPerWeek, setSessionsPerWeek] = useState(null);
  const [expandedWeek, setExpandedWeek] = useState(null);
  const [showAllWeeks, setShowAllWeeks] = useState(true);
  const [showPredictions, setShowPredictions] = useState(true);
  const [apiError, setApiError] = useState(null);

  const fetchData = async () => {
    try {
      const [planRes, cycleRes, predictionsRes] = await Promise.all([
        axios.get(`${API}/training/plan`, { headers: { "X-User-Id": USER_ID } }),
        axios.get(`${API}/training/full-cycle`, { headers: { "X-User-Id": USER_ID } }),
        axios.get(`${API}/training/race-predictions`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null }))
      ]);
      setPlan(planRes.data);
      setFullCycle(cycleRes.data);
      setApiError(null);
      if (predictionsRes.data) {
        setPredictions(predictionsRes.data);
      }
      if (planRes.data?.sessions_per_week) {
        setSessionsPerWeek(planRes.data.sessions_per_week);
      }
      // Expand current week by default
      if (cycleRes.data?.current_week) {
        setExpandedWeek(cycleRes.data.current_week);
      }
    } catch (err) {
      console.error("Error fetching plan:", err);
      // Check if it's a subscription error
      if (err.response?.status === 403 && err.response?.data?.error === "subscription_required") {
        setApiError("subscription_required");
      } else {
        toast.error(lang === "fr" ? "Erreur de chargement" : "Loading error");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleRefresh = async (newSessionCount = sessionsPerWeek) => {
    setRefreshing(true);
    try {
      const params = newSessionCount ? `?sessions=${newSessionCount}` : "";
      const res = await axios.post(`${API}/training/refresh${params}`, {}, {
        headers: { "X-User-Id": USER_ID }
      });
      setPlan(res.data);
      // Refresh full cycle too
      const cycleRes = await axios.get(`${API}/training/full-cycle`, { headers: { "X-User-Id": USER_ID } });
      setFullCycle(cycleRes.data);
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
      fetchData();
    } catch (err) {
      toast.error(lang === "fr" ? "Erreur" : "Error");
    } finally {
      setSettingGoal(false);
    }
  };

  if (loading || subLoading) {
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

  // Show paywall for free users
  if (isFree || apiError === "subscription_required") {
    return <Paywall language={lang} returnPath="/training" />;
  }

  const context = plan?.context || {};
  const sessions = plan?.plan?.sessions || [];
  const weeks = fullCycle?.weeks || [];
  const currentWeek = fullCycle?.current_week || 1;
  const totalWeeks = fullCycle?.total_weeks || 12;

  return (
    <div className="p-4 pb-24 space-y-4" style={{ background: "var(--bg-primary)" }} data-testid="training-plan-page">
      
      {/* Trial Banner */}
      {isTrial && trialDaysRemaining !== null && (
        <div 
          className="p-3 rounded-xl flex items-center justify-between"
          style={{ 
            background: "linear-gradient(135deg, rgba(59,130,246,0.2) 0%, rgba(139,92,246,0.2) 100%)",
            border: "1px solid rgba(59,130,246,0.3)"
          }}
        >
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-blue-400" />
            <span className="text-sm text-blue-300">
              {lang === "fr" 
                ? `Essai gratuit : ${trialDaysRemaining} jour${trialDaysRemaining > 1 ? 's' : ''} restant${trialDaysRemaining > 1 ? 's' : ''}`
                : `Free trial: ${trialDaysRemaining} day${trialDaysRemaining > 1 ? 's' : ''} remaining`}
            </span>
          </div>
          <a 
            href="/settings" 
            className="text-xs font-medium px-3 py-1 rounded-full"
            style={{ background: "rgba(59,130,246,0.3)", color: "#93c5fd" }}
          >
            {lang === "fr" ? "S'abonner" : "Subscribe"}
          </a>
        </div>
      )}
      
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold uppercase tracking-tight text-white">
            {lang === "fr" ? "Plan d'Entraînement" : "Training Plan"}
          </h1>
          <p className="text-sm font-mono" style={{ color: "var(--text-tertiary)" }}>
            {lang === "fr" ? "Semaine" : "Week"} {currentWeek} / {totalWeeks}
            {" • "}
            <span className="capitalize">{fullCycle?.goal_description || "Semi-marathon"}</span>
          </p>
        </div>
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => handleRefresh()}
          disabled={refreshing}
          className="border-slate-600 text-slate-300 hover:bg-slate-700"
          data-testid="refresh-plan-btn"
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
          {lang === "fr" ? "Actualiser" : "Refresh"}
        </Button>
      </div>

      {/* Progress Bar */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Trophy className="w-4 h-4" style={{ color: "#f59e0b" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
              {lang === "fr" ? "Progression du cycle" : "Cycle Progress"}
            </span>
          </div>
          <span className="text-sm font-bold text-white">
            {Math.round((currentWeek / totalWeeks) * 100)}%
          </span>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-secondary)" }}>
          <div 
            className="h-full rounded-full transition-all duration-500"
            style={{ 
              width: `${(currentWeek / totalWeeks) * 100}%`,
              background: "linear-gradient(90deg, #8b5cf6 0%, #ec4899 100%)"
            }}
          />
        </div>
        <div className="flex justify-between mt-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
          <span>{lang === "fr" ? "Début" : "Start"}</span>
          <span>{fullCycle?.goal || "SEMI"}</span>
        </div>
      </div>

      {/* Objectif & Séances selection */}
      <div className="grid grid-cols-2 gap-3">
        {/* Objectif */}
        <div className="card-modern p-3" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "12px" }}>
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-3 h-3" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>Objectif</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {GOAL_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => handleSetGoal(opt.value)}
                disabled={settingGoal}
                className={`px-2 py-1 rounded-full text-[10px] font-medium transition-all ${
                  fullCycle?.goal === opt.value ? "text-white" : "text-slate-400 hover:text-white"
                }`}
                style={{
                  background: fullCycle?.goal === opt.value ? "#8b5cf6" : "var(--bg-secondary)",
                  border: `1px solid ${fullCycle?.goal === opt.value ? "#8b5cf6" : "var(--border-color)"}`
                }}
                data-testid={`goal-btn-${opt.value}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Séances par semaine */}
        <div className="card-modern p-3" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "12px" }}>
          <div className="flex items-center gap-2 mb-2">
            <Calendar className="w-3 h-3" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>Séances/sem</span>
          </div>
          <div className="flex gap-1">
            {[3, 4, 5, 6].map((num) => (
              <button
                key={num}
                onClick={() => {
                  setSessionsPerWeek(num);
                  handleRefresh(num);
                }}
                disabled={refreshing}
                className={`px-3 py-1 rounded-full text-xs font-bold transition-all ${
                  sessionsPerWeek === num ? "text-white" : "text-slate-400 hover:text-white"
                }`}
                style={{
                  background: sessionsPerWeek === num ? "#22c55e" : "var(--bg-secondary)",
                  border: `1px solid ${sessionsPerWeek === num ? "#22c55e" : "var(--border-color)"}`
                }}
                data-testid={`sessions-btn-${num}`}
              >
                {num}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* PRÉDICTIONS DE COURSE */}
      {predictions?.has_data && (
        <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Timer className="w-4 h-4" style={{ color: "#f59e0b" }} />
              <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
                {lang === "fr" ? "Prédictions de course" : "Race Predictions"}
              </span>
            </div>
            <button
              onClick={() => setShowPredictions(!showPredictions)}
              className="text-xs flex items-center gap-1 px-2 py-1 rounded"
              style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)" }}
            >
              {showPredictions ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {showPredictions ? (lang === "fr" ? "Réduire" : "Collapse") : (lang === "fr" ? "Voir" : "Show")}
            </button>
          </div>

          {showPredictions && (
            <>
              {/* Profil athlète */}
              <div className="grid grid-cols-3 gap-2 mb-4 p-3 rounded-lg" style={{ background: "var(--bg-secondary)" }}>
                <div className="text-center">
                  <p className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>VMA est.</p>
                  <p className="text-sm font-bold text-white">{predictions.athlete_profile?.estimated_vma || "--"} km/h</p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>Vol./sem</p>
                  <p className="text-sm font-bold text-white">{predictions.athlete_profile?.weekly_km || "--"} km</p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>Sortie max</p>
                  <p className="text-sm font-bold text-white">{predictions.athlete_profile?.max_long_run || "--"} km</p>
                </div>
              </div>

              {/* Prédictions par distance */}
              <div className="space-y-2">
                {predictions.predictions?.map((pred, idx) => (
                  <div 
                    key={pred.distance}
                    className="flex items-center gap-3 p-3 rounded-xl transition-all"
                    style={{ 
                      background: pred.distance === fullCycle?.goal ? `${pred.readiness_color}15` : "var(--bg-secondary)",
                      border: pred.distance === fullCycle?.goal ? `2px solid ${pred.readiness_color}` : "1px solid transparent"
                    }}
                  >
                    {/* Distance badge */}
                    <div 
                      className="shrink-0 w-12 h-12 rounded-xl flex flex-col items-center justify-center"
                      style={{ background: `${pred.readiness_color}20` }}
                    >
                      <span className="text-xs font-bold" style={{ color: pred.readiness_color }}>
                        {pred.distance}
                      </span>
                    </div>

                    {/* Temps prédit */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold text-white">{pred.predicted_time}</span>
                        {pred.distance === fullCycle?.goal && (
                          <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: "#8b5cf6", color: "white" }}>
                            OBJECTIF
                          </span>
                        )}
                      </div>
                      <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                        {pred.predicted_pace} • {pred.predicted_range}
                      </p>
                    </div>

                    {/* Readiness */}
                    <div className="shrink-0 text-right">
                      <div 
                        className="px-2 py-1 rounded-full text-[10px] font-bold mb-1"
                        style={{ background: `${pred.readiness_color}20`, color: pred.readiness_color }}
                      >
                        {pred.readiness_label}
                      </div>
                      <p className="text-[9px]" style={{ color: "var(--text-tertiary)" }}>
                        {pred.readiness_score}% prêt
                      </p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Légende */}
              <div className="mt-3 pt-3 border-t border-white/10 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] px-2 py-0.5 rounded" style={{ background: "var(--bg-tertiary)", color: "var(--text-secondary)" }}>
                    VMA: {predictions.athlete_profile?.estimated_vma} km/h
                  </span>
                  <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                    {predictions.athlete_profile?.vma_efforts_count > 0 
                      ? `(${predictions.athlete_profile.vma_efforts_count} effort(s) ≥ 6 min)`
                      : "(estimée depuis allure moyenne)"}
                  </span>
                </div>
                <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                  {predictions.methodology?.vma_calculation || (lang === "fr" 
                    ? "VMA basée sur efforts ≥ 6 min. Prédictions ajustées selon volume et endurance."
                    : "VMA based on efforts ≥ 6 min. Predictions adjusted by volume and endurance.")}
                </p>
              </div>
            </>
          )}
        </div>
      )}

      {/* TOUTES LES SEMAINES DU CYCLE */}
      <div className="card-modern p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)", borderRadius: "16px" }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4" style={{ color: "var(--text-tertiary)" }} />
            <span className="text-xs font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
              {lang === "fr" ? "Cycle complet" : "Full Cycle"} • {totalWeeks} {lang === "fr" ? "semaines" : "weeks"}
            </span>
          </div>
          <button
            onClick={() => setShowAllWeeks(!showAllWeeks)}
            className="text-xs flex items-center gap-1 px-2 py-1 rounded"
            style={{ color: "var(--text-secondary)", background: "var(--bg-secondary)" }}
          >
            {showAllWeeks ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {showAllWeeks ? (lang === "fr" ? "Réduire" : "Collapse") : (lang === "fr" ? "Voir tout" : "Show all")}
          </button>
        </div>

        <div className="space-y-2">
          {weeks.map((week, idx) => {
            const phaseStyle = PHASE_COLORS[week.phase] || PHASE_COLORS.build;
            const isExpanded = expandedWeek === week.week;
            const isCurrent = week.is_current;
            const isCompleted = week.is_completed;
            
            // Only show: current week, 2 before, 2 after, and first/last if not showing all
            const shouldShow = showAllWeeks || 
              isCurrent || 
              Math.abs(week.week - currentWeek) <= 2 ||
              week.week === 1 ||
              week.week === totalWeeks;
            
            if (!shouldShow) return null;

            return (
              <div
                key={week.week}
                className={`rounded-xl overflow-hidden transition-all ${isCurrent ? "ring-2 ring-violet-500" : ""}`}
                style={{
                  background: isCompleted ? "var(--bg-secondary)" : phaseStyle.bg,
                  border: `1px solid ${isCompleted ? "var(--border-color)" : phaseStyle.border}`,
                  opacity: isCompleted ? 0.6 : 1
                }}
                data-testid={`week-${week.week}`}
              >
                {/* Week Header */}
                <button
                  onClick={() => setExpandedWeek(isExpanded ? null : week.week)}
                  className="w-full p-3 flex items-center justify-between text-left"
                >
                  <div className="flex items-center gap-3">
                    <div 
                      className="w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm"
                      style={{ 
                        background: isCurrent ? "#8b5cf6" : isCompleted ? "var(--bg-tertiary)" : phaseStyle.border + "30",
                        color: isCurrent ? "white" : isCompleted ? "var(--text-tertiary)" : phaseStyle.text
                      }}
                    >
                      {isCompleted ? <CheckCircle2 className="w-4 h-4" /> : week.week}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`font-semibold text-sm ${isCompleted ? "line-through" : ""}`} style={{ color: isCompleted ? "var(--text-tertiary)" : "white" }}>
                          {lang === "fr" ? "Semaine" : "Week"} {week.week}
                        </span>
                        {isCurrent && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-violet-500 text-white">
                            {lang === "fr" ? "EN COURS" : "CURRENT"}
                          </span>
                        )}
                        {week.phase === "race" && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-500 text-white flex items-center gap-1">
                            <Trophy className="w-3 h-3" /> COURSE
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span 
                          className="text-[10px] font-mono uppercase"
                          style={{ color: isCompleted ? "var(--text-tertiary)" : phaseStyle.text }}
                        >
                          {week.phase_name}
                        </span>
                        <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>•</span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          ~{week.target_km} km
                        </span>
                        <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>•</span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          {week.sessions} séances
                        </span>
                      </div>
                    </div>
                  </div>
                  <ChevronDown 
                    className={`w-4 h-4 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                    style={{ color: "var(--text-tertiary)" }}
                  />
                </button>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="px-3 pb-3 space-y-2">
                    <div className="text-xs p-2 rounded-lg" style={{ background: "rgba(0,0,0,0.2)", color: "var(--text-secondary)" }}>
                      <strong>{lang === "fr" ? "Focus:" : "Focus:"}</strong> {week.phase_focus}
                    </div>
                    
                    {/* Session types for this week */}
                    <div className="flex flex-wrap gap-1">
                      {week.session_types?.map((type, i) => {
                        const styleKey = getSessionStyleKey(type);
                        const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
                        return (
                          <span 
                            key={i}
                            className="px-2 py-1 rounded-full text-[10px] font-medium"
                            style={{ background: style.badge, color: style.badgeText }}
                          >
                            {type}
                          </span>
                        );
                      })}
                    </div>

                    {/* If current week, show detailed sessions */}
                    {isCurrent && sessions.length > 0 && (
                      <div className="mt-3 pt-3 border-t border-white/10 space-y-2">
                        <span className="text-[10px] font-mono uppercase" style={{ color: "var(--text-tertiary)" }}>
                          {lang === "fr" ? "Détail de la semaine" : "Week Details"}
                        </span>
                        {sessions.map((session, sidx) => {
                          const styleKey = getSessionStyleKey(session.type, session.intensity);
                          const style = SESSION_STYLES[styleKey] || SESSION_STYLES.endurance;
                          const isRest = styleKey === "repos";
                          
                          return (
                            <div
                              key={sidx}
                              className="flex items-center gap-2 p-2 rounded-lg"
                              style={{ background: style.bg }}
                            >
                              <div 
                                className="w-1 h-8 rounded-full shrink-0"
                                style={{ background: style.border }}
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-bold" style={{ color: style.text }}>
                                    {session.day}
                                  </span>
                                  <span className="text-[10px]" style={{ color: style.text, opacity: 0.8 }}>
                                    {session.type}
                                  </span>
                                </div>
                                {!isRest && session.distance_km > 0 && (
                                  <span className="text-[10px]" style={{ color: style.text, opacity: 0.7 }}>
                                    {session.distance_km} km
                                  </span>
                                )}
                              </div>
                              <span 
                                className="px-2 py-0.5 rounded-full text-[9px] font-bold shrink-0"
                                style={{ background: style.badge, color: style.badgeText }}
                              >
                                {session.estimated_tss || 0} TSS
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
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
