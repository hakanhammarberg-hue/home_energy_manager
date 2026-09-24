import { Battery } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useBatterySocRange } from '../hooks/useBatterySocRange';

/**
 * Added 2026-09-03 after a live 3-day check-in showed the battery cycling
 * repeatedly between its configured floor and a ~60-63% ceiling — a
 * pattern invisible from BatteryLevelChart's single-day view. Mirrors
 * PerificPowerCard's shape exactly: reuse StatusCard, self-fetching hook,
 * no props.
 */
export default function BatterySocRangeCard() {
  const { minPercent, maxPercent, windowHours, sampleCount, error } = useBatterySocRange();

  const hasRange = sampleCount > 0 && minPercent !== null && maxPercent !== null;
  const windowLabel = windowHours !== null ? `${Math.round(windowHours / 24)} dygn` : '';

  return (
    <StatusCard
      title="Batteri-SOC, senaste dygnen"
      icon={Battery}
      color="green"
      keyMetric={hasRange ? `Spann senaste ${windowLabel}` : 'Spann'}
      keyValue={hasRange ? `${minPercent!.toFixed(0)}–${maxPercent!.toFixed(0)}` : '—'}
      keyUnit="%"
      keyAnnotation={
        error
          ? [`Kunde inte nå API:t: ${error}`]
          : !hasRange
            ? ['Ingen data än — fylls på i takt med att BESS pollar SOC.']
            : undefined
      }
      metrics={[]}
    />
  );
}
