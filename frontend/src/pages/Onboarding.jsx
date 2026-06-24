import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { API_BASE_URL } from "@/config";
const API = API_BASE_URL;
const USER_ID = "default";

const STEPS = [
  { key: "welcome", title: "Welcome" },
  { key: "fitness", title: "Fitness level" },
  { key: "goal", title: "Goal" },
  { key: "frequency", title: "Training frequency" },
  { key: "device", title: "Device connection" },
  { key: "target", title: "Training plan target" },
];

const FITNESS_OPTIONS = ["Beginner", "Intermediate", "Advanced"];
const GOAL_OPTIONS = [
  "Improve performance",
  "Get fitter / healthier",
  "Lose weight",
  "Reduce stress",
];
const FREQUENCY_OPTIONS = ["1–2 times/week", "3–4 times/week", "5+ times/week"];
const DEVICE_OPTIONS = ["Apple Health", "Garmin", "Whoop", "Fitbit"];
const TARGET_OPTIONS = ["5km", "10km", "semi", "marathon", "ultra trail"];

function OptionGrid({ options, value, onSelect, testIdPrefix }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {options.map((option) => (
        <button
          key={option}
          onClick={() => onSelect(option)}
          className={`text-left px-4 py-3 rounded-lg border transition-all font-mono text-sm ${
            value === option
              ? "border-primary bg-primary/10 text-primary"
              : "border-border bg-card text-foreground hover:border-primary/40"
          }`}
          data-testid={`${testIdPrefix}-${option.replace(/\s+/g, "-").toLowerCase()}`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

export default function Onboarding() {
  const navigate = useNavigate();
  const [stepIndex, setStepIndex] = useState(0);
  const [fitnessLevel, setFitnessLevel] = useState("");
  const [goal, setGoal] = useState("");
  const [frequency, setFrequency] = useState("");
  const [device, setDevice] = useState("");
  const [target, setTarget] = useState("");
  const [physioData, setPhysioData] = useState(null);
  const [loadingPhysio, setLoadingPhysio] = useState(true);
  const [saving, setSaving] = useState(false);

  // Garmin connect UI states (sensitive data cleared after send)
  const [garminUsername, setGarminUsername] = useState("");
  const [garminPassword, setGarminPassword] = useState("");
  const [connectingGarmin, setConnectingGarmin] = useState(false);
  const [showGarminForm, setShowGarminForm] = useState(false);

  useEffect(() => {
    const loadPhysio = async () => {
      setLoadingPhysio(true);
      try {
        const res = await axios.get(`${API}/cardio-coach?user_id=${USER_ID}`);
        setPhysioData(res.data?.metrics || null);
      } catch (err) {
        setPhysioData(null);
      } finally {
        setLoadingPhysio(false);
      }
    };
    loadPhysio();
  }, []);

  const canContinue = useMemo(() => {
    const key = STEPS[stepIndex]?.key;
    if (key === "welcome") return true;
    if (key === "fitness") return Boolean(fitnessLevel);
    if (key === "goal") return Boolean(goal);
    if (key === "frequency") return Boolean(frequency);
    if (key === "device") return Boolean(device);
    if (key === "target") return Boolean(target);
    return false;
  }, [stepIndex, fitnessLevel, goal, frequency, device, target]);

  const recommendation = useMemo(() => {
    if (!target || !fitnessLevel || !goal || !frequency) return null;

    const fatigueRatio = physioData?.fatigue_ratio ?? 1.0;
    const sleepHours = physioData?.sleep_hours;
    const intensity =
      fatigueRatio > 1.5 ? "recovery-focused intensity"
      : fatigueRatio > 1.2 ? "moderate intensity"
      : "performance intensity";

    return {
      title: `${fitnessLevel} plan for ${target}`,
      summary: `Based on your goal (${goal}) and frequency (${frequency}), start with ${intensity}.`,
      detail: `Physiology signal: fatigue ratio ${fatigueRatio}${sleepHours ? `, sleep ${sleepHours}h` : ""}.`,
    };
  }, [target, fitnessLevel, goal, frequency, physioData]);

  const handleNext = () => {
    if (stepIndex < STEPS.length - 1) {
      setStepIndex((prev) => prev + 1);
    }
  };

  const handleBack = () => {
    if (stepIndex > 0) {
      setStepIndex((prev) => prev - 1);
    }
  };

  const handleApplyPlan = async () => {
    if (!target || !frequency) return;
    const targetMap = {
      "5km": "5K",
      "10km": "10K",
      semi: "SEMI",
      marathon: "MARATHON",
      "ultra trail": "ULTRA",
    };
    const sessionsMap = {
      "1–2 times/week": 2,
      "3–4 times/week": 4,
      "5+ times/week": 6,
    };

    setSaving(true);
    try {
      await axios.post(`${API}/training/set-goal?goal=${targetMap[target]}`, {}, {
        headers: { "X-User-Id": USER_ID },
      });
      await axios.post(`${API}/training/refresh?sessions=${sessionsMap[frequency]}`, {}, {
        headers: { "X-User-Id": USER_ID },
      });
      toast.success("Personalized plan updated");
      navigate("/training");
    } catch (err) {
      toast.error("Unable to save onboarding choices");
    } finally {
      setSaving(false);
    }
  };

  const stepKey = STEPS[stepIndex].key;

  return (
    <div className="p-4 pb-24 space-y-4" data-testid="onboarding-page">
      <Card className="bg-card border-border">
        <CardContent className="p-6 space-y-5">
          <div className="flex items-center justify-between">
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
              Step {stepIndex + 1} / {STEPS.length}
            </p>
            <p className="font-mono text-xs text-muted-foreground">{STEPS[stepIndex].title}</p>
          </div>

          {stepKey === "welcome" && (
            <div className="space-y-4">
              <h1 className="text-3xl font-black tracking-tight">Turn your data into performance</h1>
              <Button
                onClick={handleNext}
                className="w-full bg-primary text-white font-bold uppercase tracking-wider"
                data-testid="onboarding-start"
              >
                Start my optimization
              </Button>
            </div>
          )}

          {stepKey === "fitness" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">Select your fitness level</h2>
              <OptionGrid options={FITNESS_OPTIONS} value={fitnessLevel} onSelect={setFitnessLevel} testIdPrefix="fitness-option" />
            </div>
          )}

          {stepKey === "goal" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">What's your primary goal?</h2>
              <OptionGrid options={GOAL_OPTIONS} value={goal} onSelect={setGoal} testIdPrefix="goal-option" />
            </div>
          )}

          {stepKey === "frequency" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">How often do you want to train?</h2>
              <OptionGrid options={FREQUENCY_OPTIONS} value={frequency} onSelect={setFrequency} testIdPrefix="frequency-option" />
            </div>
          )}

          {stepKey === "device" && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold">Connect your device</h2>
              <OptionGrid
                options={DEVICE_OPTIONS}
                value={device}
                onSelect={(d) => {
                  setDevice(d);
                  if (d === "Garmin") {
                    setShowGarminForm(true);
                  } else {
                    setShowGarminForm(false);
                  }
                }}
                testIdPrefix="device-option"
              />

              {showGarminForm && (
                <div className="mt-4 p-4 border rounded bg-muted/20">
                  <p className="text-sm mb-2">Connect your Garmin account (secure).</p>
                  <input
                    type="text"
                    placeholder="Garmin username"
                    value={garminUsername}
                    onChange={(e) => setGarminUsername(e.target.value)}
                    className="w-full p-2 mb-2 rounded border"
                    data-testid="garmin-username"
                  />
                  <input
                    type="password"
                    placeholder="Garmin password"
                    value={garminPassword}
                    onChange={(e) => setGarminPassword(e.target.value)}
                    className="w-full p-2 mb-3 rounded border"
                    data-testid="garmin-password"
                  />
                  <div className="flex gap-2">
                    <button
                      className="px-3 py-2 bg-primary text-white rounded"
                      disabled={connectingGarmin || !garminUsername || !garminPassword}
                      onClick={async () => {
                        try {
                          setConnectingGarmin(true);
                          await axios.post(`${API}/auth/garmin/connect`, {
                            user_id: USER_ID,
                            garmin_username: garminUsername,
                            garmin_password: garminPassword,
                          });
                          toast.success("Garmin connection scheduled");
                          setShowGarminForm(false);
                          setStepIndex((s) => s + 1);
                        } catch (err) {
                          toast.error("Unable to connect to Garmin (check credentials)");
                        } finally {
                          // clear sensitive data immediately
                          setGarminPassword("");
                          setConnectingGarmin(false);
                        }
                      }}
                      data-testid="connect-garmin-btn"
                    >
                      {connectingGarmin ? "Connecting…" : "Connect Garmin"}
                    </button>

                    <button
                      className="px-3 py-2 border rounded"
                      onClick={() => {
                        setShowGarminForm(false);
                        setGarminPassword("");
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {stepKey === "target" && (
            <div className="space-y-4">
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">Select your training plan target</h2>
                <OptionGrid options={TARGET_OPTIONS} value={target} onSelect={setTarget} testIdPrefix="target-option" />
              </div>

              <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-2" data-testid="onboarding-recommendation">
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Personalized recommendation</p>
                {loadingPhysio ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading physiological data...
                  </div>
                ) : recommendation ? (
                  <>
                    <p className="font-semibold">{recommendation.title}</p>
                    <p className="text-sm text-muted-foreground">{recommendation.summary}</p>
                    <p className="text-xs text-muted-foreground">{recommendation.detail}</p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Complete selections to generate your recommendation.</p>
                )}
              </div>
            </div>
          )}

          {stepKey !== "welcome" && (
            <div className="flex items-center gap-2 pt-2">
              <Button variant="outline" onClick={handleBack} disabled={stepIndex === 0}>
                Back
              </Button>
              {stepKey !== "target" ? (
                <Button onClick={handleNext} disabled={!canContinue} className="ml-auto">
                  Continue
                </Button>
              ) : (
                <Button onClick={handleApplyPlan} disabled={!canContinue || saving} className="ml-auto" data-testid="apply-onboarding-plan">
                  {saving ? "Saving..." : "Apply my plan"}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
