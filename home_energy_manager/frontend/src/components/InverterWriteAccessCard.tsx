import { Shield } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useInverterWriteAccess } from '../hooks/useInverterWriteAccess';

// Raw select states from INVERTER_VPP_REMOTE_CONTROL_ENTITY (app.py) —
// only the two real values that entity has been observed to report.
// Anything else (an unrecognized string) falls back to showing the raw
// state as-is rather than guessing.
const STATE_LABELS: Record<string, string> = {
  Enabled: 'Aktiv',
  Disabled: 'Inaktiv',
};

const STATE_COLORS: Record<string, 'green' | 'yellow'> = {
  Enabled: 'green',
  Disabled: 'yellow',
};

/**
 * Added 2026-09-03 after INVERTER_VPP_REMOTE_CONTROL_ENTITY was observed
 * live sitting on "Disabled" for a day, then "Enabled" the next, with
 * nothing in the UI showing either state — the DP engine can compute a
 * perfect schedule and still have nowhere for it to go if this permission
 * happens to be off. Mirrors PerificPowerCard's shape exactly.
 */
export default function InverterWriteAccessCard() {
  const { state, available, error } = useInverterWriteAccess();

  const keyValue = available && state ? (STATE_LABELS[state] ?? state) : '—';
  const color = available && state ? (STATE_COLORS[state] ?? 'yellow') : 'blue';

  return (
    <StatusCard
      title="Skrivbehörighet till växelriktare"
      icon={Shield}
      color={color}
      keyMetric="Fjärrstyrning"
      keyValue={keyValue}
      keyUnit=""
      keyAnnotation={
        error
          ? [`Kunde inte nå API:t: ${error}`]
          : !available
            ? ['Ingen data just nu — normalt precis efter start, innan första pollningen.']
            : undefined
      }
      metrics={[]}
    />
  );
}
