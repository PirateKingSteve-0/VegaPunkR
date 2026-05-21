import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
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
