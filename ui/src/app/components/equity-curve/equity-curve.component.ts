import {
  Component,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration, ChartData } from 'chart.js';
import { Subscription, forkJoin } from 'rxjs';
import { distinctUntilChanged, skip } from 'rxjs/operators';

import { TradierService, HistoricalBalances } from '../../services/tradier.service';
import { StrategyService, ClosedTrade } from '../../services/strategy.service';
import { SystemService } from '../../services/system.service';
import { ThemeService } from '../../services/theme.service';
import { RangeId, etDateKey, resolveRange } from '../../models/date-range';

/**
 * The account's equity curve, in the two flavours the data actually supports.
 *
 * This is the Performance page's chart lifted into a component so the Overview
 * shows the same curve rather than a second, subtly different one. The two
 * modes plot DIFFERENT QUANTITIES and the caption has to say which:
 *
 *   intraday  — cumulative realized P&L from our own fills, plotted at fill
 *               time. Tradier's balance history is nightly-only and its dates
 *               carry no time (docs/tradier/accounts/balance_overtime.md), so
 *               there is no intraday account value to plot. Excludes unrealized
 *               P&L on anything still open.
 *   daily     — account value per day, straight from the broker.
 *
 * Conflating the two would let a day with an open winner read as flat, so the
 * subtitle is not decoration.
 */
@Component({
  selector: 'app-equity-curve',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonToggleModule,
    MatIconModule,
    MatProgressSpinnerModule,
    BaseChartDirective,
  ],
  templateUrl: './equity-curve.component.html',
  styleUrls: ['./equity-curve.component.scss'],
})
export class EquityCurveComponent implements OnInit, OnChanges, OnDestroy {
  /** Which range to plot. Changing it refetches. */
  @Input() rangeId: RangeId = 'DAY';

  /** Ranges offered by the built-in toggle. Empty array hides the toggle and
   *  pins the chart to `rangeId` — for hosts that own the range themselves. */
  @Input() selectableRanges: RangeId[] = ['DAY', 'WEEK', 'MONTH'];

  /** Chart height in px. The Overview card is shorter than Performance's. */
  @Input() height = 260;

  private tradier = inject(TradierService);
  private strategies = inject(StrategyService);
  private systemService = inject(SystemService);
  private themeService = inject(ThemeService);
  private settingsSub?: Subscription;

  activeRange = signal<RangeId>('DAY');
  loading = signal(false);
  error = signal<string | null>(null);

  private history = signal<HistoricalBalances | null>(null);
  private closed = signal<ClosedTrade[]>([]);

  /**
   * Bumped on every load so `range` re-resolves against the current clock.
   *
   * Without this the computed caches on `activeRange` alone and its `end` bound
   * stays frozen at whenever the component was first rendered — on the Overview,
   * which sits open all session, every fill after page load would then land
   * outside the window and silently vanish from the curve.
   */
  private resolvedAt = signal(0);

  /** Resolved bounds for the range on screen. */
  range = computed(() => {
    this.resolvedAt();
    return resolveRange(this.activeRange());
  });

  /** Plain method, not a computed: `selectableRanges` is a decorator input and
   *  is not a signal, so a computed would never see it change. */
  rangeButtons(): { id: RangeId; label: string }[] {
    return this.selectableRanges.map(id => ({ id, label: RANGE_LABELS[id] ?? id }));
  }

  chartType: ChartConfiguration<'line'>['type'] = 'line';
  chartData = signal<ChartData<'line'>>({ labels: [], datasets: [] });
  chartOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: ctx => ` ${this.fmtCurrency(ctx.parsed.y ?? 0)}`,
        },
      },
    },
    scales: {
      x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 6 } },
      y: { ticks: { callback: v => this.fmtCurrencyShort(Number(v)) } },
    },
    elements: {
      point: { radius: 0, hoverRadius: 4 },
      line: { tension: 0.25, borderWidth: 2 },
    },
  };

  constructor() {
    // Recolor live when the user toggles theme or colorblind mode. Chart.js
    // takes JS colour values, so it cannot pick up the CSS token change itself.
    effect(() => {
      this.themeService.chartColors();
      this.rebuild();
    });
  }

  ngOnInit(): void {
    this.activeRange.set(this.rangeId);
    this.load();
    // Switching environment or paper/live points at a different account, so the
    // curve has to be refetched rather than relabelled.
    this.settingsSub = this.systemService.settings$
      .pipe(
        skip(1),
        distinctUntilChanged((a, b) =>
          a?.environment === b?.environment && a?.trading_mode === b?.trading_mode,
        ),
      )
      .subscribe(s => {
        if (s) this.load();
      });
  }

  ngOnChanges(): void {
    if (this.rangeId !== this.activeRange()) {
      this.activeRange.set(this.rangeId);
      this.load();
    }
  }

  ngOnDestroy(): void {
    this.settingsSub?.unsubscribe();
  }

  selectRange(id: RangeId): void {
    if (id === this.activeRange()) return;
    this.activeRange.set(id);
    this.load();
  }

  /** Both sources every time: the range decides which one is plotted, and a
   *  range switch must not leave the other one holding stale data. */
  load(): void {
    this.resolvedAt.update(n => n + 1);
    const range = this.range();
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      history: this.tradier.getHistoricalBalances(range.brokerPeriod),
      closed: this.strategies.getClosedTrades(range),
    }).subscribe({
      next: ({ history, closed }) => {
        this.history.set(history);
        this.closed.set(closed || []);
        this.rebuild();
        this.loading.set(false);
      },
      error: err => {
        console.error('Failed to load equity curve:', err);
        this.error.set(err?.error?.detail || 'Unable to load the equity curve.');
        this.loading.set(false);
      },
    });
  }

  title(): string {
    return this.range().intraday ? 'Realized P&L' : 'Account Value';
  }

  subtitle(): string {
    return this.range().intraday
      ? 'Cumulative realized P&L from your own fills, at fill time. Excludes open positions.'
      : 'Daily account value from the broker.';
  }

  hasData(): boolean {
    return (this.chartData().labels?.length || 0) > 0;
  }

  /** Net change across the plotted series — the figure the card headlines. */
  delta = computed(() => {
    const values = (this.chartData().datasets?.[0]?.data ?? []) as number[];
    if (values.length === 0) return 0;
    return (values[values.length - 1] ?? 0) - (values[0] ?? 0);
  });

  private rebuild(): void {
    if (this.range().intraday) this.rebuildIntraday();
    else this.rebuildDaily();
  }

  private rebuildDaily(): void {
    // Tradier only takes its own coarse buckets, so the response reaches back
    // further than asked for. Trim it to the range actually selected.
    const start = this.range().start;
    const fromKey = start ? etDateKey(start) : null;
    const points = (this.history()?.balances ?? []).filter(
      p => !fromKey || (p.date || '') >= fromKey,
    );
    const values = points.map(p => p.value);
    const palette = this.themeService.chartColors();
    const up = values.length > 0 ? values[values.length - 1] >= values[0] : true;
    const stroke = up ? palette.profit : palette.loss;
    this.chartData.set({
      labels: points.map(p => this.fmtDate(p.date)),
      datasets: [
        {
          data: values,
          label: 'Equity',
          borderColor: stroke,
          backgroundColor: up ? palette.profitFill : palette.lossFill,
          fill: 'origin',
          pointBackgroundColor: stroke,
        },
      ],
    });
  }

  private rebuildIntraday(): void {
    const { start, end } = this.range();
    // The API scopes to the range already; this is belt-and-braces for the gap
    // between a range change and its response landing.
    const fills = this.closed()
      .map(p => ({ at: new Date(p.close_date), pnl: p.net_pnl ?? p.gain_loss ?? 0 }))
      .filter(f => !isNaN(f.at.getTime()) && (!start || (f.at >= start && f.at < end)))
      .sort((a, b) => a.at.getTime() - b.at.getTime());

    if (fills.length === 0) {
      this.chartData.set({ labels: [], datasets: [] });
      return;
    }

    // Anchor at zero from the session's start so the first fill reads as a move
    // off the flat line rather than as the starting level.
    const labels: string[] = [start ? this.fmtTime(start) : 'Open'];
    const values: number[] = [0];
    let cum = 0;
    for (const f of fills) {
      cum += f.pnl;
      labels.push(this.fmtTime(f.at));
      values.push(Number(cum.toFixed(2)));
    }

    const palette = this.themeService.chartColors();
    const up = cum >= 0;
    const stroke = up ? palette.profit : palette.loss;
    this.chartData.set({
      labels,
      datasets: [
        {
          data: values,
          label: 'Realized P&L',
          borderColor: stroke,
          backgroundColor: up ? palette.profitFill : palette.lossFill,
          fill: 'origin',
          pointBackgroundColor: stroke,
          pointRadius: values.length > 40 ? 0 : 2,
          // Realized P&L is a step function: it does not move between exits, it
          // jumps at one. Smoothing would draw drift that never happened.
          // 'before' holds the running total until the next fill; 'after' would
          // show a trade's P&L as if it existed before the trade closed.
          stepped: 'before',
          tension: 0,
        },
      ],
    });
  }

  fmtCurrency(value: number): string {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value || 0);
  }

  fmtSignedCurrency(value: number): string {
    const sign = value > 0 ? '+' : value < 0 ? '−' : '';
    return `${sign}${this.fmtCurrency(Math.abs(value))}`;
  }

  private fmtCurrencyShort(value: number): string {
    const abs = Math.abs(value);
    if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
    return `$${value.toFixed(0)}`;
  }

  private fmtDate(d: string): string {
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  /** Fill time on an Eastern wall clock — a session is read in market time. */
  private fmtTime(d: Date): string {
    return d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
    });
  }
}

const RANGE_LABELS: Partial<Record<RangeId, string>> = {
  DAY: '1D',
  WEEK: '1W',
  MTD: 'MTD',
  MONTH: '1M',
  QTD: 'QTD',
  MONTH_3: '3M',
  MONTH_6: '6M',
  YTD: 'YTD',
  YEAR: '1Y',
  ALL: 'All',
};
