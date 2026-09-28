import { DollarSign } from 'lucide-react';
import { useNibeSavings } from '../hooks/useNibeSavings';

// Dashboard-compaction phase (2026-09-28): the full breakdown behind
// CompactStatusRow's compact "kr idag" figure — see core/nibe/savings.py's
// module docstring for the full methodology and why this is a MODEL, not a
// measurement. Every number here is labeled accordingly; this is the one
// place the model's own assumptions (heat-loss coefficient, assumed COP)
// are shown, so Håkan can judge how much to trust the headline figure.
export default function NibeSavingsCard() {
  const {
    totalSavingsKr,
    totalAvoidedKwh,
    activeHours,
    heatLossCoefficientKwPerC,
    assumedCop,
    error,
  } = useNibeSavings();

  return (
    <div className="border rounded-lg p-4 border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-2">
        <DollarSign className="h-4 w-4 mr-1.5" />
        Uppskattad besparing idag — sänkt värme vid dyra timmar
      </div>
      <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">
        {totalSavingsKr.toFixed(1)}{' '}
        <span className="text-sm font-normal text-gray-500 dark:text-gray-400">kr</span>
      </div>
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
        {activeHours} timme{activeHours !== 1 ? 'r' : ''} med sänkt kurvoffset idag · ~
        {totalAvoidedKwh.toFixed(2)} kWh uppskattat undviken förbrukning (modell)
      </div>
      {heatLossCoefficientKwPerC !== null && assumedCop !== null && (
        <div className="text-xs text-gray-400 dark:text-gray-500 mt-2">
          Modellantaganden: {heatLossCoefficientKwPerC} kW/°C värmeförlust, antagen COP{' '}
          {assumedCop} — inte uppmätta värden för just denna installation. Räknar bara den
          aktiva sänkningen vid dyra timmar, inte boost-spakarna (sol/billigt pris/
          pristopp-förvärmning) som flyttar förbrukning i tiden snarare än minskar den.
          Gäller idag så här långt, inte ett rullande dygn.
        </div>
      )}
      {error && (
        <div className="text-xs text-red-500 dark:text-red-400 mt-2">
          Kunde inte nå API:t: {error}
        </div>
      )}
    </div>
  );
}
