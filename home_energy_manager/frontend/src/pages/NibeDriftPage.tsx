import NibeLiveCard from '../components/NibeLiveCard';
import NibeHistoryCharts from '../components/NibeHistoryCharts';
import NibeControls from '../components/NibeControls';
import NibeSavingsCard from '../components/NibeSavingsCard';

// Dedicated Nibe page (2026-09-28), built at Håkan's explicit request:
// "vad som sker för sekunden" — real-time operating data, which the
// Dashboard's old NibeStatusCard (a 30s-cached last-decision summary) and
// NibeHistoryCharts (hourly trends) didn't show on their own.
//
// Dashboard-compaction phase (also 2026-09-28, same day): now that this
// page exists, Håkan asked for the detailed Nibe UI to live here ONLY
// ("övriga nibe-värden behövs bara på nibe-sidan") — the Dashboard itself
// now shows just a compact status/savings tile (CompactStatusRow.tsx). Two
// things moved here as a result: the "Lyxläge varmvatten" toggle
// (NibeControls, previously NibeStatusCard's headerRight button — this
// page's one write control, deliberately its own component since
// NibeLiveCard documents itself as read-only) and the full cost-savings
// breakdown (NibeSavingsCard) behind the Dashboard's compact "kr idag"
// figure.
export default function NibeDriftPage() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Nibe — drift just nu
        </h2>
        <NibeLiveCard />
      </div>

      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Styrning
        </h2>
        <NibeControls />
      </div>

      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Kostnadsbesparing
        </h2>
        <NibeSavingsCard />
      </div>

      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
          Historik
        </h2>
        <NibeHistoryCharts />
      </div>
    </div>
  );
}
