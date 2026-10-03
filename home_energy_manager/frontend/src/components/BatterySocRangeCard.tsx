import { Battery } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { useBatterySocRange } from '../hooks/useBatterySocRange';

/**
 * Added 2026-09-03 after a live 3-day check-in showed the battery cycling
 * repeatedly between its configured floor and a ~60-63% ceiling — a
 * pattern invisible from BatteryLevelChart's single-day view. Mirrors
 * PerificPowerCard's shape exactly: reuse StatusCard, self-fetching hook,
 * no props.
 *
 * Fixed 2026-09-29: this used to label the range with the fixed target
 * window (always "senaste 3 dygn"), even though the sample buffer lives
 * only in process memory and empties on every add-on restart — right
 * after a restart it takes days to grow back out to the target, so the
 * card was claiming a 3-day range while actually showing barely an hour
 * of data (which is what Håkan noticed). `windowHours` from the hook is
 * now the buffer's actual current span, so the label and the note below
 * are honest about how much history is really behind the shown min/max.
 */
function formatWindowLabel(hours: number): string {
  if (hours < 1) return '< 1 h';
  if (hours < 24) return `${Math.round(hours)} h`;
  return `${Math.round(hours / 24)} dygn`;
}

export default function BatterySocRangeCard() {
  const { minPercent, maxPercent, windowHours, targetWindowHours, sampleCount, error } =
    useBatterySocRange();

  const hasRange = sampleCount > 0 && minPercent !== null && maxPercent !== null;
  const windowLabel = windowHours !== null ? formatWindowLabel(windowHours) : '';
  // A full hour of slack before calling it "still filling up" avoids a
  // permanent, pointless note once the buffer is essentially at target
  // (it never exactly reaches targetWindowHours, since the oldest sample
  // held is always at least one 30s poll old).
  const stillFilling =
    hasRange &&
    windowHours !== null &&
    targetWindowHours !== null &&
    windowHours < targetWindowHours - 1;

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
            ? ['Ingen data än — fylls på i takt med att H.E.M. pollar SOC.']
            : stillFilling
              ? [
                  `Fyller fortfarande på efter omstart — når ${
                    targetWindowHours !== null ? formatWindowLabel(targetWindowHours) : ''
                  } inom några dygn.`,
                ]
              : undefined
      }
      metrics={[]}
    />
  );
}
