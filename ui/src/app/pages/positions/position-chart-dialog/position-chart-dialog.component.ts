import {
  Component,
  ElementRef,
  Inject,
  OnDestroy,
  OnInit,
  ViewChild,
  AfterViewInit,
  inject,
} from '@angular/core';
import { CommonModule, CurrencyPipe, DatePipe } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  CandlestickSeries,
  ColorType,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  Time,
  UTCTimestamp,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import { TradierService, HistoryBar, IntradayBar } from '../../../services/tradier.service';
import { ThemeService } from '../../../services/theme.service';

export interface PositionChartData {
  symbol: string;
  avg_entry_price: number;
  date_acquired: string;
  qty: number;
  close_date?: string;
  exit_price?: number;
  /** Precise ISO timestamp of the opening trade (from history endpoint), if known. */
  open_time?: string;
  /** Precise ISO timestamp of the closing trade (from history endpoint), if known. */
  close_time?: string;
}

type RangeKey = '1D' | '5D' | '1M' | '3M' | '6M' | '1Y' | 'ALL';

interface RangeSpec {
  key: RangeKey;
  label: string;
  endpoint: 'history' | 'timesales';
  interval: 'daily' | '1min' | '5min' | '15min';
  daysBack: number;
  /** Max position-age (days) for which intraday data is reliably available; null = unlimited. */
  maxAgeDays: number | null;
}

const RANGE_SPECS: RangeSpec[] = [
  { key: '1D',  label: '1D',  endpoint: 'timesales', interval: '1min',  daysBack: 1,   maxAgeDays: 14 },
  { key: '5D',  label: '5D',  endpoint: 'timesales', interval: '5min',  daysBack: 5,   maxAgeDays: 30 },
  { key: '1M',  label: '1M',  endpoint: 'timesales', interval: '15min', daysBack: 30,  maxAgeDays: 30 },
  { key: '3M',  label: '3M',  endpoint: 'history',   interval: 'daily', daysBack: 90,  maxAgeDays: null },
  { key: '6M',  label: '6M',  endpoint: 'history',   interval: 'daily', daysBack: 180, maxAgeDays: null },
  { key: '1Y',  label: '1Y',  endpoint: 'history',   interval: 'daily', daysBack: 365, maxAgeDays: null },
  { key: 'ALL', label: 'ALL', endpoint: 'history',   interval: 'daily', daysBack: 0,   maxAgeDays: null },
];

@Component({
  selector: 'app-position-chart-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatButtonToggleModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    CurrencyPipe,
    DatePipe,
  ],
  templateUrl: './position-chart-dialog.component.html',
  styleUrls: ['./position-chart-dialog.component.scss'],
})
export class PositionChartDialogComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('chartContainer', { static: false }) chartContainer!: ElementRef<HTMLDivElement>;

  private tradier = inject(TradierService);
  private themeService = inject(ThemeService);
  private chart?: IChartApi;
  private series?: ISeriesApi<'Candlestick'>;
  private resizeObserver?: ResizeObserver;
  private viewReady = false;
  private priceLines: IPriceLine[] = [];
  private markersApi?: ISeriesMarkersPluginApi<any>;

  ranges = RANGE_SPECS;
  loading = true;
  error = '';
  range: RangeKey = '6M';
  chartMode: 'contract' | 'underlying' = 'contract';

  constructor(
    public dialogRef: MatDialogRef<PositionChartDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public position: PositionChartData,
  ) {
    // Pick the best default given the position's age + symbol type.
    // Options don't have intraday data on Tradier — go straight to daily.
    const age = this.entryAgeDays();
    const isOption = this.isOptionSymbol(position.symbol);
    if (isOption) {
      this.range = age <= 90 ? '3M' : '6M';
    } else if (age <= 5) {
      this.range = '5D';
    } else if (age <= 30) {
      this.range = '1M';
    } else if (age <= 90) {
      this.range = '3M';
    } else {
      this.range = '6M';
    }
  }

  isOptionSymbol(symbol: string): boolean {
    return /\d{6}[CP]\d{8}$/.test(symbol || '');
  }

  extractUnderlying(symbol: string): string | null {
    const m = /^([A-Z]+)\d{6}[CP]\d{8}$/.exec(symbol || '');
    return m ? m[1] : null;
  }

  currentSymbol(): string {
    if (this.chartMode === 'underlying') {
      return this.extractUnderlying(this.position.symbol) || this.position.symbol;
    }
    return this.position.symbol;
  }

  setChartMode(mode: 'contract' | 'underlying'): void {
    if (mode === this.chartMode) return;
    this.chartMode = mode;
    this.loadData();
  }

  ngOnInit(): void {}

  ngAfterViewInit(): void {
    this.viewReady = true;
    this.initChart();
    this.loadData();
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.chart?.remove();
  }

  setRange(r: RangeKey): void {
    if (r === this.range) return;
    if (this.isRangeDisabled(r)) return;
    this.range = r;
    this.loadData();
  }

  isRangeDisabled(key: RangeKey): boolean {
    const spec = RANGE_SPECS.find((s) => s.key === key);
    if (!spec) return false;
    // Tradier timesales doesn't support OCC option symbols — disable intraday only when
    // we'd be charting the contract itself. Underlying mode falls back to the equity symbol.
    const chartingContractOption =
      this.isOptionSymbol(this.position.symbol) && this.chartMode === 'contract';
    if (spec.endpoint === 'timesales' && chartingContractOption) {
      return true;
    }
    if (spec.maxAgeDays == null) return false;
    return this.entryAgeDays() > spec.maxAgeDays;
  }

  rangeTooltip(spec: RangeSpec): string {
    if (this.isRangeDisabled(spec.key)) {
      const chartingContractOption =
        this.isOptionSymbol(this.position.symbol) && this.chartMode === 'contract';
      if (spec.endpoint === 'timesales' && chartingContractOption) {
        return 'Intraday data is not available for option contracts. Switch to Underlying to view intraday.';
      }
      return `Intraday ${spec.interval} data only goes back ~${spec.maxAgeDays} days; this position is older.`;
    }
    return spec.endpoint === 'timesales'
      ? `Intraday ${spec.interval} bars`
      : `Daily bars`;
  }

  private entryAgeDays(): number {
    const acquired = new Date(this.position.date_acquired);
    const now = new Date();
    return Math.max(0, Math.floor((now.getTime() - acquired.getTime()) / 86_400_000));
  }

  private initChart(): void {
    const el = this.chartContainer.nativeElement;
    const palette = this.themeService.chartColors();
    this.chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: palette.surface },
        textColor: palette.text,
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid },
      },
      timeScale: {
        borderColor: palette.grid,
        timeVisible: false,
        secondsVisible: false,
        tickMarkFormatter: (time: any) => this.formatAxisTick(time),
      },
      rightPriceScale: { borderColor: palette.grid },
      crosshair: { mode: 1 },
      localization: {
        timeFormatter: (time: any) => this.formatCrosshairTime(time),
      },
    });
    this.series = this.chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });
  }

  private loadData(): void {
    if (!this.viewReady || !this.series || !this.chart) return;
    const spec = RANGE_SPECS.find((s) => s.key === this.range);
    if (!spec) return;

    this.loading = true;
    this.error = '';

    // Toggle time-of-day axis for intraday vs daily
    this.chart.applyOptions({
      timeScale: { timeVisible: spec.endpoint === 'timesales', secondsVisible: false },
    });

    const symbol = this.currentSymbol();
    if (spec.endpoint === 'history') {
      const { start, end } = this.computeDailyRange(spec);
      this.tradier.getMarketHistory(symbol, 'daily', start, end).subscribe({
        next: (bars) => {
          this.applyDailyBars(bars);
          this.loading = false;
        },
        error: (err) => this.handleError(err),
      });
    } else {
      const { start, end } = this.computeIntradayRange(spec);
      this.tradier
        .getMarketTimesales(symbol, spec.interval as any, start, end, 'all')
        .subscribe({
          next: (bars) => {
            this.applyIntradayBars(bars);
            this.loading = false;
          },
          error: (err) => this.handleError(err),
        });
    }
  }

  private handleError(err: any): void {
    this.error = err?.error?.detail || err?.message || 'Failed to load chart data';
    this.loading = false;
  }

  private applyDailyBars(bars: HistoryBar[]): void {
    if (!this.series || !this.chart) return;

    this.clearOverlays();

    const data = bars
      .filter((b) => b && b.date)
      .map((b) => ({
        time: b.date as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));

    this.series.setData(data);

    const entryIso = this.extractDate(this.position.date_acquired);
    const entryTime: Time =
      (data.find((d) => (d.time as string) >= entryIso)?.time as Time) ??
      (data[data.length - 1]?.time as Time) ??
      (entryIso as Time);

    const markers: any[] = [
      {
        time: entryTime,
        position: 'belowBar',
        color: '#1976d2',
        shape: 'arrowUp',
        text: `Entry @ $${this.position.avg_entry_price.toFixed(2)}`,
      },
    ];

    if (this.chartMode === 'contract') this.addEntryPriceLine();

    if (this.position.close_date && this.position.exit_price != null) {
      const exitIso = this.extractDate(this.position.close_date);
      const exitTime: Time =
        ([...data].reverse().find((d) => (d.time as string) <= exitIso)?.time as Time) ??
        (data[data.length - 1]?.time as Time) ??
        (exitIso as Time);
      markers.push({
        time: exitTime,
        position: 'aboveBar',
        color: this.themeService.chartColors().loss,
        shape: 'arrowDown',
        text: `Exit @ $${this.position.exit_price.toFixed(2)}`,
      });
      if (this.chartMode === 'contract') this.addExitPriceLine();
    }

    this.setMarkers(markers);
    this.chart.timeScale().fitContent();
  }

  private applyIntradayBars(bars: IntradayBar[]): void {
    if (!this.series || !this.chart) return;

    this.clearOverlays();

    const data = bars
      .filter((b) => b && (b.timestamp != null || b.time))
      .map((b) => ({
        time: this.toUnixSecond(b) as UTCTimestamp,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
      .filter((d) => Number.isFinite(d.time as number))
      .sort((a, b) => (a.time as number) - (b.time as number));

    this.series.setData(data);

    const markers: any[] = [];

    if (data.length > 0) {
      const entryTime = this.placeIntradayMarker(data, this.position.open_time, this.position.date_acquired, 'after');
      markers.push({
        time: entryTime,
        position: 'belowBar',
        color: '#1976d2',
        shape: 'arrowUp',
        text: `Entry @ $${this.position.avg_entry_price.toFixed(2)}`,
      });
      if (this.chartMode === 'contract') this.addEntryPriceLine();

      if (this.position.close_date && this.position.exit_price != null) {
        const exitTime = this.placeIntradayMarker(data, this.position.close_time, this.position.close_date, 'before');
        markers.push({
          time: exitTime,
          position: 'aboveBar',
          color: this.themeService.chartColors().loss,
          shape: 'arrowDown',
          text: `Exit @ $${this.position.exit_price.toFixed(2)}`,
        });
        if (this.chartMode === 'contract') this.addExitPriceLine();
      }
    }

    this.setMarkers(markers);
    this.chart.timeScale().fitContent();
  }

  /**
   * Pick the chart bar to anchor a marker on for intraday data.
   * Prefers a precise ISO timestamp if available; falls back to ET-trading-day matching
   * (NOT UTC date — an after-hours bar from the prior session can have the next UTC
   * calendar date but still belongs to the previous ET trading day).
   */
  private placeIntradayMarker(
    data: { time: UTCTimestamp }[],
    preciseIso: string | undefined,
    fallbackDate: string,
    direction: 'before' | 'after',
  ): UTCTimestamp {
    if (preciseIso) {
      const target = Math.floor(new Date(preciseIso).getTime() / 1000);
      if (Number.isFinite(target)) {
        if (direction === 'after') {
          return (data.find((b) => (b.time as number) >= target)?.time ??
            data[data.length - 1].time) as UTCTimestamp;
        }
        return ([...data].reverse().find((b) => (b.time as number) <= target)?.time ??
          data[0].time) as UTCTimestamp;
      }
    }
    // Date-only fallback: anchor to regular market hours (Tradier returns 24h data for
    // some equities, so "first bar of trading day" can be midnight overnight — useless).
    const dateStr = this.extractDate(fallbackDate);
    const sessionTime = direction === 'after' ? '09:30:00' : '16:00:00';
    const target = this.parseEtTimestamp(`${dateStr} ${sessionTime}`);
    if (direction === 'after') {
      return (data.find((b) => (b.time as number) >= target)?.time ??
        data[data.length - 1].time) as UTCTimestamp;
    }
    return ([...data].reverse().find((b) => (b.time as number) <= target)?.time ??
      data[0].time) as UTCTimestamp;
  }

  private toUnixSecond(b: IntradayBar): number {
    if (b.timestamp != null) {
      // Heuristic: values beyond ~year 5138 (1e11 sec) are almost certainly milliseconds.
      const t = b.timestamp;
      return Math.floor(t > 1e11 ? t / 1000 : t);
    }
    const s = (b.time || '').trim();
    // ISO with explicit timezone (Z or ±HH:MM) — let Date handle it
    if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(s)) {
      return Math.floor(new Date(s).getTime() / 1000);
    }
    // Tradier "YYYY-MM-DD HH:MM:SS" — Eastern wall-clock
    return this.parseEtTimestamp(s);
  }

  /**
   * Parse a Tradier intraday time string ("YYYY-MM-DD HH:MM:SS" in US/Eastern)
   * into a UTC unix-second timestamp, accounting for EST/EDT.
   */
  private parseEtTimestamp(s: string): number {
    const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec((s || '').trim());
    if (!m) return Math.floor(new Date((s || '').replace(' ', 'T')).getTime() / 1000);
    const [, yy, mm, dd, hh, mi, ss] = m;
    const year = +yy, month = +mm - 1, day = +dd;
    const hour = +hh, minute = +mi, second = ss != null ? +ss : 0;
    const offsetMinutes = this.isEasternDst(year, month, day) ? 240 : 300;
    const utcMillis = Date.UTC(year, month, day, hour, minute, second) + offsetMinutes * 60_000;
    return Math.floor(utcMillis / 1000);
  }

  /** US Eastern DST: second Sunday of March → first Sunday of November. */
  private isEasternDst(year: number, month: number, day: number): boolean {
    if (month < 2 || month > 10) return false;
    if (month > 2 && month < 10) return true;
    if (month === 2) {
      const dow = new Date(Date.UTC(year, 2, 1)).getUTCDay();
      const secondSunday = 1 + ((7 - dow) % 7) + 7;
      return day >= secondSunday;
    }
    const dow = new Date(Date.UTC(year, 10, 1)).getUTCDay();
    const firstSunday = 1 + ((7 - dow) % 7);
    return day < firstSunday;
  }

  private clearOverlays(): void {
    if (!this.series) return;
    for (const line of this.priceLines) this.series.removePriceLine(line);
    this.priceLines = [];
  }

  private setMarkers(markers: any[]): void {
    if (!this.series) return;
    if (this.markersApi) {
      this.markersApi.setMarkers(markers);
    } else {
      this.markersApi = createSeriesMarkers(this.series, markers);
    }
  }

  private addEntryPriceLine(): void {
    if (!this.series) return;
    this.priceLines.push(
      this.series.createPriceLine({
        price: this.position.avg_entry_price,
        color: '#1976d2',
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'Entry',
      }),
    );
  }

  private addExitPriceLine(): void {
    if (!this.series || this.position.exit_price == null) return;
    this.priceLines.push(
      this.series.createPriceLine({
        price: this.position.exit_price,
        color: this.themeService.chartColors().loss,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: 'Exit',
      }),
    );
  }

  private computeDailyRange(spec: RangeSpec): { start: string; end: string } {
    const today = new Date();
    const acquired = new Date(this.position.date_acquired);
    const closed = this.position.close_date ? new Date(this.position.close_date) : null;

    const endDate = closed
      ? new Date(Math.min(this.addDays(closed, 14).getTime(), today.getTime()))
      : today;
    const start = new Date(endDate);

    if (spec.key === 'ALL') {
      start.setTime(acquired.getTime());
      start.setDate(start.getDate() - 14);
    } else {
      start.setDate(start.getDate() - spec.daysBack);
      const buffer = this.addDays(acquired, -14);
      if (buffer < start) start.setTime(buffer.getTime());
    }

    return { start: this.formatDate(start), end: this.formatDate(endDate) };
  }

  private computeIntradayRange(spec: RangeSpec): { start: string; end: string } {
    const today = new Date();
    const closed = this.position.close_date ? new Date(this.position.close_date) : null;

    const endDate = closed
      ? new Date(Math.min(this.addDays(closed, 1).getTime(), today.getTime()))
      : today;
    const startDate = this.addDays(endDate, -spec.daysBack);

    return {
      start: `${this.formatDate(startDate)} 00:00`,
      end: `${this.formatDate(endDate)} 23:59`,
    };
  }

  private formatAxisTick(time: any): string {
    const d = this.timeToDate(time);
    if (!d) return '';
    const isIntraday = this.range === '1D' || this.range === '5D' || this.range === '1M';
    if (!isIntraday) {
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    return d.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  }

  private formatCrosshairTime(time: any): string {
    const d = this.timeToDate(time);
    if (!d) return '';
    const isIntraday = this.range === '1D' || this.range === '5D' || this.range === '1M';
    if (!isIntraday) {
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    }
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  }

  private timeToDate(time: any): Date | null {
    if (typeof time === 'number') {
      return new Date(time * 1000);
    }
    if (typeof time === 'string') {
      return new Date(time + 'T00:00:00');
    }
    if (time && typeof time === 'object' && 'year' in time) {
      return new Date(time.year, (time.month ?? 1) - 1, time.day ?? 1);
    }
    return null;
  }

  private addDays(d: Date, days: number): Date {
    const out = new Date(d);
    out.setDate(out.getDate() + days);
    return out;
  }

  private formatDate(d: Date): string {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
  }

  /**
   * Extract a UTC YYYY-MM-DD calendar date from a Tradier-style timestamp.
   * Avoids local-TZ shifting (e.g., midnight UTC → previous day for users west of UTC).
   */
  private extractDate(s: string): string {
    if (!s) return '';
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
    return this.formatDate(new Date(s));
  }
}
