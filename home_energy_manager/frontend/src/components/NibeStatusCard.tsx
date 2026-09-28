import { Flame } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useNibeStatus } from '../hooks/useNibeStatus';
import {
  dhwStatusLabel,
  heatingStatusColor,
  heatingStatusLabel,
} from '../lib/nibeStatusLabels';

/**
 * Fas 4a's one visible piece of Nibe UI: the space-heating curve-offset
 * boost status, plus the "Lyxläge varmvatten" toggle and its current
 * comfort mode. Mirrors GovernorStatusCard/EvSchedulerStatusCard's shape
 * (reuse StatusCard, self-fetching hook) and the same "never a recomputed
 * hypothetical" contract — reflects _poll_nibe's last applied decisions
 * exactly as nibe_api.py returns them.
 *
 * REVISED 2026-09-22: the lever behind this card used to be SG Ready
 * (switch.sg_ready_heating_*); it's now number.heat_offset_s1_* directly
 * (see core/nibe/decision.py's MECHANISM CHOICE section) — true SG Ready
 * needs two physical relay-driven AUX inputs Håkan doesn't have wired.
 * The card's own labels/title were updated to match; only the internal
 * `heating.offsetC` field name changed on the wire (was `heating.active`).
 */
export default function NibeStatusCard() {
  const {
    enabled,
    dhwLuxuryEnabled,
    heating,
    dhw,
    error,
    togglingDhwLuxury,
    setDhwLuxuryEnabled,
  } = useNibeStatus();

  const heatingValue = !enabled
    ? 'Av'
    : heatingStatusLabel(heating.status) +
      (heating.offsetC ? ` (offset +${heating.offsetC})` : '');

  const heatingColor = !enabled ? 'blue' : heatingStatusColor(heating.status);

  const dhwValue = !enabled
    ? 'Av'
    : !dhwLuxuryEnabled
      ? 'Av'
      : dhwStatusLabel(dhw.status);

  return (
    <StatusCard
      title="Nibe F750"
      icon={Flame}
      color={heatingColor}
      keyMetric="Rumsuppvärmning (värmekurva-offset)"
      keyValue={heatingValue}
      keyUnit=""
      keyAnnotation={
        error
          ? [`Kunde inte nå API:t: ${error}`]
          : enabled && heating.reason
            ? [heating.reason]
            : undefined
      }
      metrics={[
        {
          label: 'Lyxläge varmvatten',
          value: dhwValue,
          unit: '',
        },
      ]}
      headerRight={
        enabled ? (
          <button
            type="button"
            onClick={() => setDhwLuxuryEnabled(!dhwLuxuryEnabled)}
            disabled={togglingDhwLuxury}
            className={`text-xs font-medium px-2.5 py-1 rounded-md border transition-colors ${
              dhwLuxuryEnabled
                ? 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-600'
            } disabled:opacity-50`}
            title="Sätt varmvatten till Lyxläge när elen är billig eller vid solöverskott, alltid inom effektvaktens utrymme. Annars Ekonomi."
          >
            {dhwLuxuryEnabled ? 'Lyxläge varmvatten: På' : 'Lyxläge varmvatten: Av'}
          </button>
        ) : undefined
      }
    />
  );
}
