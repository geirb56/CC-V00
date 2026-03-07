import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  ResponsiveContainer,
  Tooltip,
  Cell
} from "recharts";
import { 
  TrendingUp, 
  Activity,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Bike,
  Footprints,
  Calendar,
  Timer,
  Zap,
  Target
} from "lucide-react";
import Paywall from "@/components/Paywall";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const USER_ID = "default";

const getWorkoutIcon = (type) => {
  switch (type) {
    case "cycle":
      return Bike;
    case "run":
    default:
      return Footprints;
  }
};

const formatDuration = (minutes) => {
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) {
    return `${hrs}h ${mins}m`;
  }
  return `${mins}m`;
};

const CustomTooltip = ({ active, payload, label, t }) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-popover border border-border p-3">
        <p className="font-mono text-xs text-muted-foreground mb-1">{label}</p>
        <p className="font-mono text-sm font-medium">
          {payload[0].value.toFixed(1)} {t("dashboard.km")}
        </p>
      </div>
    );
  }
  return null;
};

export default function Progress() {
  const [stats, setStats] = useState(null);
  const [workouts, setWorkouts] = useState([]);
  const [predictions, setPredictions] = useState(null);
  const [fullCycle, setFullCycle] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showPredictions, setShowPredictions] = useState(true);
  const { t, lang } = useLanguage();
  const { isFree, loading: subLoading } = useSubscription();

  const dateLocale = t("dateFormat.locale");

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statsRes, workoutsRes, predictionsRes, cycleRes] = await Promise.all([
          axios.get(`${API}/stats`),
          axios.get(`${API}/workouts`),
          axios.get(`${API}/training/race-predictions`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null })),
          axios.get(`${API}/training/full-cycle`, { headers: { "X-User-Id": USER_ID } }).catch(() => ({ data: null }))
        ]);
        setStats(statsRes.data);
        setWorkouts(workoutsRes.data);
        if (predictionsRes.data) setPredictions(predictionsRes.data);
        if (cycleRes.data) setFullCycle(cycleRes.data);
      } catch (error) {
        console.error("Failed to fetch data:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading || subLoading) {
    return (
      <div className="p-6 md:p-8 animate-pulse">
        <div className="h-8 w-48 bg-muted rounded mb-8" />
        <div className="h-64 bg-muted rounded mb-8" />
      </div>
    );
  }

  // Show paywall for free users
  if (isFree) {
    return <Paywall language={lang} returnPath="/progress" />;
  }

  // Prepare chart data with localized day names
  const chartData = stats?.weekly_summary?.map(day => ({
    date: new Date(day.date).toLocaleDateString(dateLocale, { weekday: "short" }),
    distance: day.distance,
    count: day.count
  })) || [];

  const typeData = stats?.workouts_by_type || {};

  return (
    <div className="p-6 md:p-8 pb-24 md:pb-8" data-testid="progress-page">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-2xl md:text-3xl uppercase tracking-tight font-bold mb-1">
          {t("progress.title")}
        </h1>
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {t("progress.subtitle")}
        </p>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8">
        <Card className="metric-card bg-card border-border">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-start justify-between mb-3">
              <span className="data-label">{t("progress.totalVolume")}</span>
              <TrendingUp className="w-4 h-4 text-chart-2" />
            </div>
            <p className="font-heading text-3xl md:text-4xl font-bold">
              {stats?.total_distance_km?.toFixed(0) || 0}
            </p>
            <p className="font-mono text-xs text-muted-foreground mt-1">{t("progress.kilometers")}</p>
          </CardContent>
        </Card>

        <Card className="metric-card bg-card border-border">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-start justify-between mb-3">
              <span className="data-label">{t("progress.sessions")}</span>
              <Activity className="w-4 h-4 text-primary" />
            </div>
            <p className="font-heading text-3xl md:text-4xl font-bold">
              {stats?.total_workouts || 0}
            </p>
            <p className="font-mono text-xs text-muted-foreground mt-1">{t("progress.workouts")}</p>
          </CardContent>
        </Card>

        <Card className="metric-card bg-card border-border col-span-2 md:col-span-1">
          <CardContent className="p-4 md:p-6">
            <div className="flex items-start justify-between mb-3">
              <span className="data-label">{t("progress.byType")}</span>
              <Calendar className="w-4 h-4 text-muted-foreground" />
            </div>
            <div className="flex items-center gap-4">
              {Object.entries(typeData).map(([type, count]) => {
                const Icon = getWorkoutIcon(type);
                return (
                  <div key={type} className="flex items-center gap-2">
                    <Icon className="w-4 h-4 text-muted-foreground" />
                    <span className="font-mono text-sm">{count}</span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Distance Chart */}
      {chartData.length > 0 && (
        <div className="mb-8">
          <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-4">
            {t("progress.dailyDistance")}
          </h2>
          <Card className="chart-container">
            <CardContent className="p-6">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis 
                    dataKey="date" 
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10, fontFamily: "JetBrains Mono" }}
                  />
                  <YAxis 
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10, fontFamily: "JetBrains Mono" }}
                  />
                  <Tooltip content={(props) => <CustomTooltip {...props} t={t} />} cursor={false} />
                  <Bar dataKey="distance" radius={[0, 0, 0, 0]}>
                    {chartData.map((entry, index) => (
                      <Cell 
                        key={`cell-${index}`} 
                        fill={entry.distance > 0 ? "hsl(var(--primary))" : "hsl(var(--muted))"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Race Predictions & VMA */}
      {predictions?.has_data && (
        <div className="mb-8">
          <Card className="bg-card border-border overflow-hidden">
            <CardContent className="p-0">
              {/* Header */}
              <div 
                className="flex items-center justify-between p-4 cursor-pointer"
                onClick={() => setShowPredictions(!showPredictions)}
                style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.1) 0%, rgba(251,191,36,0.05) 100%)" }}
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "rgba(245,158,11,0.2)" }}>
                    <Timer className="w-5 h-5" style={{ color: "#f59e0b" }} />
                  </div>
                  <div>
                    <h2 className="font-heading text-lg uppercase tracking-tight font-semibold">
                      {lang === "fr" ? "Prédictions de course" : "Race Predictions"}
                    </h2>
                    <p className="font-mono text-xs text-muted-foreground">
                      {lang === "fr" ? "Basées sur ta VMA et ton volume" : "Based on your VMA and volume"}
                    </p>
                  </div>
                </div>
                <button className="p-2 rounded-lg" style={{ background: "rgba(255,255,255,0.05)" }}>
                  {showPredictions ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
              </div>

              {showPredictions && (
                <div className="p-4 space-y-4">
                  {/* Athlete Profile - VMA */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-4 rounded-xl text-center" style={{ background: "linear-gradient(135deg, rgba(139,92,246,0.15) 0%, rgba(168,85,247,0.1) 100%)", border: "1px solid rgba(139,92,246,0.3)" }}>
                      <div className="flex items-center justify-center gap-1 mb-1">
                        <Zap className="w-4 h-4" style={{ color: "#a855f7" }} />
                        <span className="text-[10px] font-mono uppercase" style={{ color: "rgba(168,85,247,0.8)" }}>VMA</span>
                      </div>
                      <p className="text-2xl font-bold text-white">{predictions.athlete_profile?.estimated_vma || "--"}</p>
                      <p className="text-[10px] text-muted-foreground">km/h</p>
                    </div>
                    <div className="p-4 rounded-xl text-center" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)" }}>
                      <div className="flex items-center justify-center gap-1 mb-1">
                        <TrendingUp className="w-4 h-4 text-muted-foreground" />
                        <span className="text-[10px] font-mono uppercase text-muted-foreground">Vol./sem</span>
                      </div>
                      <p className="text-2xl font-bold text-white">{predictions.athlete_profile?.weekly_km || "--"}</p>
                      <p className="text-[10px] text-muted-foreground">km</p>
                    </div>
                    <div className="p-4 rounded-xl text-center" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)" }}>
                      <div className="flex items-center justify-center gap-1 mb-1">
                        <Target className="w-4 h-4 text-muted-foreground" />
                        <span className="text-[10px] font-mono uppercase text-muted-foreground">Sortie max</span>
                      </div>
                      <p className="text-2xl font-bold text-white">{predictions.athlete_profile?.max_long_run || "--"}</p>
                      <p className="text-[10px] text-muted-foreground">km</p>
                    </div>
                  </div>

                  {/* Predictions by distance */}
                  <div className="space-y-2">
                    {predictions.predictions?.map((pred) => (
                      <div 
                        key={pred.distance}
                        className="flex items-center gap-3 p-3 rounded-xl transition-all"
                        style={{ 
                          background: pred.distance === fullCycle?.goal ? `${pred.readiness_color}15` : "rgba(255,255,255,0.03)",
                          border: pred.distance === fullCycle?.goal ? `2px solid ${pred.readiness_color}` : "1px solid rgba(255,255,255,0.05)"
                        }}
                      >
                        {/* Distance badge */}
                        <div 
                          className="shrink-0 w-14 h-14 rounded-xl flex flex-col items-center justify-center"
                          style={{ background: `${pred.readiness_color}20` }}
                        >
                          <span className="text-sm font-bold" style={{ color: pred.readiness_color }}>
                            {pred.distance}
                          </span>
                        </div>

                        {/* Predicted time */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xl font-bold text-white">{pred.predicted_time}</span>
                            {pred.distance === fullCycle?.goal && (
                              <span className="px-2 py-0.5 rounded-full text-[9px] font-bold" style={{ background: "#8b5cf6", color: "white" }}>
                                OBJECTIF
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground">
                            {pred.predicted_pace} • {pred.predicted_range}
                          </p>
                        </div>

                        {/* Readiness */}
                        <div className="shrink-0 text-right">
                          <div 
                            className="px-3 py-1 rounded-full text-xs font-bold mb-1"
                            style={{ background: `${pred.readiness_color}20`, color: pred.readiness_color }}
                          >
                            {pred.readiness_label}
                          </div>
                          <p className="text-[10px] text-muted-foreground">
                            {pred.readiness_score}% prêt
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Legend */}
                  <div className="pt-3 border-t border-white/10 space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs px-2 py-1 rounded-lg" style={{ background: "rgba(139,92,246,0.2)", color: "#a855f7" }}>
                        VMA: {predictions.athlete_profile?.estimated_vma} km/h
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {predictions.athlete_profile?.vma_efforts_count > 0 
                          ? `(${predictions.athlete_profile.vma_efforts_count} effort(s) ≥ 6 min)`
                          : (lang === "fr" ? "(estimée depuis allure moyenne)" : "(estimated from average pace)")}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      {predictions.methodology?.vma_calculation || (lang === "fr" 
                        ? "VMA basée sur efforts ≥ 6 min. Prédictions ajustées selon volume et endurance."
                        : "VMA based on efforts ≥ 6 min. Predictions adjusted by volume and endurance.")}
                    </p>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* All Workouts */}
      <div>
        <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-4">
          {t("progress.allWorkouts")}
        </h2>
        <div className="space-y-3">
          {workouts.map((workout, index) => {
            const Icon = getWorkoutIcon(workout.type);
            const typeLabel = t(`workoutTypes.${workout.type}`) || workout.type;
            return (
              <Link
                key={workout.id}
                to={`/workout/${workout.id}`}
                data-testid={`progress-workout-${workout.id}`}
                className="block animate-in"
                style={{ animationDelay: `${index * 30}ms` }}
              >
                <Card className="metric-card bg-card border-border hover:border-primary/30 transition-colors">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-4">
                      <div className="flex-shrink-0 w-10 h-10 flex items-center justify-center bg-muted border border-border">
                        <Icon className="w-5 h-5 text-muted-foreground" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="workout-type-badge">
                            {typeLabel}
                          </span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {new Date(workout.date).toLocaleDateString(dateLocale, {
                              month: "short",
                              day: "numeric"
                            })}
                          </span>
                        </div>
                        <p className="font-medium text-sm truncate">
                          {workout.name}
                        </p>
                      </div>
                      <div className="flex items-center gap-4">
                        <div className="text-right">
                          <p className="font-mono text-sm font-medium">
                            {workout.distance_km.toFixed(1)} {t("dashboard.km")}
                          </p>
                          <p className="font-mono text-[10px] text-muted-foreground">
                            {formatDuration(workout.duration_minutes)}
                          </p>
                        </div>
                        <ChevronRight className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </div>
    </div>
  );
}
