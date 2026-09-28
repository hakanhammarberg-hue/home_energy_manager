import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';
import { DhwStatus, HeatingStatus } from '../lib/nibeStatusLabels';

// Mirrors the backend response shape from GET /api/nibe/status
// (backend/nibe_api.py) exactly, camelCase included. The status unions
// live in lib/nibeStatusLabels.ts (one definition, shared with the label
// maps) rather than being repeated here — see that file's docstring for
// why (Fas 4c/4d/4e added five status values that this type used to be
// missing entirely).
export interface NibeStatusResponse {
  enabled: boolean;
  dhwLuxuryEnabled: boolean;
  heating: {
    status: HeatingStatus | null;
    offsetC: number | null;
    reason: string | null;
  };
  dhw: {
    status: DhwStatus | null;
    comfortMode: 'luxury' | 'economy' | null;
    reason: string | null;
  };
}

const EMPTY_STATUS: NibeStatusResponse = {
  enabled: false,
  dhwLuxuryEnabled: false,
  heating: { status: null, offsetC: null, reason: null },
  dhw: { status: null, comfortMode: null, reason: null },
};

/**
 * Polls GET /api/nibe/status every 30s — the same cadence app.py's
 * _poll_nibe itself runs on, mirroring useGovernorStatus/
 * useEvSchedulerStatus exactly. `heating`/`dhw` inner fields are null both
 * while the relevant switch is off and before the first tick since
 * startup — both normal states, not errors (see nibe_api.py's docstring).
 * `error` here only ever reflects this hook's own fetch failing.
 */
export function useNibeStatus() {
  const [data, setData] = useState<NibeStatusResponse>(EMPTY_STATUS);
  const [error, setError] = useState<string | null>(null);
  const [togglingDhwLuxury, setTogglingDhwLuxury] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<NibeStatusResponse>('/api/nibe/status');
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach Nibe status API');
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // POST /api/nibe/dhw-luxury returns the same shape GET does, so the
  // toggle's effect is visible immediately without waiting for the next
  // 30s poll — same pattern as useEvSchedulerStatus's requestOverride.
  const setDhwLuxuryEnabled = useCallback(async (enabled: boolean) => {
    setTogglingDhwLuxury(true);
    try {
      const res = await api.post<NibeStatusResponse>('/api/nibe/dhw-luxury', { enabled });
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update Lyxläge varmvatten');
    } finally {
      setTogglingDhwLuxury(false);
    }
  }, []);

  return { ...data, error, togglingDhwLuxury, setDhwLuxuryEnabled };
}
