import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SystemService, EnvironmentSettings } from '../../services/system.service';

@Component({
  selector: 'app-environment-controls',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './environment-controls.component.html',
  styleUrls: ['./environment-controls.component.scss']
})
export class EnvironmentControlsComponent implements OnInit {
  private systemService = inject(SystemService);

  settings: EnvironmentSettings | null = null;
  loading = false;
  error: string | null = null;

  ngOnInit() {
    this.loadSettings();
  }

  loadSettings() {
    this.loading = true;
    this.error = null;

    this.systemService.getEnvironmentSettings().subscribe({
      next: (settings) => {
        this.settings = settings;
        this.loading = false;
      },
      error: (err) => {
        console.error('Failed to load environment settings:', err);
        this.error = 'Failed to load settings';
        this.loading = false;
      }
    });
  }

  /**
   * Switch database environment
   */
  changeEnvironment(env: 'dev' | 'test' | 'prod') {
    if (this.settings?.environment === env) {
      return; // Already on this environment
    }

    this.loading = true;
    this.error = null;

    this.systemService.setEnvironment(env).subscribe({
      next: (response) => {
        console.log('Environment changed:', response.message);
        this.loading = false;
        // Settings will auto-refresh via service tap()
      },
      error: (err) => {
        console.error('Failed to change environment:', err);
        this.error = 'Failed to change environment';
        this.loading = false;
      }
    });
  }

  /**
   * Switch trading mode with confirmation for live mode
   */
  changeTradingMode(mode: 'paper' | 'live') {
    if (this.settings?.trading_mode === mode) {
      return; // Already in this mode
    }

    // Show confirmation dialog for live mode
    if (mode === 'live') {
      const confirmed = confirm(
        '⚠️ WARNING: Live trading uses REAL MONEY via your Tradier LIVE account!\n\n' +
        'All orders will execute with real capital. Are you absolutely sure you want to enable live trading?'
      );

      if (!confirmed) {
        return;
      }
    }

    this.loading = true;
    this.error = null;

    this.systemService.setTradingMode(mode).subscribe({
      next: (response) => {
        console.log('Trading mode changed:', response.message);
        if (response.warning) {
          alert(response.warning);
        }
        this.loading = false;
        // Settings will auto-refresh via service tap()
      },
      error: (err) => {
        console.error('Failed to change trading mode:', err);
        this.error = 'Failed to change trading mode';
        this.loading = false;
      }
    });
  }

  /**
   * Get badge color for current environment
   */
  getEnvironmentBadgeClass(env: string): string {
    switch (env) {
      case 'dev': return 'badge-dev';
      case 'test': return 'badge-test';
      case 'prod': return 'badge-prod';
      default: return '';
    }
  }

  /**
   * Get badge color for current trading mode
   */
  getTradingModeBadgeClass(mode: string): string {
    return mode === 'live' ? 'badge-danger' : 'badge-safe';
  }

  /**
   * Valid combinations:
   * - Paper mode: dev, test only (no prod)
   * - Live mode: prod only (no dev, test)
   */

  /**
   * Check if an environment is disabled based on current trading mode
   */
  isEnvironmentDisabled(env: 'dev' | 'test' | 'prod'): boolean {
    if (this.loading) return true;

    const tradingMode = this.settings?.trading_mode;

    // Paper mode: only dev/test allowed
    if (tradingMode === 'paper' && env === 'prod') {
      return true;
    }

    // Live mode: only prod allowed
    if (tradingMode === 'live' && (env === 'dev' || env === 'test')) {
      return true;
    }

    return false;
  }

  /**
   * Check if a trading mode is disabled based on current environment
   */
  isTradingModeDisabled(mode: 'paper' | 'live'): boolean {
    if (this.loading) return true;

    const environment = this.settings?.environment;

    // Paper mode: not allowed in prod
    if (mode === 'paper' && environment === 'prod') {
      return true;
    }

    // Live mode: not allowed in dev/test
    if (mode === 'live' && (environment === 'dev' || environment === 'test')) {
      return true;
    }

    return false;
  }

  /**
   * Get tooltip for environment button
   */
  getEnvironmentTooltip(env: 'dev' | 'test' | 'prod'): string {
    const tradingMode = this.settings?.trading_mode;

    if (tradingMode === 'paper' && env === 'prod') {
      return 'Prod requires live trading mode. Switch to live first.';
    }
    if (tradingMode === 'live' && (env === 'dev' || env === 'test')) {
      return 'Live trading requires prod environment.';
    }

    switch (env) {
      case 'dev': return 'Development database - for feature development';
      case 'test': return 'Test database (in-memory) - for strategy validation';
      case 'prod': return 'Production database - for live trading';
      default: return '';
    }
  }

  /**
   * Get tooltip for trading mode button
   */
  getTradingModeTooltip(mode: 'paper' | 'live'): string {
    const environment = this.settings?.environment;

    if (mode === 'paper' && environment === 'prod') {
      return 'Paper trading not allowed in production.';
    }
    if (mode === 'live' && (environment === 'dev' || environment === 'test')) {
      return 'Live trading requires prod environment. Switch to prod first.';
    }

    switch (mode) {
      case 'paper': return 'Paper trading via Tradier Sandbox (no real money)';
      case 'live': return 'LIVE TRADING via Tradier Live (REAL MONEY!)';
      default: return '';
    }
  }
}
