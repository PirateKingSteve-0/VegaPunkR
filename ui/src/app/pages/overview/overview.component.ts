import { Component, OnInit, OnDestroy, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { Subscription } from 'rxjs';
import { distinctUntilChanged, skip } from 'rxjs/operators';
import { AccountService } from '../../services/account.service';
import { SystemService } from '../../services/system.service';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { RiskService, AccountRiskStatus } from '../../services/risk.service';
import { AuthService } from '../../services/auth.service';
import { EventService, SystemEvent } from '../../services/event.service';
import { TradingHaltDialogComponent } from '../../components/trading-halt-dialog/trading-halt-dialog.component';
import { EquityCurveComponent } from '../../components/equity-curve/equity-curve.component';
import { etDateKey } from '../../models/date-range';

/**
 * What earns a row in "Today's Activity".
 *
 * Deliberately a curated list rather than "everything": ORDER_RATE_LIMITED
 * alone logged 98 rows on 2026-09-08 against 3 actual fills, and ENTRY_SKIPPED
 * fires once per evaluation tick while a position is open. Either would bury
 * the events that describe the session. Every type kept here is one the day
 * cannot be understood without — a fill, a position lifecycle change, or the
 * reason the engine stopped taking entries.
 *
 * The full unfiltered log stays one click away on the Trades page.
 */
const ACTIVITY_TYPES = [
  // Fills and their failures
  'ORDER_PLACED',
  'ORDER_FAILED',
  'ORDER_BACKFILLED',
  'ORDER_UNCONFIRMED',
  'ORDER_PREVIEW_REJECTED',
  'ORDER_PREVIEW_FAILED',
  // Position lifecycle.
  //
  // POSITION_OPENED is deliberately absent: the engine writes it in the same
  // second as ORDER_PLACED with strictly less information ("Opened SPY" vs
  // "BUY 1x SPY" plus price and order id), so including it doubles every entry
  // in the feed for nothing. Exits are the reverse — `_close_position` never
  // writes ORDER_PLACED, and POSITION_CLOSED is the only row carrying the P&L
  // and the exit reason. So: entries arrive as orders, exits as closes.
  'POSITION_CLOSED',
  'POSITION_MANUALLY_CLOSED',
  'POSITION_ADOPTED_FROM_BROKER',
  'POSITION_STACKED',
  'POSITION_QTY_RECONCILED',
  'POSITION_OWNERSHIP_TRANSFERRED',
  'CLOSE_FAILED',
  'CLOSE_REJECTED',
  'CLOSE_UNCONFIRMED',
  // Why entries stopped — the single most useful thing on a quiet afternoon
  'ENTRY_SKIPPED_NO_CASH',
  'ENTRY_BLOCKED_BY_ROLE',
  'ENTRY_BLOCKED_BAD_CONTRACT',
  'ENTRY_BLOCKED_UNCONFIRMED',
  // The entry_before_et wall (midday/theta cutoff) or the forced-exit time.
  // Emitted once per strategy per day, so it reads as "entries are done for
  // today" rather than as a recurring alarm.
  'ENTRY_BLOCKED_TIME_WINDOW',
  'STRATEGY_STARTED',
].join(',');

@Component({
  selector: 'app-overview',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatDialogModule,
    EquityCurveComponent
  ],
  templateUrl: './overview.component.html',
  styleUrls: ['./overview.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OverviewComponent implements OnInit, OnDestroy {
  private accountService = inject(AccountService);
  private systemService = inject(SystemService);
  private riskService = inject(RiskService);
  private authService = inject(AuthService);
  private events = inject(EventService);
  private dialog = inject(MatDialog);
  private settingsSubscription?: Subscription;

  // Reactive signals for stat values
  portfolioValue = signal('$0.00');
  cashAvailable = signal('$0.00');
  openPositions = signal('0');
  totalPnL = signal('$0.00');
  pnlColor = signal<'primary' | 'accent' | 'warn'>('primary');

  // Account-wide daily-loss session status (TODO #7)
  accountRisk = signal<AccountRiskStatus | null>(null);

  // Stats configuration with signal getters
  stats = [
    { label: 'Total Portfolio Value', value: () => this.portfolioValue(), icon: 'account_balance_wallet', color: 'primary' as const },
    { label: 'Cash Available', value: () => this.cashAvailable(), icon: 'payments', color: 'accent' as const },
    { label: 'Open Positions', value: () => this.openPositions(), icon: 'trending_up', color: 'warn' as const },
    { label: 'Total P&L', value: () => this.totalPnL(), icon: 'analytics', color: 'primary' as const }
  ];

  loading = signal(false);
  error = signal<string | null>(null);

  // Today's activity feed
  activity = signal<SystemEvent[]>([]);
  activityLoading = signal(false);
  activityError = signal<string | null>(null);

  ngOnInit() {
    // Load initial data
    this.loadAccountData();
    this.loadAccountRisk();
    this.loadActivity();

    // Subscribe to environment/trading mode changes and reload data
    // Skip the first emission to avoid double-loading on init
    // Only reload when settings actually change
    this.settingsSubscription = this.systemService.settings$.pipe(
      skip(1),  // Skip the initial value
      distinctUntilChanged((prev, curr) => {
        // Only reload if environment or trading mode actually changed
        return prev?.environment === curr?.environment &&
               prev?.trading_mode === curr?.trading_mode;
      })
    ).subscribe(settings => {
      if (settings) {
        console.log('🔄 Environment settings changed, reloading account data...', {
          environment: settings.environment,
          trading_mode: settings.trading_mode
        });
        this.loadAccountData();
        this.loadAccountRisk();
        this.loadActivity();
      }
    });
  }

  ngOnDestroy() {
    this.settingsSubscription?.unsubscribe();
  }

  /** Read-only roles get the control disabled rather than hidden — the halt is
   *  safety state a viewer should still be able to see. The backend
   *  (`require_can_write_own`) is the actual boundary. */
  canWrite(): boolean {
    const role = this.authService.currentUserValue?.role;
    return role === 'user' || role === 'admin' || role === 'strategy_author';
  }

  openHaltDialog(): void {
    const ref = this.dialog.open(TradingHaltDialogComponent, {
      width: '520px',
      maxWidth: '100vw',
      autoFocus: false,
    });
    // Re-read rather than patching locally: a flatten also changes open
    // positions and today's P&L, so the whole tile needs to be refetched.
    ref.afterClosed().subscribe(result => {
      if (result) {
        this.loadAccountRisk();
        this.loadAccountData();
        // A flatten closes positions, which writes POSITION_CLOSED rows.
        this.loadActivity();
      }
    });
  }

  loadAccountRisk() {
    this.riskService.getAccountStatus().subscribe({
      next: (status) => this.accountRisk.set(status),
      error: (err: Error) => console.error('Failed to load account risk status:', err),
    });
  }

  formatSignedCurrency(value: number): string {
    const sign = value > 0 ? '+' : value < 0 ? '−' : '';
    return `${sign}${this.formatCurrency(Math.abs(value))}`;
  }

  /** Clamp the progress-bar fill so a >100% breach still renders cleanly. */
  riskBarPct(): number {
    const r = this.accountRisk();
    if (!r) return 0;
    return Math.max(0, Math.min(100, r.pct_consumed));
  }

  loadAccountData() {
    this.loading.set(true);
    this.error.set(null);

    // Get account info (routes to Tradier Sandbox or Tradier Live by trading mode)
    this.accountService.getAccount().subscribe({
      next: (account) => {
        // Update Total Portfolio Value (equity)
        this.portfolioValue.set(this.formatCurrency(account.equity));

        // Update Cash Available
        this.cashAvailable.set(this.formatCurrency(account.cash));

        this.loading.set(false);
      },
      error: (err: Error) => {
        console.error('Failed to load account:', err);
        this.error.set('Failed to load account data. Please ensure you are authenticated.');
        this.loading.set(false);
      }
    });

    // Get positions (routes to Tradier Sandbox or Tradier Live by trading mode)
    this.accountService.getPositions().subscribe({
      next: (positions) => {
        // Update Open Positions count
        this.openPositions.set(positions.length.toString());

        // Calculate Total P&L from positions
        const totalPnL = positions.reduce((sum: number, pos) => sum + pos.unrealized_pl, 0);
        this.totalPnL.set(this.formatCurrency(totalPnL));
        this.pnlColor.set(totalPnL >= 0 ? 'primary' : 'warn');
      },
      error: (err: Error) => {
        console.error('Failed to load positions:', err);
      }
    });
  }

  /**
   * Today's engine activity, newest first.
   *
   * Scoped to the current ET date. The API compares `start`/`end` against
   * `created_at`, which is stored UTC — but the whole session (04:00–20:00 ET
   * = 08:00–00:00 UTC) shares the ET calendar date, so the two agree for every
   * hour the engine can trade. Only post-20:00-ET rows would land on the next
   * UTC day, and nothing trades then.
   */
  loadActivity() {
    const today = etDateKey(new Date());
    this.activityLoading.set(true);
    this.activityError.set(null);
    this.events.getEvents({ eventType: ACTIVITY_TYPES, start: today, end: today, limit: 40 })
      .subscribe({
        next: ({ events }) => {
          this.activity.set(events ?? []);
          this.activityLoading.set(false);
        },
        error: (err: any) => {
          console.error('Failed to load activity:', err);
          this.activityError.set('Unable to load today\u2019s activity.');
          this.activityLoading.set(false);
        },
      });
  }

  /** Fill time on an Eastern wall clock — a session is read in market time,
   *  and these timestamps are what you line up against a chart. */
  activityTime(e: SystemEvent): string {
    const d = new Date(e.created_at);
    if (isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  }

  activityIcon(e: SystemEvent): string {
    switch (e.event_type) {
      case 'ORDER_PLACED':
        return e.event_data?.['signal_type'] === 'exit' ? 'call_made' : 'call_received';
      case 'POSITION_ADOPTED_FROM_BROKER':
      case 'POSITION_STACKED':
        return 'add_circle_outline';
      case 'POSITION_CLOSED':
      case 'POSITION_MANUALLY_CLOSED':
        return 'check_circle_outline';
      case 'ENTRY_SKIPPED_NO_CASH':
        return 'account_balance_wallet';
      case 'ENTRY_BLOCKED_BY_ROLE':
      case 'ENTRY_BLOCKED_BAD_CONTRACT':
      case 'ENTRY_BLOCKED_UNCONFIRMED':
        return 'block';
      case 'STRATEGY_STARTED':
        return 'play_circle_outline';
      case 'ORDER_FAILED':
      case 'CLOSE_FAILED':
      case 'CLOSE_REJECTED':
      case 'ORDER_PREVIEW_REJECTED':
      case 'ORDER_PREVIEW_FAILED':
        return 'error_outline';
      case 'ORDER_UNCONFIRMED':
      case 'CLOSE_UNCONFIRMED':
      case 'POSITION_QTY_RECONCILED':
      case 'POSITION_OWNERSHIP_TRANSFERRED':
      case 'ORDER_BACKFILLED':
        return 'sync_problem';
      default:
        return 'radio_button_unchecked';
    }
  }

  /** Colour key. A close is keyed on its P&L rather than its severity so a
   *  losing exit reads red even though closing cleanly is "success" to the
   *  engine. */
  activityTone(e: SystemEvent): 'profit' | 'loss' | 'warning' | 'neutral' {
    const pnl = this.activityPnl(e);
    if (pnl !== null) return pnl >= 0 ? 'profit' : 'loss';
    if (e.severity === 'error') return 'loss';
    if (e.severity === 'warning') return 'warning';
    if (e.severity === 'success') return 'profit';
    return 'neutral';
  }

  /** Realized P&L carried on a close event, or null when the row has none. */
  activityPnl(e: SystemEvent): number | null {
    const raw = e.event_data?.['pnl'];
    return typeof raw === 'number' && isFinite(raw) ? raw : null;
  }

  /** The contract, when the event names one — `symbol` is only the underlying. */
  activityContract(e: SystemEvent): string | null {
    const d = e.event_data || {};
    return (d['option_symbol'] as string) || null;
  }

  activityQty(e: SystemEvent): string | null {
    const d = e.event_data || {};
    const qty = d['qty'];
    const price = d['price'] ?? d['exit_price'];
    if (typeof qty !== 'number') return null;
    return typeof price === 'number' ? `${qty} @ ${this.formatCurrency(price)}` : `${qty}`;
  }

  formatCurrency(value: number): string {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  }

  refresh() {
    this.loadAccountData();
    this.loadAccountRisk();
    this.loadActivity();
  }
}
