// Swedish labels/colors for every status value core/nibe/decision.py's
// decide_heating_boost() and decide_dhw_luxury() can return, shared by
// NibeStatusCard.tsx and NibeLiveCard.tsx so there is exactly one place to
// keep this in sync with decision.py.
//
// HISTORY: NibeStatusCard.tsx originally kept its own copy of these two
// maps, written for Fas 4a/4b and never updated as Fas 4c/4d/4e added five
// more status values (engaged_price_spike_ahead, reduced_expensive_price,
// blocked_low_degree_minutes, suppressed_anti_flap,
// forced_normal_legionella_guard) — an unknown status still rendered fine
// (both call sites fall back to the raw status string via `?? status`),
// but with the English decision.py identifier instead of a Swedish label.
// Pulled out into its own module 2026-09-28 when building the "Nibe drift"
// page, which needed the same maps, so the fix lands in one place instead
// of two copies drifting again.

export type HeatingStatus =
  | 'no_data'
  | 'no_headroom'
  | 'blocked_low_degree_minutes'
  | 'engaged_cheap_price'
  | 'engaged_solar_surplus'
  | 'engaged_price_spike_ahead'
  | 'reduced_expensive_price'
  | 'suppressed_anti_flap'
  | 'normal'
  | 'watchdog_reset';

export type DhwStatus =
  | 'disabled'
  | 'no_headroom'
  | 'luxury_cheap_price'
  | 'luxury_solar_surplus'
  | 'economy_no_condition'
  | 'forced_normal_legionella_guard';

export type StatusColor = 'blue' | 'green' | 'yellow' | 'red' | 'purple';

export const HEATING_STATUS_LABELS: Record<HeatingStatus, string> = {
  no_data: 'Ingen data',
  no_headroom: 'Normalläge — effektvakten saknar utrymme',
  blocked_low_degree_minutes: 'Normalläge — gradminutsgolv når (eltillsatsrisk)',
  engaged_cheap_price: 'Extra värme — billig timme',
  engaged_solar_surplus: 'Extra värme — solöverskott',
  engaged_price_spike_ahead: 'Extra värme — förvärmer inför kommande prisspik',
  reduced_expensive_price: 'Sänkt värme — dyr timme',
  suppressed_anti_flap: 'Håller kvar föregående läge (anti-flap, nyss ändrad)',
  normal: 'Normalläge',
  watchdog_reset: 'Säkerhetsåterställd till normalläge — ingen kontakt med pumpen på länge',
};

export const HEATING_STATUS_COLORS: Record<HeatingStatus, StatusColor> = {
  no_data: 'red',
  no_headroom: 'yellow',
  blocked_low_degree_minutes: 'yellow',
  engaged_cheap_price: 'green',
  engaged_solar_surplus: 'green',
  engaged_price_spike_ahead: 'green',
  reduced_expensive_price: 'blue',
  suppressed_anti_flap: 'blue',
  normal: 'blue',
  watchdog_reset: 'red',
};

export const DHW_STATUS_LABELS: Record<DhwStatus, string> = {
  disabled: 'Av',
  no_headroom: 'Ekonomi — effektvakten saknar utrymme',
  luxury_cheap_price: 'Lyxläge — billig timme',
  luxury_solar_surplus: 'Lyxläge — solöverskott',
  economy_no_condition: 'Ekonomi',
  forced_normal_legionella_guard: 'Normal — legionellaskydd (Ekonomi för länge sammanhängande)',
};

export const DHW_STATUS_COLORS: Record<DhwStatus, StatusColor> = {
  disabled: 'blue',
  no_headroom: 'yellow',
  luxury_cheap_price: 'green',
  luxury_solar_surplus: 'green',
  economy_no_condition: 'blue',
  forced_normal_legionella_guard: 'yellow',
};

export function heatingStatusLabel(status: string | null): string {
  if (status === null) return 'Väntar på första mätningen…';
  return HEATING_STATUS_LABELS[status as HeatingStatus] ?? status;
}

export function heatingStatusColor(status: string | null): StatusColor {
  if (status === null) return 'blue';
  return HEATING_STATUS_COLORS[status as HeatingStatus] ?? 'blue';
}

export function dhwStatusLabel(status: string | null): string {
  if (status === null) return 'Väntar på första mätningen…';
  return DHW_STATUS_LABELS[status as DhwStatus] ?? status;
}

export function dhwStatusColor(status: string | null): StatusColor {
  if (status === null) return 'blue';
  return DHW_STATUS_COLORS[status as DhwStatus] ?? 'blue';
}
