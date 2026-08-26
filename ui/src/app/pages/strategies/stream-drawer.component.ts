import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  Input,
  NgZone,
  OnDestroy,
  OnInit,
  ViewChild,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Subscription } from 'rxjs';
import { filter } from 'rxjs/operators';
import { Strategy } from '../../models/strategy.model';
import {
  MarketStreamService,
  StreamEvent,
  ConnectionStatus,
} from '../../services/market-stream.service';

interface TimestampedEvent extends StreamEvent {
  id: number;
  receivedAt: number;
  eventTime: number;
}

const MAX_EVENTS = 300;
const FLUSH_INTERVAL_MS = 100;

@Component({
  selector: 'app-stream-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    MatButtonModule,
    MatIconModule,
    MatButtonToggleModule,
    MatDividerModule,
    MatTooltipModule,
  ],
  templateUrl: './stream-drawer.component.html',
  styleUrls: ['./stream-drawer.component.scss'],
})
export class StreamDrawerComponent implements OnInit, OnDestroy {
  @Input() strategy!: Strategy;
  @ViewChild('eventFeed') eventFeed!: ElementRef<HTMLElement>;

  private streamService = inject(MarketStreamService);
  private cdr = inject(ChangeDetectorRef);
  private zone = inject(NgZone);

  private subscription?: Subscription;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private buffer: TimestampedEvent[] = [];
  private eventCounter = 0;

  events: TimestampedEvent[] = [];
  activeFilters = new Set<string>(['quote', 'trade']);
  status$ = this.streamService.status$;

  ngOnInit(): void {
    const symbols = this.strategy.instruments || [];

    // Collect raw events outside Angular's zone — no CD triggered per-event
    this.zone.runOutsideAngular(() => {
      this.subscription = this.streamService.events$
        .pipe(filter(e => symbols.includes(e.symbol) && this.activeFilters.has(e.type)))
        .subscribe(event => {
          const eventTime = +(event.biddate ?? event.date ?? Date.now()) || Date.now();
          this.buffer.push({ ...event, id: ++this.eventCounter, receivedAt: Date.now(), eventTime });
        });

      // Flush buffer into the view at a steady 100ms cadence
      this.flushTimer = setInterval(() => this.flush(), FLUSH_INTERVAL_MS);
    });
  }

  private flush(): void {
    if (this.buffer.length === 0) return;

    const incoming = this.buffer.splice(0);
    this.events.push(...incoming);

    if (this.events.length > MAX_EVENTS) {
      this.events = this.events.slice(-MAX_EVENTS);
    }

    // Re-enter Angular zone once per flush to update the view and scroll
    this.zone.run(() => {
      this.cdr.markForCheck();
      // Schedule scroll after DOM updates
      setTimeout(() => {
        const el = this.eventFeed?.nativeElement;
        if (el) el.scrollTop = el.scrollHeight;
      }, 0);
    });
  }

  connect(): void {
    this.streamService.connect(this.strategy.instruments || []);
  }

  disconnect(): void {
    this.streamService.disconnect();
  }

  toggleFilter(type: string): void {
    if (this.activeFilters.has(type)) {
      this.activeFilters.delete(type);
    } else {
      this.activeFilters.add(type);
    }
    this.cdr.markForCheck();
  }

  clearEvents(): void {
    this.events = [];
    this.buffer = [];
    this.cdr.markForCheck();
  }

  // The dot is a DOM style binding, so it can read the theme tokens directly and
  // stays correct in dark and colorblind mode without a re-render.
  statusColor(status: ConnectionStatus | null): string {
    const idle = 'var(--text-faint)';
    const map: Record<ConnectionStatus, string> = {
      connected: 'var(--color-profit)',
      connecting: 'var(--color-warning)',
      disconnected: idle,
      error: 'var(--color-loss)',
    };
    return status ? (map[status] ?? idle) : idle;
  }

  statusLabel(status: ConnectionStatus | null): string {
    const map: Record<ConnectionStatus, string> = {
      connected: 'Connected',
      connecting: 'Connecting…',
      disconnected: 'Disconnected',
      error: 'Connection error',
    };
    return status ? (map[status] ?? '') : 'Disconnected';
  }

  ngOnDestroy(): void {
    if (this.flushTimer !== null) clearInterval(this.flushTimer);
    this.subscription?.unsubscribe();
  }
}
