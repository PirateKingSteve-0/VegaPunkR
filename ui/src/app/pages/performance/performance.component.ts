import { Component, OnInit, OnDestroy, inject, signal, computed, ViewChild } from '@angular/core';
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
import { Subscription, forkJoin } from 'rxjs';
import { distinctUntilChanged, skip } from 'rxjs/operators';
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

interface MetricCard {
  label: string;
  value: string;
  sub?: string;
  icon: string;
  tone: 'neutral' | 'positive' | 'negative';
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
  private systemService = inject(SystemService);
  private dialog = inject(MatDialog);
  private settingsSub?: Subscription;

  @ViewChild(MatSort) sort?: MatSort;
  @ViewChild(MatPaginator) paginator?: MatPaginator;

  readonly periods: { value: BalancePeriod; label: string }[] = [
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
    const wins = inPeriodClosed.filter(p => p.gain_loss > 0).length;
    const losses = inPeriodClosed.filter(p => p.gain_loss < 0).length;
    const totalTrades = inPeriodClosed.length;
    const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;

    const tone = (n: number): 'positive' | 'negative' | 'neutral' =>
      n > 0 ? 'positive' : n < 0 ? 'negative' : 'neutral';

    return [
      {
        label: 'Portfolio Value',
        value: this.fmtCurrency(portfolioValue),
        sub: b ? `Cash ${this.fmtCurrency(b.total_cash ?? 0)}` : undefined,
        icon: 'account_balance_wallet',
        tone: 'neutral',
      },
      {
        label: `${this.periodLabel()} Change`,
        value: `${delta >= 0 ? '+' : ''}${this.fmtCurrency(delta)}`,
        sub: `${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(2)}%`,
        icon: delta >= 0 ? 'trending_up' : 'trending_down',
        tone: tone(delta),
      },
      {
        label: 'Open P&L',
        value: `${openPL >= 0 ? '+' : ''}${this.fmtCurrency(openPL)}`,
        icon: 'show_chart',
        tone: tone(openPL),
      },
      {
        label: `Realized P&L (${this.periodLabel()})`,
        value: `${realizedPL >= 0 ? '+' : ''}${this.fmtCurrency(realizedPL)}`,
        sub: `${totalTrades} trade${totalTrades === 1 ? '' : 's'}`,
        icon: 'attach_money',
        tone: tone(realizedPL),
      },
      {
        label: 'Win Rate',
        value: `${winRate.toFixed(1)}%`,
        sub: `${wins}W / ${losses}L`,
        icon: 'check_circle',
        tone: 'neutral',
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
      gainloss: this.tradier.getGainLoss(1, 200),
    }).subscribe({
      next: ({ balances, history, gainloss }) => {
        this.balances.set(balances);
        this.history.set(history);
        this.closedPositions.set(gainloss || []);
        this.closedDataSource.data = gainloss || [];
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
    const stroke = trendUp ? '#4caf50' : '#f44336';
    this.chartData.set({
      labels,
      datasets: [
        {
          data: values,
          label: 'Equity',
          borderColor: stroke,
          backgroundColor: trendUp ? 'rgba(76, 175, 80, 0.12)' : 'rgba(244, 67, 54, 0.12)',
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
}
