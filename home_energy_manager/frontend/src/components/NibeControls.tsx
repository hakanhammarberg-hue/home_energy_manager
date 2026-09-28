import { useNibeStatus } from '../hooks/useNibeStatus';

// Dashboard-compaction phase (2026-09-28): "Lyxläge varmvatten" used to be
// NibeStatusCard's headerRight button on the Dashboard. NibeStatusCard was
// retired when the Dashboard's Nibe section was replaced by a compact,
// read-only status tile (see CompactStatusRow.tsx) — that tile has no room
// for an interactive control, so this button needed a new home rather than
// disappearing. Its own small component, not folded into NibeLiveCard,
// which documents itself as read-only/zero-writes on purpose; this keeps
// that contract intact and gives the Nibe page's one write control an
// explicit, separate place.
export default function NibeControls() {
  const { enabled, dhwLuxuryEnabled, togglingDhwLuxury, setDhwLuxuryEnabled, error } =
    useNibeStatus();

  if (!enabled) {
    // Mirrors every other Nibe UI's convention: nothing to control while
    // the nibe.enabled master switch itself is off (see nibe_api.py).
    return null;
  }

  return (
    <div className="flex items-center justify-between gap-4 border rounded-lg p-4 border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <div className="min-w-0">
        <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
          Lyxläge varmvatten
        </div>
        <div className="text-xs text-gray-500 dark:text-gray-400">
          Lyxläge när elen är billig eller vid solöverskott, alltid inom effektvaktens
          utrymme. Annars Ekonomi.
        </div>
        {error && (
          <div className="text-xs text-red-500 dark:text-red-400 mt-1">
            Kunde inte nå API:t: {error}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={() => setDhwLuxuryEnabled(!dhwLuxuryEnabled)}
        disabled={togglingDhwLuxury}
        className={`text-xs font-medium px-2.5 py-1 rounded-md border transition-colors shrink-0 ${
          dhwLuxuryEnabled
            ? 'bg-green-100 text-green-800 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700'
            : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-600'
        } disabled:opacity-50`}
      >
        {dhwLuxuryEnabled ? 'Lyxläge varmvatten: På' : 'Lyxläge varmvatten: Av'}
      </button>
    </div>
  );
}
