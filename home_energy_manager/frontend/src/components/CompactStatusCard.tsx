import React from 'react';

// Dashboard-compaction phase (2026-09-28): a small status tile, sitting
// alongside StatusCard (SystemStatusCard.tsx) rather than replacing it —
// see claude/dashboard-compaction-and-nibe-savings-forslag.md's "Del 1" for
// the competitive-research writeup behind this shape. No single community
// HA card had a reusable "four square tiles in a row" component to copy;
// this synthesizes solar-bar-card's small icon+number "stat tile" pattern
// with the classic app-grid convention (icon, one headline number, a short
// status line) that Håkan asked for explicitly ("kvadratiska... bredvid
// varandra").
//
// Fixed 2026-09-29: the first version used `aspect-square` to get that
// squareness, but on the row's wide `sm:grid-cols-4` columns a square sized
// to the COLUMN WIDTH is very tall — the opposite of compact, and exactly
// what Håkan's screenshot showed ("Rutorna kan bli mycket kompaktare").
// Height now simply follows the content (header row + one value + one
// status line), which is what "compact" actually means here; the tiles end
// up wider than they are tall rather than perfectly square, which is the
// right trade-off against Håkan's explicit follow-up feedback.
//
// Deliberately a MUCH smaller sibling of StatusCard, not a variant/prop on
// it: a compact tile shows exactly one headline value and one status line,
// no metrics list, no headerRight controls — trying to cram StatusCard's
// full shape into a small box would fight the whole point of compacting it.
//
// Static per-color class maps, duplicated from StatusCard's own
// colorClasses/iconColorClasses rather than imported — same reasoning
// NibeLiveCard.tsx's STATUS_TEXT_CLASSES gives: Tailwind's build only picks
// up class names it can see literally in source, so sharing color logic via
// a `text-${color}-600`-style template string would silently drop those
// classes from the production CSS.
export type CompactStatusColor = 'blue' | 'green' | 'yellow' | 'red' | 'purple';

const COLOR_CLASSES: Record<CompactStatusColor, string> = {
  blue: 'bg-blue-50 border-blue-200 dark:bg-blue-900/20 dark:border-blue-800',
  green: 'bg-green-50 border-green-200 dark:bg-green-900/20 dark:border-green-800',
  red: 'bg-red-50 border-red-200 dark:bg-red-900/20 dark:border-red-800',
  yellow: 'bg-yellow-50 border-yellow-200 dark:bg-yellow-900/20 dark:border-yellow-800',
  purple: 'bg-purple-50 border-purple-200 dark:bg-purple-900/20 dark:border-purple-800',
};

const ICON_COLOR_CLASSES: Record<CompactStatusColor, string> = {
  blue: 'text-blue-600 dark:text-blue-400',
  green: 'text-green-600 dark:text-green-400',
  red: 'text-red-600 dark:text-red-400',
  yellow: 'text-yellow-600 dark:text-yellow-400',
  purple: 'text-purple-600 dark:text-purple-400',
};

export interface CompactStatusMetric {
  label: string;
  value: string;
}

export interface CompactStatusCardProps {
  title: string;
  /** A lucide icon component. Ignored when `image` is also given — see
   * `image` below. Optional only so an image-only tile doesn't have to
   * supply a throwaway icon just to satisfy the type. */
  icon?: React.ComponentType<{ className?: string }>;
  /**
   * Added 2026-10-03, Håkan's ask to put real device photos (his own,
   * not stock/manufacturer images — see frontend/src/assets/devices/'s
   * own provenance notes) directly in these tiles instead of a generic
   * lucide icon, e.g. the Perific One unit's own photo on the Perific
   * One tile. Takes over the icon's slot (same position/sizing) when
   * present, so a tile never shows both.
   */
  image?: { src: string; alt: string };
  color: CompactStatusColor;
  keyValue: string;
  keyUnit?: string;
  /** One short line under the headline value — a secondary metric or the
   * current status, never a list (see module docstring). */
  statusLine?: string;
  /** Error/no-data note, rendered in place of statusLine AND metrics when
   * present (an unreachable API means none of this tile's data is fresh). */
  annotation?: string;
  /**
   * Added 2026-09-30 for Håkan's "varje ruta bör kunna innehålla betydligt
   * mer information" ask — a couple of extra label/value facts (e.g. the
   * governor's configured target, or the EV charger's live power) that
   * don't fit the single headline+statusLine shape. Rendered as compact
   * label/value rows, capped at 2 by convention (not enforced here) to
   * keep tiles from growing tall again — see CompactStatusCard's own
   * 2026-09-29 aspect-square lesson in the module docstring above.
   */
  metrics?: CompactStatusMetric[];
}

export default function CompactStatusCard({
  title,
  icon: Icon,
  image,
  color,
  keyValue,
  keyUnit,
  statusLine,
  annotation,
  metrics,
}: CompactStatusCardProps) {
  return (
    <div className={`border rounded-lg p-2.5 flex flex-col gap-1 ${COLOR_CLASSES[color]}`}>
      <div className="flex items-center min-w-0">
        {image ? (
          <img
            src={image.src}
            alt={image.alt}
            className="h-5 w-5 rounded-sm object-cover mr-1.5 shrink-0 bg-white"
          />
        ) : Icon ? (
          <Icon className={`h-4 w-4 ${ICON_COLOR_CLASSES[color]} mr-1.5 shrink-0`} />
        ) : null}
        <h3 className="text-xs font-medium text-gray-600 dark:text-gray-400 truncate">
          {title}
        </h3>
      </div>

      <div>
        <p className="text-xl font-bold text-gray-900 dark:text-gray-100 leading-tight truncate">
          {keyValue}
          {keyUnit && (
            <span className="text-xs font-normal text-gray-600 dark:text-gray-400 ml-1">
              {keyUnit}
            </span>
          )}
        </p>
        {annotation ? (
          <p className="text-xs text-red-500 dark:text-red-400 truncate mt-0.5">{annotation}</p>
        ) : (
          <>
            {statusLine && (
              <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
                {statusLine}
              </p>
            )}
            {metrics?.map(m => (
              <p
                key={m.label}
                className="flex justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400 truncate"
              >
                <span className="truncate">{m.label}</span>
                <span className="shrink-0 font-medium text-gray-600 dark:text-gray-300">
                  {m.value}
                </span>
              </p>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
