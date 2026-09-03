import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';

/** What happens to positions that are already open when you call it a day.
 *  Both modes stop new entries — that is the whole point of the halt — and
 *  differ only here. */
export type TradingHaltMode = 'ride' | 'flatten';

export interface AccountRiskStatus {
  today_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  account_size: number;
  daily_loss_limit_pct: number;
  daily_loss_limit: number;
  daily_loss_remaining: number;
  pct_consumed: number;
  /** The daily-LOSS-cap state only. A manual halt is reported separately in
   *  `trading_halted` so a deliberate stop never renders as a risk breach. */
  risk_status: 'OK' | 'WARNING' | 'HALTED';
  trading_halted: boolean;
  trading_halt_mode: TradingHaltMode | null;
  /** True when EITHER reason is blocking entries. */
  entries_halted: boolean;
}

export interface TradingHaltStatus {
  trading_halted: boolean;
  trading_halt_mode: TradingHaltMode | null;
  trading_halted_on: string | null;
  message: string;
}

@Injectable({ providedIn: 'root' })
export class RiskService {
  private http = inject(HttpClient);
  private base = `${environment.apiUrl}/risk-events`;
  private authBase = `${environment.apiUrl}/auth`;

  /** Shared halt state. The toolbar control and the Overview session card both
   *  read this signal, so stopping trading from either surface updates both
   *  without a round trip or a refresh. */
  readonly haltStatus = signal<TradingHaltStatus | null>(null);

  private getHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  getAccountStatus(): Observable<AccountRiskStatus> {
    return this.http.get<AccountRiskStatus>(
      `${this.base}/account-status`,
      { headers: this.getHeaders() }
    ).pipe(
      // The account-status payload already carries the halt, so keep the
      // shared signal fresh from it rather than firing a second request.
      tap(s => this.haltStatus.set({
        trading_halted: s.trading_halted,
        trading_halt_mode: s.trading_halt_mode,
        trading_halted_on: null,
        message: '',
      }))
    );
  }

  getTradingHalt(): Observable<TradingHaltStatus> {
    return this.http.get<TradingHaltStatus>(
      `${this.authBase}/me/trading-halt`,
      { headers: this.getHeaders() }
    ).pipe(tap(s => this.haltStatus.set(s)));
  }

  /** Stop trading for the rest of the market day. Re-postable with a different
   *  mode — switching from 'ride' to 'flatten' mid-session is normal. */
  setTradingHalt(mode: TradingHaltMode): Observable<TradingHaltStatus> {
    return this.http.post<TradingHaltStatus>(
      `${this.authBase}/me/trading-halt`,
      { mode },
      { headers: this.getHeaders() }
    ).pipe(tap(s => this.haltStatus.set(s)));
  }

  /** Resume for the rest of today. Lifts only the manual halt — the
   *  daily-loss cap and every other gate are untouched. */
  clearTradingHalt(): Observable<TradingHaltStatus> {
    return this.http.delete<TradingHaltStatus>(
      `${this.authBase}/me/trading-halt`,
      { headers: this.getHeaders() }
    ).pipe(tap(s => this.haltStatus.set(s)));
  }
}
