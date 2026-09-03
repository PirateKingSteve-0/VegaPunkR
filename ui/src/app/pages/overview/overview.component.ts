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
import { TradingHaltDialogComponent } from '../../components/trading-halt-dialog/trading-halt-dialog.component';

@Component({
  selector: 'app-overview',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatDialogModule
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

  ngOnInit() {
    // Load initial data
    this.loadAccountData();
    this.loadAccountRisk();

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
  }
}
