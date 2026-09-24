import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/perific/power
// (backend/perific_api.py) exactly, camelCase included.
interface PerificPowerResponse {
  powerKw: number | null;
  available: boolean;
}

/**
 * Polls GET /api/perific/power every 30s — matching how often
 * core.governor will eventually poll the same reader once Fas 3 lands, so
 * this hook shows the same freshness the governor will actually act on.
 *
 * `available: false` is a normal state (Perific hasn't reported a fresh
 * value yet), not an error — kept as its own field so the UI can show
 * "no data" calmly instead of an error banner, same distinction
 * PerificReader itself makes.
 */
export function usePerificPower() {
  const [powerKw, setPowerKw] = useState<number | null>(null);
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPower = useCallback(async () => {
    try {
      const res = await api.get<PerificPowerResponse>('/api/perific/power');
      setPowerKw(res.data.powerKw);
      setAvailable(res.data.available);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach Perific');
      setAvailable(false);
    }
  }, []);

  useEffect(() => {
    fetchPower();
    const interval = setInterval(fetchPower, 30_000);
    return () => clearInterval(interval);
  }, [fetchPower]);

  return { powerKw, available, error };
}
