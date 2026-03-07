import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { 
  Lock, 
  Sparkles, 
  CheckCircle2, 
  Zap, 
  Target, 
  Activity,
  MessageSquare,
  Watch,
  TrendingUp,
  Crown
} from "lucide-react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const FEATURE_ICONS = {
  0: Target,
  1: Zap,
  2: Activity,
  3: MessageSquare,
  4: Watch,
  5: TrendingUp
};

export default function Paywall({ 
  onClose, 
  userId = "default", 
  language = "fr",
  returnPath = "/training"
}) {
  const navigate = useNavigate();
  const [offer, setOffer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);

  useEffect(() => {
    fetchOffer();
  }, [language]);

  const fetchOffer = async () => {
    try {
      const res = await axios.get(`${API}/subscription/early-adopter-offer?language=${language}`);
      setOffer(res.data);
    } catch (err) {
      console.error("Error fetching offer:", err);
      // Fallback offer
      setOffer({
        title: language === "fr" ? "Active ton coach running" : "Activate your running coach",
        subtitle: language === "fr" ? "Ton plan d'entraînement personnalisé est prêt" : "Your personalized training plan is ready",
        description: language === "fr" ? "Active ton abonnement pour y accéder." : "Activate your subscription to access it.",
        offer_name: "Early Adopter",
        price: 4.99,
        price_display: language === "fr" ? "4,99 € / mois" : "€4.99 / month",
        price_guarantee: language === "fr" ? "Prix garanti à vie" : "Price guaranteed for life",
        features: [
          language === "fr" ? "Plan d'entraînement personnalisé" : "Personalized training plan",
          language === "fr" ? "Adaptation automatique du plan" : "Automatic plan adaptation",
          language === "fr" ? "Analyse intelligente des séances" : "Smart session analysis",
          language === "fr" ? "Coach IA conversationnel" : "AI conversational coach",
          language === "fr" ? "Synchronisation montres/apps" : "Watch/app sync",
          language === "fr" ? "Prédictions de course" : "Race predictions"
        ],
        cta_button: language === "fr" ? "Activer mon coach" : "Activate my coach"
      });
    } finally {
      setLoading(false);
    }
  };

  const handleActivate = async () => {
    setActivating(true);
    try {
      // Pour la démo, on active directement
      // En production, cela redirigerait vers Stripe Checkout
      await axios.post(`${API}/subscription/activate-early-adopter`, {
        user_id: userId
      });
      
      // Rediriger vers la page demandée
      if (onClose) {
        onClose();
      }
      navigate(returnPath);
      window.location.reload(); // Refresh pour mettre à jour l'état
    } catch (err) {
      console.error("Error activating subscription:", err);
    } finally {
      setActivating(false);
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.9)" }}>
        <div className="animate-pulse text-white">Chargement...</div>
      </div>
    );
  }

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "linear-gradient(180deg, rgba(0,0,0,0.95) 0%, rgba(15,10,30,0.98) 100%)" }}
      data-testid="paywall"
    >
      <div className="max-w-md w-full space-y-6">
        {/* Lock Icon */}
        <div className="flex justify-center">
          <div 
            className="w-20 h-20 rounded-full flex items-center justify-center"
            style={{ background: "linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)" }}
          >
            <Lock className="w-10 h-10 text-white" />
          </div>
        </div>

        {/* Title */}
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold text-white">
            {offer?.title}
          </h1>
          <p className="text-base text-slate-300">
            {offer?.subtitle}
          </p>
          <p className="text-sm text-slate-400">
            {offer?.description}
          </p>
        </div>

        {/* Offer Card */}
        <div 
          className="rounded-2xl p-6 space-y-4"
          style={{ 
            background: "linear-gradient(135deg, rgba(139,92,246,0.15) 0%, rgba(236,72,153,0.1) 100%)",
            border: "1px solid rgba(139,92,246,0.3)"
          }}
        >
          {/* Offer Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Crown className="w-5 h-5 text-amber-400" />
              <span className="font-bold text-white">{offer?.offer_name}</span>
            </div>
            <div 
              className="px-2 py-1 rounded-full text-[10px] font-bold"
              style={{ background: "rgba(251,191,36,0.2)", color: "#fbbf24" }}
            >
              {offer?.price_guarantee}
            </div>
          </div>

          {/* Price */}
          <div className="text-center py-2">
            <span className="text-4xl font-bold text-white">{offer?.price_display?.split('/')[0]}</span>
            <span className="text-lg text-slate-400">/ {language === "fr" ? "mois" : "month"}</span>
          </div>

          {/* Features */}
          <div className="space-y-2">
            {offer?.features?.map((feature, idx) => {
              const Icon = FEATURE_ICONS[idx] || CheckCircle2;
              return (
                <div key={idx} className="flex items-center gap-3">
                  <div 
                    className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                    style={{ background: "rgba(34,197,94,0.2)" }}
                  >
                    <Icon className="w-3.5 h-3.5 text-emerald-400" />
                  </div>
                  <span className="text-sm text-slate-200">{feature}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* CTA Button */}
        <Button
          onClick={handleActivate}
          disabled={activating}
          className="w-full h-14 text-lg font-bold rounded-xl"
          style={{ 
            background: "linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)",
            border: "none"
          }}
          data-testid="paywall-cta"
        >
          {activating ? (
            <span className="flex items-center gap-2">
              <span className="animate-spin">⏳</span>
              {language === "fr" ? "Activation..." : "Activating..."}
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <Sparkles className="w-5 h-5" />
              {offer?.cta_button}
            </span>
          )}
        </Button>

        {/* Close / Skip */}
        {onClose && (
          <button
            onClick={onClose}
            className="w-full text-center text-sm text-slate-500 hover:text-slate-300 transition-colors"
          >
            {language === "fr" ? "Plus tard" : "Maybe later"}
          </button>
        )}
      </div>
    </div>
  );
}
