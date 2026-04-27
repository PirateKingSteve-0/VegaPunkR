import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTableModule } from '@angular/material/table';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { Subject } from 'rxjs';
import { debounceTime, takeUntil } from 'rxjs/operators';
import { environment } from '../../../environments/environment';

export interface SystemEvent {
  id: number;
  event_type: string;
  severity: string;
  title: string;
  detail: string | null;
  symbol: string | null;
  strategy_id: number | null;
  event_data: Record<string, any>;
  created_at: string;
}

export const EVENT_TYPES = [
  'ORDER_PLACED',
  'ORDER_FAILED',
  'POSITION_OPENED',
  'POSITION_CLOSED',
  'STRATEGY_STARTED',
  'STRATEGY_STOPPED',
  'STRATEGY_ERROR',
  'RISK_ALERT',
];

@Component({
  selector: 'app-trades',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatProgressSpinnerModule,
    MatPaginatorModule,
    DatePipe,
  ],
  templateUrl: './trades.component.html',
  styleUrls: ['./trades.component.scss']
})
export class TradesComponent implements OnInit, OnDestroy {
  displayedColumns: string[] = ['created_at', 'event_type', 'severity', 'title', 'symbol'];
  events: SystemEvent[] = [];
  total = 0;
  loading = false;

  pageSize = 50;
  pageIndex = 0;

  eventTypeOptions = EVENT_TYPES;
  eventTypeControl = new FormControl('');
  symbolControl = new FormControl('');
  startDateControl = new FormControl<Date | null>(null);
  endDateControl = new FormControl<Date | null>(null);

  private destroy$ = new Subject<void>();
  private apiUrl = `${environment.apiUrl}/events`;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.eventTypeControl.valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe(() => { this.pageIndex = 0; this.loadEvents(); });

    this.symbolControl.valueChanges.pipe(debounceTime(400), takeUntil(this.destroy$))
      .subscribe(() => { this.pageIndex = 0; this.loadEvents(); });

    this.startDateControl.valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe(() => { this.pageIndex = 0; this.loadEvents(); });

    this.endDateControl.valueChanges.pipe(takeUntil(this.destroy$))
      .subscribe(() => { this.pageIndex = 0; this.loadEvents(); });

    this.loadEvents();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadEvents(): void {
    this.loading = true;

    let params = new HttpParams()
      .set('page', this.pageIndex + 1)
      .set('limit', this.pageSize);

    const eventType = this.eventTypeControl.value;
    if (eventType) params = params.set('event_type', eventType);

    const symbol = this.symbolControl.value?.trim();
    if (symbol) params = params.set('symbol', symbol);

    const start = this.startDateControl.value;
    if (start) params = params.set('start', this.formatDate(start));

    const end = this.endDateControl.value;
    if (end) params = params.set('end', this.formatDate(end));

    this.http.get<{ total: number; events: SystemEvent[] }>(this.apiUrl, {
      headers: this.headers(),
      params,
    }).subscribe({
      next: ({ total, events }) => {
        this.total = total;
        this.events = events;
        this.loading = false;
      },
      error: () => { this.loading = false; }
    });
  }

  onPage(event: PageEvent): void {
    this.pageIndex = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadEvents();
  }

  formatEventType(type: string): string {
    return type.replace(/_/g, ' ');
  }

  private formatDate(date: Date): string {
    return date.toISOString().split('T')[0];
  }

  private headers(): HttpHeaders {
    const token = localStorage.getItem('access_token');
    return new HttpHeaders({ 'Authorization': token ? `Bearer ${token}` : '' });
  }
}
