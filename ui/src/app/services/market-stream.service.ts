import { Injectable } from '@angular/core';
import { Subject, BehaviorSubject } from 'rxjs';

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface StreamEvent {
  type: 'quote' | 'trade' | 'summary' | 'timesale' | 'tradex' | 'heartbeat';
  symbol: string;
  // quote fields
  bid?: number;
  bidsz?: number;
  bidexch?: string;
  biddate?: string;
  ask?: number;
  asksz?: number;
  askexch?: string;
  askdate?: string;
  // trade fields
  exch?: string;
  price?: string;
  size?: string;
  cvol?: string;
  date?: string;
  last?: string;
}

@Injectable({ providedIn: 'root' })
export class MarketStreamService {
  private readonly apiUrl = 'http://localhost:8000/api/v1';

  private eventSource: EventSource | null = null;
  private subscribedSymbols = new Set<string>();

  private _events = new Subject<StreamEvent>();
  private _status = new BehaviorSubject<ConnectionStatus>('disconnected');

  readonly events$ = this._events.asObservable();
  readonly status$ = this._status.asObservable();

  connect(symbols: string[]): void {
    const current = this._status.value;
    if (current === 'connected' || current === 'connecting') {
      symbols.forEach(s => this.subscribedSymbols.add(s));
      // Re-open with updated symbol list if already connected
      if (current === 'connected') this._reopen();
      return;
    }

    this._status.next('connecting');
    symbols.forEach(s => this.subscribedSymbols.add(s));
    this._open();
  }

  addSymbols(symbols: string[]): void {
    const hadNew = symbols.some(s => !this.subscribedSymbols.has(s));
    symbols.forEach(s => this.subscribedSymbols.add(s));
    if (hadNew && this._status.value === 'connected') {
      this._reopen();
    }
  }

  disconnect(): void {
    this._close();
    this.subscribedSymbols.clear();
    this._status.next('disconnected');
  }

  private _open(): void {
    const token = localStorage.getItem('access_token') || '';
    const symbolsParam = Array.from(this.subscribedSymbols).join(',');
    const url = `${this.apiUrl}/tradier/stream/events?symbols=${encodeURIComponent(symbolsParam)}&token=${encodeURIComponent(token)}`;

    this.eventSource = new EventSource(url);

    this.eventSource.onopen = () => {
      this._status.next('connected');
    };

    this.eventSource.onmessage = (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as StreamEvent;
        if (data.type !== 'heartbeat') {
          this._events.next(data);
        }
      } catch {
        // ignore malformed lines
      }
    };

    this.eventSource.onerror = () => {
      // EventSource reconnects automatically on transient errors;
      // only mark as error if it moves to CLOSED state
      if (this.eventSource?.readyState === EventSource.CLOSED) {
        this._status.next('error');
        this.eventSource = null;
      }
    };
  }

  private _close(): void {
    this.eventSource?.close();
    this.eventSource = null;
  }

  private _reopen(): void {
    this._close();
    this._open();
  }
}
