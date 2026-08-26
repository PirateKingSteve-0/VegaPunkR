import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface TradierBalances {
  total_equity: number;
  total_cash: number;
  open_pl: number;
  close_pl: number;
  market_value: number;
  long_market_value: number;
  short_market_value: number;
  pending_orders_count: number;
  account_number: string;
  account_type: string;
  [key: string]: any;
}

export interface BalanceSnapshot {
  date: string;
  value: number;
}

export interface HistoricalBalances {
  balances: BalanceSnapshot[];
  delta: number;
  deltaPercent: number;
}

export interface ClosedPosition {
  close_date: string;
  open_date: string;
  cost: number;
  proceeds: number;
  gain_loss: number;
  gain_loss_percent: number;
  quantity: number;
  symbol: string;
  term: number;
  // Populated client-side by reconciling /account/history events
  commission?: number;
  fees?: number;
  net_pnl?: number;
}

export interface TradeEvent {
  date: string;
  amount: number;
  type: string;
  trade?: {
    commission?: number;
    description?: string;
    price?: number;
    quantity?: number;
    symbol?: string;
    trade_type?: string;
  };
  [key: string]: any;
}

// BalancePeriod is Tradier's own enum and now lives with the range model, which
// is what decides which bucket a given range needs. Re-exported so existing
// importers of this service keep working.
import type { BalancePeriod } from '../models/date-range';
export type { BalancePeriod };

export interface HistoryBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type HistoryInterval = 'daily' | 'weekly' | 'monthly';

export interface IntradayBar {
  time: string;
  timestamp?: number;
  price?: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export type IntradayInterval = '1min' | '5min' | '15min';
export type SessionFilter = 'open' | 'all';

export interface WatchlistSummary {
  name: string;
  id: string;
  public_id: string;
}

export interface WatchlistItem {
  symbol: string;
  id: string;
}

export interface Watchlist {
  name: string;
  id: string;
  public_id: string;
  items: WatchlistItem[];
}

export interface Quote {
  symbol: string;
  description?: string;
  last?: number;
  change?: number;
  change_percentage?: number;
  prevclose?: number;
  volume?: number;
  bid?: number;
  ask?: number;
  [key: string]: any;
}

@Injectable({ providedIn: 'root' })
export class TradierService {
  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/tradier`;

  private headers(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({ Authorization: token ? `Bearer ${token}` : '' });
  }

  getBalances(): Observable<TradierBalances> {
    return this.http.get<TradierBalances>(`${this.apiUrl}/account/balances`, {
      headers: this.headers(),
    });
  }

  /**
   * Daily account-value snapshots. `period` must be one of Tradier's buckets —
   * use `brokerPeriodFor()` to pick the narrowest one covering your range, then
   * slice the returned bars down. The broker cannot filter to a date range and
   * has no intraday bucket (docs/tradier/accounts/balance_overtime.md).
   */
  getHistoricalBalances(period: BalancePeriod = 'MONTH'): Observable<HistoricalBalances> {
    const params = new HttpParams().set('period', period);
    return this.http.get<HistoricalBalances>(`${this.apiUrl}/account/historical-balances`, {
      headers: this.headers(),
      params,
    });
  }

  getMarketHistory(
    symbol: string,
    interval: HistoryInterval = 'daily',
    start?: string,
    end?: string,
  ): Observable<HistoryBar[]> {
    let params = new HttpParams().set('symbol', symbol).set('interval', interval);
    if (start) params = params.set('start', start);
    if (end) params = params.set('end', end);
    return this.http.get<HistoryBar[]>(`${this.apiUrl}/market/history`, {
      headers: this.headers(),
      params,
    });
  }

  getMarketTimesales(
    symbol: string,
    interval: IntradayInterval = '5min',
    start?: string,
    end?: string,
    session_filter: SessionFilter = 'all',
  ): Observable<IntradayBar[]> {
    let params = new HttpParams()
      .set('symbol', symbol)
      .set('interval', interval)
      .set('session_filter', session_filter);
    if (start) params = params.set('start', start);
    if (end) params = params.set('end', end);
    return this.http.get<IntradayBar[]>(`${this.apiUrl}/market/timesales`, {
      headers: this.headers(),
      params,
    });
  }

  getTradeEvents(symbol: string, start?: string, end?: string, limit = 100): Observable<TradeEvent[]> {
    let params = new HttpParams()
      .set('type', 'trade')
      .set('symbol', symbol)
      .set('exact_match', 'true')
      .set('limit', limit);
    if (start) params = params.set('start', start);
    if (end) params = params.set('end', end);
    return this.http.get<TradeEvent[]>(`${this.apiUrl}/account/history`, {
      headers: this.headers(),
      params,
    });
  }

  getGainLoss(page = 1, limit = 100): Observable<ClosedPosition[]> {
    const params = new HttpParams().set('page', page).set('limit', limit);
    return this.http.get<ClosedPosition[]>(`${this.apiUrl}/account/gainloss`, {
      headers: this.headers(),
      params,
    });
  }

  getAccountHistory(
    type?: 'trade' | 'option' | 'fee' | 'dividend' | 'ach' | 'interest',
    start?: string,
    end?: string,
    limit = 500,
    page = 1,
  ): Observable<TradeEvent[]> {
    let params = new HttpParams().set('limit', limit).set('page', page);
    if (type) params = params.set('type', type);
    if (start) params = params.set('start', start);
    if (end) params = params.set('end', end);
    return this.http.get<TradeEvent[]>(`${this.apiUrl}/account/history`, {
      headers: this.headers(),
      params,
    });
  }

  getWatchlists(): Observable<WatchlistSummary[]> {
    return this.http.get<WatchlistSummary[]>(`${this.apiUrl}/watchlists`, {
      headers: this.headers(),
    });
  }

  getWatchlist(watchlistId: string): Observable<Watchlist> {
    return this.http.get<Watchlist>(`${this.apiUrl}/watchlists/${encodeURIComponent(watchlistId)}`, {
      headers: this.headers(),
    });
  }

  createWatchlist(name: string, symbols: string[] = []): Observable<Watchlist> {
    return this.http.post<Watchlist>(
      `${this.apiUrl}/watchlists`,
      { name, symbols },
      { headers: this.headers() },
    );
  }

  updateWatchlist(watchlistId: string, name: string, symbols?: string[]): Observable<Watchlist> {
    const body: { name: string; symbols?: string[] } = { name };
    if (symbols !== undefined) body.symbols = symbols;
    return this.http.put<Watchlist>(
      `${this.apiUrl}/watchlists/${encodeURIComponent(watchlistId)}`,
      body,
      { headers: this.headers() },
    );
  }

  deleteWatchlist(watchlistId: string): Observable<WatchlistSummary[]> {
    return this.http.delete<WatchlistSummary[]>(
      `${this.apiUrl}/watchlists/${encodeURIComponent(watchlistId)}`,
      { headers: this.headers() },
    );
  }

  addWatchlistSymbols(watchlistId: string, symbols: string[]): Observable<Watchlist> {
    return this.http.post<Watchlist>(
      `${this.apiUrl}/watchlists/${encodeURIComponent(watchlistId)}/symbols`,
      { symbols },
      { headers: this.headers() },
    );
  }

  getQuotes(symbols: string[]): Observable<Quote[]> {
    const params = new HttpParams().set('symbols', symbols.join(','));
    return this.http.get<Quote[]>(`${this.apiUrl}/market/quotes`, {
      headers: this.headers(),
      params,
    });
  }

  removeWatchlistSymbol(watchlistId: string, symbol: string): Observable<Watchlist> {
    return this.http.delete<Watchlist>(
      `${this.apiUrl}/watchlists/${encodeURIComponent(watchlistId)}/symbols/${encodeURIComponent(symbol)}`,
      { headers: this.headers() },
    );
  }
}
