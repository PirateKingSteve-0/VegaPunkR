import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** One row of the engine's own audit log (`system_events`). */
export interface SystemEvent {
  id: number;
  event_type: string;
  severity: string;
  title: string;
  detail: string | null;
  symbol: string | null;
  strategy_id: number | null;
  event_data: Record<string, any>;
  /** UTC ISO-8601, stamped by the API. */
  created_at: string;
}

export interface EventPage {
  total: number;
  page: number;
  limit: number;
  events: SystemEvent[];
}

export interface EventQuery {
  limit?: number;
  page?: number;
  eventType?: string;
  severity?: string;
  symbol?: string;
  /** yyyy-mm-dd, inclusive. The API compares against `created_at`. */
  start?: string;
  end?: string;
}

@Injectable({ providedIn: 'root' })
export class EventService {
  private http = inject(HttpClient);
  private base = `${environment.apiUrl}/events`;

  private getHeaders(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'Authorization': token ? `Bearer ${token}` : ''
    });
  }

  getEvents(q: EventQuery = {}): Observable<EventPage> {
    let params = new HttpParams()
      .set('page', q.page ?? 1)
      .set('limit', q.limit ?? 50);
    if (q.eventType) params = params.set('event_type', q.eventType);
    if (q.severity) params = params.set('severity', q.severity);
    if (q.symbol) params = params.set('symbol', q.symbol);
    if (q.start) params = params.set('start', q.start);
    if (q.end) params = params.set('end', q.end);
    return this.http.get<EventPage>(this.base, { headers: this.getHeaders(), params });
  }
}
