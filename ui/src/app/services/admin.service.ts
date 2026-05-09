import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface AdminUserSummary {
  id: number;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  last_login: string | null;
  active_strategies: number;
  open_positions: number;
  today_pnl: number;
  last_trade_at: string | null;
}

export interface AdminUserDashboard {
  user: {
    id: number;
    email: string;
    name: string;
    role: string;
    is_active: boolean;
    last_login: string | null;
    selected_environment: string | null;
    selected_trading_mode: string | null;
  };
  account: {
    account_size_usd: number;
    daily_loss_limit_pct: number;
  };
  session_status: {
    today_pnl: number;
    daily_loss_limit: number;
    daily_loss_remaining: number;
    pct_consumed: number;
    risk_status: 'OK' | 'WARNING' | 'HALTED';
    entries_halted: boolean;
  };
  counts: {
    active_strategies: number;
    open_positions: number;
  };
  last_trade_at: string | null;
}

@Injectable({ providedIn: 'root' })
export class AdminService {
  private http = inject(HttpClient);
  private base = `${environment.apiUrl}/admin`;

  private getHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  listUsers(): Observable<AdminUserSummary[]> {
    return this.http.get<AdminUserSummary[]>(
      `${this.base}/users`,
      { headers: this.getHeaders() }
    );
  }

  getUserDashboard(userId: number): Observable<AdminUserDashboard> {
    return this.http.get<AdminUserDashboard>(
      `${this.base}/users/${userId}/dashboard`,
      { headers: this.getHeaders() }
    );
  }

  setUserRole(userId: number, role: string): Observable<unknown> {
    return this.http.patch(
      `${this.base}/users/${userId}/role`,
      { role },
      { headers: this.getHeaders() }
    );
  }
}
