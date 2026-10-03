// Added 2026-10-03, Håkan's explicit ask ("Jag vill ha in bilderna på
// apparaterna i home assistant managers dashboard"). All six images are
// Håkan's own photos of his own installed equipment (confirmed by him
// after I flagged that their white/studio backgrounds looked like
// manufacturer product shots — he confirmed they are genuinely his own,
// 2026-10-03), so there's no copyright concern importing them straight
// into the bundle like the house photo in App.tsx's header.
//
// A simple photo + label grid rather than wiring these into
// SystemStatusCard/CompactStatusRow: those cards are already dense with
// live numbers, and cramming a photo into a 4px-icon-sized tile would
// fight their whole "compact" point (see CompactStatusCard's own
// docstring). This is purely a visual "here's what's actually in my
// house" section — no live data, so no hooks/polling needed.
import solarPanelsImage from '../assets/devices/solar-panels.jpg';
import batteryImage from '../assets/devices/battery.jpg';
import inverterImage from '../assets/devices/inverter.jpg';
import heatPumpImage from '../assets/devices/heat-pump.jpg';
import evImage from '../assets/devices/ev.jpg';
import evChargerImage from '../assets/devices/ev-charger.jpg';

interface Device {
  name: string;
  subtitle: string;
  image: string;
}

const DEVICES: Device[] = [
  { name: 'Solceller', subtitle: 'Perific One', image: solarPanelsImage },
  { name: 'Batteri', subtitle: 'Growatt', image: batteryImage },
  { name: 'Växelriktare', subtitle: 'Growatt', image: inverterImage },
  { name: 'Nibe F750', subtitle: 'Värmepump', image: heatPumpImage },
  { name: 'Elbil', subtitle: 'Kia', image: evImage },
  { name: 'Laddbox', subtitle: 'Zaptec', image: evChargerImage },
];

export default function DeviceGallery() {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
      {DEVICES.map((device) => (
        <div
          key={device.name}
          className="flex flex-col items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2"
        >
          <img
            src={device.image}
            alt={device.name}
            className="h-16 w-16 sm:h-20 sm:w-20 rounded-md object-contain bg-white"
          />
          <p className="text-xs font-medium text-gray-900 dark:text-gray-100 text-center leading-tight">
            {device.name}
          </p>
          <p className="text-[11px] text-gray-500 dark:text-gray-400 text-center leading-tight">
            {device.subtitle}
          </p>
        </div>
      ))}
    </div>
  );
}
