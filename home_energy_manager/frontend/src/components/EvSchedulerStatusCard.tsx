import { Car } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useEvSchedulerStatus, EvSchedulerStatusResponse } from '../hooks/useEvSchedulerStatus';

// Swedish labels for scheduler.decide()'s status values
// (core/zaptec/scheduler.py), plus the two states that never come from
// decide() itself: scheduler off entirely, and on but not yet ticked once
// since startup. "allowed_below_cap" alone is ambiguous — decide() returns
// it both when this hour is cheap enough to charge AND when it's waiting
// for a cheaper one (see that module's _decide_below_cap) — so it's
// resolved below using chargingAllowed instead of being a plain lookup.
const STATUS_LABELS: Record<string, string> = {
  no_data: 'Ingen data',
  not_plugged_in: 'Ej inkopplad',
  blocked_battery_discharging: 'Blockerad — batteriet laddar ur',
  blocked_above_cap: 'Blockerad — över SOC-tak',
  allowed_override: 'Laddar — override aktiv',
  allowed_solar_surplus: 'Laddar — soköverskott',
  allowed_low_price: 'Laddar — lågt pris',
};

const STATUS_COLORS: Record<string, 'blue' | 'green' | 'yellow' | 'red' | 'purple'> = {
  no_data: 'red',
  not_plugged_in: 'blue',
  blocked_battery_discharging: 'yellow',
  blocked_above_cap: 'yellow',
  allowed_override: 'green',
  allowed_solar_surplus: 'green',
  allowed_low_price: 'green',
};

function statusLabel(status: EvSchedulerStatusResponse['status'], chargingAllowed: boolean | null): string {
  if (status === null) return 'Väntar på första mätningen…';
  if (status === 'allowed_below_cap') {
    return chargingAllowed ? 'Laddar — billig timme' : 'Väntar på billigare timme';
  }
  return STATUS_LABELS[status] ?? status;
}

function statusColor(
  status: EvSchedulerStatusResponse['status'],
  chargingAllowed: boolean | null,
): 'blue' | 'green' | 'yellow' | 'red' | 'purple' {
  if (status === null) return 'blue';
  if (status === 'allowed_below_cap') return chargingAllowed ? 'green' : 'blue';
  return STATUS_COLORS[status] ?? 'blue';
}

/**
 * Fas 5c's one visible piece of EV-scheduler UI: what the price/SOC/solar
 * gate is doing right now, plus the one-shot override button. Mirrors
 * GovernorStatusCard's shape (reuse StatusCard, self-fetching hook) and
 * the same "never a recomputed hypothetical" contract — this reflects
 * _poll_ev_charging's last applied decision exactly as ev_scheduler_api.py
 * returns it.
 */
export default function EvSchedulerStatusCard() {
  const {
    enabled,
    evSocPercent,
    socCapPercent,
    overrideRequested,
    status,
    chargingAllowed,
    reason,
    error,
    requestingOverride,
    requestOverride,
  } = useEvSchedulerStatus();

  const keyValue = !enabled ? 'Av' : statusLabel(status, chargingAllowed);
  const color = !enabled ? 'blue' : statusColor(status, chargingAllowed);

  return (
    <StatusCard
      title="EV-laddning (pris/SOC)"
      icon={Car}
      color={color}
      keyMetric="Status"
      keyValue={keyValue}
      keyUnit=""
      keyAnnotation={
        error
          ? [`Kunde inte nå API:t: ${error}`]
          : enabled && reason
            ? [reason]
            : undefined
      }
      metrics={[
        {
          label: 'SOC (nu)',
          value: evSocPercent !== null ? evSocPercent.toFixed(0) : '—',
          unit: '%',
        },
        {
          label: 'SOC-tak',
          value: socCapPercent !== null ? socCapPercent.toFixed(0) : '—',
          unit: '%',
        },
      ]}
      headerRight={
        enabled ? (
          <button
            type="button"
            onClick={requestOverride}
            disabled={requestingOverride || overrideRequested}
            className={`text-xs font-medium px-2.5 py-1 rounded-md border transition-colors ${
              overrideRequested
                ? 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700 cursor-default'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-600 disabled:opacity-50'
            }`}
            title="Ladda till 100% under denna laddsession, oavsett SOC-tak/pris/sol. Nollställs automatiskt nästa gång bilen kopplas in."
          >
            {overrideRequested ? 'Override aktiv' : 'Ladda till 100 % (denna session)'}
          </button>
        ) : undefined
      }
    />
  );
}
