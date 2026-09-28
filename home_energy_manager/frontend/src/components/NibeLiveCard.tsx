import React from 'react';
import { Activity, Droplet, Flame, Gauge, Thermometer, Zap } from 'lucide-react';
import { useNibeLive } from '../hooks/useNibeLive';
import {
  dhwStatusColor,
  dhwStatusLabel,
  heatingStatusColor,
  heatingStatusLabel,
} from '../lib/nibeStatusLabels';

// "Nibe drift" (2026-09-28): the real-time counterpart to NibeHistoryCharts'
// multi-hour trends and NibeStatusCard's Dashboard summary — Håkan asked
// for "driftdata, vad som sker för sekunden" (what's happening right now),
// which the 30s-cached last-decision status alone can't show for power/
// frequency/current. Polls GET /api/nibe/live every 10s via useNibeLive.
//
// Prio (sensor.prio_43086) is the headline: it's the pump's own single
// source of truth for "what am I doing right now" (Off/Hot Water/Heat/
// Pool) — found and enabled while investigating the heat/DHW priority
// question (see the project status doc's Fas 4/Nibe-priority entry), kept
// unused until this page gave it a home.

const PRIO_LABELS: Record<string, string> = {
  OFF: 'Av',
  'Hot Water': 'Varmvatten',
  Heat: 'Värme',
  Pool: 'Pool',
};

// Static class strings, one per StatusColor — Tailwind's build only picks
// up classes it can see literally in source, so `text-${color}-600`
// (interpolated at runtime) would silently vanish from the production
// CSS. Same reason StatusCard.tsx keeps its own colorClasses/
// iconColorClasses maps instead of building class names dynamically.
const STATUS_TEXT_CLASSES: Record<string, string> = {
  blue: 'text-blue-600 dark:text-blue-400',
  green: 'text-green-600 dark:text-green-400',
  yellow: 'text-yellow-600 dark:text-yellow-400',
  red: 'text-red-600 dark:text-red-400',
  purple: 'text-purple-600 dark:text-purple-400',
};

function formatNumber(value: number | null, digits = 1): string {
  return value === null ? '—' : value.toFixed(digits);
}

interface TileProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  unit?: string;
  highlight?: 'yellow' | 'red';
}

function Tile({ icon: Icon, label, value, unit, highlight }: TileProps) {
  const highlightClasses =
    highlight === 'red'
      ? 'border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-900/20'
      : highlight === 'yellow'
        ? 'border-yellow-300 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-900/20'
        : 'border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800';

  return (
    <div className={`border rounded-lg p-4 ${highlightClasses}`}>
      <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-1">
        <Icon className="h-4 w-4 mr-1.5" />
        {label}
      </div>
      <div className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        {value}
        {unit && <span className="text-sm font-normal text-gray-500 dark:text-gray-400 ml-1">{unit}</span>}
      </div>
    </div>
  );
}

export default function NibeLiveCard() {
  const { enabled, heating, dhw, live, error, loading } = useNibeLive();

  const prioLabel = live.prio === null ? '—' : (PRIO_LABELS[live.prio] ?? live.prio);
  const compressorRunning = live.compressorState !== null && live.compressorState !== 'STOPPED';

  return (
    <div className="space-y-4">
      {error && (
        <div className="text-sm text-red-600 dark:text-red-400">
          Kunde inte nå live-API:t: {error}
        </div>
      )}

      {/* Headline: what the pump's own Prio register says it's doing, plus
          this app's own heating/DHW decision status (null/"Av" whenever
          nibe.enabled is off — see useNibeLive's docstring, same
          convention as NibeStatusCard). */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="border rounded-lg p-4 border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-1">
            <Flame className="h-4 w-4 mr-1.5" />
            Prio (pumpens egen status)
          </div>
          <div className={`text-xl font-semibold ${compressorRunning ? 'text-orange-600 dark:text-orange-400' : 'text-gray-900 dark:text-gray-100'}`}>
            {prioLabel}
          </div>
        </div>
        <div className="border rounded-lg p-4 border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">Rumsuppvärmning</div>
          <div className={`text-base font-semibold ${enabled ? STATUS_TEXT_CLASSES[heatingStatusColor(heating.status)] : STATUS_TEXT_CLASSES.blue}`}>
            {enabled ? heatingStatusLabel(heating.status) : 'Av'}
          </div>
        </div>
        <div className="border rounded-lg p-4 border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
          <div className="text-sm text-gray-500 dark:text-gray-400 mb-1">Varmvatten (Lyxläge-styrning)</div>
          <div className={`text-base font-semibold ${enabled ? STATUS_TEXT_CLASSES[dhwStatusColor(dhw.status)] : STATUS_TEXT_CLASSES.blue}`}>
            {enabled ? dhwStatusLabel(dhw.status) : 'Av'}
          </div>
        </div>
      </div>

      {/* Compressor detail */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Tile icon={Zap} label="Kompressor, ineffekt" value={formatNumber(live.compressorPowerKw, 2)} unit="kW" />
        <Tile icon={Zap} label="Kompressor, medeleffekt" value={formatNumber(live.compressorPowerMeanKw, 2)} unit="kW" />
        <Tile icon={Activity} label="Kompressorfrekvens" value={formatNumber(live.compressorFrequencyHz, 0)} unit="Hz" />
        <Tile icon={Activity} label="Kompressorström" value={formatNumber(live.compressorCurrentA, 1)} unit="A" />
        <Tile
          icon={Zap}
          label="Eltillsats"
          value={formatNumber(live.electricAdditionKw, 2)}
          unit="kW"
          highlight={live.electricAdditionKw !== null && live.electricAdditionKw > 0 ? 'yellow' : undefined}
        />
        <Tile
          icon={Gauge}
          label="Gradminuter"
          value={formatNumber(live.degreeMinutes, 0)}
          unit="DM"
          highlight={live.degreeMinutes !== null && live.degreeMinutes <= -400 ? 'red' : undefined}
        />
        <Tile icon={Gauge} label="Laddpump GP1" value={formatNumber(live.chargePumpSpeedPct, 0)} unit="%" />
        <Tile icon={Gauge} label="Framledningspump" value={formatNumber(live.supplyPumpSpeedPct, 0)} unit="%" />
      </div>

      {/* Temperatures + applied curve offset */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Tile icon={Thermometer} label="Rumstemp, verklig" value={formatNumber(live.indoorActualC)} unit="°C" />
        <Tile icon={Thermometer} label="Rumstemp, mål" value={formatNumber(live.indoorTargetC)} unit="°C" />
        <Tile icon={Droplet} label="Varmvatten, verklig" value={formatNumber(live.dhwActualC)} unit="°C" />
        <Tile icon={Gauge} label="Kurvoffset, tillämpad" value={formatNumber(live.heatOffsetC, 0)} unit="°C" />
      </div>

      {loading && live.prio === null && (
        <div className="text-sm text-gray-400 dark:text-gray-500">Hämtar driftdata…</div>
      )}
    </div>
  );
}
