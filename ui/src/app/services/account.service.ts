import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface AccountInfo {
  account_number: string;
  cash: number;
  buying_power: number;
  portfolio_value: number;
  equity: number;
  open_pl: number;
  api: string;  // "Tradier Sandbox" or "Tradier Live" — Tradier is the only broker
}

export interface Position {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  cost_basis?: number;
  date_acquired?: string;
  api: string;
}

@Injectable({
  providedIn: 'root'
})
export class AccountService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/trading`;

  // Observable streams for real-time updates
  private accountSubject = new BehaviorSubject<AccountInfo | null>(null);
  public account$ = this.accountSubject.asObservable();

  private positionsSubject = new BehaviorSubject<Position[]>([]);
  public positions$ = this.positionsSubject.asObservable();

  private getHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  /**
   * Get account information from the appropriate API based on trading mode.
   * - Paper mode: Returns Tradier Sandbox account
   * - Live mode: Returns Tradier Live account
   */
  getAccount(): Observable<AccountInfo> {
    return this.http.get<AccountInfo>(
      `${this.apiUrl}/account`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(account => this.accountSubject.next(account))
    );
  }

  /**
   * Get positions from the appropriate API based on trading mode.
   * - Paper mode: Returns Tradier Sandbox positions
   * - Live mode: Returns Tradier Live positions
   */
  getPositions(): Observable<Position[]> {
    return this.http.get<Position[]>(
      `${this.apiUrl}/positions`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(positions => this.positionsSubject.next(positions))
    );
  }

  /**
   * Refresh all account data (account info and positions)
   */
  refreshData(): void {
    this.getAccount().subscribe({
      error: (err) => console.error('Failed to fetch account:', err)
    });
    this.getPositions().subscribe({
      error: (err) => console.error('Failed to fetch positions:', err)
    });
  }
}
