import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { Subscription } from 'rxjs';
import { distinctUntilChanged, skip } from 'rxjs/operators';
import { AccountService } from '../../services/account.service';
import { SystemService } from '../../services/system.service';
import { RiskService, AccountRiskStatus } from '../../services/risk.service';

@Component({
  selector: 'app-overview',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule
  ],
  templateUrl: './overview.component.html',
  styleUrls: ['./overview.component.scss']
})
export class OverviewComponent implements OnInit, OnDestroy {
  private accountService = inject(AccountService);
  private systemService = inject(SystemService);
  private riskService = inject(RiskService);
  private settingsSubscription?: Subscription;
  private accountStatusInterval?: ReturnType<typeof setInterval>;

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
    // Refresh the session-status tile every 30s. The cap is computed from
    // realized+unrealized PnL, and unrealized PnL changes whenever option
    // marks update — a stale tile would understate how close to halt we are.
    this.accountStatusInterval = setInterval(() => this.loadAccountRisk(), 30_000);

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
    if (this.accountStatusInterval) {
      clearInterval(this.accountStatusInterval);
    }
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

    // Get account info (routes to Alpaca or Schwab based on trading mode)
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

    // Get positions (routes to Alpaca or Schwab based on trading mode)
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
