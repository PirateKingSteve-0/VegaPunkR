import { Component, OnInit, ViewChild, effect, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSidenavModule, MatSidenav } from '@angular/material/sidenav';
import { BaseChartDirective } from 'ng2-charts';
import { ChartConfiguration, ChartData } from 'chart.js';
import { Strategy } from '../../models/strategy.model';
import { StrategyService, EquityCurve } from '../../services/strategy.service';
import { ThemeService } from '../../services/theme.service';
import { TemplateGalleryModalComponent } from './template-gallery-modal.component';
import { StreamDrawerComponent } from './stream-drawer.component';
import { EquityCurveDialogComponent, EquityCurveDialogData } from './equity-curve-dialog.component';

@Component({
  selector: 'app-strategy-list',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatMenuModule,
    MatTooltipModule,
    MatDividerModule,
    MatDialogModule,
    MatSidenavModule,
    BaseChartDirective,
    StreamDrawerComponent,
  ],
  templateUrl: './strategy-list.component.html',
  styleUrls: ['./strategy-list.component.scss']
})
export class StrategyListComponent implements OnInit {
  @ViewChild('streamSidenav') streamSidenav!: MatSidenav;

  private strategyService = inject(StrategyService);
  private themeService = inject(ThemeService);
  private router = inject(Router);
  private dialog = inject(MatDialog);

  strategies: Strategy[] = [];
  isLoading = true;
  displayedColumns: string[] = ['name', 'type', 'status', 'symbols', 'equity', 'updated', 'actions'];
  activeStreamStrategy: Strategy | null = null;

  // Equity-curve sparkline state
  private curvesById = new Map<number, EquityCurve>();
  sparkDataById = new Map<number, ChartData<'line'>>();
  sparkChartType: ChartConfiguration<'line'>['type'] = 'line';
  sparkOptions: ChartConfiguration<'line'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: {
      legend: { display: false },
      tooltip: { enabled: false },
    },
    scales: {
      x: { display: false, grid: { display: false } },
      y: { display: false, grid: { display: false } },
    },
    elements: {
      point: { radius: 0, hoverRadius: 0 },
      line: { tension: 0.25, borderWidth: 1.5 },
    },
  };

  constructor() {
    // Recolor sparklines live when theme/colorblind toggles
    effect(() => {
      this.themeService.chartColors();
      if (this.curvesById.size > 0) this.rebuildSparks();
    });
  }

  ngOnInit(): void {
    this.loadStrategies();
    this.loadEquityCurves();
  }

  loadStrategies(): void {
    this.isLoading = true;
    this.strategyService.getStrategies().subscribe({
      next: (strategies) => {
        this.strategies = strategies;
        this.isLoading = false;
      },
      error: (error) => {
        console.error('Error loading strategies:', error);
        this.isLoading = false;
      }
    });
  }

  loadEquityCurves(): void {
    this.strategyService.getEquityCurves().subscribe({
      next: (curves) => {
        this.curvesById = new Map(curves.map((c) => [c.strategy_id, c]));
        this.rebuildSparks();
      },
      error: (error) => {
        console.error('Error loading equity curves:', error);
      },
    });
  }

  private rebuildSparks(): void {
    const palette = this.themeService.chartColors();
    const next = new Map<number, ChartData<'line'>>();
    for (const [id, curve] of this.curvesById.entries()) {
      const values = curve.points.map((p) => p.cum_pnl);
      const last = values.length > 0 ? values[values.length - 1] : 0;
      const stroke = last > 0 ? palette.profit : last < 0 ? palette.loss : palette.textMuted;
      next.set(id, {
        labels: curve.points.map((_, i) => String(i)),
        datasets: [
          {
            data: values,
            borderColor: stroke,
            backgroundColor: 'transparent',
            fill: false,
            pointBackgroundColor: stroke,
          },
        ],
      });
    }
    this.sparkDataById = next;
  }

  hasCurve(strategy: Strategy): boolean {
    const curve = this.curvesById.get(strategy.id);
    return !!curve && curve.points.length > 0;
  }

  curveLastPnl(strategy: Strategy): number | null {
    const curve = this.curvesById.get(strategy.id);
    if (!curve || curve.points.length === 0) return null;
    return curve.points[curve.points.length - 1].cum_pnl;
  }

  openEquityChart(strategy: Strategy): void {
    const curve = this.curvesById.get(strategy.id);
    if (!curve || curve.points.length === 0) return;
    const data: EquityCurveDialogData = { strategy_id: strategy.id, name: strategy.name, points: curve.points };
    this.dialog.open(EquityCurveDialogComponent, {
      width: '90vw',
      maxWidth: '900px',
      data,
      panelClass: 'equity-curve-dialog',
    });
  }

  createStrategy(): void {
    this.router.navigate(['/dashboard/strategies/new']);
  }

  browseTemplates(): void {
    const dialogRef = this.dialog.open(TemplateGalleryModalComponent, {
      width: '90vw',
      maxWidth: '1200px',
      maxHeight: '90vh',
      panelClass: 'template-gallery-dialog'
    });

    dialogRef.afterClosed().subscribe((clonedStrategy) => {
      if (clonedStrategy) {
        // Template was cloned, refresh the list
        this.loadStrategies();
        this.loadEquityCurves();
      }
    });
  }

  viewStrategy(strategy: Strategy): void {
    this.router.navigate(['/dashboard/strategies', strategy.id]);
  }

  editStrategy(strategy: Strategy): void {
    this.router.navigate(['/dashboard/strategies', strategy.id, 'edit']);
  }

  deleteStrategy(strategy: Strategy): void {
    if (confirm(`Are you sure you want to delete "${strategy.name}"?`)) {
      this.strategyService.deleteStrategy(strategy.id).subscribe({
        next: () => {
          this.loadStrategies();
          this.loadEquityCurves();
        },
        error: (error) => {
          console.error('Error deleting strategy:', error);
          alert('Failed to delete strategy');
        }
      });
    }
  }

  toggleStrategyStatus(strategy: Strategy): void {
    this.strategyService.toggleStrategy(strategy.id).subscribe({
      next: () => {
        this.loadStrategies();
      },
      error: (error) => {
        console.error('Error updating strategy:', error);
        alert('Failed to update strategy status');
      }
    });
  }

  openStream(strategy: Strategy): void {
    this.activeStreamStrategy = strategy;
    this.streamSidenav.open();
  }

  closeStream(): void {
    this.streamSidenav.close();
  }

  getStatusColor(isActive: boolean): string {
    return isActive ? 'primary' : 'accent';
  }

  getSymbolsList(strategy: Strategy): string {
    return strategy.instruments?.join(', ') || 'N/A';
  }
}
