import { Component, OnInit, OnDestroy, inject, signal, computed, effect, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule, MatTableDataSource } from '@angular/material/table';
import { MatSortModule, MatSort } from '@angular/material/sort';
import { MatPaginatorModule, MatPaginator } from '@angular/material/paginator';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { PositionChartDialogComponent } from '../positions/position-chart-dialog/position-chart-dialog.component';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError, distinctUntilChanged, skip } from 'rxjs/operators';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration, ChartData } from 'chart.js';

import {
  TradierService,
  BalancePeriod,
  ClosedPosition,
  HistoricalBalances,
  TradeEvent,
  TradierBalances,
} from '../../services/tradier.service';
import { SystemService } from '../../services/system.service';
import { ThemeService } from '../../services/theme.service';
import { StrategyService } from '../../services/strategy.service';

interface MetricCard {
  label: string;
  value: string;
  sub?: string;
  icon: string;
  tone: 'neutral' | 'positive' | 'negative';
  /** Plain-language explanation shown on hover via the card's help icon. */
  tooltip?: string;
}

interface CalendarCell {
  date: Date;
  inMonth: boolean;
  isToday: boolean;
  pl: number | null;
  trades: number;
}

@Component({
  selector: 'app-performance',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatIconModule,
    MatTableModule,
    MatSortModule,
    MatPaginatorModule,
    MatProgressSpinnerModule,
    MatDialogModule,
    MatTooltipModule,
    BaseChartDirective,
  ],
  templateUrl: './performance.component.html',
  styleUrls: ['./performance.component.scss'],
})
export class PerformanceComponent implements OnInit, OnDestroy {
  private tradier = inject(TradierService);
  private strategies = inject(StrategyService);
  private systemService = inject(SystemService);
  private dialog = inject(MatDialog);
  private themeService = inject(ThemeService);
  private settingsSub?: Subscription;

  @ViewChild(MatSort) sort?: MatSort;
  @ViewChild(MatPaginator) paginator?: MatPaginator;

  readonly periods: { value: BalancePeriod; label: string }[] = [
    { value: 'DAY', label: '1D' },
    { value: 'WEEK', label: '1W' },
    { value: 'MONTH', label: '1M' },
    { value: 'YTD', label: 'YTD' },
    { value: 'YEAR', label: '1Y' },
    { value: 'YEAR_3', label: '3Y' },
    { value: 'YEAR_5', label: '5Y' },
    { value: 'ALL', label: 'All' },
  ];

  period = signal<BalancePeriod>('MONTH');
  loading = signal(false);
  error = signal<string | null>(null);

  balances = signal<TradierBalances | null>(null);
  history = signal<HistoricalBalances | null>(null);
  closedPositions = signal<ClosedPosition[]>([]);

  // Anchored to the first of the displayed month
  calendarMonth = signal<Date>(this.startOfMonth(new Date()));
  readonly weekdayLabels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  dailyPL = computed<Map<string, { pl: number; trades: number }>>(() => {
    const map = new Map<string, { pl: number; trades: number }>();
    for (const p of this.closedPositions()) {
      const key = (p.close_date || '').slice(0, 10);
      if (!key) continue;
      const cur = map.get(key) ?? { pl: 0, trades: 0 };
      cur.pl += p.gain_loss || 0;
      cur.trades += 1;
      map.set(key, cur);
    }
    return map;
  });

  calendarCells = computed<CalendarCell[]>(() => {
    const anchor = this.calendarMonth();
    const year = anchor.getFullYear();
    const month = anchor.getMonth();
    const firstWeekday = new Date(year, month, 1).getDay();
    const start = new Date(year, month, 1 - firstWeekday);
    const today = new Date();
    const todayKey = this.toDateKey(today);
    const pl = this.dailyPL();
    const cells: CalendarCell[] = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      const key = this.toDateKey(d);
      const entry = pl.get(key);
      cells.push({
        date: d,
        inMonth: d.getMonth() === month,
        isToday: key === todayKey,
        pl: entry ? entry.pl : null,
        trades: entry ? entry.trades : 0,
      });
    }
    return cells;
  });

  calendarSummary = computed(() => {
    const anchor = this.calendarMonth();
    const year = anchor.getFullYear();
    const month = anchor.getMonth();
    let total = 0;
    let wins = 0;
    let losses = 0;
    for (const [key, v] of this.dailyPL()) {
      const [y, m] = key.split('-').map(Number);
      if (y === year && m - 1 === month) {
        total += v.pl;
        if (v.pl > 0) wins++;
        else if (v.pl < 0) losses++;
      }
    }
    return { total, wins, losses };
  });

  calendarMonthLabel = computed(() =>
    this.calendarMonth().toLocaleDateString('en-US', { month: 'long', year: 'numeric' }),
  );

  closedDataSource = new MatTableDataSource<ClosedPosition>([]);
  displayedColumns = [
    'symbol',
    'open_date',
    'close_date',
    'term',
    'quantity',
    'cost',
    'proceeds',
    'gain_loss',
    'commission',
    'fees',
    'net_pnl',
    'gain_loss_percent',
  ];

  metrics = computed<MetricCard[]>(() => {
    const b = this.balances();
    const h = this.history();
    const inPeriodClosed = this.filteredClosedForPeriod();

    const portfolioValue = b?.total_equity ?? 0;
    const delta = h?.delta ?? 0;
    const deltaPct = h?.deltaPercent ?? 0;
    const openPL = b?.open_pl ?? 0;
    const realizedPL = inPeriodClosed.reduce((s, p) => s + (p.gain_loss || 0), 0);
    const periodCommission = inPeriodClosed.reduce((s, p) => s + (p.commission || 0), 0);
    const periodFees = inPeriodClosed.reduce((s, p) => s + (p.fees || 0), 0);
    const periodCosts = periodCommission + periodFees;
    const netPL = realizedPL - periodCosts;
    const wins = inPeriodClosed.filter(p => p.gain_loss > 0).length;
    const losses = inPeriodClosed.filter(p => p.gain_loss < 0).length;
    const totalTrades = inPeriodClosed.length;
    const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;

    // Calculate Sharpe Ratio (using per-trade percentage returns)
    // For each trade: return% = (net_pnl / cost) * 100
    const returns: number[] = [];
    for (const p of inPeriodClosed) {
      const cost = Math.abs(p.cost || 0);
      // Skip trades with zero cost (data quality issues)
      if (cost < 0.01) continue;

      const pnl = p.net_pnl ?? p.gain_loss ?? 0;
      const returnPct = (pnl / cost) * 100;
      returns.push(returnPct);
    }

    let sharpeRatio: number | null = null;
    let sharpeLabel = 'N/A';
    let sharpeQuality = '';

    if (returns.length > 1) {
      const meanReturn = returns.reduce((sum, val) => sum + val, 0) / returns.length;
      const variance = returns.reduce((sum, val) => sum + Math.pow(val - meanReturn, 2), 0) / returns.length;
      const stdDevReturn = Math.sqrt(variance);

      if (stdDevReturn > 0) {
        sharpeRatio = meanReturn / stdDevReturn;
        sharpeLabel = sharpeRatio.toFixed(2);

        // Quality indicator
        if (sharpeRatio >= 3.0) sharpeQuality = 'Excellent';
        else if (sharpeRatio >= 2.0) sharpeQuality = 'Very Good';
        else if (sharpeRatio >= 1.0) sharpeQuality = 'Good';
        else if (sharpeRatio >= 0) sharpeQuality = 'Poor';
        else sharpeQuality = 'Negative';
      }
    }

    const tone = (n: number): 'positive' | 'negative' | 'neutral' =>
      n > 0 ? 'positive' : n < 0 ? 'negative' : 'neutral';

    const sharpeTone = (): 'positive' | 'negative' | 'neutral' => {
      if (sharpeRatio === null) return 'neutral';
      if (sharpeRatio >= 2.0) return 'positive';
      if (sharpeRatio >= 1.0) return 'neutral';
      return 'negative';
    };

    return [
      {
        label: 'Portfolio Value',
        value: this.fmtCurrency(portfolioValue),
        sub: b ? `Cash ${this.fmtCurrency(b.total_cash ?? 0)}` : undefined,
        icon: 'account_balance_wallet',
        tone: 'neutral',
        tooltip:
          'Total account value right now: the market value of your open positions ' +
          'plus available cash.',
      },
      {
        label: `${this.periodLabel()} Change`,
        value: `${delta >= 0 ? '+' : ''}${this.fmtCurrency(delta)}`,
        sub: `${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(2)}%`,
        icon: delta >= 0 ? 'trending_up' : 'trending_down',
        tone: tone(delta),
        tooltip:
          'How much your total account value moved over the selected period, ' +
          'in dollars and percent. Includes both realized and unrealized changes.',
      },
      {
        label: 'Open P&L',
        value: `${openPL >= 0 ? '+' : ''}${this.fmtCurrency(openPL)}`,
        icon: 'show_chart',
        tone: tone(openPL),
        tooltip:
          'Unrealized profit/loss on positions you still hold. It moves with the ' +
          "market and isn't locked in until you close the position.",
      },
      {
        label: `Realized P&L (${this.periodLabel()})`,
        value: `${realizedPL >= 0 ? '+' : ''}${this.fmtCurrency(realizedPL)}`,
        sub: `${totalTrades} trade${totalTrades === 1 ? '' : 's'}`,
        icon: 'attach_money',
        tone: tone(realizedPL),
        tooltip:
          'Actual profit/loss from positions you closed during this period, ' +
          'before commissions and fees are subtracted.',
      },
      {
        label: `Net P&L (${this.periodLabel()})`,
        value: `${netPL >= 0 ? '+' : ''}${this.fmtCurrency(netPL)}`,
        sub: `After ${this.fmtCurrency(periodCosts)} costs`,
        icon: 'request_quote',
        tone: tone(netPL),
        tooltip:
          'Realized P&L after subtracting commissions and fees — your true ' +
          'take-home result for the period.',
      },
      {
        label: 'Costs (Commission + Fees)',
        value: this.fmtCurrency(periodCosts),
        sub: `${this.fmtCurrency(periodCommission)} comm + ${this.fmtCurrency(periodFees)} fees`,
        icon: 'receipt_long',
        tone: 'neutral',
        tooltip:
          'Total trading costs for the period: broker commissions plus exchange ' +
          'and regulatory fees. These are already deducted from Net P&L.',
      },
      {
        label: 'Win Rate',
        value: `${winRate.toFixed(1)}%`,
        sub: `${wins}W / ${losses}L`,
        icon: 'check_circle',
        tone: 'neutral',
        tooltip:
          'Percentage of closed trades that were profitable.\n\n' +
          'Read it alongside average win vs. loss size — a high win rate can ' +
          'still lose money if the occasional loss is large, and a low win rate ' +
          'can still profit if wins are big.',
      },
      {
        label: 'Sharpe Ratio',
        value: sharpeLabel,
        sub: sharpeQuality || `Risk-adjusted return`,
        icon: 'insights',
        tone: sharpeTone(),
        tooltip:
          'Risk-adjusted return: average trade return divided by how much your ' +
          'returns vary (volatility). Higher means more consistent gains per unit ' +
          'of risk taken.\n\n' +
          'Below 0: Negative — losing on average\n' +
          '0 to 1: Poor\n' +
          '1 to 2: Good\n' +
          '2 to 3: Very Good\n' +
          '3+: Excellent\n\n' +
          'Computed from this period’s per-trade returns (net P&L ÷ cost); ' +
          'no risk-free rate assumed. Needs at least 2 closed trades.',
      },
    ];
  });

  // Equity-curve chart config
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
      x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
      y: {
        ticks: {
          callback: v => this.fmtCurrencyShort(Number(v)),
        },
      },
    },
    elements: {
      point: { radius: 0, hoverRadius: 4 },
      line: { tension: 0.25, borderWidth: 2 },
    },
  };

  constructor() {
    // Rebuild equity chart when theme/colorblind mode changes so colors update live
    effect(() => {
      this.themeService.chartColors();
      if (this.history()) this.rebuildChart();
    });
  }

  ngOnInit(): void {
    this.loadAll();
    this.settingsSub = this.systemService.settings$
      .pipe(
        skip(1),
        distinctUntilChanged((a, b) =>
          a?.environment === b?.environment && a?.trading_mode === b?.trading_mode,
        ),
      )
      .subscribe(s => {
        if (s) this.loadAll();
      });
  }

  ngOnDestroy(): void {
    this.settingsSub?.unsubscribe();
  }

  onPeriodChange(p: BalancePeriod): void {
    if (p === this.period()) return;
    this.period.set(p);
    this.loadHistory();
  }

  refresh(): void {
    this.loadAll();
  }

  openChart(row: ClosedPosition): void {
    const qty = row.quantity || 1;
    // Options are quoted per-share but trade in 100-share contracts, so cost/proceeds
    // need an extra /100 to match the per-share premium the history endpoint returns.
    const multiplier = this.isOptionSymbol(row.symbol) ? 100 : 1;
    const denom = qty !== 0 ? qty * multiplier : multiplier;
    const entryPerShare = row.cost / denom;
    const exitPerShare = row.proceeds / denom;

    // Look up the actual trade execution timestamps via the history endpoint —
    // gainloss only carries date precision, so intraday markers can be off.
    const start = (row.open_date || '').slice(0, 10);
    const end = (row.close_date || '').slice(0, 10);

    this.tradier.getTradeEvents(row.symbol, start, end).subscribe({
      next: (events) => {
        const { open_time, close_time } = this.pickOpenCloseTimes(events);
        this.launchChart(row, entryPerShare, exitPerShare, open_time, close_time);
      },
      error: () => {
        // Sandbox or any failure — open with date-only precision
        this.launchChart(row, entryPerShare, exitPerShare);
      },
    });
  }

  private pickOpenCloseTimes(events: TradeEvent[]): { open_time?: string; close_time?: string } {
    if (!events || events.length === 0) return {};
    const sorted = [...events]
      .filter((e) => e && e.date)
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    if (sorted.length === 0) return {};
    if (sorted.length === 1) return { open_time: sorted[0].date };
    return { open_time: sorted[0].date, close_time: sorted[sorted.length - 1].date };
  }

  private launchChart(
    row: ClosedPosition,
    entryPerShare: number,
    exitPerShare: number,
    open_time?: string,
    close_time?: string,
  ): void {
    this.dialog.open(PositionChartDialogComponent, {
      data: {
        symbol: row.symbol,
        avg_entry_price: entryPerShare,
        date_acquired: row.open_date,
        qty: row.quantity,
        close_date: row.close_date,
        exit_price: exitPerShare,
        open_time,
        close_time,
      },
      panelClass: 'position-chart-panel',
      autoFocus: false,
    });
  }

  private isOptionSymbol(symbol: string): boolean {
    // OCC option symbol: ROOT + YYMMDD + C/P + 8-digit strike (e.g. TSLA250423C00270000)
    return /\d{6}[CP]\d{8}$/.test(symbol || '');
  }

  private loadAll(): void {
    this.loading.set(true);
    this.error.set(null);
    forkJoin({
      balances: this.tradier.getBalances(),
      history: this.tradier.getHistoricalBalances(this.period()),
      // Closed trades come from the ENGINE, not Tradier's /gainloss. That report's
      // cost basis is corrupt for repeatedly round-tripped contracts (it reported
      // -21,057 on 2026-07-13 for a day that lost -1,851) and it truncates at its
      // page limit. The engine pairs each exit with its own entry at fill time.
      gainloss: this.strategies.getClosedTrades(this.period()),
      tradeHistory: this.tradier.getAccountHistory('trade', undefined, undefined, 500).pipe(
        catchError(() => of([] as TradeEvent[])),
      ),
      optionHistory: this.tradier.getAccountHistory('option', undefined, undefined, 500).pipe(
        catchError(() => of([] as TradeEvent[])),
      ),
      feeHistory: this.tradier.getAccountHistory('fee', undefined, undefined, 500).pipe(
        catchError(() => of([] as TradeEvent[])),
      ),
    }).subscribe({
      next: ({ balances, history, gainloss, tradeHistory, optionHistory, feeHistory }) => {
        this.balances.set(balances);
        this.history.set(history);
        const enriched = this.attachCostsToClosedPositions(
          gainloss || [],
          [...(tradeHistory || []), ...(optionHistory || [])],
          feeHistory || [],
        );
        this.closedPositions.set(enriched);
        this.closedDataSource.data = enriched;
        if (this.sort) this.closedDataSource.sort = this.sort;
        if (this.paginator) this.closedDataSource.paginator = this.paginator;
        this.rebuildChart();
        this.loading.set(false);
      },
      error: err => {
        console.error('Failed to load performance data:', err);
        this.error.set(
          err?.error?.detail || 'Unable to load performance data. Check Tradier credentials and try again.',
        );
        this.loading.set(false);
      },
    });
  }

  private attachCostsToClosedPositions(
    closed: ClosedPosition[],
    tradeEvents: TradeEvent[],
    feeEvents: TradeEvent[],
  ): ClosedPosition[] {
    // Bucket commission by symbol -> [{date, commission}], so each closed
    // position gets the commissions paid on the open + close legs.
    const commByEvent = tradeEvents
      .map(e => ({
        symbol: (e.trade?.symbol || e['symbol'] || '').toString(),
        date: (e.date || '').slice(0, 10),
        commission: Number(e.trade?.commission ?? e['commission'] ?? 0) || 0,
      }))
      .filter(x => x.symbol && x.date);

    // Fee events generally lack a symbol — we attribute them to whichever
    // closed position was closed on the same day. If multiple, split evenly.
    const feesByDay = new Map<string, number>();
    for (const e of feeEvents) {
      const day = (e.date || '').slice(0, 10);
      if (!day) continue;
      const amt = Math.abs(Number(e['amount'] ?? 0)) || 0;
      feesByDay.set(day, (feesByDay.get(day) || 0) + amt);
    }
    const closesPerDay = new Map<string, number>();
    for (const p of closed) {
      const day = (p.close_date || '').slice(0, 10);
      if (!day) continue;
      closesPerDay.set(day, (closesPerDay.get(day) || 0) + 1);
    }

    return closed.map(p => {
      const openDay = (p.open_date || '').slice(0, 10);
      const closeDay = (p.close_date || '').slice(0, 10);
      const derivedCommission = commByEvent
        .filter(c => c.symbol === p.symbol && (c.date === openDay || c.date === closeDay))
        .reduce((s, c) => s + c.commission, 0);
      const dayFees = feesByDay.get(closeDay) || 0;
      const share = closesPerDay.get(closeDay) || 1;
      const derivedFees = dayFees / share;

      // Rows now come from the engine, whose Trade records already carry commission and
      // fees reconciled from Tradier's account history. Prefer those; only fall back to
      // deriving from raw history events when the row has none, so a failed symbol match
      // here can't silently zero out real costs.
      const commission = (p.commission ?? 0) || derivedCommission;
      const fees = (p.fees ?? 0) || derivedFees;
      const net = (p.gain_loss || 0) - commission - fees;
      return { ...p, commission, fees, net_pnl: net };
    });
  }

  private loadHistory(): void {
    this.loading.set(true);
    this.tradier.getHistoricalBalances(this.period()).subscribe({
      next: h => {
        this.history.set(h);
        this.rebuildChart();
        this.loading.set(false);
      },
      error: err => {
        console.error('Failed to load historical balances:', err);
        this.loading.set(false);
      },
    });
  }

  private rebuildChart(): void {
    const h = this.history();
    const points = h?.balances ?? [];
    const labels = points.map(p => this.fmtChartDate(p.date));
    const values = points.map(p => p.value);
    const last = values.length > 0 ? values[values.length - 1] : 0;
    const first = values.length > 0 ? values[0] : 0;
    const trendUp = last >= first;
    const palette = this.themeService.chartColors();
    const stroke = trendUp ? palette.profit : palette.loss;
    const fill = trendUp ? palette.profitFill : palette.lossFill;
    this.chartData.set({
      labels,
      datasets: [
        {
          data: values,
          label: 'Equity',
          borderColor: stroke,
          backgroundColor: fill,
          fill: 'origin',
          pointBackgroundColor: stroke,
        },
      ],
    });
  }

  private filteredClosedForPeriod(): ClosedPosition[] {
    const cutoff = this.periodCutoff();
    if (!cutoff) return this.closedPositions();
    return this.closedPositions().filter(p => {
      const d = new Date(p.close_date);
      return !isNaN(d.getTime()) && d >= cutoff;
    });
  }

  private periodCutoff(): Date | null {
    const now = new Date();
    switch (this.period()) {
      case 'DAY':
        // Midnight local today — close_date is a date-only stamp from Tradier,
        // so anything closed today lands at or after this.
        return new Date(now.getFullYear(), now.getMonth(), now.getDate());
      case 'WEEK':
        return new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7);
      case 'MONTH':
        return new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
      case 'YTD':
        return new Date(now.getFullYear(), 0, 1);
      case 'YEAR':
        return new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
      case 'YEAR_3':
        return new Date(now.getFullYear() - 3, now.getMonth(), now.getDate());
      case 'YEAR_5':
        return new Date(now.getFullYear() - 5, now.getMonth(), now.getDate());
      case 'ALL':
      default:
        return null;
    }
  }

  periodLabel(): string {
    return this.periods.find(p => p.value === this.period())?.label ?? '';
  }

  fmtCurrency(value: number): string {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value || 0);
  }

  private fmtCurrencyShort(value: number): string {
    const abs = Math.abs(value);
    if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
    return `$${value.toFixed(0)}`;
  }

  private fmtChartDate(d: string): string {
    const date = new Date(d);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  prevMonth(): void {
    const a = this.calendarMonth();
    this.calendarMonth.set(new Date(a.getFullYear(), a.getMonth() - 1, 1));
  }

  nextMonth(): void {
    const a = this.calendarMonth();
    this.calendarMonth.set(new Date(a.getFullYear(), a.getMonth() + 1, 1));
  }

  thisMonth(): void {
    this.calendarMonth.set(this.startOfMonth(new Date()));
  }

  fmtCalendarPL(value: number): string {
    const abs = Math.abs(value);
    const sign = value >= 0 ? '+' : '-';
    if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(abs >= 10_000 ? 0 : 1)}K`;
    return `${sign}$${abs.toFixed(0)}`;
  }

  private startOfMonth(d: Date): Date {
    return new Date(d.getFullYear(), d.getMonth(), 1);
  }

  private toDateKey(d: Date): string {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  fmtDate(d: string): string {
    if (!d) return '';
    // Tradier returns dates as midnight UTC (e.g. "2026-04-27T00:00:00.000Z").
    // Parse the calendar date directly so timezone offset doesn't shift the day.
    const ymd = d.slice(0, 10).split('-');
    if (ymd.length !== 3) return d;
    const [y, m, day] = ymd.map(Number);
    const date = new Date(y, m - 1, day);
    if (isNaN(date.getTime())) return d;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  /**
   * Full open/close timestamp for the closed-positions table. Tradier's
   * gain/loss timestamps are ISO-8601 UTC. When a real fill time is present
   * (e.g. "2026-04-27T15:25:47.000Z") we show local date + time; when Tradier
   * only reports the calendar date padded to midnight UTC ("…T00:00:00.000Z")
   * we fall back to the timezone-safe date-only format so the day can't shift.
   */
  fmtDateTime(d: string): string {
    if (!d) return '';
    const time = d.slice(11, 19); // "HH:MM:SS"
    const hasRealTime = d.includes('T') && time !== '' && time !== '00:00:00';
    if (!hasRealTime) return this.fmtDate(d);
    const date = new Date(d);
    if (isNaN(date.getTime())) return this.fmtDate(d);
    return date.toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit', second: '2-digit',
    });
  }
}
