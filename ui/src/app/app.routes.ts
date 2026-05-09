import { Routes } from '@angular/router';
import { authGuard } from './guards/auth.guard';
import { adminGuard } from './guards/admin.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: '/dashboard',
    pathMatch: 'full'
  },
  {
    path: 'login',
    loadComponent: () => import('./pages/login/login.component').then(m => m.LoginComponent)
  },
  {
    path: 'dashboard',
    loadComponent: () => import('./pages/dashboard/dashboard.component').then(m => m.DashboardComponent),
    canActivate: [authGuard],
    children: [
      {
        path: '',
        redirectTo: 'overview',
        pathMatch: 'full'
      },
      {
        path: 'overview',
        loadComponent: () => import('./pages/overview/overview.component').then(m => m.OverviewComponent)
      },
      {
        path: 'strategies',
        loadComponent: () => import('./pages/strategies/strategy-list.component').then(m => m.StrategyListComponent)
      },
      {
        path: 'strategies/new',
        loadComponent: () => import('./pages/strategies/strategy-form.component').then(m => m.StrategyFormComponent)
      },
      {
        path: 'strategies/:id/edit',
        loadComponent: () => import('./pages/strategies/strategy-form.component').then(m => m.StrategyFormComponent)
      },
      {
        path: 'positions',
        loadComponent: () => import('./pages/positions/positions.component').then(m => m.PositionsComponent)
      },
      {
        path: 'watchlists',
        loadComponent: () => import('./pages/watchlists/watchlists.component').then(m => m.WatchlistsComponent)
      },
      {
        path: 'events',
        loadComponent: () => import('./pages/trades/trades.component').then(m => m.TradesComponent)
      },
      {
        path: 'performance',
        loadComponent: () => import('./pages/performance/performance.component').then(m => m.PerformanceComponent)
      },
      {
        path: 'risk',
        loadComponent: () => import('./pages/risk/risk.component').then(m => m.RiskComponent)
      },
      {
        path: 'admin/users',
        canActivate: [adminGuard],
        loadComponent: () => import('./pages/admin/admin-users.component').then(m => m.AdminUsersComponent)
      }
    ]
  },
  {
    path: '**',
    redirectTo: '/dashboard'
  }
];
