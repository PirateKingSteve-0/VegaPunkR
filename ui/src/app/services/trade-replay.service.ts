import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** One recorded quote of the option contract. `bid` is what the exit rules read. */
export interface ReplayPoint {
  t: number;
  bid: number;
  ask: number;
}

export interface ReplayBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface ReplayVwap {
  t: number;
  vwap: number;
  wiggle: number;
}

/** Recomputed offline from the recorded ticks — the engine never stores these. */
export interface ReplayContext {
  recomputed: boolean;
  vwap?: number;
  wiggle?: number;
  stretch?: number;
  above_vwap?: boolean;
  spot?: number;
  volume_ratio?: number;
  broker_delta?: number;
  broker_delta_age_min?: number | null;
}

export interface TradeReplay {
  /** The round trip: the buy trade and the sell that closed it. A Position row is
   *  reused across re-entries into the same contract, so it does not identify one. */
  trade_id: number | null;
  buy_trade_id: number;
  position_id: number;
  generated_at: string;
  /** True while the position is still open: the path stops at the last recorded tick. */
  partial: boolean;
  contract: {
    symbol: string;
    price_series: 'bid';
    points: ReplayPoint[];
    levels: {
      stop?: number;
      target?: number;
      trail_arms_at?: number;
      trail_gives_back_pct?: number;
    };
  };
  underlying: { symbol: string; bars: ReplayBar[]; vwap: ReplayVwap[] };
  entry: { t: number; price: number; qty: number; gates: string[]; context: ReplayContext };
  exit: { t: number; price: number; reason: string | null; pnl: number } | null;
  facts: {
    strategy_id: number | null;
    strategy_name: string | null;
    mfe_price: number | null;
    mae_price: number | null;
    hold_s: number | null;
  };
}

/**
 * Fetches one position's recorded price path.
 *
 * There is no HTTP interceptor in this app — every service builds its own
 * Authorization header from localStorage or the call 401s.
 */
@Injectable({ providedIn: 'root' })
export class TradeReplayService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/trades/replay`;

  private headers(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({ Authorization: token ? `Bearer ${token}` : '' });
  }

  /**
   * `openedAt` disambiguates the same strike traded more than once in a day.
   * A 404 means that session was never recorded — callers fall back to the
   * basic Tradier chart rather than showing an error.
   */
  get(symbol: string, openedAt?: string): Observable<TradeReplay> {
    let params = new HttpParams().set('symbol', symbol);
    if (openedAt) params = params.set('opened_at', openedAt);
    return this.http.get<TradeReplay>(this.apiUrl, { headers: this.headers(), params });
  }
}
