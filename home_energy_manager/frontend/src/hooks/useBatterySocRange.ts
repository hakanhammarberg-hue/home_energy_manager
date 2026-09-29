import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/diagnostics/battery-soc-range
// (backend/diagnostics_api.py) exactly, camelCase included.
interface BatterySocRangeResponse {
  minPercent: number | null;
  maxPercent: number | null;
  windowHours: number;
  targetWindowHours: number;
  sampleCount: number;
}

/**
 * Polls GET /api/diagnostics/battery-soc-range every 30s — same cadence as
 * app.py's _poll_battery_soc_range itself, so this never shows a range
 * staler than the next sample.
 *
 * `sampleCount: 0` (both percents null) is the normal state right after
 * startup, before the first successful SOC read — not an error, same
 * distinction PerificReader's `available` flag makes for its own card.
 * `error` here only ever reflects this hook's own fetch failing.
 *
 * `windowHours` is the ACTUAL span currently covered by the in-memory
 * sample buffer (it resets to ~0 on every add-on restart and grows back
 * towards `targetWindowHours` over the following days) — never the fixed
 * target on its own, so the card can be honest when it's still filling up
 * after a restart instead of claiming a multi-day range it doesn't have.
 */
export function useBatterySocRange() {
  const [minPercent, setMinPercent] = useState<number | null>(null);
  const [maxPercent, setMaxPercent] = useState<number | null>(null);
  const [windowHours, setWindowHours] = useState<number | null>(null);
  const [targetWindowHours, setTargetWindowHours] = useState<number | null>(null);
  const [sampleCount, setSampleCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const fetchRange = useCallback(async () => {
    try {
      const res = await api.get<BatterySocRangeResponse>('/api/diagnostics/battery-soc-range');
      setMinPercent(res.data.minPercent);
      setMaxPercent(res.data.maxPercent);
      setWindowHours(res.data.windowHours);
      setTargetWindowHours(res.data.targetWindowHours);
      setSampleCount(res.data.sampleCount);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach battery SOC range API');
    }
  }, []);

  useEffect(() => {
    fetchRange();
    const interval = setInterval(fetchRange, 30_000);
    return () => clearInterval(interval);
  }, [fetchRange]);

  return { minPercent, maxPercent, windowHours, targetWindowHours, sampleCount, error };
}
