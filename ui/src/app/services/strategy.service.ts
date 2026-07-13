import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Strategy, StrategyTemplate, CreateStrategyRequest, UpdateStrategyRequest } from '../models/strategy.model';
import { AuthService } from './auth.service';

@Injectable({
  providedIn: 'root'
})
export class StrategyService {
  private http = inject(HttpClient);
  private authService = inject(AuthService);

  private apiUrl = 'http://localhost:8000/api/v1';

  private getHeaders(): HttpHeaders {
    const token = this.authService.getToken();
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    });
  }

  // User strategy endpoints
  getStrategies(): Observable<Strategy[]> {
    return this.http.get<Strategy[]>(`${this.apiUrl}/strategies`, {
      headers: this.getHeaders()
    });
  }

  getStrategy(id: number): Observable<Strategy> {
    return this.http.get<Strategy>(`${this.apiUrl}/strategies/${id}`, {
      headers: this.getHeaders()
    });
  }

  createStrategy(strategy: CreateStrategyRequest): Observable<Strategy> {
    return this.http.post<Strategy>(`${this.apiUrl}/strategies`, strategy, {
      headers: this.getHeaders()
    });
  }

  updateStrategy(id: number, strategy: UpdateStrategyRequest): Observable<Strategy> {
    return this.http.put<Strategy>(`${this.apiUrl}/strategies/${id}`, strategy, {
      headers: this.getHeaders()
    });
  }

  deleteStrategy(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/strategies/${id}`, {
      headers: this.getHeaders()
    });
  }

  toggleStrategy(id: number): Observable<Strategy> {
    return this.http.post<Strategy>(`${this.apiUrl}/strategies/${id}/toggle`, {}, {
      headers: this.getHeaders()
    });
  }

  // Strategy template endpoints (read-only)
  getTemplates(): Observable<StrategyTemplate[]> {
    return this.http.get<StrategyTemplate[]>(`${this.apiUrl}/strategies/templates`, {
      headers: this.getHeaders()
    });
  }

  getTemplate(templateId: string): Observable<StrategyTemplate> {
    return this.http.get<StrategyTemplate>(`${this.apiUrl}/strategies/templates/${templateId}`, {
      headers: this.getHeaders()
    });
  }

  cloneTemplate(templateId: string): Observable<Strategy> {
    return this.http.post<Strategy>(`${this.apiUrl}/strategies/templates/${templateId}/clone`, {}, {
      headers: this.getHeaders()
    });
  }

  getEquityCurves(): Observable<EquityCurve[]> {
    return this.http.get<EquityCurve[]>(`${this.apiUrl}/performance/equity-curves`, {
      headers: this.getHeaders()
    });
  }

  /**
   * Closed trades from the engine's own fill records.
   *
   * Replaces Tradier's /account/gainloss as the P&L source. That report's cost basis
   * is corrupt when a contract is round-tripped repeatedly in a session — on
   * 2026-07-13 it reported -21,057 for a day that actually lost -1,851 — and it is
   * paginated, so a busy day was truncated on top of being wrong.
   */
  getClosedTrades(period: string): Observable<ClosedTrade[]> {
    return this.http.get<ClosedTrade[]>(`${this.apiUrl}/performance/closed-trades`, {
      headers: this.getHeaders(),
      params: new HttpParams().set('period', period),
    });
  }
}

export interface ClosedTrade {
  close_date: string;
  open_date: string;
  cost: number;
  proceeds: number;
  gain_loss: number;
  gain_loss_percent: number;
  quantity: number;
  symbol: string;
  term: number;
  commission: number;
  fees: number;
  net_pnl: number;
}

export interface EquityCurvePoint {
  t: string;          // ISO timestamp of trade close
  cum_pnl: number;    // running sum of realized PnL from zero
  trade_pnl: number;  // pnl of the individual trade at this point
}

export interface EquityCurve {
  strategy_id: number;
  name: string;
  points: EquityCurvePoint[];
}
