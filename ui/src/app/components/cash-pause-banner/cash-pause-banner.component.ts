import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { EventService, SystemEvent } from '../../services/event.service';

/**
 * "Entries paused — out of settled cash".
 *
 * The engine already records this: `order_manager._record_cash_block` writes ONE
 * `ENTRY_SKIPPED_NO_CASH` row on the transition into the blocked state and then
 * skips quietly, so the log does not fill with 125 identical warnings. That is
 * the right behaviour for the log and the wrong behaviour for the operator —
 * on 2026-09-08 the account stopped trading at 10:30 ET and nothing said so.
 *
 * DERIVED, never stored. There is deliberately no flag on the user row: a stored
 * boolean survives the condition that set it, and a banner that claims the
 * account is blocked when it is not is worse than no banner. The rule is:
 *
 *     show it when today's newest cash-pause has no ORDER_PLACED after it
 *
 * so a single real fill clears it on the next poll with nothing to reset. The
 * engine logs the resume to stdout only (`order_manager.py:502`), which is why
 * this reads the absence of a later order rather than waiting for an event that
 * is never written.
 */
@Component({
  selector: 'app-cash-pause-banner',
  standalone: true,
  imports: [CommonModule, MatIconModule],
  templateUrl: './cash-pause-banner.component.html',
  styleUrls: ['./cash-pause-banner.component.scss'],
})
export class CashPauseBannerComponent implements OnInit, OnDestroy {
  private events = inject(EventService);

  private readonly pause = signal<SystemEvent | null>(null);
  private timer?: ReturnType<typeof setInterval>;

  /** 60s: the condition only changes when an order fills or cash settles. */
  private static readonly POLL_MS = 60_000;

  readonly blocked = computed(() => this.pause() !== null);

  /** "10:30 AM" in the market's timezone, not the viewer's — this is a
   *  statement about the trading session, so ET is the honest clock. */
  readonly since = computed(() => {
    const ev = this.pause();
    if (!ev) return '';
    return new Date(ev.created_at).toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: 'numeric',
      minute: '2-digit',
    });
  });

  readonly needed = computed(() => this.money(this.pause()?.event_data?.['estimate']));
  readonly available = computed(() => this.money(this.pause()?.event_data?.['available']));

  ngOnInit(): void {
    this.load();
    this.timer = setInterval(() => this.load(), CashPauseBannerComponent.POLL_MS);
  }

  ngOnDestroy(): void {
    if (this.timer) clearInterval(this.timer);
  }

  private money(v: unknown): string {
    const n = Number(v);
    return Number.isFinite(n)
      ? n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
      : '—';
  }

  /** ET calendar day, so an evening session is never mistaken for today. */
  private etDay(d: Date): string {
    return d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
  }

  private load(): void {
    // Both types in one request — the API takes a comma-separated list, and the
    // rule needs the newest of each. 50 is ample: ORDER_PLACED and the once-per
    // -episode pause are both rare next to ORDER_RATE_LIMITED (98:1 on 09-08),
    // which is exactly why this asks for two types instead of "newest N".
    this.events
      .getEvents({ eventType: 'ENTRY_SKIPPED_NO_CASH,ORDER_PLACED', limit: 50 })
      .subscribe({
        next: (page) => this.pause.set(this.resolve(page.events)),
        // A failed poll must not invent a state. Leave whatever we last knew.
        error: () => {},
      });
  }

  /** `events` arrives newest-first (the API orders by created_at desc). */
  private resolve(events: SystemEvent[]): SystemEvent | null {
    const pause = events.find((e) => e.event_type === 'ENTRY_SKIPPED_NO_CASH');
    if (!pause) return null;

    const today = this.etDay(new Date());
    if (this.etDay(new Date(pause.created_at)) !== today) return null;

    const order = events.find((e) => e.event_type === 'ORDER_PLACED');
    if (order && new Date(order.created_at) > new Date(pause.created_at)) return null;

    return pause;
  }
}
