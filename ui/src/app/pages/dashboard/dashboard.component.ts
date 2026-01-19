import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';
import { MatDividerModule } from '@angular/material/divider';
import { MatChipsModule } from '@angular/material/chips';
import { AuthService } from '../../services/auth.service';
import { SystemService, EnvironmentSettings } from '../../services/system.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatSidenavModule,
    MatToolbarModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule,
    MatDividerModule,
    MatChipsModule
  ],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements OnInit {
  private authService = inject(AuthService);
  private systemService = inject(SystemService);
  private router = inject(Router);

  currentUser$ = this.authService.currentUser$;
  isSidenavOpen = signal(true);

  // Environment and trading mode settings
  environmentSettings = signal<EnvironmentSettings | null>(null);
  loading = signal(false);

  menuItems = [
    { icon: 'dashboard', label: 'Overview', route: '/dashboard/overview' },
    { icon: 'psychology', label: 'Strategies', route: '/dashboard/strategies' },
    { icon: 'account_balance', label: 'Positions', route: '/dashboard/positions' },
    { icon: 'swap_horiz', label: 'Trades', route: '/dashboard/trades' },
    { icon: 'analytics', label: 'Performance', route: '/dashboard/performance' },
    { icon: 'warning', label: 'Risk', route: '/dashboard/risk' },
  ];

  ngOnInit() {
    this.loadEnvironmentSettings();
  }

  loadEnvironmentSettings() {
    this.loading.set(true);
    this.systemService.getEnvironmentSettings().subscribe({
      next: (settings) => {
        this.environmentSettings.set(settings);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Failed to load environment settings:', err);
        this.loading.set(false);
      }
    });
  }

  toggleSidenav(): void {
    this.isSidenavOpen.update(value => !value);
  }

  setEnvironment(env: 'dev' | 'test' | 'prod'): void {
    this.loading.set(true);
    this.systemService.setEnvironment(env).subscribe({
      next: () => {
        console.log(`Environment switched to: ${env}`);
        this.loadEnvironmentSettings();
        // Redirect to overview to refresh account data
        this.router.navigate(['/dashboard/overview']);
      },
      error: (err) => {
        console.error('Failed to switch environment:', err);
        this.loading.set(false);
      }
    });
  }

  setTradingMode(mode: 'paper' | 'live'): void {
    const currentEnv = this.environmentSettings()?.environment;

    // Auto-switch environment if needed
    if (mode === 'live' && currentEnv !== 'prod') {
      const confirmed = confirm(
        '⚠️ WARNING: Live trading uses REAL MONEY via Schwab API!\n\n' +
        'Switching to live trading will also switch to production database.\n\n' +
        'All orders will execute with real capital. Are you absolutely sure?'
      );
      if (!confirmed) return;

      // Switch to live FIRST, then switch to prod
      // (backend blocks paper+prod, but allows live+dev/test temporarily)
      this.loading.set(true);
      this.systemService.setTradingMode(mode).subscribe({
        next: () => {
          // Now switch to prod
          this.systemService.setEnvironment('prod').subscribe({
            next: () => {
              console.log('Switched to live + prod');
              this.loadEnvironmentSettings();
              // Redirect to overview to refresh account data
              this.router.navigate(['/dashboard/overview']);
            },
            error: (err) => {
              console.error('Failed to switch to prod:', err);
              alert('❌ Failed to switch to production environment');
              this.loading.set(false);
            }
          });
        },
        error: (err) => {
          console.error('Failed to switch to live:', err);
          const errorMsg = err.error?.detail || 'Failed to switch to live mode';
          alert(`❌ ${errorMsg}`);
          this.loading.set(false);
        }
      });
    } else if (mode === 'paper' && currentEnv === 'prod') {
      // Switch to paper FIRST, then switch to dev
      this.loading.set(true);
      this.systemService.setTradingMode(mode).subscribe({
        next: () => {
          // Now switch to dev
          this.systemService.setEnvironment('dev').subscribe({
            next: () => {
              console.log('Switched to paper + dev');
              this.loadEnvironmentSettings();
              // Redirect to overview to refresh account data
              this.router.navigate(['/dashboard/overview']);
            },
            error: (err) => {
              console.error('Failed to switch to dev:', err);
              alert('❌ Failed to switch to development environment');
              this.loading.set(false);
            }
          });
        },
        error: (err) => {
          console.error('Failed to switch to paper:', err);
          const errorMsg = err.error?.detail || 'Failed to switch to paper mode';
          alert(`❌ ${errorMsg}`);
          this.loading.set(false);
        }
      });
    } else {
      // Environment already compatible, just switch trading mode
      if (mode === 'live') {
        const confirmed = confirm(
          '⚠️ WARNING: Live trading uses REAL MONEY via Schwab API!\n\n' +
          'All orders will execute with real capital. Are you absolutely sure?'
        );
        if (!confirmed) return;
      }
      this.switchTradingModeAfterEnvChange(mode);
    }
  }

  private switchTradingModeAfterEnvChange(mode: 'paper' | 'live'): void {
    this.loading.set(true);
    this.systemService.setTradingMode(mode).subscribe({
      next: (response) => {
        console.log(`Trading mode switched to: ${mode}`);
        if (response.warning) {
          alert(response.warning);
        }
        this.loadEnvironmentSettings();
        // Redirect to overview to refresh account data
        this.router.navigate(['/dashboard/overview']);
      },
      error: (err) => {
        console.error('Failed to switch trading mode:', err);
        const errorMsg = err.error?.detail || 'Failed to switch trading mode';
        alert(`❌ ${errorMsg}`);
        this.loading.set(false);
      }
    });
  }

  getEnvironmentDisplayName(): string {
    const env = this.environmentSettings()?.environment;
    if (!env) return 'Loading...';
    return env.charAt(0).toUpperCase() + env.slice(1);
  }

  getTradingModeDisplayName(): string {
    const mode = this.environmentSettings()?.trading_mode;
    if (!mode) return 'Loading...';
    return mode.charAt(0).toUpperCase() + mode.slice(1);
  }

  logout(): void {
    this.authService.logout();
  }
}
