import React from 'react';
import {
  Battery,
  BatteryCharging,
  Car,
  Flame,
  Gauge,
  RefreshCw,
  Zap,
} from 'lucide-react';
import { useHardwareInfo } from '../hooks/useHardwareInfo';

// "Info om hårdvara" (2026-10-13), built at Håkan's direct request: one
// place listing identification info (serial numbers, firmware/model
// versions, VIN, MAC) for every physical product in this installation —
// useful the next time something needs a serial number for a support
// ticket or a warranty claim, without hunting through Home Assistant's
// own device pages. One fetch on mount via useHardwareInfo (no polling —
// this data essentially never changes during a session), with a manual
// "Uppdatera" button for the rare case something changed (a firmware
// update, a new battery module).
//
// Same "never fabricate a value" convention as every other page here:
// any field whose value is null renders as a muted "Ej tillgänglig",
// never blank and never a guessed placeholder — see
// core/hardware_info.py's own docstring for why each field can be null.

function formatValue(value: string | null | undefined): React.ReactNode {
  if (value === null || value === undefined || value === '') {
    return <span className="text-gray-400 dark:text-gray-500 italic">Ej tillgänglig</span>;
  }
  return value;
}

interface InfoRowProps {
  label: string;
  value: string | null | undefined;
}

function InfoRow({ label, value }: InfoRowProps) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 border-b border-gray-100 dark:border-gray-700/50 last:border-0">
      <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
      <span className="text-sm font-medium text-gray-900 dark:text-gray-100 text-right">
        {formatValue(value)}
      </span>
    </div>
  );
}

interface ProductCardProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}

function ProductCard({ icon: Icon, title, children }: ProductCardProps) {
  return (
    <div className="border rounded-lg p-4 border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-center text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">
        <Icon className="h-4 w-4 mr-1.5 text-gray-500 dark:text-gray-400" />
        {title}
      </div>
      <div>{children}</div>
    </div>
  );
}

export default function HardwareInfoPage() {
  const { data, loading, error, refresh } = useHardwareInfo();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
          Info om hårdvara
        </h2>
        <button
          onClick={() => refresh()}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-sm text-gray-700 dark:text-gray-200 transition-colors disabled:opacity-50"
          title="Hämta om hårdvaruinformationen"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Uppdatera
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-600 dark:text-red-400">
          Kunde inte nå hårdvaru-API:t: {error}
        </div>
      )}

      {loading && !data && (
        <div className="text-sm text-gray-400 dark:text-gray-500">Hämtar hårdvaruinformation…</div>
      )}

      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <ProductCard icon={Flame} title="Nibe F750">
            <InfoRow label="Tillverkare" value={data.nibe.manufacturer} />
            <InfoRow label="Modell" value={data.nibe.model} />
            <InfoRow label="HW-version" value={data.nibe.hwVersion} />
            <InfoRow label="SW-version" value={data.nibe.swVersion} />
          </ProductCard>

          <ProductCard icon={Zap} title="Växelriktare">
            <InfoRow label="Tillverkare" value={data.inverter.manufacturer} />
            <InfoRow label="Modell" value={data.inverter.model} />
            <InfoRow label="Serienummer" value={data.inverter.serialNumber} />
            <InfoRow label="Firmware-version" value={data.inverter.firmwareVersion} />
          </ProductCard>

          <ProductCard icon={Battery} title="Batteri">
            <InfoRow label="BMS-typ" value={data.battery.bmsType} />
            <InfoRow label="Anslutna BMS-enheter" value={data.battery.bmsConnectedStatus} />
            <InfoRow label="BMS 1, serienummer" value={data.battery.bms1SerialNumber} />
            <InfoRow label="BMS 1, övervakningsversion" value={data.battery.bms1MonitoringVersion} />
            {data.battery.modules.length === 0 ? (
              <InfoRow label="Moduler" value={null} />
            ) : (
              data.battery.modules.map((module) => (
                <InfoRow
                  key={module.index}
                  label={`Modul ${module.index}, serienummer`}
                  value={module.serialNumber}
                />
              ))
            )}
          </ProductCard>

          <ProductCard icon={BatteryCharging} title="Laddare">
            <InfoRow label="Tillverkare" value={data.evCharger.manufacturer} />
            <InfoRow label="Modell" value={data.evCharger.model} />
            <InfoRow label="Enhetsnamn" value={data.evCharger.deviceName} />
            <InfoRow label="Installerad firmware-version" value={data.evCharger.installedFirmwareVersion} />
          </ProductCard>

          <ProductCard icon={Car} title="Kia EV3">
            <InfoRow label="Tillverkare" value={data.vehicle.manufacturer} />
            <InfoRow label="Modell" value={data.vehicle.model} />
            <InfoRow label="VIN-nummer" value={data.vehicle.vin} />
          </ProductCard>

          <ProductCard icon={Gauge} title="Perific One">
            <InfoRow label="Tillverkare" value={data.perificOne.manufacturer} />
            <InfoRow label="Modell" value={data.perificOne.model} />
            <InfoRow label="MAC-adress" value={data.perificOne.macAddress} />
            <InfoRow label="Item ID" value={data.perificOne.itemId} />
          </ProductCard>
        </div>
      )}
    </div>
  );
}
