import { Activity } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useGovernorStatus } from '../hooks/useGovernorStatus';

// Swedish labels for peak_governor.py's status values (core/governor/peak_governor.py),
// plus the two states that never come from decide() itself: governed off
// entirely, and on but not yet ticked once since startup.
const STATUS_LABELS: Record<string, string> = {
  within_budget: 'Inom budget',
  throttling_ev: 'Stryper EV-laddning',
  no_data: 'Ingen data',
};

const STATUS_COLORS: Record<string, 'blue' | 'green' | 'yellow' | 'red' | 'purple'> = {
  within_budget: 'green',
  throttling_ev: 'yellow',
  no_data: 'red',
};

/**
 * Fas 3b's one visible piece of governor UI: what the peak-power governor
 * is doing right now, mirroring PerificPowerCard's shape (reuse StatusCard,
 * self-fetching hook, no props). Reflects _poll_peak_governor's last
 * applied decision exactly as governor_api.py returns it — never a
 * recomputed hypothetical (see that file's docstring).
 */
export default function GovernorStatusCard() {
  const { enabled, targetKw, status, reason, recentPeakKw, error } = useGovernorStatus();

  const keyValue = !enabled
    ? 'Av'
    : status !== null
      ? (STATUS_LABELS[status] ?? status)
      : 'Väntar på första mätningen…';

  const color = !enabled ? 'blue' : status !== null ? (STATUS_COLORS[status] ?? 'blue') : 'blue';

  return (
    <StatusCard
      title="Effektvakt (EV-laddning)"
      icon={Activity}
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
          label: 'Måleffekt',
          value: targetKw !== null ? targetKw.toFixed(1) : '—',
          unit: 'kW',
        },
        {
          // Added 2026-09-03: real toppimport sedan effektvakten senast
          // slogs på, som kontext bredvid måleffekten ovan — se
          // governor_api.py:s recentPeakKw-docstring. Tomt (—) tills
          // effektvakten är på och har hunnit ticka minst en gång.
          label: 'Uppmätt toppimport',
          value: recentPeakKw !== null ? recentPeakKw.toFixed(1) : '—',
          unit: 'kW',
        },
      ]}
    />
  );
}
