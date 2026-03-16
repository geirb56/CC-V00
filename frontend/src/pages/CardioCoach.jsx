import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { API_BASE_URL } from "@/config";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import {
  Heart,
  Moon,
  BarChart2,
  Zap,
  Play,
  RefreshCw,
  Loader2,
  Activity,
  CheckCircle,
  AlertTriangle,
  XCircle,
} from "lucide-react";

const API = API_BASE_URL;

// ─── Recommendation thresholds (must match backend logic) ────────────────────
const FATIGUE_REST_THRESHOLD = 1.5;   // FatigueRatio > this → REST
const FATIGUE_EASY_THRESHOLD = 1.2;   // FatigueRatio > this → EASY RUN (else RUN HARD)
const LOAD_OPTIMAL_MIN = 0.8;         // ACWR optimal zone lower bound
const LOAD_OPTIMAL_MAX = 1.3;         // ACWR optimal zone upper bound

// ─── Colour helpers ──────────────────────────────────────────────────────────

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
    label: "RUN HARD",
  },
  yellow: {
    bg: "linear-gradient(135deg, #1c1003 0%, #451a03 100%)",
    accent: "#f59e0b",
    button: "#d97706",
    buttonHover: "#b45309",
    label: "EASY RUN",
  },
  red: {
    bg: "linear-gradient(135deg, #1c0202 0%, #450a0a 100%)",
    accent: "#ef4444",
    button: "#ef4444",
    buttonHover: "#dc2626",
    label: "REST",
  },
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function StatusIcon({ status, size = 16 }) {
  if (status === "green")
    return <CheckCircle size={size} color="#22c55e" />;
  if (status === "yellow")
    return <AlertTriangle size={size} color="#f59e0b" />;
  return <XCircle size={size} color="#ef4444" />;
}

function MetricWidget({ icon: Icon, label, value, unit, status, detail }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.green;
  return (
    <div
      className="flex-shrink-0 rounded-2xl p-4 flex flex-col gap-1"
      style={{
        width: 140,
        background: colors.bg,
        border: `1px solid ${colors.border}`,
      }}
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

// Custom tooltip for the trend graph
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

// ─── Main page ───────────────────────────────────────────────────────────────

export default function CardioCoach() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [runStarted, setRunStarted] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API}/cardio-coach?user_id=default`);
      setData(res.data);
    } catch (err) {
      console.error("CardioCoach fetch failed:", err);
      setError("Unable to load data. Showing cached demo.");
      // Fallback mock – matches the backend mock shape
      setData({
        mock: true,
        recommendation: "RUN HARD",
        recommendation_emoji: "🟢",
        recommendation_color: "green",
        next_workout: { label: "Intervals – 6 x 800 m", icon: "run" },
        metrics: {
          hrv_today: 58,
          hrv_baseline: 55,
          hrv_delta: -3,
          hrv_status: "green",
          rhr_today: 48,
          rhr_baseline: 50,
          rhr_delta: -2,
          rhr_status: "green",
          sleep_hours: 7.5,
          sleep_efficiency: 0.88,
          sleep_score: 0.74,
          sleep_status: "yellow",
          training_load: 1.05,
          training_load_status: "green",
          fatigue_physio: 0.0,
          fatigue_ratio: 0.7,
          fatigue_status: "green",
        },
        reasons: [
          "HRV above baseline (+3 ms) → good recovery",
          "RHR below baseline (−2 bpm) → rested",
          "Sleep 7.5 h at 88% efficiency",
          "Training load (ACWR) 1.05 → optimal",
          "Fatigue Ratio 0.70 → ready to perform",
        ],
        history: [
          { day: "Mon", hrv: 52, training_load: 1.1, fatigue_ratio: 0.85 },
          { day: "Tue", hrv: 55, training_load: 1.05, fatigue_ratio: 0.8 },
          { day: "Wed", hrv: 50, training_load: 1.2, fatigue_ratio: 1.1 },
          { day: "Thu", hrv: 48, training_load: 1.3, fatigue_ratio: 1.3 },
          { day: "Fri", hrv: 54, training_load: 1.0, fatigue_ratio: 0.9 },
          { day: "Sat", hrv: 57, training_load: 0.9, fatigue_ratio: 0.75 },
          { day: "Sun", hrv: 58, training_load: 1.05, fatigue_ratio: 0.7 },
        ],
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ── Loading state ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div
        className="flex flex-col items-center justify-center min-h-[60vh] gap-3"
        data-testid="cardio-coach-loading"
      >
        <Loader2
          className="animate-spin"
          size={32}
          style={{ color: "var(--accent-violet)" }}
        />
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          Computing your readiness…
        </p>
      </div>
    );
  }

  const m = data?.metrics || {};
  const recStyle = REC_STYLES[data?.recommendation_color] || REC_STYLES.green;
  const history = data?.history || [];

  return (
    <div
      className="p-4 pb-28 space-y-4"
      style={{ background: "var(--bg-primary)" }}
      data-testid="cardio-coach-screen"
    >
      {/* ── Error banner ────────────────────────────────────────────────────── */}
      {error && (
        <div
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
          style={{ background: "#f59e0b15", border: "1px solid #f59e0b30", color: "#f59e0b" }}
        >
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      )}

      {/* ── Decision card ───────────────────────────────────────────────────── */}
      <div
        className="rounded-2xl p-5 space-y-3"
        style={{ background: recStyle.bg, border: `1px solid ${recStyle.accent}30` }}
        data-testid="decision-card"
      >
        {/* Header row */}
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: recStyle.accent }}>
            Today's Recommendation
          </span>
          <button
            onClick={fetchData}
            className="p-1 rounded-lg opacity-60 hover:opacity-100 transition-opacity"
            aria-label="Refresh"
          >
            <RefreshCw size={14} style={{ color: recStyle.accent }} />
          </button>
        </div>

        {/* Recommendation badge */}
        <div className="flex items-center gap-3">
          <span className="text-4xl">{data?.recommendation_emoji}</span>
          <span
            className="text-3xl font-black tracking-tight"
            style={{ color: recStyle.accent }}
          >
            {data?.recommendation || "—"}
          </span>
        </div>

        {/* Reasons list */}
        <ul className="space-y-1">
          {(data?.reasons || []).map((r, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-xs"
              style={{ color: "var(--text-secondary)" }}
            >
              <span className="mt-0.5 shrink-0" style={{ color: recStyle.accent }}>
                ›
              </span>
              {r}
            </li>
          ))}
        </ul>
      </div>

      {/* ── Next workout card ───────────────────────────────────────────────── */}
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
            Next Workout
          </p>
          <p
            className="font-bold text-base truncate"
            style={{ color: "var(--text-primary)" }}
          >
            {data?.next_workout?.label || "—"}
          </p>
        </div>
        <Play size={20} style={{ color: recStyle.accent }} />
      </div>

      {/* ── Metric widgets (horizontal scroll) ─────────────────────────────── */}
      <div>
        <h2
          className="text-xs uppercase tracking-widest mb-3 font-semibold"
          style={{ color: "var(--text-tertiary)" }}
        >
          Today's Metrics
        </h2>
        <div
          className="flex gap-3 overflow-x-auto pb-2 -mx-4 px-4"
          style={{ scrollbarWidth: "none" }}
          data-testid="metrics-scroll"
        >
          <MetricWidget
            icon={Heart}
            label="HRV Deviation"
            value={m.hrv_delta !== undefined ? (m.hrv_delta >= 0 ? `+${m.hrv_delta}` : `${m.hrv_delta}`) : "—"}
            unit="ms"
            status={m.hrv_status || "green"}
            detail={`Today ${m.hrv_today ?? "—"} ms`}
          />
          <MetricWidget
            icon={Moon}
            label="Resting HR"
            value={m.rhr_today ?? "—"}
            unit="bpm"
            status={m.rhr_status || "green"}
            detail={`Baseline ${m.rhr_baseline ?? "—"} bpm`}
          />
          <MetricWidget
            icon={Zap}
            label="Sleep"
            value={m.sleep_hours ?? "—"}
            unit="h"
            status={m.sleep_status || "green"}
            detail={`${m.sleep_efficiency !== undefined ? Math.round(m.sleep_efficiency * 100) : "—"}% efficiency`}
          />
          <MetricWidget
            icon={BarChart2}
            label="Training Load"
            value={m.training_load ?? "—"}
            unit="ACWR"
            status={m.training_load_status || "green"}
            detail={m.training_load >= LOAD_OPTIMAL_MIN && m.training_load <= LOAD_OPTIMAL_MAX ? "Optimal zone" : "Outside zone"}
          />
          <MetricWidget
            icon={Activity}
            label="Fatigue Ratio"
            value={m.fatigue_ratio ?? "—"}
            unit=""
            status={m.fatigue_status || "green"}
            detail={m.fatigue_ratio <= FATIGUE_EASY_THRESHOLD ? "Low fatigue" : m.fatigue_ratio <= FATIGUE_REST_THRESHOLD ? "Moderate" : "High fatigue"}
          />
        </div>
      </div>

      {/* ── 7-Day Trend Graph ───────────────────────────────────────────────── */}
      <div
        className="rounded-2xl p-4"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border-color)" }}
        data-testid="trend-graph"
      >
        <h2
          className="text-xs uppercase tracking-widest mb-4 font-semibold"
          style={{ color: "var(--text-tertiary)" }}
        >
          7-Day Trend — Load vs Recovery
        </h2>

        <ResponsiveContainer width="100%" height={220}>
          <BarChart
            data={history}
            margin={{ top: 5, right: 5, left: -20, bottom: 0 }}
            barCategoryGap="20%"
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="var(--border-color)"
              vertical={false}
            />
            <XAxis
              dataKey="day"
              tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              yAxisId="left"
              tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              domain={[0, "auto"]}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              domain={[0, "auto"]}
            />
            <Tooltip content={<TrendTooltip />} />
            <Legend
              iconType="circle"
              iconSize={8}
              formatter={(v) => (
                <span style={{ color: "var(--text-secondary)", fontSize: 10 }}>{v}</span>
              )}
            />
            <Bar
              yAxisId="left"
              dataKey="training_load"
              name="Training Load (ACWR)"
              fill="#8b5cf680"
              radius={[4, 4, 0, 0]}
              maxBarSize={24}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="fatigue_ratio"
              name="Fatigue Ratio"
              stroke="#ec4899"
              strokeWidth={2}
              dot={{ r: 3, fill: "#ec4899" }}
              activeDot={{ r: 5 }}
            />
          </BarChart>
        </ResponsiveContainer>

        {/* Reference lines legend */}
        <div className="flex gap-4 mt-2 justify-center">
          <div className="flex items-center gap-1 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
            <div className="w-2 h-2 rounded-full" style={{ background: "#ec4899" }} />
            <span>Fatigue &gt;{FATIGUE_REST_THRESHOLD} → REST</span>
          </div>
          <div className="flex items-center gap-1 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
            <div className="w-2 h-2 rounded-full" style={{ background: "#f59e0b" }} />
            <span>&gt;{FATIGUE_EASY_THRESHOLD} → EASY</span>
          </div>
        </div>
      </div>

      {/* ── Start Run CTA ───────────────────────────────────────────────────── */}
      <button
        onClick={() => setRunStarted((v) => !v)}
        className="w-full py-4 rounded-2xl font-black text-white text-lg tracking-wider uppercase transition-all duration-200 active:scale-95 flex items-center justify-center gap-3 shadow-lg"
        style={{
          background: runStarted
            ? "var(--bg-card)"
            : `linear-gradient(135deg, ${recStyle.button} 0%, ${recStyle.buttonHover} 100%)`,
          border: `2px solid ${recStyle.accent}`,
          color: runStarted ? recStyle.accent : "white",
          boxShadow: runStarted ? "none" : `0 8px 24px ${recStyle.accent}40`,
        }}
        data-testid="start-run-btn"
      >
        <Play size={22} fill={runStarted ? recStyle.accent : "white"} />
        {runStarted ? "Running…" : data?.recommendation === "REST" ? "Log Rest Day" : "Start Run"}
      </button>

      {/* Mock data notice */}
      {data?.mock && (
        <p className="text-center text-[10px]" style={{ color: "var(--text-tertiary)" }}>
          Demo data — connect Terra wearable in Settings for live metrics
        </p>
      )}
    </div>
  );
}
