import { Component, OnInit, OnDestroy, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule, CurrencyPipe } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { MatTableModule } from '@angular/material/table';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatBadgeModule } from '@angular/material/badge';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Subscription } from 'rxjs';
import { environment } from '../../../environments/environment';
import { PositionChartDialogComponent } from './position-chart-dialog/position-chart-dialog.component';

export interface DbPosition {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  cost_basis: number;
  date_acquired: string;
  api: string;
}

@Component({
  selector: 'app-positions',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatBadgeModule,
    MatDialogModule,
    MatTooltipModule,
    CurrencyPipe,
  ],
  templateUrl: './positions.component.html',
  styleUrls: ['./positions.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PositionsComponent implements OnInit, OnDestroy {
  displayedColumns: string[] = ['symbol', 'quantity', 'entryPrice', 'currentPrice', 'pnl', 'pnlPercent', 'openedAt'];
  positions: DbPosition[] = [];
  loading = true;
  private sub?: Subscription;
  private apiUrl = `${environment.apiUrl}/trading/positions`;

  constructor(
    private http: HttpClient,
    private dialog: MatDialog,
    private cdr: ChangeDetectorRef,
  ) {}

  openChart(p: DbPosition): void {
    this.dialog.open(PositionChartDialogComponent, {
      data: {
        symbol: p.symbol,
        avg_entry_price: p.avg_entry_price,
        date_acquired: p.date_acquired,
        qty: p.qty,
      },
      panelClass: 'position-chart-panel',
      autoFocus: false,
    });
  }

  ngOnInit(): void {
    this.loadPositions();
  }

  refresh(): void {
    this.loadPositions();
  }

  private loadPositions(): void {
    this.sub?.unsubscribe();
    this.loading = true;
    this.cdr.markForCheck();
    this.sub = this.http.get<DbPosition[]>(this.apiUrl, { headers: this.headers() }).subscribe({
      next: (positions) => {
        this.positions = positions.filter(p => p.qty > 0);
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.loading = false;
        this.cdr.markForCheck();
      }
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  pnlPercent(p: DbPosition): number {
    const cost = p.avg_entry_price * p.qty;
    return cost > 0 ? +((p.unrealized_pl / cost) * 100).toFixed(2) : 0;
  }

  private headers(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({ 'Authorization': token ? `Bearer ${token}` : '' });
  }
}
