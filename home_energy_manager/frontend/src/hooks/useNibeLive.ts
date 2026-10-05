import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';
import { DhwStatus, HeatingStatus } from '../lib/nibeStatusLabels';

// Mirrors GET /api/nibe/live's response shape (backend/nibe_api.py) —
// the same settings/last-decision fields GET /api/nibe/status returns,
// plus `live`, a fresh read straight from Home Assistant. Any `live`
// field can be null (that entity unavailable right now), and the whole
// `live` object is `{}` only if Home Assistant couldn't be reached at
// all — see core/nibe/live.py's docstring.
export interface NibeLiveResponse {
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
  live: {
    prio: string | null;
    compressorPowerKw: number | null;
    compressorPowerMeanKw: number | null;
    compressorCurrentA: number | null;
    compressorFrequencyHz: number | null;
    compressorState: string | null;
    chargePumpSpeedPct: number | null;
    supplyPumpSpeedPct: number | null;
    electricAdditionKw: number | null;
    degreeMinutes: number | null;
    heatOffsetC: number | null;
    indoorActualC: number | null;
    indoorTargetC: number | null;
    dhwActualC: number | null;
    dhwTargetHighC: number | null;
    dhwTargetLowC: number | null;
    // Added 2026-10-05 — the pump's own effektvakt (power-guard) inputs.
    // Both null means effektvakt has never been turned on at the pump's
    // own panel (confirmed live 2026-10-05) — an honest "not configured",
    // not a read failure. See core/nibe/live.py's comment.
    effektvaktMaxPowerKw: number | null;
    effektvaktFuseRatingA: number | null;
  };
}

const EMPTY_LIVE: NibeLiveResponse = {
  enabled: false,
  dhwLuxuryEnabled: false,
  heating: { status: null, offsetC: null, reason: null },
  dhw: { status: null, comfortMode: null, reason: null },
  live: {
    prio: null,
    compressorPowerKw: null,
    compressorPowerMeanKw: null,
    compressorCurrentA: null,
    compressorFrequencyHz: null,
    compressorState: null,
    chargePumpSpeedPct: null,
    supplyPumpSpeedPct: null,
    electricAdditionKw: null,
    degreeMinutes: null,
    heatOffsetC: null,
    indoorActualC: null,
    indoorTargetC: null,
    dhwActualC: null,
    dhwTargetHighC: null,
    dhwTargetLowC: null,
    effektvaktMaxPowerKw: null,
    effektvaktFuseRatingA: null,
  },
};

// Polled every 10s — much faster than useNibeStatus's 30s, since this
// page's whole point is "what's happening right now" (compressor power/
// frequency swing on the order of seconds, not the 30s cadence
// _poll_nibe's own curve-offset decisions run on). Each tick is one
// request that does several HA reads server-side (see core/nibe/live.py),
// so 10s stays comfortably below anything that would stress a local HA
// instance or the Modbus gateway behind it.
const LIVE_REFRESH_MS = 10_000;

export function useNibeLive() {
  const [data, setData] = useState<NibeLiveResponse>(EMPTY_LIVE);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchLive = useCallback(async () => {
    try {
      const res = await api.get<NibeLiveResponse>('/api/nibe/live');
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach Nibe live API');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLive();
    const interval = setInterval(fetchLive, LIVE_REFRESH_MS);
    return () => clearInterval(interval);
  }, [fetchLive]);

  return { ...data, loading, error };
}
