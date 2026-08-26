/**
 * Reporting date ranges — the single source of truth.
 *
 * Before this existed, a "period" was defined in four places that had to agree:
 * the `BalancePeriod` union, the performance page's `periods` array, its
 * `periodCutoff()` switch, and `_period_cutoff()` on the API. Adding "6M" meant
 * editing all four. Here a preset is one row in `RANGE_PRESETS`, and everything
 * else — the buttons, the API query, the client-side filtering, the broker
 * bucket — is derived from the resolved `{start, end}`.
 *
 * Boundaries are anchored to **Eastern time**, not the viewer's timezone: a
 * trading day, month or year is defined by the market's calendar. A viewer in
 * Los Angeles asking for "today" means today's *session*, not midnight Pacific.
 */

/** Tradier's historical-balances buckets. This is the broker's enum verbatim —
 *  see docs/tradier/accounts/balance_overtime.md. There is deliberately no DAY:
 *  the endpoint has no intraday bucket and 400s if you ask for one. */
export type BalancePeriod = 'WEEK' | 'MONTH' | 'YTD' | 'YEAR' | 'YEAR_3' | 'YEAR_5' | 'ALL';

export type RangeId =
  | 'DAY'
  | 'WEEK'
  | 'MTD'
  | 'MONTH'
  | 'QTD'
  | 'MONTH_3'
  | 'MONTH_6'
  | 'YTD'
  | 'YEAR'
  | 'YEAR_3'
  | 'YEAR_5'
  | 'ALL'
  | 'CUSTOM';

export interface RangePreset {
  id: RangeId;
  /** Terse label for the inline segmented control. */
  label: string;
  /** Fuller wording for the overflow menu. */
  title: string;
  /** Shown as one of the always-visible quick buttons. */
  quick: boolean;
  /** Lower bound, or null for "everything". */
  start: (now: Date) => Date | null;
}

const MS_DAY = 86_400_000;
const ET = 'America/New_York';

// -----------------------------------------------------------------------------
// Eastern-time helpers
// -----------------------------------------------------------------------------

/** Milliseconds that `tz` is ahead of UTC at the given instant (DST-aware). */
function tzOffsetMs(at: Date, tz: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(at);

  const f: Record<string, number> = {};
  for (const p of parts) if (p.type !== 'literal') f[p.type] = Number(p.value);
  // `hour` comes back as 24 for midnight under hour12:false in some engines.
  const asUtc = Date.UTC(f['year'], f['month'] - 1, f['day'], f['hour'] % 24, f['minute'], f['second']);
  return asUtc - at.getTime();
}

/**
 * The UTC instant corresponding to a wall-clock time in `tz`.
 *
 * Two passes: guess by treating the wall time as UTC, measure the zone's offset
 * near that guess, correct, then re-measure in case the correction stepped
 * across a DST transition.
 */
function zonedToUtc(y: number, month1: number, d: number, tz: string): Date {
  const guess = Date.UTC(y, month1 - 1, d, 0, 0, 0);
  const firstPass = new Date(guess - tzOffsetMs(new Date(guess), tz));
  return new Date(guess - tzOffsetMs(firstPass, tz));
}

/** The Y/M/D showing on an Eastern-time wall clock at the given instant. */
function etParts(at: Date): { y: number; m: number; d: number } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: ET,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(at);
  const f: Record<string, number> = {};
  for (const p of parts) if (p.type !== 'literal') f[p.type] = Number(p.value);
  return { y: f['year'], m: f['month'], d: f['day'] };
}

/** Midnight ET on the day in progress. */
export function etDayStart(now: Date): Date {
  const { y, m, d } = etParts(now);
  return zonedToUtc(y, m, d, ET);
}

/** Midnight ET on the 1st of the current month. */
export function etMonthStart(now: Date): Date {
  const { y, m } = etParts(now);
  return zonedToUtc(y, m, 1, ET);
}

/** Midnight ET on the 1st of the current calendar quarter. */
export function etQuarterStart(now: Date): Date {
  const { y, m } = etParts(now);
  return zonedToUtc(y, m - ((m - 1) % 3), 1, ET);
}

/** Midnight ET on January 1st of the current year. */
export function etYearStart(now: Date): Date {
  const { y } = etParts(now);
  return zonedToUtc(y, 1, 1, ET);
}

/** `YYYY-MM-DD` as it reads on an Eastern wall clock. Matches the date-only
 *  keys Tradier returns in historical-balances. */
export function etDateKey(at: Date): string {
  const { y, m, d } = etParts(at);
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

const backDays = (n: number) => (now: Date) => new Date(now.getTime() - n * MS_DAY);

// -----------------------------------------------------------------------------
// Presets
// -----------------------------------------------------------------------------

/**
 * Adding a range is one row here. `quick: true` puts it in the inline segmented
 * control; everything else lands in the overflow menu, in this order.
 */
export const RANGE_PRESETS: RangePreset[] = [
  { id: 'DAY', label: '1D', title: 'Today', quick: true, start: etDayStart },
  { id: 'WEEK', label: '1W', title: 'Last 7 days', quick: true, start: backDays(7) },
  { id: 'MTD', label: 'MTD', title: 'Month to date', quick: false, start: etMonthStart },
  { id: 'MONTH', label: '1M', title: 'Last 30 days', quick: true, start: backDays(30) },
  { id: 'QTD', label: 'QTD', title: 'Quarter to date', quick: false, start: etQuarterStart },
  { id: 'MONTH_3', label: '3M', title: 'Last 3 months', quick: false, start: backDays(90) },
  { id: 'MONTH_6', label: '6M', title: 'Last 6 months', quick: false, start: backDays(180) },
  { id: 'YTD', label: 'YTD', title: 'Year to date', quick: true, start: etYearStart },
  { id: 'YEAR', label: '1Y', title: 'Last 12 months', quick: false, start: backDays(365) },
  { id: 'YEAR_3', label: '3Y', title: 'Last 3 years', quick: false, start: backDays(365 * 3) },
  { id: 'YEAR_5', label: '5Y', title: 'Last 5 years', quick: false, start: backDays(365 * 5) },
  { id: 'ALL', label: 'All', title: 'All time', quick: true, start: () => null },
];

export const QUICK_PRESETS = RANGE_PRESETS.filter(p => p.quick);
export const MENU_PRESETS = RANGE_PRESETS.filter(p => !p.quick);

// -----------------------------------------------------------------------------
// Resolution
// -----------------------------------------------------------------------------

export interface ResolvedRange {
  id: RangeId;
  /** Human label for the header and chart caption. */
  label: string;
  /**
   * Compact label for embedding in metric-tile headings. A custom range's full
   * "2026-07-27 → 2026-08-26" wraps a tile heading onto three lines and knocks
   * the row out of alignment, so tiles get this instead.
   */
  shortLabel: string;
  /** Inclusive lower bound; null means unbounded. */
  start: Date | null;
  /** Exclusive upper bound. */
  end: Date;
  /**
   * The range covers roughly a single session, so per-trade timestamps are
   * meaningful and the equity chart switches to an intraday realized-P&L curve.
   */
  intraday: boolean;
  /**
   * Narrowest Tradier bucket that still *covers* the range. Its daily bars get
   * sliced down to `start` afterwards — the broker cannot filter for us.
   */
  brokerPeriod: BalancePeriod;
}

/** Narrowest broker bucket that covers back to `start`. */
export function brokerPeriodFor(start: Date | null, now: Date): BalancePeriod {
  if (!start) return 'ALL';
  const days = (now.getTime() - start.getTime()) / MS_DAY;
  // YTD is skipped deliberately: YEAR always covers at least as much, and we
  // slice client-side anyway, so one fewer bucket to reason about.
  if (days <= 7) return 'WEEK';
  if (days <= 30) return 'MONTH';
  if (days <= 365) return 'YEAR';
  if (days <= 365 * 3) return 'YEAR_3';
  if (days <= 365 * 5) return 'YEAR_5';
  return 'ALL';
}

/** A range spanning no more than this is treated as intraday. */
const INTRADAY_MAX_MS = 36 * 3600_000;

export function resolveRange(
  id: RangeId,
  custom?: { start: Date; end: Date } | null,
  now: Date = new Date(),
): ResolvedRange {
  if (id === 'CUSTOM') {
    if (!custom) return resolveRange('MONTH', null, now);
    // The picker yields dates, not instants; take the whole of the end day so a
    // same-day start/end selects that session rather than an empty window.
    const start = custom.start;
    const end = new Date(custom.end.getTime() + MS_DAY);
    return {
      id,
      label: `${etDateKey(start)} → ${etDateKey(custom.end)}`,
      shortLabel: 'custom range',
      start,
      end,
      intraday: end.getTime() - start.getTime() <= INTRADAY_MAX_MS,
      brokerPeriod: brokerPeriodFor(start, now),
    };
  }

  const preset = RANGE_PRESETS.find(p => p.id === id) ?? RANGE_PRESETS[3];
  const start = preset.start(now);
  return {
    id: preset.id,
    label: preset.title,
    shortLabel: preset.title,
    start,
    end: now,
    intraday: !!start && now.getTime() - start.getTime() <= INTRADAY_MAX_MS,
    brokerPeriod: brokerPeriodFor(start, now),
  };
}
