import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AdminService, AdminUserSummary, AdminUserDashboard } from '../../services/admin.service';
import { AuthService } from '../../services/auth.service';

const ALL_ROLES = ['user', 'admin', 'viewer', 'auditor', 'strategy_author'];

@Component({
  selector: 'app-admin-users',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatSelectModule,
  ],
  templateUrl: './admin-users.component.html',
  styleUrls: ['./admin-users.component.scss'],
})
export class AdminUsersComponent implements OnInit {
  private adminService = inject(AdminService);
  private authService = inject(AuthService);
  private snackBar = inject(MatSnackBar);

  users = signal<AdminUserSummary[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);

  // Inline detail panel for the selected user (right-hand side of the page).
  selectedUserId = signal<number | null>(null);
  selectedDetail = signal<AdminUserDashboard | null>(null);
  detailLoading = signal(false);

  readonly allRoles = ALL_ROLES;
  readonly displayedColumns = [
    'email', 'role', 'is_active', 'active_strategies',
    'open_positions', 'today_pnl', 'last_trade_at', 'last_login', 'actions',
  ];

  // The viewer of this page may be admin (can change roles) or auditor
  // (read-only). The role-change dropdown is rendered for admin only.
  isAdmin = computed(() => (this.authService.currentUserValue?.role ?? 'user') === 'admin');

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.adminService.listUsers().subscribe({
      next: (rows) => {
        this.users.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? 'Failed to load users');
        this.loading.set(false);
      },
    });
  }

  selectUser(userId: number): void {
    this.selectedUserId.set(userId);
    this.detailLoading.set(true);
    this.selectedDetail.set(null);
    this.adminService.getUserDashboard(userId).subscribe({
      next: (dash) => {
        this.selectedDetail.set(dash);
        this.detailLoading.set(false);
      },
      error: () => {
        this.detailLoading.set(false);
      },
    });
  }

  closeDetail(): void {
    this.selectedUserId.set(null);
    this.selectedDetail.set(null);
  }

  changeRole(user: AdminUserSummary, newRole: string): void {
    if (newRole === user.role) return;
    this.adminService.setUserRole(user.id, newRole).subscribe({
      next: () => {
        this.snackBar.open(`Role updated to ${newRole}`, 'Dismiss', { duration: 3000 });
        this.refresh();
      },
      error: (err) => {
        const msg = err?.error?.detail ?? 'Failed to update role';
        this.snackBar.open(msg, 'Dismiss', { duration: 5000 });
      },
    });
  }

  formatCurrency(value: number | null | undefined): string {
    if (value === null || value === undefined) return '$0.00';
    return new Intl.NumberFormat('en-US', {
      style: 'currency', currency: 'USD',
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    }).format(value);
  }

  formatSignedCurrency(value: number | null | undefined): string {
    if (value === null || value === undefined) return '$0.00';
    const sign = value > 0 ? '+' : value < 0 ? '−' : '';
    return `${sign}${this.formatCurrency(Math.abs(value))}`;
  }

  pnlClass(value: number | null | undefined): string {
    if (value === null || value === undefined || value === 0) return '';
    return value > 0 ? 'pnl-positive' : 'pnl-negative';
  }
}
