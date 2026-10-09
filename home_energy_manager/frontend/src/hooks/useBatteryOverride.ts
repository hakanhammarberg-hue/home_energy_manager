import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/battery/override/status
// (backend/battery_override_api.py) exactly, camelCase included. See
// core/bess/battery_override.py's module docstring for the full design
// (Fas 6, 2026-10-09 — a manual force-charge override + anti-dormancy
// wake-up pulses, built after confirmed BMS-dormancy incidents).
export interface BatteryOverrideStatusResponse {
  overrideForceChargeUntil: string | null;
  antiDormancyEnabled: boolean;
  antiDormancySocThreshold: number | null;
  antiDormancyIdleMinutes: number | null;
  antiDormancyPulseMinutes: number | null;
  /** Ground truth from the last 30s poll tick, not recomputed here — same
   * reasoning as useGovernorStatus/useEvSchedulerStatus's own status
   * fields. */
  active: boolean;
  reason: 'manual_override' | 'anti_dormancy' | 'none';
  until: string | null;
}

/**
 * Polls GET /api/battery/override/status every 10s — tighter than the
 * other 30s-poll hooks in this app because a countdown-to-expiry display
 * benefits from fresher data, and the endpoint itself does zero extra I/O
 * (same contract as useGovernorStatus/useEvSchedulerStatus).
 */
export function useBatteryOverride() {
  const [data, setData] = useState<BatteryOverrideStatusResponse>({
    overrideForceChargeUntil: null,
    antiDormancyEnabled: false,
    antiDormancySocThreshold: null,
    antiDormancyIdleMinutes: null,
    antiDormancyPulseMinutes: null,
    active: false,
    reason: 'none',
    until: null,
  });
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<BatteryOverrideStatusResponse>(
        '/api/battery/override/status'
      );
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to reach battery override status API'
      );
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 10_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // POST /api/battery/override[/cancel] returns the same shape GET does,
  // so the button's effect is visible immediately without waiting for the
  // next poll.
  const requestOverride = useCallback(async (minutes: number) => {
    setRequesting(true);
    try {
      const res = await api.post<BatteryOverrideStatusResponse>('/api/battery/override', {
        minutes,
      });
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to request force-charge override');
    } finally {
      setRequesting(false);
    }
  }, []);

  const cancelOverride = useCallback(async () => {
    setRequesting(true);
    try {
      const res = await api.post<BatteryOverrideStatusResponse>(
        '/api/battery/override/cancel'
      );
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cancel override');
    } finally {
      setRequesting(false);
    }
  }, []);

  return { ...data, error, requesting, requestOverride, cancelOverride };
}
