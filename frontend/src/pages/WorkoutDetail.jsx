import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/context/LanguageContext";
import { 
  ArrowLeft, 
  Heart, 
  TrendingUp,
  TrendingDown,
  Zap,
  Scale,
  Activity,
  MessageSquare,
  Loader2,
  Bike,
  Footprints,
  HeartPulse,
  Sparkles,
  Target,
  AlertTriangle,
  AlertCircle,
  Lightbulb,
  History,
  Clock,
  ChevronDown,
  ChevronUp
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const getWorkoutIcon = (type) => {
  if (type === "cycle") return Bike;
  return Footprints;
};

const formatDuration = (minutes) => {
  if (!minutes) return "--";
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0) return `${hrs}h${mins > 0 ? mins : ""}`;
  return `${mins}m`;
};

// Splits Chart Component - Graphique des allures par km
const SplitsChart = ({ splits, lang }) => {
  if (!splits || splits.length === 0) return null;
  
  // Calculate min/max pace for scaling
  const paces = splits.map(s => s.pace_min_km);
  const minPace = Math.min(...paces);
  const maxPace = Math.max(...paces);
  const avgPace = paces.reduce((a, b) => a + b, 0) / paces.length;
  
  // Add padding for visual clarity
  const chartMin = Math.max(0, minPace - 0.5);
  const chartMax = maxPace + 0.5;
  const range = chartMax - chartMin;
  
  // Find fastest and slowest km
  const fastestIdx = paces.indexOf(minPace);
  const slowestIdx = paces.indexOf(maxPace);
  
  // Calculate bar height percentage (inverted: lower pace = taller bar)
  const getBarHeight = (pace) => {
    return ((chartMax - pace) / range) * 100;
  };
  
  // Get color based on pace relative to average
  const getBarColor = (pace, idx) => {
    if (idx === fastestIdx) return "#22c55e"; // Green for fastest
    if (idx === slowestIdx) return "#f97316"; // Orange for slowest
    if (pace < avgPace - 0.2) return "#3b82f6"; // Blue for fast
    if (pace > avgPace + 0.2) return "#eab308"; // Yellow for slow
    return "#8b5cf6"; // Purple for average
  };

  return (
    <div className="space-y-3">
      {/* Chart header with stats */}
      <div className="flex items-center justify-between">
        <div className="flex gap-4">
          <div>
            <p className="font-mono text-[9px] text-muted-foreground uppercase">
              {lang === "fr" ? "Plus rapide" : "Fastest"}
            </p>
            <p className="font-mono text-xs font-semibold text-emerald-400">
              Km {splits[fastestIdx]?.km} • {splits[fastestIdx]?.pace_str}
            </p>
          </div>
          <div>
            <p className="font-mono text-[9px] text-muted-foreground uppercase">
              {lang === "fr" ? "Plus lent" : "Slowest"}
            </p>
            <p className="font-mono text-xs font-semibold text-orange-400">
              Km {splits[slowestIdx]?.km} • {splits[slowestIdx]?.pace_str}
            </p>
          </div>
          <div>
            <p className="font-mono text-[9px] text-muted-foreground uppercase">
              {lang === "fr" ? "Moyenne" : "Average"}
            </p>
            <p className="font-mono text-xs font-semibold">
              {Math.floor(avgPace)}:{String(Math.round((avgPace % 1) * 60)).padStart(2, '0')}/km
            </p>
          </div>
        </div>
      </div>

      {/* Bar chart */}
      <div className="relative h-32 flex items-end gap-0.5 bg-muted/20 rounded-lg p-2 pt-6">
        {/* Y-axis labels */}
        <div className="absolute left-1 top-1 bottom-6 flex flex-col justify-between text-[8px] font-mono text-muted-foreground">
          <span>{Math.floor(chartMin)}:{String(Math.round((chartMin % 1) * 60)).padStart(2, '0')}</span>
          <span>{Math.floor(chartMax)}:{String(Math.round((chartMax % 1) * 60)).padStart(2, '0')}</span>
        </div>
        
        {/* Average line */}
        <div 
          className="absolute left-8 right-2 h-px bg-white/30 z-10"
          style={{ 
            bottom: `${getBarHeight(avgPace) + 8}%`,
          }}
        >
          <span className="absolute -right-1 -top-2 text-[8px] font-mono text-white/50">moy</span>
        </div>

        {/* Bars container */}
        <div className="flex-1 flex items-end gap-0.5 h-full ml-6">
          {splits.map((split, idx) => {
            const height = getBarHeight(split.pace_min_km);
            const color = getBarColor(split.pace_min_km, idx);
            
            return (
              <div
                key={split.km}
                className="flex-1 flex flex-col items-center justify-end group relative"
                style={{ minWidth: splits.length > 15 ? '8px' : '16px' }}
              >
                {/* Tooltip on hover */}
                <div className="absolute bottom-full mb-1 hidden group-hover:block z-20 bg-black/90 px-2 py-1 rounded text-[10px] font-mono whitespace-nowrap">
                  <p className="text-white font-semibold">Km {split.km}</p>
                  <p className="text-emerald-400">{split.pace_str}/km</p>
                  {split.avg_hr && <p className="text-red-400">{split.avg_hr} bpm</p>}
                </div>
                
                {/* Bar */}
                <div
                  className="w-full rounded-t transition-all duration-300 hover:opacity-80"
                  style={{
                    height: `${Math.max(height, 5)}%`,
                    backgroundColor: color,
                    minHeight: '4px'
                  }}
                />
                
                {/* Km label (show every 5km or if few splits) */}
                {(splits.length <= 10 || split.km % 5 === 0 || split.km === 1) && (
                  <span className="font-mono text-[8px] text-muted-foreground mt-1">
                    {split.km}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-4 text-[9px] font-mono text-muted-foreground">
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-emerald-400" />
          <span>{lang === "fr" ? "Rapide" : "Fast"}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-violet-500" />
          <span>{lang === "fr" ? "Normal" : "Normal"}</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-orange-400" />
          <span>{lang === "fr" ? "Lent" : "Slow"}</span>
        </div>
      </div>
    </div>
  );
};

// Heart Rate Zones Visualization Component
const HRZonesChart = ({ zones, t }) => {
  if (!zones) return null;
  
  const zoneConfig = [
    { key: "z1", color: "#3B82F6", label: "Z1", desc: "recovery" },
    { key: "z2", color: "#22C55E", label: "Z2", desc: "endurance" },
    { key: "z3", color: "#EAB308", label: "Z3", desc: "tempo" },
    { key: "z4", color: "#F97316", label: "Z4", desc: "threshold" },
    { key: "z5", color: "#EF4444", label: "Z5", desc: "max" },
  ];
  
  const maxPct = Math.max(...zoneConfig.map(z => zones[z.key] || 0), 1);
  
  return (
    <div className="space-y-2">
      {zoneConfig.map((zone) => {
        const pct = zones[zone.key] || 0;
        const barWidth = Math.max((pct / maxPct) * 100, pct > 0 ? 8 : 0);
        
        return (
          <div key={zone.key} className="flex items-center gap-2">
            <span className="font-mono text-[10px] w-6 text-muted-foreground">
              {zone.label}
            </span>
            <div className="flex-1 h-5 bg-muted/30 relative overflow-hidden">
              <div 
                className="h-full transition-all duration-500 ease-out flex items-center"
                style={{ 
                  width: `${barWidth}%`,
                  backgroundColor: zone.color,
                  minWidth: pct > 0 ? "24px" : "0"
                }}
              >
                {pct > 0 && (
                  <span className="font-mono text-[10px] text-white font-semibold px-1.5 drop-shadow-sm">
                    {pct}%
                  </span>
                )}
              </div>
            </div>
            <span className="font-mono text-[9px] w-16 text-muted-foreground hidden sm:block">
              {t(`zones.${zone.desc}`)}
            </span>
          </div>
        );
      })}
    </div>
  );
};

// Zone summary component
const ZoneSummary = ({ zones, t }) => {
  if (!zones) return null;
  
  const easyPct = (zones.z1 || 0) + (zones.z2 || 0);
  const moderatePct = zones.z3 || 0;
  const hardPct = (zones.z4 || 0) + (zones.z5 || 0);
  
  let dominant = "balanced";
  let dominantColor = "text-chart-3";
  
  if (hardPct >= 50) {
    dominant = "hard";
    dominantColor = "text-chart-1";
  } else if (easyPct >= 60) {
    dominant = "easy";
    dominantColor = "text-chart-2";
  }
  
  return (
    <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
      <div className="flex gap-4">
        <div className="text-center">
          <p className="font-mono text-xs font-semibold text-chart-2">{easyPct}%</p>
          <p className="font-mono text-[8px] text-muted-foreground uppercase">{t("zones.easy")}</p>
        </div>
        <div className="text-center">
          <p className="font-mono text-xs font-semibold text-chart-3">{moderatePct}%</p>
          <p className="font-mono text-[8px] text-muted-foreground uppercase">{t("zones.moderate")}</p>
        </div>
        <div className="text-center">
          <p className="font-mono text-xs font-semibold text-chart-1">{hardPct}%</p>
          <p className="font-mono text-[8px] text-muted-foreground uppercase">{t("zones.hard")}</p>
        </div>
      </div>
      <div className={`px-2 py-1 rounded-sm ${dominant === "hard" ? "bg-chart-1/10" : dominant === "easy" ? "bg-chart-2/10" : "bg-chart-3/10"}`}>
        <p className={`font-mono text-[10px] font-semibold ${dominantColor}`}>
          {t(`zones.dominant_${dominant}`)}
        </p>
      </div>
    </div>
  );
};

export default function WorkoutDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t, lang } = useLanguage();
  const [workout, setWorkout] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [detailedAnalysis, setDetailedAnalysis] = useState(null);
  const [ragAnalysis, setRagAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    loadWorkout();
  }, [id, lang]);

  const loadWorkout = async () => {
    setLoading(true);
    try {
      const [workoutRes, analysisRes, detailedRes, ragRes] = await Promise.all([
        axios.get(`${API}/workouts/${id}`),
        axios.get(`${API}/coach/workout-analysis/${id}?language=${lang}`),
        axios.get(`${API}/coach/detailed-analysis/${id}?language=${lang}`).catch(() => ({ data: null })),
        axios.get(`${API}/rag/workout/${id}`).catch(() => ({ data: null }))
      ]);
      setWorkout(workoutRes.data);
      setAnalysis(analysisRes.data);
      setDetailedAnalysis(detailedRes.data);
      setRagAnalysis(ragRes.data);
    } catch (error) {
      console.error("Failed to load workout:", error);
      try {
        const res = await axios.get(`${API}/workouts/${id}`);
        setWorkout(res.data);
      } catch (e) {
        console.error("Workout not found");
      }
    } finally {
      setLoading(false);
    }
  };

  const goToAskCoach = () => {
    navigate("/coach");
  };

  if (loading) {
    return (
      <div className="p-4 pb-24 flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-primary" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            {lang === "fr" ? "Analyse en cours..." : "Analyzing..."}
          </span>
        </div>
      </div>
    );
  }

  if (!workout) {
    return (
      <div className="p-4 pb-24" data-testid="workout-not-found">
        <Link to="/" className="inline-flex items-center gap-2 text-muted-foreground mb-6">
          <ArrowLeft className="w-4 h-4" />
          <span className="font-mono text-xs uppercase">{t("workout.back")}</span>
        </Link>
        <p className="text-muted-foreground">{t("workout.notFound")}</p>
      </div>
    );
  }

  const Icon = getWorkoutIcon(workout.type);
  const typeLabel = t(`workoutTypes.${workout.type}`) || workout.type;
  const dateStr = new Date(workout.date).toLocaleDateString(
    lang === "fr" ? "fr-FR" : "en-US",
    { weekday: "short", month: "short", day: "numeric" }
  );

  const getSessionTypeStyle = (label) => {
    if (label === "hard") return "text-chart-1 bg-chart-1/10";
    if (label === "easy") return "text-chart-2 bg-chart-2/10";
    return "text-chart-3 bg-chart-3/10";
  };

  const getIntensityColor = (intensity) => {
    const lower = intensity?.toLowerCase();
    if (lower?.includes("soutenu") || lower?.includes("sustain") || lower?.includes("hard") || lower?.includes("haute")) {
      return "text-chart-1 bg-chart-1/10";
    }
    if (lower?.includes("facile") || lower?.includes("easy") || lower?.includes("basse")) {
      return "text-chart-2 bg-chart-2/10";
    }
    return "text-chart-3 bg-chart-3/10";
  };

  return (
    <div className="p-4 pb-24" data-testid="workout-detail">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <Link to="/progress" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="font-mono text-[10px] uppercase text-muted-foreground">{typeLabel}</span>
        </div>
        <span className="font-mono text-[10px] text-muted-foreground">{dateStr}</span>
      </div>

      {/* Workout Title */}
      <h1 className="font-heading text-base uppercase tracking-tight font-bold mb-4 leading-tight">
        {workout.name}
      </h1>

      {/* 1) RÉSUMÉ COACH - Premier élément visible */}
      {analysis?.coach_summary && (
        <Card className="bg-card border-border mb-3">
          <CardContent className="p-3">
            <p className="font-mono text-sm leading-relaxed" data-testid="coach-summary">
              {analysis.coach_summary}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 2) SNAPSHOT - 3 Cards: Intensité, Charge, Type */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        {/* Intensité */}
        {(analysis?.intensity || detailedAnalysis?.execution) && (
          <Card className="bg-card border-border">
            <CardContent className="p-2">
              <div className="flex items-center gap-1 mb-1">
                <Zap className="w-3 h-3 text-muted-foreground" />
                <span className="font-mono text-[8px] uppercase tracking-widest text-muted-foreground">
                  {t("analysis.intensity")}
                </span>
              </div>
              {detailedAnalysis?.execution?.intensity ? (
                <span className={`inline-block px-2 py-0.5 rounded-sm font-mono text-xs ${getIntensityColor(detailedAnalysis.execution.intensity)}`}>
                  {detailedAnalysis.execution.intensity}
                </span>
              ) : (
                <>
                  <p className="font-mono text-xs font-semibold leading-tight">
                    {analysis?.intensity?.pace || "--"}
                  </p>
                  {analysis?.intensity?.avg_hr && (
                    <p className="font-mono text-[10px] text-muted-foreground flex items-center gap-1">
                      <Heart className="w-2.5 h-2.5" />
                      {analysis.intensity.avg_hr}
                    </p>
                  )}
                </>
              )}
            </CardContent>
          </Card>
        )}

        {/* Charge/Volume */}
        {(analysis?.load || detailedAnalysis?.execution) && (
          <Card className="bg-card border-border">
            <CardContent className="p-2">
              <div className="flex items-center gap-1 mb-1">
                <Scale className="w-3 h-3 text-muted-foreground" />
                <span className="font-mono text-[8px] uppercase tracking-widest text-muted-foreground">
                  {t("analysis.load")}
                </span>
              </div>
              <p className="font-mono text-xs font-semibold leading-tight">
                {analysis?.load?.distance_km || detailedAnalysis?.execution?.volume || "--"} {analysis?.load?.distance_km ? "km" : ""}
              </p>
              {analysis?.load?.duration_min && (
                <p className="font-mono text-[10px] text-muted-foreground">
                  {formatDuration(analysis.load.duration_min)}
                </p>
              )}
              {analysis?.load?.direction && analysis.load.direction !== "stable" && (
                <p className={`font-mono text-[9px] mt-1 flex items-center gap-0.5 ${
                  analysis.load.direction === "up" ? "text-chart-1" : "text-chart-4"
                }`}>
                  {analysis.load.direction === "up" ? (
                    <TrendingUp className="w-2.5 h-2.5" />
                  ) : (
                    <TrendingDown className="w-2.5 h-2.5" />
                  )}
                  {t(`analysis.load_${analysis.load.direction}`)}
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {/* Type/Régularité */}
        {(analysis?.session_type || detailedAnalysis?.execution) && (
          <Card className="bg-card border-border">
            <CardContent className="p-2">
              <div className="flex items-center gap-1 mb-1">
                <Activity className="w-3 h-3 text-muted-foreground" />
                <span className="font-mono text-[8px] uppercase tracking-widest text-muted-foreground">
                  {t("analysis.type")}
                </span>
              </div>
              {analysis?.session_type ? (
                <div className={`inline-block px-2 py-1 rounded-sm ${getSessionTypeStyle(analysis.session_type.label)}`}>
                  <p className="font-mono text-xs font-semibold">
                    {t(`analysis.session_types.${analysis.session_type.label}`)}
                  </p>
                </div>
              ) : detailedAnalysis?.execution?.regularity ? (
                <p className="font-mono text-xs">{detailedAnalysis.execution.regularity}</p>
              ) : null}
            </CardContent>
          </Card>
        )}
      </div>

      {/* 3) ZONES CARDIAQUES */}
      {workout.effort_zone_distribution && (
        <Card className="bg-card border-border mb-3" data-testid="hr-zones-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <HeartPulse className="w-4 h-4 text-chart-1" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {t("analysis.hrZones")}
              </span>
              {workout.avg_heart_rate && (
                <span className="ml-auto font-mono text-[10px] text-muted-foreground flex items-center gap-1">
                  <Heart className="w-3 h-3" />
                  {t("analysis.avgHr")}: {workout.avg_heart_rate} bpm
                </span>
              )}
            </div>
            <HRZonesChart zones={workout.effort_zone_distribution} t={t} />
            <ZoneSummary zones={workout.effort_zone_distribution} t={t} />
          </CardContent>
        </Card>
      )}

      {/* 3.5) GRAPHIQUE DES ALLURES PAR KM */}
      {workout.km_splits && workout.km_splits.length > 0 && (
        <Card className="bg-card border-border mb-3" data-testid="splits-chart-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-violet-400" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {lang === "fr" ? "Allure par kilomètre" : "Pace per kilometer"}
              </span>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                {workout.km_splits.length} km
              </span>
            </div>
            <SplitsChart splits={workout.km_splits} lang={lang} />
          </CardContent>
        </Card>
      )}

      {/* 4) CE QUE ÇA SIGNIFIE - Fusionné */}
      {(analysis?.insight || detailedAnalysis?.meaning?.text) && (
        <Card className="bg-card border-border mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="w-4 h-4 text-muted-foreground" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {lang === "fr" ? "Ce que ça signifie" : "What it means"}
              </span>
            </div>
            <p className="font-mono text-xs text-muted-foreground leading-relaxed" data-testid="meaning-text">
              {detailedAnalysis?.meaning?.text || analysis?.insight}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 5) RÉCUPÉRATION */}
      {detailedAnalysis?.recovery?.text && (
        <Card className="bg-orange-500/5 border-orange-500/20 mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="w-4 h-4 text-orange-400" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-orange-400">
                {lang === "fr" ? "Récupération" : "Recovery"}
              </span>
            </div>
            <p className="font-mono text-xs text-orange-300 leading-relaxed" data-testid="recovery-text">
              {detailedAnalysis.recovery.text}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 6) CONSEIL COACH */}
      {(analysis?.guidance || detailedAnalysis?.advice?.text) && (
        <Card className="bg-primary/5 border-primary/20 mb-3">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Lightbulb className="w-4 h-4 text-primary" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-primary">
                {lang === "fr" ? "Conseil coach" : "Coach advice"}
              </span>
            </div>
            <p className="font-mono text-xs text-primary leading-relaxed" data-testid="advice-text">
              {detailedAnalysis?.advice?.text || analysis?.guidance}
            </p>
          </CardContent>
        </Card>
      )}

      {/* 7) ANALYSE RAG ENRICHIE */}
      {ragAnalysis && (
        <Card className="bg-card border-border mb-3" data-testid="rag-workout-card">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="w-4 h-4 text-amber-400" />
              <p className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {lang === "fr" ? "Analyse enrichie" : "Enhanced Analysis"}
              </p>
            </div>
            
            {/* RAG Summary */}
            <p className="font-mono text-xs text-muted-foreground leading-relaxed mb-3 whitespace-pre-line" data-testid="rag-workout-summary">
              {ragAnalysis.rag_summary?.split('\n').slice(0, 4).join('\n')}
            </p>

            {/* Split Analysis */}
            {ragAnalysis.workout?.split_analysis && Object.keys(ragAnalysis.workout.split_analysis).length > 0 && (
              <div className="p-2 bg-blue-500/10 rounded-sm mb-3" data-testid="split-analysis-card">
                <div className="flex items-center gap-2 mb-2">
                  <Activity className="w-3 h-3 text-blue-400" />
                  <span className="font-mono text-[9px] uppercase text-blue-400">
                    {lang === "fr" ? "Analyse des Splits" : "Split Analysis"}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {lang === "fr" ? "Km le + rapide" : "Fastest km"}
                    </p>
                    <p className="font-mono text-emerald-400 font-semibold">
                      Km {ragAnalysis.workout.split_analysis.fastest_km} 
                      <span className="text-muted-foreground ml-1">
                        ({Math.floor(ragAnalysis.workout.split_analysis.fastest_split_pace)}:{String(Math.round((ragAnalysis.workout.split_analysis.fastest_split_pace % 1) * 60)).padStart(2, '0')})
                      </span>
                    </p>
                  </div>
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {lang === "fr" ? "Km le + lent" : "Slowest km"}
                    </p>
                    <p className="font-mono text-amber-400 font-semibold">
                      Km {ragAnalysis.workout.split_analysis.slowest_km}
                      <span className="text-muted-foreground ml-1">
                        ({Math.floor(ragAnalysis.workout.split_analysis.slowest_split_pace)}:{String(Math.round((ragAnalysis.workout.split_analysis.slowest_split_pace % 1) * 60)).padStart(2, '0')})
                      </span>
                    </p>
                  </div>
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {lang === "fr" ? "Écart allure" : "Pace drop"}
                    </p>
                    <p className="font-mono font-semibold">
                      {ragAnalysis.workout.split_analysis.pace_drop > 0 ? '+' : ''}{Math.round(ragAnalysis.workout.split_analysis.pace_drop * 60)}s/km
                    </p>
                  </div>
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {lang === "fr" ? "Régularité" : "Consistency"}
                    </p>
                    <p className={`font-mono font-semibold ${
                      ragAnalysis.workout.split_analysis.consistency_score >= 80 ? 'text-emerald-400' :
                      ragAnalysis.workout.split_analysis.consistency_score >= 60 ? 'text-amber-400' : 'text-red-400'
                    }`}>
                      {Math.round(ragAnalysis.workout.split_analysis.consistency_score)}%
                    </p>
                  </div>
                </div>
                {ragAnalysis.workout.split_analysis.negative_split && (
                  <div className="mt-2 px-2 py-1 bg-emerald-500/20 rounded-sm">
                    <p className="font-mono text-[10px] text-emerald-400 font-semibold">
                      ✨ Negative Split - {lang === "fr" ? "Tu as accéléré en fin de sortie !" : "You sped up at the end!"}
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* HR Analysis */}
            {ragAnalysis.workout?.hr_analysis && Object.keys(ragAnalysis.workout.hr_analysis).length > 0 && (
              <div className="p-2 bg-red-500/10 rounded-sm mb-3" data-testid="hr-analysis-card">
                <div className="flex items-center gap-2 mb-2">
                  <Heart className="w-3 h-3 text-red-400" />
                  <span className="font-mono text-[9px] uppercase text-red-400">
                    {lang === "fr" ? "Analyse Cardiaque" : "Heart Rate Analysis"}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">Min</p>
                    <p className="font-mono font-semibold">{ragAnalysis.workout.hr_analysis.min_hr} bpm</p>
                  </div>
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">Moy</p>
                    <p className="font-mono font-semibold">{ragAnalysis.workout.hr_analysis.avg_hr} bpm</p>
                  </div>
                  <div>
                    <p className="font-mono text-[10px] text-muted-foreground">Max</p>
                    <p className="font-mono font-semibold">{ragAnalysis.workout.hr_analysis.max_hr} bpm</p>
                  </div>
                </div>
                {ragAnalysis.workout.hr_analysis.hr_drift !== 0 && (
                  <div className="mt-2">
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {lang === "fr" ? "Dérive cardiaque" : "HR Drift"}
                    </p>
                    <p className={`font-mono text-xs font-semibold ${
                      Math.abs(ragAnalysis.workout.hr_analysis.hr_drift) > 10 ? 'text-amber-400' : 'text-muted-foreground'
                    }`}>
                      {ragAnalysis.workout.hr_analysis.hr_drift > 0 ? '+' : ''}{ragAnalysis.workout.hr_analysis.hr_drift} bpm
                      {Math.abs(ragAnalysis.workout.hr_analysis.hr_drift) > 10 && (
                        <span className="ml-2 text-[10px]">
                          ({lang === "fr" ? "Hydratation à surveiller" : "Watch hydration"})
                        </span>
                      )}
                    </p>
                  </div>
                )}
              </div>
            )}
            
            {/* Comparison with similar workouts */}
            {ragAnalysis.comparison?.similar_found > 0 && (
              <div className="p-2 bg-muted/30 rounded-sm mb-3">
                <div className="flex items-center gap-2 mb-1">
                  <History className="w-3 h-3 text-muted-foreground" />
                  <span className="font-mono text-[9px] uppercase text-muted-foreground">
                    {lang === "fr" ? "Comparaison" : "Comparison"}
                  </span>
                </div>
                <p className="font-mono text-xs">
                  {ragAnalysis.comparison.similar_found} {lang === "fr" ? "séances similaires" : "similar workouts"}
                </p>
                {ragAnalysis.comparison.progression && (
                  <p className={`font-mono text-xs mt-1 ${
                    ragAnalysis.comparison.progression.includes('plus rapide') || ragAnalysis.comparison.progression.includes('faster')
                      ? 'text-emerald-400' 
                      : 'text-amber-400'
                  }`}>
                    {ragAnalysis.comparison.progression.includes('plus rapide') || ragAnalysis.comparison.progression.includes('faster') ? (
                      <TrendingUp className="w-3 h-3 inline mr-1" />
                    ) : (
                      <TrendingDown className="w-3 h-3 inline mr-1" />
                    )}
                    {ragAnalysis.comparison.progression}
                  </p>
                )}
                {ragAnalysis.comparison.date_precedente && (
                  <p className="font-mono text-[10px] text-muted-foreground mt-1 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {lang === "fr" ? "vs" : "vs"} {ragAnalysis.comparison.date_precedente}
                  </p>
                )}
              </div>
            )}
            
            {/* Points forts & améliorer */}
            {(ragAnalysis.points_forts?.length > 0 || ragAnalysis.points_ameliorer?.length > 0) && (
              <div className="flex flex-wrap gap-2">
                {ragAnalysis.points_forts?.slice(0, 2).map((point, i) => (
                  <span key={`fort-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-emerald-500/10 text-emerald-400 rounded-sm">
                    <Target className="w-3 h-3" />
                    <span className="font-mono text-[10px]">{point}</span>
                  </span>
                ))}
                {ragAnalysis.points_ameliorer?.slice(0, 1).map((point, i) => (
                  <span key={`ameliorer-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-amber-500/10 text-amber-400 rounded-sm">
                    <AlertTriangle className="w-3 h-3" />
                    <span className="font-mono text-[10px]">{point}</span>
                  </span>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 8) POUR ALLER PLUS LOIN - Accordion (from detailed analysis) */}
      {detailedAnalysis?.advanced?.comparisons && (
        <Card className="bg-card border-border mb-3">
          <CardContent className="p-0">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="w-full p-3 flex items-center justify-between text-left"
              data-testid="advanced-toggle"
            >
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                {lang === "fr" ? "Pour aller plus loin" : "Go further"}
              </span>
              {showAdvanced ? (
                <ChevronUp className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              )}
            </button>
            {showAdvanced && (
              <div className="px-3 pb-3 border-t border-border pt-3">
                <p className="font-mono text-[11px] text-muted-foreground leading-relaxed whitespace-pre-line" data-testid="advanced-text">
                  {detailedAnalysis.advanced.comparisons}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 9) ACTION - Poser une question */}
      <div className="mt-4">
        <Button
          onClick={goToAskCoach}
          data-testid="ask-coach-btn"
          className="w-full bg-primary text-white hover:bg-primary/90 rounded-none h-10 font-mono text-xs uppercase tracking-wider flex items-center justify-center gap-2"
        >
          <MessageSquare className="w-3.5 h-3.5" />
          {lang === "fr" ? "Poser une question au coach" : "Ask the coach"}
        </Button>
      </div>
    </div>
  );
}
