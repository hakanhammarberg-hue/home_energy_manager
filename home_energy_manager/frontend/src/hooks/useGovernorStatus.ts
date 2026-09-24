import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/governor/status
// (backend/governor_api.py) exactly, camelCase included.
interface GovernorStatusResponse {
  enabled: boolean;
  targetKw: number | null;
  status: 'within_budget' | 'throttling_ev' | 'no_data' | null;
  reason: string | null;
  recentPeakKw: number | null;
}

/**
 * Polls GET /api/governor/status every 30s — the same cadence
 * app.py's _poll_peak_governor itself runs on, so this hook never shows a
 * decision staler than the governor's own next tick.
 *
 * `status`/`reason` are null both while the governor is switched off and
 * before its first tick since startup — both normal states, not errors
 * (see governor_api.py's docstring). `error` here only ever reflects this
 * hook's own fetch failing, never a governor-side condition.
 *
 * `recentPeakKw` (added 2026-09-03) follows the same null-while-off rule —
 * it's context for target_kw, not a separate feature with its own gate.
 */
export function useGovernorStatus() {
  const [enabled, setEnabled] = useState(false);
  const [targetKw, setTargetKw] = useState<number | null>(null);
  const [status, setStatus] = useState<GovernorStatusResponse['status']>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [recentPeakKw, setRecentPeakKw] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get<GovernorStatusResponse>('/api/governor/status');
      setEnabled(res.data.enabled);
      setTargetKw(res.data.targetKw);
      setStatus(res.data.status);
      setReason(res.data.reason);
      setRecentPeakKw(res.data.recentPeakKw);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach governor status API');
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30_000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  return { enabled, targetKw, status, reason, recentPeakKw, error };
}
