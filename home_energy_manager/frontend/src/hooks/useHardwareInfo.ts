import { useCallback, useEffect, useState } from 'react';
import api from '../lib/api';

// Mirrors the backend response shape from GET /api/hardware/info
// (backend/hardware_api.py / core/hardware_info.py) exactly, camelCase
// included. Any field can be null whenever its HA entity is unavailable
// -- never a fabricated placeholder -- see core/hardware_info.py's own
// docstring. Hardcoded facts (manufacturer/model/deviceName) are always
// present as plain strings.
export interface HardwareInfoResponse {
  nibe: {
    manufacturer: string;
    model: string;
    hwVersion: string | null;
    swVersion: string | null;
  };
  inverter: {
    manufacturer: string;
    model: string | null;
    serialNumber: string | null;
    firmwareVersion: string | null;
  };
  battery: {
    bmsType: string | null;
    bms1SerialNumber: string | null;
    bms1MonitoringVersion: string | null;
    modules: { index: number; serialNumber: string }[];
    bmsConnectedStatus: string | null;
  };
  evCharger: {
    manufacturer: string;
    model: string;
    deviceName: string;
    installedFirmwareVersion: string | null;
  };
  vehicle: {
    manufacturer: string;
    model: string;
    vin: string | null;
  };
  perificOne: {
    manufacturer: string;
    model: string;
    macAddress: string | null;
    itemId: string | null;
  };
}

/**
 * Fetches GET /api/hardware/info once on mount -- no polling interval,
 * unlike usePerificPower/useNibeLive: identification facts (serial
 * numbers, firmware/model versions, VIN, MAC) essentially never change
 * during a session, so a manual "Uppdatera" button (see
 * HardwareInfoPage.tsx) is enough to pick up a real change without
 * re-fetching every few seconds for nothing.
 */
export function useHardwareInfo() {
  const [data, setData] = useState<HardwareInfoResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchInfo = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<HardwareInfoResponse>('/api/hardware/info');
      setData(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reach hardware info API');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInfo();
  }, [fetchInfo]);

  return { data, loading, error, refresh: fetchInfo };
}
