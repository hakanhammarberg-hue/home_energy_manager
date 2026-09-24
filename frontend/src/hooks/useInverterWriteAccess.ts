import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/diagnostics/inverter-write-access
// (backend/diagnostics_api.py) exactly, camelCase included.
interface InverterWriteAccessResponse {
  state: string | null;
  available: boolean;
}

/**
 * Polls GET /api/diagnostics/inverter-write-access every 30s — same
 * cadence as app.py's _poll_inverter_write_access itself.
 *
 * `available: false` covers both "not read yet since startup" and the
 * entity being unavailable/unknown right now — both a normal "no data"
 * state, not an error (see diagnostics_api.py's docstring). `error` here
 * only ever reflects this hook's own fetch failing.
 */
export function useInverterWriteAccess() {
  const [state, setState] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchState = useCallback(async () => {
    try {
      const res = await api.get<InverterWriteAccessResponse>(
        '/api/diagnostics/inverter-write-access'
      );
      setState(res.data.state);
      setAvailable(res.data.available);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach inverter write-access API');
      setAvailable(false);
    }
  }, []);

  useEffect(() => {
    fetchState();
    const interval = setInterval(fetchState, 30_000);
    return () => clearInterval(interval);
  }, [fetchState]);

  return { state, available, error };
}
