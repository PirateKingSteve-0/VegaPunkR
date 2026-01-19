import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface SchwabBalances {
  cash: number;
  buying_power: number;
  equity: number;
  market_value: number;
  day_trading_buying_power: number;
}

export interface SchwabPosition {
  symbol: string;
  quantity: number;
  side: 'LONG' | 'SHORT';
  current_price: number;
  average_cost: number;
  market_value: number;
  unrealized_pnl: number;
  pnl_percentage: number;
}

export interface SchwabAuthStatus {
  authenticated: boolean;
}

@Injectable({
  providedIn: 'root'
})
export class SchwabService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/schwab`;

  // Observable streams for real-time updates
  private authStatusSubject = new BehaviorSubject<boolean>(false);
  public authStatus$ = this.authStatusSubject.asObservable();

  private balancesSubject = new BehaviorSubject<SchwabBalances | null>(null);
  public balances$ = this.balancesSubject.asObservable();

  private positionsSubject = new BehaviorSubject<SchwabPosition[]>([]);
  public positions$ = this.positionsSubject.asObservable();

  private getHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  /**
   * Check Schwab API authentication status
   */
  checkAuthStatus(): Observable<SchwabAuthStatus> {
    return this.http.get<SchwabAuthStatus>(
      `${this.apiUrl}/auth/status`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(status => this.authStatusSubject.next(status.authenticated))
    );
  }

  /**
   * Get simplified account balances
   */
  getAccountBalances(): Observable<SchwabBalances> {
    return this.http.get<SchwabBalances>(
      `${this.apiUrl}/account/balances`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(balances => this.balancesSubject.next(balances))
    );
  }

  /**
   * Get current positions from Schwab account
   */
  getPositions(): Observable<SchwabPosition[]> {
    return this.http.get<SchwabPosition[]>(
      `${this.apiUrl}/account/positions`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(positions => this.positionsSubject.next(positions))
    );
  }

  /**
   * Refresh all Schwab data (balances and positions)
   */
  refreshData(): void {
    this.getAccountBalances().subscribe({
      error: (err) => console.error('Failed to fetch Schwab balances:', err)
    });
    this.getPositions().subscribe({
      error: (err) => console.error('Failed to fetch Schwab positions:', err)
    });
  }
}
