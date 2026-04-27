import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule, CurrencyPipe } from '@angular/common';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { MatTableModule } from '@angular/material/table';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatBadgeModule } from '@angular/material/badge';
import { interval, Subscription } from 'rxjs';
import { switchMap, startWith } from 'rxjs/operators';
import { environment } from '../../../environments/environment';

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
    CurrencyPipe,
  ],
  templateUrl: './positions.component.html',
  styleUrls: ['./positions.component.scss']
})
export class PositionsComponent implements OnInit, OnDestroy {
  displayedColumns: string[] = ['symbol', 'quantity', 'entryPrice', 'currentPrice', 'pnl', 'pnlPercent', 'openedAt'];
  positions: DbPosition[] = [];
  loading = true;
  private sub?: Subscription;
  private apiUrl = `${environment.apiUrl}/trading/positions`;
  poll_interval: number = 10000;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.sub = interval(this.poll_interval).pipe(
      startWith(0),
      switchMap(() => this.http.get<DbPosition[]>(this.apiUrl, { headers: this.headers() }))
    ).subscribe({
      next: (positions) => {
        this.positions = positions.filter(p => p.qty > 0);
        this.loading = false;
      },
      error: () => { this.loading = false; }
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
