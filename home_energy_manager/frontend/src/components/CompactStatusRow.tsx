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
//
// Richer-tiles pass (2026-09-30): Håkan asked for each tile to carry more
// information ("Varje ruta bör kunna innehålla betydligt mer information"),
// specifically calling out EV-laddning (charging active + power) and
// Perific One (the effektvakt/governor target), and explicitly excluding
// Nibe ("förutom nibe-värden förmodar jag" — that tile already just
// summarizes what the dedicated /nibe page covers in full). Effektvakt got
// its own small addition (the same target number, for symmetry with
// Perific One) as the obvious "what else is relevant" call. Implemented via
// CompactStatusCard's new optional `metrics` prop rather than growing
// keyValue/statusLine further — see that component's docstring.
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

// Added 2026-09-29 for Håkan's "när beräknas batteriet nå 100%" ask.
// Kia UVO's own "Estimated Charge Duration" (minutes, via whatever charger
// is currently connected) already accounts for charge-curve tapering near
// full — turned into a clock-time ETA here rather than re-derived from
// power/capacity, which would be a worse estimate than the car's own BMS.
// Only shown while the car itself reports actively charging; a stale
// duration figure while charging is paused/finished would be misleading.
function formatChargeEta(
  chargingActive: boolean | null,
  durationMin: number | null
): string | undefined {
  if (!chargingActive || durationMin === null) return undefined;
  const eta = new Date(Date.now() + durationMin * 60_000);
  const hh = eta.getHours().toString().padStart(2, '0');
  const mm = eta.getMinutes().toString().padStart(2, '0');
  return `Fulladdad ~${hh}:${mm}`;
}

export default function CompactStatusRow() {
  const perific = usePerificPower();
  const governor = useGovernorStatus();
  const ev = useEvSchedulerStatus();
  const nibeStatus = useNibeStatus();
  const nibeSavings = useNibeSavings();

  // Perific One — headline totaleffekt (kW). Added 2026-09-30, Håkan's
  // explicit ask ("perific one rutan kan kompletteras med
  // effektvaktsinställningen"): show the governor's configured target here
  // too, since Perific One's own reading is exactly what that target is
  // measured against — plus a derived margin (target minus current draw)
  // as the obvious next-most-useful number once the target itself is
  // visible. Both only shown while the governor is actually on; showing a
  // target for a feature that isn't enforcing anything would be noise.
  const perificValue =
    perific.available && perific.powerKw !== null ? perific.powerKw.toFixed(2) : '—';
  const perificMetrics =
    governor.enabled && governor.targetKw !== null
      ? [
          { label: 'Effektvakt mål', value: `${governor.targetKw.toFixed(1)} kW` },
          ...(perific.available && perific.powerKw !== null
            ? [
                {
                  label: 'Marginal',
                  value: `${(governor.targetKw - perific.powerKw).toFixed(1)} kW`,
                },
              ]
            : []),
        ]
      : undefined;

  // Effektvakt — headline status, subline uppmätt toppimport, plus the
  // configured target (added 2026-09-30 alongside Perific One's mirror of
  // the same number — seeing "Topp: 8.2 kW" without "Mål: 12 kW" next to it
  // told only half the story).
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
  const governorMetrics =
    governor.enabled && governor.targetKw !== null
      ? [{ label: 'Mål', value: `${governor.targetKw.toFixed(1)} kW` }]
      : undefined;

  // EV-laddning — headline Kians nuvarande SOC (alltid när bilen rapporterar
  // den, oavsett om pris-/sol-schemaläggningen är påslagen — fixat
  // 2026-09-29: det är bilens egna rapporterade fakta, inte ett
  // schemaläggarbeslut, se app.py:s _poll_ev_charging). Sublinjen visar en
  // "Fulladdad ~HH:MM"-uppskattning medan bilen faktiskt laddar, annars
  // schemaläggarens status/SOC-tak när den är påslagen.
  const evEnabled = ev.enabled;
  const evStatus = ev.status === 'allowed_below_cap'
    ? (ev.chargingAllowed ? 'Laddar (billigt)' : 'Väntar')
    : ev.status !== null
      ? (EV_STATUS_LABELS[ev.status] ?? ev.status)
      : 'Väntar…';
  const evColor: 'blue' | 'green' | 'yellow' | 'red' | 'purple' = ev.chargingActive
    ? 'green'
    : !evEnabled
      ? 'blue'
      : ev.status === 'allowed_below_cap'
        ? (ev.chargingAllowed ? 'green' : 'blue')
        : ev.status !== null
          ? (EV_STATUS_COLORS[ev.status] ?? 'blue')
          : 'blue';
  const evValue =
    ev.evSocPercent !== null ? `${ev.evSocPercent.toFixed(0)}%` : evEnabled ? evStatus : '—';
  const evEtaLabel = formatChargeEta(ev.chargingActive, ev.estimatedChargeDurationMin);
  const evStatusLine =
    evEtaLabel ??
    (evEnabled
      ? ev.socCapPercent !== null
        ? `Tak: ${ev.socCapPercent.toFixed(0)}%`
        : evStatus
      : undefined);
  // Added 2026-09-30, Håkan's explicit ask ("Laddningsrutan för elbil kan
  // berätta om laddning pågår eller ej och med vilken effekt"): the
  // charger's own always-on facts (see useEvSchedulerStatus's docstring —
  // chargingActive/chargingPowerKw are read every tick regardless of
  // evEnabled), so this shows even while the price/solar automation itself
  // is off. Distinct from evStatusLine above, which is about the
  // SCHEDULER's decision/ETA — this metric is about the charger's own
  // measured reality.
  const evChargingMetrics = [
    {
      label: 'Laddning',
      value:
        ev.chargingActive === null
          ? 'Ingen data'
          : ev.chargingActive
            ? `${(ev.chargingPowerKw ?? 0).toFixed(1)} kW`
            : 'Ej aktiv',
    },
  ];

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
        metrics={perificMetrics}
        annotation={perific.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="Effektvakt"
        icon={Activity}
        color={governorColor}
        keyValue={governorValue}
        statusLine={governorStatusLine}
        metrics={governorMetrics}
        annotation={governor.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="EV-laddning"
        icon={Car}
        color={evColor}
        keyValue={evValue}
        statusLine={evStatusLine}
        metrics={evChargingMetrics}
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
