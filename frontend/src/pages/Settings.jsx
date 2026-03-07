import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useLanguage } from "@/context/LanguageContext";
import { useSubscription } from "@/context/SubscriptionContext";
import { Globe, Info, Link2, Loader2, Check, X, RefreshCw, Target, Calendar, Trash2, Clock, Route, Crown, Sparkles } from "lucide-react";
import { toast } from "sonner";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const USER_ID = "default";

const DISTANCE_OPTIONS = ["5k", "10k", "semi", "marathon", "ultra"];
const DISTANCE_KM = {
  "5k": 5,
  "10k": 10,
  "semi": 21.1,
  "marathon": 42.195,
  "ultra": 50
};

export default function Settings() {
  const { t, lang, setLang } = useLanguage();
  const { 
    subscription, 
    isTrial, 
    isEarlyAdopter, 
    isFree, 
    trialDaysRemaining,
    refreshSubscription 
  } = useSubscription();
  const [searchParams, setSearchParams] = useSearchParams();
  const [stravaStatus, setStravaStatus] = useState(null);
  const [loadingStrava, setLoadingStrava] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  
  // Premium state
  const [premiumStatus, setPremiumStatus] = useState(null);
  const [loadingPremium, setLoadingPremium] = useState(true);
  const [processingPayment, setProcessingPayment] = useState(false);
  
  // Goal state
  const [goal, setGoal] = useState(null);
  const [loadingGoal, setLoadingGoal] = useState(true);
  const [eventName, setEventName] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [distanceType, setDistanceType] = useState("marathon");
  const [targetHours, setTargetHours] = useState("");
  const [targetMinutes, setTargetMinutes] = useState("");
  const [savingGoal, setSavingGoal] = useState(false);

  useEffect(() => {
    loadStravaStatus();
    loadGoal();
    loadPremiumStatus();
    
    // Handle OAuth callback
    const stravaParam = searchParams.get("strava");
    if (stravaParam === "connected") {
      toast.success(lang === "fr" ? "Compte connecté" : "Account connected");
      setSearchParams({});
      triggerInitialSync();
    } else if (stravaParam === "error") {
      toast.error(lang === "fr" ? "Erreur de connexion" : "Connection failed");
      setSearchParams({});
    }
    
    // Handle Stripe callback
    const sessionId = searchParams.get("session_id");
    const premiumParam = searchParams.get("premium");
    
    if (sessionId && premiumParam === "success") {
      handlePaymentSuccess(sessionId);
    } else if (premiumParam === "cancelled") {
      toast.info(lang === "fr" ? "Paiement annulé" : "Payment cancelled");
      setSearchParams({});
    }
  }, [searchParams]);

  const loadPremiumStatus = async () => {
    try {
      const res = await axios.get(`${API}/premium/status?user_id=${USER_ID}`);
      setPremiumStatus(res.data);
    } catch (error) {
      console.error("Failed to load premium status:", error);
    } finally {
      setLoadingPremium(false);
    }
  };

  const handlePaymentSuccess = async (sessionId) => {
    setProcessingPayment(true);
    try {
      // Poll for payment completion
      let attempts = 0;
      const maxAttempts = 10;
      
      while (attempts < maxAttempts) {
        const res = await axios.get(`${API}/premium/checkout/status/${sessionId}?user_id=${USER_ID}`);
        
        if (res.data.status === "completed" || res.data.payment_status === "paid") {
          toast.success(lang === "fr" ? "🎉 Premium activé ! Bienvenue dans CardioCoach Pro" : "🎉 Premium activated!");
          loadPremiumStatus();
          setSearchParams({});
          break;
        } else if (res.data.status === "expired") {
          toast.error(lang === "fr" ? "Session expirée" : "Session expired");
          setSearchParams({});
          break;
        }
        
        await new Promise(r => setTimeout(r, 2000));
        attempts++;
      }
    } catch (error) {
      console.error("Payment verification error:", error);
      toast.error(lang === "fr" ? "Erreur de vérification" : "Verification error");
    } finally {
      setProcessingPayment(false);
      setSearchParams({});
    }
  };

  const handleSubscribe = async () => {
    try {
      const res = await axios.post(`${API}/premium/checkout`, {
        origin_url: window.location.origin
      }, {
        params: { user_id: USER_ID }
      });
      
      window.location.href = res.data.checkout_url;
    } catch (error) {
      console.error("Checkout error:", error);
      toast.error(lang === "fr" ? "Erreur de paiement" : "Payment error");
    }
  };

  const loadGoal = async () => {
    try {
      const res = await axios.get(`${API}/user/goal?user_id=${USER_ID}`);
      if (res.data) {
        setGoal(res.data);
        setEventName(res.data.event_name);
        setEventDate(res.data.event_date);
        setDistanceType(res.data.distance_type || "marathon");
        if (res.data.target_time_minutes) {
          setTargetHours(Math.floor(res.data.target_time_minutes / 60).toString());
          setTargetMinutes((res.data.target_time_minutes % 60).toString().padStart(2, "0"));
        }
      }
    } catch (error) {
      console.error("Failed to load goal:", error);
    } finally {
      setLoadingGoal(false);
    }
  };

  const handleSaveGoal = async () => {
    if (!eventName.trim() || !eventDate || !distanceType) {
      toast.error(lang === "fr" ? "Remplis tous les champs obligatoires" : "Fill all required fields");
      return;
    }
    
    // Calculate target time in minutes
    let targetTimeMinutes = null;
    if (targetHours || targetMinutes) {
      const hours = parseInt(targetHours) || 0;
      const mins = parseInt(targetMinutes) || 0;
      if (hours > 0 || mins > 0) {
        targetTimeMinutes = hours * 60 + mins;
      }
    }
    
    setSavingGoal(true);
    try {
      const res = await axios.post(`${API}/user/goal?user_id=${USER_ID}`, {
        event_name: eventName.trim(),
        event_date: eventDate,
        distance_type: distanceType,
        target_time_minutes: targetTimeMinutes
      });
      setGoal(res.data.goal);
      toast.success(t("settings.goalSaved"));
    } catch (error) {
      console.error("Failed to save goal:", error);
      toast.error(lang === "fr" ? "Erreur" : "Error");
    } finally {
      setSavingGoal(false);
    }
  };

  const handleDeleteGoal = async () => {
    try {
      await axios.delete(`${API}/user/goal?user_id=${USER_ID}`);
      setGoal(null);
      setEventName("");
      setEventDate("");
      setDistanceType("marathon");
      setTargetHours("");
      setTargetMinutes("");
      toast.success(t("settings.goalDeleted"));
    } catch (error) {
      console.error("Failed to delete goal:", error);
      toast.error(lang === "fr" ? "Erreur" : "Error");
    }
  };

  const triggerInitialSync = async () => {
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/strava/sync?user_id=${USER_ID}`);
      if (res.data.success) {
        const msg = lang === "fr" 
          ? `${res.data.synced_count} seances importees` 
          : `${res.data.synced_count} workouts imported`;
        toast.success(msg);
      }
      loadStravaStatus();
    } catch (error) {
      console.error("Initial sync failed:", error);
    } finally {
      setSyncing(false);
    }
  };

  const loadStravaStatus = async () => {
    try {
      const res = await axios.get(`${API}/strava/status?user_id=${USER_ID}`);
      setStravaStatus(res.data);
    } catch (error) {
      console.error("Failed to load connection status:", error);
      setStravaStatus({ connected: false, last_sync: null, workout_count: 0 });
    } finally {
      setLoadingStrava(false);
    }
  };

  const handleConnect = async () => {
    setConnecting(true);
    try {
      const res = await axios.get(`${API}/strava/authorize?user_id=${USER_ID}`);
      window.location.href = res.data.authorization_url;
    } catch (error) {
      console.error("Failed to initiate auth:", error);
      const message = error.response?.data?.detail || (lang === "fr" ? "Erreur de connexion" : "Connection failed");
      toast.error(message);
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await axios.delete(`${API}/strava/disconnect?user_id=${USER_ID}`);
      setStravaStatus({ connected: false, last_sync: null, workout_count: 0 });
      toast.success(lang === "fr" ? "Compte deconnecte" : "Account disconnected");
    } catch (error) {
      console.error("Failed to disconnect:", error);
      toast.error(lang === "fr" ? "Erreur" : "Error");
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await axios.post(`${API}/strava/sync?user_id=${USER_ID}`);
      if (res.data.success) {
        toast.success(res.data.message);
        loadStravaStatus();
      } else {
        toast.error(res.data.message);
      }
    } catch (error) {
      console.error("Failed to sync:", error);
      toast.error(lang === "fr" ? "Erreur de synchronisation" : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const formatLastSync = (isoString) => {
    if (!isoString) return lang === "fr" ? "Jamais" : "Never";
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);
    
    if (lang === "fr") {
      if (diffMins < 1) return "A l'instant";
      if (diffMins < 60) return `Il y a ${diffMins} min`;
      if (diffHours < 24) return `Il y a ${diffHours}h`;
      if (diffDays < 7) return `Il y a ${diffDays}j`;
      return date.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
    }
    
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins} min ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString("en-US", { day: "numeric", month: "short" });
  };

  const calculateDaysUntil = (dateStr) => {
    if (!dateStr) return null;
    const eventDate = new Date(dateStr);
    const today = new Date();
    const diffTime = eventDate - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return diffDays > 0 ? diffDays : null;
  };

  const formatTargetTime = (minutes) => {
    if (!minutes) return null;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h${mins.toString().padStart(2, "0")}`;
  };

  const daysUntil = goal ? calculateDaysUntil(goal.event_date) : null;

  return (
    <div className="p-6 md:p-8 pb-24 md:pb-8" data-testid="settings-page">
      {/* Header */}
      <div className="mb-8">
        <h1 className="font-heading text-2xl md:text-3xl uppercase tracking-tight font-bold mb-1">
          {t("settings.title")}
        </h1>
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          {t("settings.subtitle")}
        </p>
      </div>

      <div className="space-y-6">
        {/* Training Goal Section */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Target className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.goal")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.goalDesc")}
                </p>
                
                {loadingGoal ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="font-mono text-xs">{t("common.loading")}</span>
                  </div>
                ) : goal && daysUntil ? (
                  <div className="space-y-4">
                    {/* Current Goal Display */}
                    <div className="p-4 bg-primary/5 border border-primary/20 rounded-lg">
                      <div className="flex items-center justify-between mb-3">
                        <span className="font-mono text-sm font-semibold text-primary">
                          {goal.event_name}
                        </span>
                        <Button
                          onClick={handleDeleteGoal}
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground hover:text-destructive h-8 w-8 p-0"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                      
                      {/* Goal Details Grid */}
                      <div className="grid grid-cols-2 gap-3 mb-3">
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Route className="w-4 h-4" />
                          <span className="font-mono text-xs">
                            {t(`settings.distances.${goal.distance_type}`)} ({goal.distance_km}km)
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <Calendar className="w-4 h-4" />
                          <span className="font-mono text-xs">
                            {new Date(goal.event_date).toLocaleDateString(
                              lang === "fr" ? "fr-FR" : "en-US",
                              { day: "numeric", month: "short", year: "numeric" }
                            )}
                          </span>
                        </div>
                        {goal.target_time_minutes && (
                          <div className="flex items-center gap-2 text-muted-foreground">
                            <Clock className="w-4 h-4" />
                            <span className="font-mono text-xs">
                              {t("settings.targetTime")}: {formatTargetTime(goal.target_time_minutes)}
                            </span>
                          </div>
                        )}
                        {goal.target_pace && (
                          <div className="flex items-center gap-2 text-primary">
                            <Target className="w-4 h-4" />
                            <span className="font-mono text-xs font-semibold">
                              {t("settings.targetPace")}: {goal.target_pace}/km
                            </span>
                          </div>
                        )}
                      </div>
                      
                      {/* Days Until */}
                      <div className="pt-3 border-t border-primary/20">
                        <p className="font-mono text-2xl font-bold text-primary">
                          {daysUntil} <span className="text-sm font-normal">{t("settings.daysUntil")}</span>
                        </p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Goal Form */}
                    <div className="space-y-3">
                      {/* Event Name */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.eventName")} *
                        </label>
                        <Input
                          value={eventName}
                          onChange={(e) => setEventName(e.target.value)}
                          placeholder={lang === "fr" ? "Ex: Marathon de Paris" : "Ex: Paris Marathon"}
                          className="bg-muted border-border font-mono text-sm"
                          data-testid="goal-name-input"
                        />
                      </div>
                      
                      {/* Distance Type */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.distance")} *
                        </label>
                        <Select value={distanceType} onValueChange={setDistanceType}>
                          <SelectTrigger className="bg-muted border-border font-mono text-sm" data-testid="goal-distance-select">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {DISTANCE_OPTIONS.map((dist) => (
                              <SelectItem key={dist} value={dist} className="font-mono text-sm">
                                {t(`settings.distances.${dist}`)} ({DISTANCE_KM[dist]}km)
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      
                      {/* Event Date */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.eventDate")} *
                        </label>
                        <Input
                          type="date"
                          value={eventDate}
                          onChange={(e) => setEventDate(e.target.value)}
                          min={new Date().toISOString().split('T')[0]}
                          className="bg-muted border-border font-mono text-sm"
                          data-testid="goal-date-input"
                        />
                      </div>
                      
                      {/* Target Time */}
                      <div>
                        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1 block">
                          {t("settings.targetTime")}
                        </label>
                        <p className="font-mono text-[9px] text-muted-foreground mb-2">
                          {t("settings.targetTimeDesc")}
                        </p>
                        <div className="flex items-center gap-2">
                          <Input
                            type="number"
                            min="0"
                            max="24"
                            value={targetHours}
                            onChange={(e) => setTargetHours(e.target.value)}
                            placeholder="0"
                            className="bg-muted border-border font-mono text-sm w-20 text-center"
                            data-testid="goal-hours-input"
                          />
                          <span className="font-mono text-sm text-muted-foreground">h</span>
                          <Input
                            type="number"
                            min="0"
                            max="59"
                            value={targetMinutes}
                            onChange={(e) => setTargetMinutes(e.target.value)}
                            placeholder="00"
                            className="bg-muted border-border font-mono text-sm w-20 text-center"
                            data-testid="goal-minutes-input"
                          />
                          <span className="font-mono text-sm text-muted-foreground">min</span>
                        </div>
                      </div>
                    </div>
                    
                    <Button
                      onClick={handleSaveGoal}
                      disabled={savingGoal || !eventName.trim() || !eventDate || !distanceType}
                      data-testid="save-goal"
                      className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-9 px-4 flex items-center gap-2"
                    >
                      {savingGoal ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Check className="w-4 h-4" />
                      )}
                      {t("settings.saveGoal")}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Data Sync Section */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Link2 className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.dataSync")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.dataSyncDesc")}
                </p>
                
                {loadingStrava ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="font-mono text-xs">{t("common.loading")}</span>
                  </div>
                ) : stravaStatus?.connected ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-chart-2">
                      <Check className="w-4 h-4" />
                      <span className="font-mono text-xs uppercase tracking-wider">
                        {t("settings.connected")}
                      </span>
                    </div>
                    
                    <div className="p-3 bg-muted/50 border border-border">
                      <div className="flex items-center justify-between">
                        <div>
                          <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                            {t("settings.lastSync")}
                          </p>
                          <p className="font-mono text-sm">
                            {formatLastSync(stravaStatus.last_sync)}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1">
                            {t("settings.workouts")}
                          </p>
                          <p className="font-mono text-sm">
                            {stravaStatus.workout_count}
                          </p>
                        </div>
                      </div>
                    </div>
                    
                    <div className="flex gap-3">
                      <Button
                        onClick={handleSync}
                        disabled={syncing}
                        data-testid="sync-strava"
                        className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-9 px-4 flex items-center gap-2"
                      >
                        {syncing ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <RefreshCw className="w-4 h-4" />
                        )}
                        {t("settings.sync")}
                      </Button>
                      <Button
                        onClick={handleDisconnect}
                        variant="ghost"
                        data-testid="disconnect-strava"
                        className="text-muted-foreground hover:text-destructive rounded-none uppercase font-mono text-xs h-9 px-4"
                      >
                        {t("settings.disconnect")}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <X className="w-4 h-4" />
                      <span className="font-mono text-xs uppercase tracking-wider">
                        {t("settings.notConnected")}
                      </span>
                    </div>
                    <Button
                      onClick={handleConnect}
                      disabled={connecting}
                      data-testid="connect-strava"
                      className="bg-primary text-white hover:bg-primary/90 rounded-none uppercase font-bold tracking-wider text-xs h-9 px-4 flex items-center gap-2"
                    >
                      {connecting ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Link2 className="w-4 h-4" />
                      )}
                      {t("settings.connect")}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Language Setting */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Globe className="w-5 h-5 text-primary" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.language")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.languageDesc")}
                </p>
                
                <div className="flex gap-3">
                  <button
                    onClick={() => setLang("en")}
                    data-testid="lang-en"
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors ${
                      lang === "en"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <span className="block text-lg mb-1">EN</span>
                    <span className="block text-xs">{t("settings.english")}</span>
                  </button>
                  
                  <button
                    onClick={() => setLang("fr")}
                    data-testid="lang-fr"
                    className={`flex-1 p-4 border font-mono text-sm uppercase tracking-wider transition-colors ${
                      lang === "fr"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <span className="block text-lg mb-1">FR</span>
                    <span className="block text-xs">{t("settings.french")}</span>
                  </button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Premium Subscription */}
        <Card className={`border-border ${premiumStatus?.is_premium ? "bg-gradient-to-br from-amber-500/5 to-orange-500/5 border-amber-500/20" : "bg-card"}`}>
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className={`w-10 h-10 flex items-center justify-center flex-shrink-0 ${
                premiumStatus?.is_premium 
                  ? "bg-gradient-to-br from-amber-500 to-orange-500" 
                  : "bg-muted border border-border"
              }`}>
                <Crown className={`w-5 h-5 ${premiumStatus?.is_premium ? "text-white" : "text-muted-foreground"}`} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h2 className="font-heading text-lg uppercase tracking-tight font-semibold">
                    CardioCoach Premium
                  </h2>
                  {premiumStatus?.is_premium && (
                    <Badge className="bg-amber-500 text-white text-[9px]">ACTIF</Badge>
                  )}
                </div>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {lang === "fr" 
                    ? "Chat coach interactif avec analyse personnalisée" 
                    : "Interactive coach chat with personalized analysis"
                  }
                </p>
                
                {loadingPremium || processingPayment ? (
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="font-mono text-xs">
                      {processingPayment 
                        ? (lang === "fr" ? "Vérification du paiement..." : "Verifying payment...")
                        : (lang === "fr" ? "Chargement..." : "Loading...")
                      }
                    </span>
                  </div>
                ) : premiumStatus?.is_premium ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-4 text-sm">
                      <div className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-amber-500" />
                        <span className="font-mono text-xs">
                          {premiumStatus.messages_remaining}/{30} {lang === "fr" ? "messages restants" : "messages left"}
                        </span>
                      </div>
                    </div>
                    <div className="w-full h-2 bg-muted rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-amber-500 to-orange-500 transition-all"
                        style={{ width: `${(premiumStatus.messages_remaining / 30) * 100}%` }}
                      />
                    </div>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {lang === "fr" 
                        ? "Les messages se réinitialisent chaque mois" 
                        : "Messages reset every month"
                      }
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <ul className="space-y-2">
                      <li className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Sparkles className="w-3 h-3 text-amber-500" />
                        {lang === "fr" ? "30 messages/mois avec le coach" : "30 messages/month with coach"}
                      </li>
                      <li className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Sparkles className="w-3 h-3 text-amber-500" />
                        {lang === "fr" ? "Analyse personnalisée de tes données" : "Personalized data analysis"}
                      </li>
                      <li className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Sparkles className="w-3 h-3 text-amber-500" />
                        {lang === "fr" ? "Conseils adaptés à ton profil" : "Advice tailored to your profile"}
                      </li>
                    </ul>
                    <Button
                      onClick={handleSubscribe}
                      data-testid="subscribe-premium"
                      className="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white rounded-none uppercase font-bold tracking-wider text-xs h-9 px-4 flex items-center gap-2"
                    >
                      <Crown className="w-4 h-4" />
                      {lang === "fr" ? "S'abonner • 4.99€/mois" : "Subscribe • €4.99/month"}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* About */}
        <Card className="bg-card border-border">
          <CardContent className="p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 flex items-center justify-center bg-muted border border-border flex-shrink-0">
                <Info className="w-5 h-5 text-muted-foreground" />
              </div>
              <div className="flex-1">
                <h2 className="font-heading text-lg uppercase tracking-tight font-semibold mb-1">
                  {t("settings.about")}
                </h2>
                <p className="font-mono text-xs text-muted-foreground mb-4">
                  {t("settings.aboutDesc")}
                </p>
                <p className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  {t("settings.version")} 1.4.0
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
