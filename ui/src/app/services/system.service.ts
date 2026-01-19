import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';
import { tap } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface EnvironmentSettings {
  environment: 'dev' | 'test' | 'prod';
  trading_mode: 'paper' | 'live';
  database: string;
  trading_api: string;
  can_toggle_trading_mode: boolean;
  warning: string | null;
}

export interface EnvironmentUpdateResponse {
  success: boolean;
  environment: string;
  database: string;
  message: string;
}

export interface TradingModeUpdateResponse {
  success: boolean;
  trading_mode: string;
  trading_api: string;
  message: string;
  warning: string | null;
}

@Injectable({
  providedIn: 'root'
})
export class SystemService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/system`;

  // Observable stream for environment settings
  private settingsSubject = new BehaviorSubject<EnvironmentSettings | null>(null);
  public settings$ = this.settingsSubject.asObservable();

  private getHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  /**
   * Get current environment and trading mode settings
   */
  getEnvironmentSettings(): Observable<EnvironmentSettings> {
    return this.http.get<EnvironmentSettings>(
      `${this.apiUrl}/environment`,
      { headers: this.getHeaders() }
    ).pipe(
      tap(settings => {
        console.log('📊 Current Environment Settings:', {
          database: settings.database,
          environment: settings.environment,
          trading_api: settings.trading_api,
          trading_mode: settings.trading_mode
        });
        this.settingsSubject.next(settings);
      })
    );
  }

  /**
   * Switch database environment (dev/test/prod)
   * No server restart required - changes instantly
   */
  setEnvironment(env: 'dev' | 'test' | 'prod'): Observable<EnvironmentUpdateResponse> {
    return this.http.post<EnvironmentUpdateResponse>(
      `${this.apiUrl}/environment`,
      { environment: env },
      { headers: this.getHeaders() }
    ).pipe(
      tap(response => {
        console.log('🔄 Database Environment Switched:', {
          environment: response.environment,
          database: response.database,
          message: response.message
        });
        // Refresh settings after update
        this.getEnvironmentSettings().subscribe();
      })
    );
  }

  /**
   * Switch trading mode (paper/live)
   * No server restart required - changes instantly
   *
   * WARNING: Live mode uses real money!
   */
  setTradingMode(mode: 'paper' | 'live'): Observable<TradingModeUpdateResponse> {
    return this.http.post<TradingModeUpdateResponse>(
      `${this.apiUrl}/trading-mode`,
      { mode },
      { headers: this.getHeaders() }
    ).pipe(
      tap(response => {
        if (mode === 'live') {
          console.error('⚠️  TRADING MODE: LIVE', {
            trading_mode: response.trading_mode,
            trading_api: response.trading_api,
            warning: response.warning
          });
        } else {
          console.log('🔄 Trading Mode Switched:', {
            trading_mode: response.trading_mode,
            trading_api: response.trading_api,
            message: response.message
          });
        }
        // Refresh settings after update
        this.getEnvironmentSettings().subscribe();
      })
    );
  }

  /**
   * Health check endpoint
   */
  healthCheck(): Observable<any> {
    return this.http.get(`${this.apiUrl}/health`);
  }
}
