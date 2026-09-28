import NibeLiveCard from '../components/NibeLiveCard';
import NibeHistoryCharts from '../components/NibeHistoryCharts';

// New dedicated Nibe page (2026-09-28), built at Håkan's explicit request:
// "vad som sker för sekunden" — real-time operating data, which the
// Dashboard's NibeStatusCard (a 30s-cached last-decision summary) and
// NibeHistoryCharts (hourly trends) don't show on their own. Both existing
// components stay exactly where they are on the Dashboard too; this page
// is additive, not a replacement, and simply gives Nibe its own place that
// combines "right now" (NibeLiveCard, polls every 10s) with "the last
// 24h/48h/7 days" (NibeHistoryCharts, unchanged) in one view.
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
          Historik
        </h2>
        <NibeHistoryCharts />
      </div>
    </div>
  );
}
