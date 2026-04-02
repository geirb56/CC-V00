import { useEffect, useRef } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Hook to automatically sync Strava data on app startup
 * Only syncs if:
 * - User is connected to Strava
 * - Last sync was more than 1 hour ago OR no sync has been done
 */
export function useAutoSync() {
  const hasTriedSync = useRef(false);

  useEffect(() => {
    // Prevent multiple sync attempts in same session
    if (hasTriedSync.current) return;
    hasTriedSync.current = true;

    const autoSync = async () => {
      try {
        // Check Strava connection status
        const statusRes = await axios.get(`${API}/strava/status`);
        const { connected, last_sync } = statusRes.data;

        if (!connected) {
          return;
        }

        // Check if sync is needed (more than 1 hour since last sync)
        const ONE_HOUR_MS = 60 * 60 * 1000;
        const now = Date.now();
        const lastSyncTime = last_sync ? new Date(last_sync).getTime() : 0;
        const timeSinceLastSync = now - lastSyncTime;

        if (timeSinceLastSync < ONE_HOUR_MS) {
          return;
        }

        // Perform sync
        await axios.post(`${API}/strava/sync`);
      } catch (error) {
        // Silent fail - don't disrupt user experience
      }
    };

    // Delay sync slightly to not block initial render
    const timeoutId = setTimeout(autoSync, 2000);

    return () => clearTimeout(timeoutId);
  }, []);
}
