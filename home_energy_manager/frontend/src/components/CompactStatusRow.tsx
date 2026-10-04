import CompactStatusCard from './CompactStatusCard';
import { usePerificPower } from '../hooks/usePerificPower';
import { useGovernorStatus } from '../hooks/useGovernorStatus';
import { useEvSchedulerStatus } from '../hooks/useEvSchedulerStatus';
import { useNibeStatus } from '../hooks/useNibeStatus';
import { useNibeSavings } from '../hooks/useNibeSavings';
import { useNibeLive } from '../hooks/useNibeLive';
import { heatingStatusColor, nibeActivityLabel } from '../lib/nibeStatusLabels';
import perificOneImage from '../assets/devices/perific-one.jpg';
import ev3Image from '../assets/devices/ev3.jpg';
import heatPumpImage from '../assets/devices/heat-pump.jpg';
import zaptecImage from '../assets/devices/zaptec.jpg';

// Dashboard-compaction phase (2026-09-28): four small square tiles in a
// row — see CompactStatusCard.tsx's own docstring for the layout history
// and claude/dashboard-compaction-and-nibe-savings-forslag.md's "Del 1" for
// the research behind it.
//
// Restructured 2026-10-03 per Håkan's ask to put his own device photos
// (frontend/src/assets/devices/ — confirmed his own, not manufacturer
// stock images) directly on these tiles and to regroup what each tile
// shows:
//   - "Perific One": Perific One's own device photo (the white box with
//     the "Z"-like logo — NOT the Zaptec charger, despite the visual
//     similarity; Håkan corrected this assumption explicitly). Keeps its
//     own live power reading as the headline value, and now ALSO carries
//     the Effektvakt (governor) status/metrics that used to have their
//     own tile — "Lägg status för effektvakt i perific rutan."
//   - "Zaptec Go 2" (replaces the old "Effektvakt" tile slot): the actual
//     EV charger's on/off + current charging power, moved here from the
//     old "EV-laddning" tile. Initially shown with a generic Zap icon
//     (its own photo had turned out to be Perific One's) — Håkan sent a
//     real photo of his own Zaptec Go 2 unit on 2026-10-04 (confirmed his
//     own, same provenance check as the original six device photos), so
//     it now has a proper device photo like every other tile.
//   - "Elfordon" (renamed from "EV-laddning"): the EV3's own photo, and
//     ONLY the state of charge — "Sätt bara state of charge där."
//   - "Nibe": the F750's own photo, keeping its kr-idag savings headline,
//     but with a NEW statusLine showing the pump's actual physical
//     activity (Varmvatten/Uppvärmning hus/Avfrostning/Inaktiv) via
//     nibeActivityLabel() — deliberately separate from the old
//     heatingStatusLabel (decision-engine reasoning like "extra värme,
//     billig timme"), which is still shown in full on the dedicated /nibe
//     page. Color coding is left on the decision-engine status (unchanged)
//     since Håkan only asked to change the status wording, not the color.

const GOVERNOR_STATUS_LABELS: Record<string, string> = {
  within_budget: 'Inom budget',
  throttling_ev: 'Stryper EV',
  no_data: 'Ingen data',
};

const GOVERNOR_STATUS_COLORS: Record<string, 'blue' | 'green' | 'yellow' | 'red' | 'purple'> = {
  within_budget: 'green',
  throttling_ev: 'yellow',
  no_data: 'red',
};

export default function CompactStatusRow() {
  const perific = usePerificPower();
  const governor = useGovernorStatus();
  const ev = useEvSchedulerStatus();
  const nibeStatus = useNibeStatus();
  const nibeSavings = useNibeSavings();
  const nibeLive = useNibeLive();

  // --- Perific One (own power reading + Effektvakt/governor status) ---
  const perificValue =
    perific.available && perific.powerKw !== null ? perific.powerKw.toFixed(2) : '—';

  const governorStatusLine = !governor.enabled
    ? 'Effektvakt av'
    : governor.status !== null
      ? (GOVERNOR_STATUS_LABELS[governor.status] ?? governor.status)
      : 'Väntar…';
  const governorColor: 'blue' | 'green' | 'yellow' | 'red' | 'purple' = !governor.enabled
    ? 'yellow'
    : governor.status !== null
      ? (GOVERNOR_STATUS_COLORS[governor.status] ?? 'yellow')
      : 'yellow';
  const perificMetrics =
    governor.enabled && governor.targetKw !== null
      ? [
          { label: 'Mål', value: `${governor.targetKw.toFixed(1)} kW` },
          ...(governor.recentPeakKw !== null
            ? [{ label: 'Topp', value: `${governor.recentPeakKw.toFixed(1)} kW` }]
            : []),
        ]
      : undefined;
  const perificAnnotation =
    perific.error || governor.error ? 'Kunde inte nå API:t' : undefined;

  // --- Zaptec Go 2 (actual charger: on/off + current charging power) ---
  const chargingActive = ev.chargingActive;
  const zaptecValue =
    chargingActive === null ? 'Ingen data' : chargingActive ? 'Laddar' : 'Av';
  const zaptecColor: 'blue' | 'green' | 'yellow' | 'red' | 'purple' =
    chargingActive === null ? 'red' : chargingActive ? 'green' : 'blue';
  const zaptecMetrics = chargingActive
    ? [{ label: 'Effekt', value: `${(ev.chargingPowerKw ?? 0).toFixed(1)} kW` }]
    : undefined;

  // --- Elfordon (EV3 photo, state of charge only) ---
  const evSocValue = ev.evSocPercent !== null ? `${ev.evSocPercent.toFixed(0)}%` : '—';

  // --- Nibe (heat pump photo, savings + live physical-activity status) ---
  const nibeValue = !nibeStatus.enabled ? 'Av' : `${nibeSavings.totalSavingsKr.toFixed(1)}`;
  const nibeColor = !nibeStatus.enabled ? 'blue' : heatingStatusColor(nibeStatus.heating.status);
  const nibeStatusLine = nibeStatus.enabled
    ? nibeActivityLabel(nibeLive.live.prio, nibeLive.live.compressorState)
    : undefined;
  const nibeAnnotation =
    nibeStatus.error || nibeSavings.error || nibeLive.error ? 'Kunde inte nå API:t' : undefined;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <CompactStatusCard
        title="Perific One"
        image={{ src: perificOneImage, alt: 'Perific One' }}
        color={governorColor}
        keyValue={perificValue}
        keyUnit="kW"
        statusLine={governorStatusLine}
        metrics={perificMetrics}
        annotation={perificAnnotation}
      />
      <CompactStatusCard
        title="Zaptec Go 2"
        image={{ src: zaptecImage, alt: 'Zaptec Go 2' }}
        color={zaptecColor}
        keyValue={zaptecValue}
        metrics={zaptecMetrics}
        annotation={ev.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="Elfordon"
        image={{ src: ev3Image, alt: 'Elfordon (EV3)' }}
        color="blue"
        keyValue={evSocValue}
        annotation={ev.error ? 'Kunde inte nå API:t' : undefined}
      />
      <CompactStatusCard
        title="Nibe"
        image={{ src: heatPumpImage, alt: 'Nibe F750' }}
        color={nibeColor}
        keyValue={nibeValue}
        keyUnit={nibeStatus.enabled ? 'kr idag' : undefined}
        statusLine={nibeStatusLine}
        annotation={nibeAnnotation}
      />
    </div>
  );
}
