import React, { useState, useEffect } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useNibeHistory, NibeHistoryPeriod } from '../hooks/useNibeHistory';

const HOURS_OPTIONS: { label: string; hours: number }[] = [
  { label: '24h', hours: 24 },
  { label: '48h', hours: 48 },
  { label: '7 dagar', hours: 24 * 7 },
];

function useDarkMode() {
  const [isDarkMode, setIsDarkMode] = useState(
    document.documentElement.classList.contains('dark')
  );
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);
  return isDarkMode;
}

function formatHourLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('sv-SE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

// Defensive formatters for recharts Tooltip: an early version of this
// component shaded the DHW comfort band with a single Area bound to a
// [low, high] array value, and the shared Tooltip formatter (same
// function for every series in a chart) crashed with "toFixed is not a
// function" the moment that series was hovered, since it assumed every
// value was a plain number. The band is now two ordinary Lines instead
// (simpler, no array-valued data key at all), but these formatters keep
// the array/typeof guards anyway — cheap insurance against any future
// series that isn't a plain number, and against null/undefined.
function formatTemp(v: unknown): string {
  if (Array.isArray(v)) {
    const [low, high] = v as [number, number];
    return `${low.toFixed(1)}–${high.toFixed(1)}°C`;
  }
  return typeof v === 'number' ? `${v.toFixed(1)}°C` : '–';
}

function formatOffset(v: unknown): string {
  return typeof v === 'number' ? `${v}` : '–';
}

function formatEnergy(v: unknown): string {
  return typeof v === 'number' ? `${v.toFixed(2)} kWh` : '–';
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">{title}</h3>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/**
 * Fas 5 (2026-09-24): Nibe history charts, in the same visual family as
 * BatteryLevelChart/EnergyFlowChart (dark-mode-aware recharts, single
 * responsibility per chart) but each kept single-axis rather than that
 * component's dual-axis pattern — indoor temp (~18-25°C), DHW tank temp
 * (~45-55°C) and curve offset (-2..+2) live on genuinely different scales,
 * so three focused charts read more clearly than one crowded one.
 *
 * Backed by GET /api/nibe/history (core/nibe/history.py) — hourly buckets
 * built directly from Home Assistant's own recorder history, confirmed
 * live against real entities 2026-09-24 (see the project status doc's
 * Fas 5 entry). Shown unconditionally (not gated on nibe.enabled the way
 * NibeStatusCard's boost status is) — indoor/DHW temperature and energy
 * use are meaningful regardless of whether the price/solar boost lever
 * happens to be switched on right now.
 */
export default function NibeHistoryCharts() {
  const [hours, setHours] = useState(48);
  const { periods, loading, error, refetch } = useNibeHistory(hours);
  const isDarkMode = useDarkMode();

  const colors = {
    grid: isDarkMode ? '#374151' : '#e5e7eb',
    text: isDarkMode ? '#9CA3AF' : '#374151',
    tooltipBg: isDarkMode ? '#374151' : '#ffffff',
    tooltipBorder: isDarkMode ? '#4b5563' : '#d1d5db',
    offset: '#8b5cf6',
    indoorActual: '#16a34a',
    indoorTarget: isDarkMode ? '#6b7280' : '#9ca3af',
    dhwActual: '#dc2626',
    spaceHeating: '#f59e0b',
    hotWater: '#3b82f6',
  };

  const chartData = periods.map((p: NibeHistoryPeriod) => ({
    ...p,
    label: formatHourLabel(p.timestamp),
  }));

  const tooltipStyle = {
    backgroundColor: colors.tooltipBg,
    border: `1px solid ${colors.tooltipBorder}`,
    borderRadius: '8px',
    padding: '8px 10px',
    color: colors.text,
    fontSize: 12,
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {HOURS_OPTIONS.map((opt) => (
            <button
              key={opt.hours}
              type="button"
              onClick={() => setHours(opt.hours)}
              className={`text-xs font-medium px-2.5 py-1 rounded-md border transition-colors ${
                hours === opt.hours
                  ? 'bg-blue-100 text-blue-800 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700'
                  : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-600'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={refetch}
          disabled={loading}
          className="text-xs font-medium px-2.5 py-1 rounded-md border bg-white text-gray-700 border-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-600 disabled:opacity-50"
        >
          {loading ? 'Uppdaterar…' : 'Uppdatera'}
        </button>
      </div>

      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">Kunde inte hämta historik: {error}</p>
      )}
      {!error && !loading && periods.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Ingen historik tillgänglig ännu för valt intervall.
        </p>
      )}

      {periods.length > 0 && (
        <>
          <ChartCard title="Rumstemperatur vs. mål">
            <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid stroke={colors.grid} strokeOpacity={0.3} strokeWidth={0.5} />
              <XAxis dataKey="label" tick={{ fill: colors.text, fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis
                domain={['dataMin - 1', 'dataMax + 1']}
                tick={{ fill: colors.text, fontSize: 12 }}
                tickFormatter={(v: number) => `${v}°`}
                width={40}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={formatTemp} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="indoorTargetC"
                name="Mål"
                stroke={colors.indoorTarget}
                strokeDasharray="4 3"
                strokeWidth={1.5}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="indoorActualC"
                name="Verklig"
                stroke={colors.indoorActual}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </ComposedChart>
          </ChartCard>

          <ChartCard title="Varmvattentemperatur (tank) vs. komfortband">
            <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid stroke={colors.grid} strokeOpacity={0.3} strokeWidth={0.5} />
              <XAxis dataKey="label" tick={{ fill: colors.text, fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis
                domain={['dataMin - 2', 'dataMax + 2']}
                tick={{ fill: colors.text, fontSize: 12 }}
                tickFormatter={(v: number) => `${v}°`}
                width={40}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={formatTemp} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="dhwTargetHighC"
                name="Max (komfort)"
                stroke={colors.indoorTarget}
                strokeDasharray="4 3"
                strokeWidth={1.5}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="dhwTargetLowC"
                name="Min (komfort)"
                stroke={colors.indoorTarget}
                strokeDasharray="4 3"
                strokeWidth={1.5}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="dhwActualC"
                name="Verklig"
                stroke={colors.dhwActual}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </ComposedChart>
          </ChartCard>

          <ChartCard title="Värmekurva-offset (tillämpad)">
            <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid stroke={colors.grid} strokeOpacity={0.3} strokeWidth={0.5} />
              <XAxis dataKey="label" tick={{ fill: colors.text, fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis
                domain={[-3, 3]}
                tick={{ fill: colors.text, fontSize: 12 }}
                width={40}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={formatOffset} />
              <Line
                type="stepAfter"
                dataKey="offsetC"
                name="Offset"
                stroke={colors.offset}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </ComposedChart>
          </ChartCard>

          <ChartCard title="Energianvändning per timme (uppvärmning vs. varmvatten)">
            <BarChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
              <CartesianGrid stroke={colors.grid} strokeOpacity={0.3} strokeWidth={0.5} />
              <XAxis dataKey="label" tick={{ fill: colors.text, fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis
                tick={{ fill: colors.text, fontSize: 12 }}
                tickFormatter={(v: number) => `${v} kWh`}
                width={55}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={formatEnergy} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="spaceHeatingEnergyKwh" name="Uppvärmning" stackId="energy" fill={colors.spaceHeating} />
              <Bar dataKey="hwEnergyKwh" name="Varmvatten" stackId="energy" fill={colors.hotWater} />
            </BarChart>
          </ChartCard>
        </>
      )}
    </div>
  );
}
