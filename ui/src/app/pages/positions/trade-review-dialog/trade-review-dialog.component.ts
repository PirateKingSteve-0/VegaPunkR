import {
  AfterViewInit,
  Component,
  ElementRef,
  Inject,
  OnDestroy,
  ViewChild,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  CandlestickSeries,
  ColorType,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineSeries,
  LineStyle,
  Time,
  UTCTimestamp,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import { TradeReplay } from '../../../services/trade-replay.service';
import { ThemeService } from '../../../services/theme.service';

/** Context either side of the trade when zoomed in, in seconds. */
const PAD_S = 20 * 60;

@Component({
  selector: 'app-trade-review-dialog',
  standalone: true,
  imports: [
    CommonModule,
    DecimalPipe,
    MatDialogModule,
    MatButtonModule,
    MatButtonToggleModule,
    MatIconModule,
    MatTooltipModule,
  ],
  templateUrl: './trade-review-dialog.component.html',
  styleUrls: ['./trade-review-dialog.component.scss'],
})
export class TradeReviewDialogComponent implements AfterViewInit, OnDestroy {
  @ViewChild('contractPane') contractPane!: ElementRef<HTMLDivElement>;
  @ViewChild('underlyingPane') underlyingPane!: ElementRef<HTMLDivElement>;

  private theme = inject(ThemeService);
  private contractChart?: IChartApi;
  private underlyingChart?: IChartApi;
  private contractSeries?: ISeriesApi<'Line'>;
  private candles?: ISeriesApi<'Candlestick'>;
  private vwapSeries?: ISeriesApi<'Line'>;
  private priceLines: IPriceLine[] = [];
  /** Guards the two-way range sync from bouncing between the charts forever. */
  private syncing = false;
  private built = false;

  series = signal<'bid' | 'mid'>('bid');
  zoom = signal<'trade' | 'session'>('trade');
  expanded = signal(false);

  constructor(
    public dialogRef: MatDialogRef<TradeReviewDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public replay: TradeReplay,
  ) {
    // Charts take colors as JS values, so they have to be redrawn on a theme or
    // colorblind-mode switch rather than inheriting new CSS.
    effect(() => {
      this.theme.chartColors();
      if (this.built) this.rebuild();
    });
  }

  ngAfterViewInit(): void {
    this.rebuild();
    this.built = true;
  }

  ngOnDestroy(): void {
    this.contractChart?.remove();
    this.underlyingChart?.remove();
  }

  // ------------------------------------------------------------------ display

  get contractPnlPct(): number | null {
    const x = this.replay.exit;
    if (!x) return null;
    return ((x.price - this.replay.entry.price) / this.replay.entry.price) * 100;
  }

  get holdLabel(): string {
    const s = this.replay.facts.hold_s;
    if (s == null) return 'open';
    if (s < 90) return `${s}s`;
    const m = Math.floor(s / 60);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  /** Unix seconds → "11:13:02" in ET, which is the only clock trading times mean. */
  etTime(ts: number, withSeconds = true): string {
    return new Date(ts * 1000).toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      ...(withSeconds ? { second: '2-digit' } : {}),
    });
  }

  etDate(ts: number): string {
    return new Date(ts * 1000).toLocaleDateString('en-US', {
      timeZone: 'America/New_York',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  }

  pctOf(price: number | null | undefined): number | null {
    if (price == null) return null;
    return ((price - this.replay.entry.price) / this.replay.entry.price) * 100;
  }

  setSeries(s: 'bid' | 'mid'): void {
    if (s === this.series()) return;
    this.series.set(s);
    this.rebuild();
  }

  setZoom(z: 'trade' | 'session'): void {
    if (z === this.zoom()) return;
    this.zoom.set(z);
    this.applyZoom();
  }

  toggleExpanded(): void {
    const next = !this.expanded();
    this.expanded.set(next);
    this.dialogRef.updateSize(next ? '100vw' : '1100px', next ? '100vh' : '');
    // The panes resize with the dialog; the charts need to be told.
    setTimeout(() => {
      this.contractChart?.applyOptions({});
      this.underlyingChart?.applyOptions({});
      this.applyZoom();
    }, 0);
  }

  // -------------------------------------------------------------------- chart

  private baseOptions() {
    const p = this.theme.chartColors();
    return {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: p.surface }, textColor: p.text },
      grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } },
      rightPriceScale: { borderColor: p.grid },
      timeScale: {
        borderColor: p.grid,
        timeVisible: true,
        secondsVisible: false,
        // The contract series is one point per recorded quote — 1,330 of them for
        // a 30-minute trade. At the library's default floor of 0.5px per point,
        // a 501px pane can only show ~1,000, so setVisibleRange silently clamped
        // the window to the last 24 minutes and the entry marker fell off the
        // left edge. Measured, not guessed: asked 10:53-12:03, got 11:19-11:43.
        minBarSpacing: 0.02,
        tickMarkFormatter: (t: any) => this.etTime(Number(t), false),
      },
      crosshair: { mode: 1 },
      localization: { timeFormatter: (t: any) => this.etTime(Number(t)) },
    };
  }

  private rebuild(): void {
    if (!this.contractPane || !this.underlyingPane) return;
    const p = this.theme.chartColors();

    this.contractChart?.remove();
    this.underlyingChart?.remove();
    this.priceLines = [];

    this.contractChart = createChart(this.contractPane.nativeElement, this.baseOptions() as any);
    this.underlyingChart = createChart(this.underlyingPane.nativeElement, this.baseOptions() as any);

    const won = (this.replay.exit?.pnl ?? 0) >= 0;
    this.contractSeries = this.contractChart.addSeries(LineSeries, {
      color: won ? p.profit : p.loss,
      lineWidth: 2,
      priceLineVisible: false,
      // The entry / stop / trail / target lines already label this axis; the
      // floating last-value badge only lands on top of the exit marker.
      lastValueVisible: false,
    });
    const useMid = this.series() === 'mid';
    const points = this.replay.contract.points.map((pt) => ({
      time: pt.t as UTCTimestamp,
      value: useMid ? (pt.bid + pt.ask) / 2 : pt.bid,
    }));
    // Whitespace points past the last quote. The recording stops at the exit (the
    // worker re-arms and the contract stops streaming), so the exit marker would
    // sit flush against the price scale with its label clipped. `rightOffset` does
    // not help here — it is ignored once setVisibleRange pins the window — but
    // valueless points extend the axis, which is what the library provides them
    // for.
    const tail: any[] = [];
    const lastT = points.length ? (points[points.length - 1].time as number) : 0;
    for (let i = 1; lastT && i <= 10; i++) tail.push({ time: (lastT + i * 30) as UTCTimestamp });
    this.contractSeries.setData([...points, ...tail]);

    this.candles = this.underlyingChart.addSeries(CandlestickSeries, {
      upColor: p.profit,
      downColor: p.loss,
      borderVisible: false,
      wickUpColor: p.profit,
      wickDownColor: p.loss,
    });
    this.candles.setData(
      this.replay.underlying.bars.map((b) => ({
        time: b.t as UTCTimestamp,
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
      })),
    );

    this.vwapSeries = this.underlyingChart.addSeries(LineSeries, {
      color: p.textMuted,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    this.vwapSeries.setData(
      this.replay.underlying.vwap.map((v) => ({ time: v.t as UTCTimestamp, value: v.vwap })),
    );

    this.addLevels();
    this.addMarkers();
    this.linkCharts();
    this.applyZoom();
  }

  /** Stop, target and the price at which the trail arms — the numbers the exits watch. */
  private addLevels(): void {
    if (!this.contractSeries) return;
    const p = this.theme.chartColors();
    const lv = this.replay.contract.levels;
    const add = (price: number | undefined, title: string, color: string, style: LineStyle) => {
      if (price == null || !this.contractSeries) return;
      this.priceLines.push(
        this.contractSeries.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: style,
          axisLabelVisible: true,
          title,
        }),
      );
    };
    add(this.replay.entry.price, 'entry', p.primary, LineStyle.Solid);
    add(lv.stop, 'stop', p.loss, LineStyle.Dashed);
    add(lv.trail_arms_at, 'trail arms', p.textMuted, LineStyle.Dotted);
    add(lv.target, 'target', p.profit, LineStyle.Dashed);
  }

  private addMarkers(): void {
    if (!this.contractSeries || !this.candles) return;
    const p = this.theme.chartColors();
    const entry = this.replay.entry;
    const exit = this.replay.exit;

    // Snap to a recorded quote: a marker whose time falls between two points is
    // not drawn, and entry/exit timestamps come from the fill, not the tape.
    const nearestQuote = (ts: number): Time => {
      const pts = this.replay.contract.points;
      let best = pts[0]?.t ?? ts;
      for (const q of pts) {
        if (q.t <= ts) best = q.t;
        else break;
      }
      return best as Time;
    };

    const contractMarks: any[] = [
      {
        time: nearestQuote(entry.t),
        position: 'belowBar',
        color: p.primary,
        shape: 'arrowUp',
        size: 2,
        text: `buy ${entry.qty} @ $${entry.price.toFixed(2)}`,
      },
    ];
    if (exit) {
      contractMarks.push({
        time: nearestQuote(exit.t),
        position: 'aboveBar',
        color: p.text,
        size: 2,
        shape: 'arrowDown',
        // Arrow only, in the foreground colour — a profit-green arrow on a
        // profit-green line was invisible. No label: the exit is the last point
        // on the series, so any text is centred on the right edge and half of it
        // is clipped (the whitespace tail does not help, because setVisibleRange
        // pins the window to the last VALUED point). The exit is spelled out in
        // the pane header instead.
        text: '',
      });
    }
    createSeriesMarkers(this.contractSeries, contractMarks);

    // The stock pane carries the same two moments so the eye can line them up,
    // but never the option's prices — that mismatch is what made the old dialog
    // unreadable (an entry labelled $3.66 on a $770 axis).
    const nearestBar = (ts: number): Time => {
      const bars = this.replay.underlying.bars;
      let best = bars[0]?.t ?? ts;
      for (const b of bars) {
        if (b.t <= ts) best = b.t;
        else break;
      }
      return best as Time;
    };
    const stockMarks: any[] = [
      { time: nearestBar(entry.t), position: 'belowBar', color: p.primary, shape: 'arrowUp', text: 'entry' },
    ];
    if (exit) {
      stockMarks.push({
        time: nearestBar(exit.t),
        position: 'aboveBar',
        color: exit.pnl >= 0 ? p.profit : p.loss,
        shape: 'arrowDown',
        text: 'exit',
      });
    }
    createSeriesMarkers(this.candles, stockMarks);
  }

  /**
   * Link the two panes by TIME, not by logical index: the contract is sampled per
   * second and the stock per minute, so bar 40 is a different moment in each.
   */
  private linkCharts(): void {
    const a = this.contractChart;
    const b = this.underlyingChart;
    if (!a || !b) return;

    const mirror = (from: IChartApi, to: IChartApi) => {
      from.timeScale().subscribeVisibleTimeRangeChange((range) => {
        if (!range || this.syncing) return;
        this.syncing = true;
        try {
          to.timeScale().setVisibleRange(range);
        } catch {
          // Ranges outside the other series' data throw; ignore and keep the view.
        }
        this.syncing = false;
      });
    };
    mirror(a, b);
    mirror(b, a);

    const link = (from: IChartApi, to: IChartApi, target?: ISeriesApi<any>) => {
      from.subscribeCrosshairMove((param) => {
        if (!target) return;
        if (param.time == null) {
          to.clearCrosshairPosition();
          return;
        }
        // Line points carry `value`; candles carry open/high/low/close. Reading
        // only `value` puts the mirrored crosshair at price 0 when the pointer is
        // over the stock pane.
        const d = param.seriesData.values().next().value as any;
        const price = d?.value ?? d?.close ?? 0;
        to.setCrosshairPosition(price, param.time, target);
      });
    };
    link(a, b, this.candles);
    link(b, a, this.contractSeries);
  }

  private applyZoom(): void {
    const entry = this.replay.entry.t;
    const exit = this.replay.exit?.t ?? entry;
    const pts = this.replay.contract.points;
    if (!pts.length) return;

    const range =
      this.zoom() === 'trade'
        ? { from: (entry - PAD_S) as UTCTimestamp, to: (exit + PAD_S) as UTCTimestamp }
        : {
            from: (this.replay.underlying.bars[0]?.t ?? pts[0].t) as UTCTimestamp,
            to: (this.replay.underlying.bars[this.replay.underlying.bars.length - 1]?.t ??
              pts[pts.length - 1].t) as UTCTimestamp,
          };
    // Hold the mirror off while both panes are set. Without this each chart
    // echoes the other mid-assignment and they settle on a narrower window than
    // asked for — the entry marker ended up off-screen to the left.
    this.syncing = true;
    try {
      this.contractChart?.timeScale().setVisibleRange(range);
      this.underlyingChart?.timeScale().setVisibleRange(range);
    } catch {
      this.contractChart?.timeScale().fitContent();
      this.underlyingChart?.timeScale().fitContent();
    } finally {
      this.syncing = false;
    }
  }
}
