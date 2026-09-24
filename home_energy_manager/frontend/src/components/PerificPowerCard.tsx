import { Zap } from 'lucide-react';
import { StatusCard } from './SystemStatusCard';
import { usePerificPower } from '../hooks/usePerificPower';

/**
 * Fas 2's one visible piece of UI: the live site power reading from
 * Perific One. Deliberately reuses the existing StatusCard component (the
 * same one SystemStatusCard renders) rather than inventing new styling —
 * one number doesn't need its own design language.
 *
 * Self-contained on purpose, matching SystemStatusCard/EnergyFlowCards:
 * fetches its own data via usePerificPower, so dropping <PerificPowerCard />
 * into any page is a one-line addition, no props to wire up.
 */
export default function PerificPowerCard() {
  const { powerKw, available, error } = usePerificPower();

  return (
    <StatusCard
      title="Perific One"
      icon={Zap}
      color="yellow"
      keyMetric="Totaleffekt just nu"
      keyValue={available && powerKw !== null ? powerKw.toFixed(2) : '—'}
      keyUnit="kW"
      keyAnnotation={
        error
          ? [`Kunde inte nå API:t: ${error}`]
          : !available
            ? ['Ingen data just nu — normalt om Perifics molntjänst inte hunnit uppdatera.']
            : undefined
      }
      metrics={[]}
    />
  );
}
