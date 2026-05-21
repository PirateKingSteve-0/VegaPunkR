import { Component, Inject, computed, effect, inject, signal } from '@angular/core';
import { CommonModule, CurrencyPipe } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration, ChartData } from 'chart.js';
import { EquityCurvePoint } from '../../services/strategy.service';
import { ThemeService } from '../../services/theme.service';

export interface EquityCurveDialogData {
  strategy_id: number;
  name: string;
  points: EquityCurvePoint[];
}

@Component({
  selector: 'app-equity-curve-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    CurrencyPipe,
    BaseChartDirective,
  ],
  template: `
    <h2 mat-dialog-title>
      <mat-icon>show_chart</mat-icon>
      <span>{{ data.name }}</span>
      <span class="spacer"></span>
      <button mat-icon-button mat-dialog-close aria-label="Close">
        <mat-icon>close</mat-icon>
      </button>
    </h2>

    <mat-dialog-content>
      <div class="subtitle">Lifetime cumulative realized PnL · {{ data.points.length }} closed trades</div>

      @if (data.points.length === 0) {
        <div class="empty">No closed trades yet for this strategy.</div>
      } @else {
        <div class="stats">
          <div class="stat">
            <div class="stat-label">Total Realized</div>
            <div class="stat-value" [class.profit]="totalPnl() > 0" [class.loss]="totalPnl() < 0">
              {{ totalPnl() | currency }}
            </div>
          </div>
          <div class="stat">
            <div class="stat-label">Best Trade</div>
            <div class="stat-value profit">{{ bestTrade() | currency }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Worst Trade</div>
            <div class="stat-value loss">{{ worstTrade() | currency }}</div>
          </div>
          <div class="stat">
            <div class="stat-label">Win Rate</div>
            <div class="stat-value">{{ winRatePct() }}%</div>
          </div>
        </div>

        <div class="chart-wrap">
          <canvas
            baseChart
            [data]="chartData()"
            [options]="chartOptions"
            [type]="chartType"
          ></canvas>
        </div>
      }
    </mat-dialog-content>
  `,
  styles: [`
    h2[mat-dialog-title] {
      display: flex;
      align-items: center;
      gap: 12px;
      margin: 0;
      padding: 20px 24px;
      border-bottom: 1px solid var(--border);

      mat-icon {
        color: var(--text-muted);
      }

      .spacer {
        flex: 1;
      }
    }

    mat-dialog-content {
      padding: 24px;
      max-height: calc(90vh - 100px);
      overflow-y: auto;
    }

    .subtitle {
      color: var(--text-muted);
      font-size: 13px;
      margin-bottom: 20px;
    }

    .empty {
      padding: 48px 24px;
      text-align: center;
      color: var(--text-faint);
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 20px;

      .stat {
        background: var(--surface-alt);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 12px 14px;
      }

      .stat-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--text-muted);
        margin-bottom: 4px;
      }

      .stat-value {
        font-size: 18px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--text);

        &.profit { color: var(--color-profit); }
        &.loss { color: var(--color-loss); }
      }
    }

    .chart-wrap {
      position: relative;
      height: 360px;
    }

    @media (max-width: 720px) {
      .stats {
        grid-template-columns: repeat(2, 1fr);
      }
      .chart-wrap {
        height: 280px;
      }
    }
  `],
})
export class EquityCurveDialogComponent {
  private themeService = inject(ThemeService);

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
          title: (items) => {
            const idx = items[0]?.dataIndex ?? 0;
            const p = this.data.points[idx];
            if (!p) return '';
            return `Trade #${idx + 1} · ${this.formatFullDate(p.t)}`;
          },
          label: (item) => {
            const idx = item.dataIndex;
            const p = this.data.points[idx];
            if (!p) return '';
            const cum = this.fmtCurrency(p.cum_pnl);
            const trade = this.fmtCurrency(p.trade_pnl);
            const sign = p.trade_pnl >= 0 ? '+' : '';
            return [` Cumulative: ${cum}`, ` This trade: ${sign}${trade}`];
          },
        },
      },
    },
    scales: {
      x: { ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 } },
      y: {
        ticks: {
          callback: (v) => this.fmtCurrencyShort(Number(v)),
        },
      },
    },
    elements: {
      point: { radius: 0, hoverRadius: 5 },
      line: { tension: 0.25, borderWidth: 2 },
    },
  };

  totalPnl = computed(() => {
    const pts = this.data.points;
    if (pts.length === 0) return 0;
    return pts[pts.length - 1].cum_pnl;
  });

  bestTrade = computed(() => {
    const pts = this.data.points;
    if (pts.length === 0) return 0;
    return pts.reduce((m, p) => (p.trade_pnl > m ? p.trade_pnl : m), pts[0].trade_pnl);
  });

  worstTrade = computed(() => {
    const pts = this.data.points;
    if (pts.length === 0) return 0;
    return pts.reduce((m, p) => (p.trade_pnl < m ? p.trade_pnl : m), pts[0].trade_pnl);
  });

  winRatePct = computed(() => {
    const pts = this.data.points;
    if (pts.length === 0) return '0.0';
    const wins = pts.filter((p) => p.trade_pnl > 0).length;
    return ((wins / pts.length) * 100).toFixed(1);
  });

  constructor(
    public dialogRef: MatDialogRef<EquityCurveDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: EquityCurveDialogData,
  ) {
    effect(() => {
      this.themeService.chartColors();
      this.rebuildChart();
    });
  }

  private rebuildChart(): void {
    const pts = this.data.points;
    const labels = pts.map((p) => this.formatShortDate(p.t));
    const values = pts.map((p) => p.cum_pnl);
    const last = values.length > 0 ? values[values.length - 1] : 0;
    const palette = this.themeService.chartColors();
    const stroke = last >= 0 ? palette.profit : palette.loss;
    const fill = last >= 0 ? palette.profitFill : palette.lossFill;
    this.chartData.set({
      labels,
      datasets: [
        {
          data: values,
          label: 'Cumulative PnL',
          borderColor: stroke,
          backgroundColor: fill,
          fill: 'origin',
          pointBackgroundColor: stroke,
        },
      ],
    });
  }

  private formatShortDate(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  private formatFullDate(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  private fmtCurrency(n: number): string {
    return n.toLocaleString(undefined, {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  private fmtCurrencyShort(n: number): string {
    const abs = Math.abs(n);
    if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
    return `$${n.toFixed(0)}`;
  }
}
