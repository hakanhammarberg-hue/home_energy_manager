import { useState } from 'react';
import { Battery } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useBatteryOverride } from '../hooks/useBatteryOverride';

const DURATION_OPTIONS = [30, 60, 120];

function minutesRemaining(until: string | null): number | null {
  if (!until) return null;
  const ms = new Date(until).getTime() - Date.now();
  return ms > 0 ? Math.ceil(ms / 60_000) : 0;
}

const REASON_LABELS: Record<string, string> = {
  manual_override: 'Tvångsladdning (manuell)',
  anti_dormancy: 'Väckningspuls (BMS-dvala)',
  none: 'Av',
};

/**
 * Fas 6 (2026-10-09) — the one visible piece of UI for
 * core/bess/battery_override.py's two levers: a manual "force-charge from
 * grid" button Håkan asked for after the confirmed BMS-dormancy incidents
 * (punkt 33/34/40 of the project log), plus a passive status line for the
 * automatic anti-dormancy pulse (its enabled/threshold settings live in
 * Settings → Battery, same convention as every other background lever —
 * this card only shows what it's doing, not a toggle for it).
 *
 * Mirrors EvSchedulerStatusCard's shape (reuse StatusCard, self-fetching
 * hook, "never a recomputed hypothetical" contract) with one addition: a
 * duration <select> alongside the button, since this override needs a
 * chosen length rather than being a fixed one-shot.
 */
export default function BatteryOverrideCard() {
  const {
    active,
    reason,
    until,
    overrideForceChargeUntil,
    error,
    requesting,
    requestOverride,
    cancelOverride,
  } = useBatteryOverride();

  const [selectedMinutes, setSelectedMinutes] = useState(DURATION_OPTIONS[0]);

  const manualOverrideActive = Boolean(overrideForceChargeUntil);
  const remaining = minutesRemaining(manualOverrideActive ? overrideForceChargeUntil : until);

  const keyValue = active ? REASON_LABELS[reason] ?? reason : 'Av';
  const color: 'blue' | 'green' | 'yellow' | 'red' | 'purple' = active
    ? reason === 'manual_override'
      ? 'green'
      : 'yellow'
    : 'blue';

  return (
    <StatusCard
      title="Tvångsladdning batteri"
      icon={Battery}
      color={color}
      keyMetric="Status"
      keyValue={keyValue}
      keyUnit=""
      keyAnnotation={
        error
          ? [`Kunde inte nå API:t: ${error}`]
          : active && remaining !== null
            ? [`Återstår ca ${remaining} min`]
            : reason === 'anti_dormancy'
              ? ['Automatisk väckningspuls mot BMS-dvala — se Inställningar → Batteri']
              : undefined
      }
      metrics={[]}
      headerRight={
        manualOverrideActive ? (
          <button
            type="button"
            onClick={cancelOverride}
            disabled={requesting}
            className="text-xs font-medium px-2.5 py-1 rounded-md border transition-colors bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700 hover:bg-green-200 disabled:opacity-50"
            title="Avbryt tvångsladdningen nu och återgå till normal drift."
          >
            Avbryt tvångsladdning
          </button>
        ) : (
          <div className="flex items-center gap-1.5">
            <select
              value={selectedMinutes}
              onChange={(e) => setSelectedMinutes(Number(e.target.value))}
              disabled={requesting}
              className="text-xs rounded-md border px-1.5 py-1 bg-white text-gray-700 border-gray-300 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600"
            >
              {DURATION_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {m} min
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => requestOverride(selectedMinutes)}
              disabled={requesting}
              className="text-xs font-medium px-2.5 py-1 rounded-md border transition-colors bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-600 disabled:opacity-50"
              title="Tvångsladda batteriet från nätet med full effekt tills tiden gått ut eller SOC-taket nås, vilket som kommer först. Effektvakten skyddar huvudsäkringen automatiskt genom att strypa EV/Nibe om totaleffekten blir för hög."
            >
              Tvångsladda
            </button>
          </div>
        )
      }
    />
  );
}
