import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors GET /api/nibe/savings (backend/nibe_api.py) exactly, camelCase
// included — see core/nibe/savings.py's module docstring for what this
// number actually is (a modeled estimate of the price-peak reduction
// lever's savings, today so far, NOT a measurement).
export interface NibeSavingsHour {
  timestamp: string;
  offsetC: number | null;
  priceOrePerKwh: number | null;
  active: boolean;
  avoidedKwh: number | null;
  savingsKr: number | null;
}

export interface NibeSavingsResponse {
  hours: NibeSavingsHour[];
  totalAvoidedKwh: number;
  totalSavingsKr: number;
  activeHours: number;
  heatLossCoefficientKwPerC: number | null;
  assumedCop: number | null;
}

const EMPTY_SAVINGS: NibeSavingsResponse = {
  hours: [],
  totalAvoidedKwh: 0,
  totalSavingsKr: 0,
  activeHours: 0,
  heatLossCoefficientKwPerC: null,
  assumedCop: null,
};

/**
 * Polls GET /api/nibe/savings every 5 minutes — this is a modeled estimate
 * derived from hourly history, not a live-second value, so it doesn't need
 * useNibeStatus's 30s cadence; a slower poll avoids repeatedly re-fetching
 * Home Assistant's recorder history for a number that only changes once an
 * hour at most.
 */
export function useNibeSavings() {
  const [data, setData] = useState<NibeSavingsResponse>(EMPTY_SAVINGS);
  const [error, setError] = useState<string | null>(null);

  const fetchSavings = useCallback(async () => {
    try {
      const res = await api.get<NibeSavingsResponse>('/api/nibe/savings');
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach Nibe savings API');
    }
  }, []);

  useEffect(() => {
    fetchSavings();
    const interval = setInterval(fetchSavings, 5 * 60_000);
    return () => clearInterval(interval);
  }, [fetchSavings]);

  return { ...data, error };
}
