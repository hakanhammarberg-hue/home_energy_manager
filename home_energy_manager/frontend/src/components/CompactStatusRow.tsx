import { Activity, Car, Flame, Zap } from 'lucide-react';
import CompactStatusCard from './CompactStatusCard';
import { usePerificPower } from '../hooks/usePerificPower';
import { useGovernorStatus } from '../hooks/useGovernorStatus';
import { useEvSchedulerStatus } from '../hooks/useEvSchedulerStatus';
import { useNibeStatus } from '../hooks/useNibeStatus';
import { useNibeSavings } from '../hooks/useNibeSavings';
import { heatingStatusColor, heatingStatusLabel } from '../lib/nibeStatusLabels';

// Dashboard-compaction phase (2026-09-28): Perific One, Effektvakt,
// EV-laddning and Nibe side by side in one compact row — Håkan's explicit
// ask ("effektvakt, perific one ev laddning och nibe ska få plats bredvid
// varandra"). Replaces those four sections' previous full-width StatusCard
// rendering on the Dashboard (PerificPowerCard/GovernorStatusCard/
// EvSchedulerStatusCard stay defined but are no longer mounted here; the
// old NibeStatusCard was retired outright — its "Lyxläge varmvatten" toggle
// moved to NibeControls.tsx on the /nibe page, and its status display is
// superseded by this row plus NibeLiveCard). Full Nibe detail now lives
// solely on the dedicated /nibe page (NibeDriftPage), per Håkan's "övriga
// nibe-värden behövs bara på nibe-sidan".
//
// One row component rather than four separate default-exported cards,
// since these four are always shown together now — matches the "self-
// fetching hook, no props" convention every other status section already
// uses, just packaged once instead of four times.
const GOVERNOR_STATUS_LABELS: Record<string, string> = {
  within_budget: 'Inom budget',
  throttling_ev: 'Stryper EV',
  no_data: 'Ingen data',
};

const GOVERNOR_STATUS_COLORS: Record<string, 'blue' | 'green' | 'yellow' | 'red' | 'purple'> = {
  within_budget: 'green',
  throttling_ev: 'yellow',
  no_data: 'red',
};

const EV_STATUS_LABELS: Record<string, string> = {
  no_data: 'Ingen data',
  not_plugged_in: 'Ej inkopplad',
  blocked_battery_discharging: 'Blockerad',
  blocked_above_cap: 'Över SOC-tak',
  allowed_override: 'Laddar (override)',
  allowed_solar_surplus: 'Laddar (sol)',
  allowed_low_price: 'Laddar (lågpris)',
};

const EV_STATUS_COLORS: Record<string, 'blue' | 'green' | 'yellow' | 'red' | 'purple'> = {
  no_data: 'red',
  not_plugged_in: 'blue',
  blocked_battery_discharging: 'yellow',
  blocked_above_cap: 'yellow',
  allowed_override: 'green',
  allowed_solar_surplus: 'green',
  allowed_low_price: 'green',
};

export default function CompactStatusRow() {
  const perific = usePerificPower();
  const governor = useGovernorStatus();
  const ev = useEvSchedulerStatus();
  const nibeStatus = useNibeStatus();
  const nibeSavings = useNibeSavings();

  // Perific One — headline totaleffekt (kW), no second line (mirrors the
  // full-size card's own lack of extra metrics).
  const perificValue =
    perific.available && perific.powerKw !== null ? perific.powerKw.toFixed(2) : '—';

  // Effektvakt — headline status, subline uppmätt toppimport.
  const governorValue = !governor.enabled
    ? 'Av'
    : governor.status !== null
      ? (GOVERNOR_STATUS_LABELS[governor.status] ?? governor.status)
      : 'Väntar…';
  const governorColor = !governor.enabled
    ? 'blue'
    : governor.status !== null
      ? (GOVERNOR_STATUS_COLORS[governor.status] ?? 'blue')
      : 'blue';
  const governorStatusLine =
    governor.enabled && governor.recentPeakKw !== null
      ? `Topp: ${governor.recentPeakKw.toFixed(1)} kW`
      : undefined;

  // EV-laddning — headline SOC nu, subline SOC-tak.
  const evEnabled = ev.enabled;
  const evStatus = ev.status === 'allowed_below_cap'
    ? (ev.chargingAllowed ? 'Laddar (billigt)' : 'Väntar')
    : ev.status !== null
      ? (EV_STATUS_LABELS[ev.status] ?? ev.status)
      : 'Väntar…';
  const evColor: 'blue' | 'green' | 'yellow' | 'red' | 'purple' = !evEnabled
    ? 'blue'
    : ev.status === 'allowed_below_cap'
      ? (ev.chargingAllowed ? 'green' : 'blue')
      : ev.status !== null
        ? (EV_STATUS_COLORS[ev.status] ?? 'blue')
        : 'blue';
  const evValue = evEnabled && ev.evSocPercent !== null ? `${ev.evSocPercent.toFixed(0)}%` : evStatus;
  const evStatusLine = evEnabled
    ? ev.socCapPercent !== null
      ? `Tak: ${ev.socCapPercent.toFixed(0)}%`
      : evStatus
    : undefined;

  // Nibe — headline uppskattad besparing idag (kr), subline
  // rumsuppvärmningsstatus. Full breakdown (formel, historik) lives on
  // /nibe only, per Håkan's "övriga nibe-värden behövs bara på nibe-sidan".
  const nibeValue = !nibeStatus.enabled
    ? 'Av'
    : `${nibeSavings.totalSavingsKr.toFixed(1)}`;
  const nibeColor = !nibeStatus.enabled
    ? 'blue'
    : heatingStatusColor(nibeStatus.heating.status);
  const nibeStatusLine = nibeStatus.enabled
    ? heatingStatusLabel(nibeStatus.heating.status)
    : undefined;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <CompactStatusCard
        title="Perific One"
        icon={Zap}
        color="yellow"
        keyValue={perificValue}
        keyUnit="kW"
        annotation={perific.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="Effektvakt"
        icon={Activity}
        color={governorColor}
        keyValue={governorValue}
        statusLine={governorStatusLine}
        annotation={governor.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="EV-laddning"
        icon={Car}
        color={evColor}
        keyValue={evValue}
        statusLine={evStatusLine}
        annotation={ev.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="Nibe"
        icon={Flame}
        color={nibeColor}
        keyValue={nibeValue}
        keyUnit={nibeStatus.enabled ? 'kr idag' : undefined}
        statusLine={nibeStatusLine}
        annotation={
          nibeStatus.error || nibeSavings.error ? 'Kunde inte nå API:t' : undefined
        }
      />
    </div>
  );
}
