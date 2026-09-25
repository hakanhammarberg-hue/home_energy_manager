import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/ev-scheduler/status
// (backend/ev_scheduler_api.py) exactly, camelCase included.
export interface EvSchedulerStatusResponse {
  enabled: boolean;
  evSocPercent: number | null;
  socCapPercent: number | null;
  lowPriceThresholdOre: number | null;
  cheapPricePercentile: number | null;
  overrideRequested: boolean;
  status:
    | 'no_data'
    | 'not_plugged_in'
    | 'blocked_battery_discharging'
    | 'blocked_above_cap'
    | 'allowed_below_cap'
    | 'allowed_override'
    | 'allowed_solar_surplus'
    | 'allowed_low_price'
    | null;
  chargingAllowed: boolean | null;
  reason: string | null;
}

/**
 * Polls GET /api/ev-scheduler/status every 30s — the same cadence
 * app.py's _poll_ev_charging itself runs on, so this hook never shows a
 * decision staler than the scheduler's own next tick. Mirrors
 * useGovernorStatus's shape exactly; see that hook for the "status/reason
 * are null while off or before the first tick — not an error" note, which
 * applies here identically (see ev_scheduler_api.py's docstring).
 */
export function useEvSchedulerStatus() {
  const [data, setData] = useState<EvSchedulerStatusResponse>({
    enabled: false,
    evSocPercent: null,
    socCapPercent: null,
    lowPriceThresholdOre: null,
    cheapPricePercentile: null,
    overrideRequested: false,
    status: null,
    chargingAllowed: null,
    reason: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [requestingOverride, setRequestingOverride] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<EvSchedulerStatusResponse>('/api/ev-scheduler/status');
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach EV scheduler status API');
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // POST /api/ev-scheduler/override returns the same shape GET does, so
  // the button's effect is visible immediately without waiting for the
  // next 30s poll.
  const requestOverride = useCallback(async () => {
    setRequestingOverride(true);
    try {
      const res = await api.post<EvSchedulerStatusResponse>('/api/ev-scheduler/override');
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to request override');
    } finally {
      setRequestingOverride(false);
    }
  }, []);

  return { ...data, error, requestingOverride, requestOverride };
}
