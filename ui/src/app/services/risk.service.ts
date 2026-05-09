import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface AccountRiskStatus {
  today_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  account_size: number;
  daily_loss_limit_pct: number;
  daily_loss_limit: number;
  daily_loss_remaining: number;
  pct_consumed: number;
  risk_status: 'OK' | 'WARNING' | 'HALTED';
  entries_halted: boolean;
}

@Injectable({ providedIn: 'root' })
export class RiskService {
  private http = inject(HttpClient);
  private base = `${environment.apiUrl}/risk-events`;

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
    );
  }
}
