import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors GET /api/nibe/history's response shape exactly (backend/nibe_api.py,
// core/nibe/history.py) — one row per hour, camelCase included. Any field can
// be null: before the pump's first reading in the window, or whenever a
// compressor-energy delta has no baseline yet (see history.py's docstring).
export interface NibeHistoryPeriod {
  timestamp: string; // ISO 8601, bucket end
  offsetC: number | null;
  indoorActualC: number | null;
  indoorTargetC: number | null;
  dhwActualC: number | null;
  dhwTargetHighC: number | null;
  dhwTargetLowC: number | null;
  totalEnergyKwh: number | null;
  hwEnergyKwh: number | null;
  spaceHeatingEnergyKwh: number | null;
}

export interface NibeHistoryResponse {
  periods: NibeHistoryPeriod[];
}

/**
 * Fetches GET /api/nibe/history once on mount (and whenever `hours`
 * changes) — this is charting data over a multi-hour window, not a live
 * status value, so it deliberately does NOT poll every 30s the way
 * useNibeStatus does. Call `refetch()` for a manual refresh (e.g. a
 * "refresh" button on the chart card).
 */
export function useNibeHistory(hours: number = 48) {
  const [periods, setPeriods] = useState<NibeHistoryPeriod[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<NibeHistoryResponse>('/api/nibe/history', {
        params: { hours },
      });
      setPeriods(res.data.periods ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach Nibe history API');
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  return { periods, loading, error, refetch: fetchHistory };
}
