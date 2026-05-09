import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDividerModule } from '@angular/material/divider';
import { AuthService } from '../../services/auth.service';
import { ProfileUpdate } from '../../models/user.model';

@Component({
  selector: 'app-profile-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatDividerModule,
  ],
  templateUrl: './profile-dialog.component.html',
  styleUrls: ['./profile-dialog.component.scss'],
})
export class ProfileDialogComponent implements OnInit {
  private auth = inject(AuthService);
  private dialogRef = inject(MatDialogRef<ProfileDialogComponent>);

  // Identity
  name = signal('');
  email = signal('');
  initialEmail = signal('');

  // Password change
  currentPassword = signal('');
  newPassword = signal('');
  confirmPassword = signal('');

  // Risk limits
  dailyLossLimitPct = signal<number>(5);
  initialDailyLossLimitPct = signal<number>(5);

  loading = signal(true);
  saving = signal(false);
  error = signal<string | null>(null);
  success = signal<string | null>(null);

  emailChanged = computed(() => this.email().trim() !== this.initialEmail());

  ngOnInit(): void {
    this.auth.refreshMe().subscribe({
      next: (user) => {
        this.name.set(user.name ?? '');
        this.email.set(user.email ?? '');
        this.initialEmail.set(user.email ?? '');
        const pct = user.daily_loss_limit_pct ?? 5;
        this.dailyLossLimitPct.set(pct);
        this.initialDailyLossLimitPct.set(pct);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not load profile.');
      },
    });
  }

  private validate(): string | null {
    const trimmedEmail = this.email().trim();
    if (!trimmedEmail) return 'Email is required.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) return 'Email is not valid.';
    if (!this.name().trim()) return 'Name is required.';

    const pct = this.dailyLossLimitPct();
    if (pct < 0.5 || pct > 20 || Number.isNaN(pct)) {
      return 'Daily loss limit must be between 0.5% and 20%.';
    }

    const wantsPasswordChange = !!(this.newPassword() || this.confirmPassword() || this.currentPassword());
    if (wantsPasswordChange) {
      if (!this.currentPassword()) return 'Current password is required to change password.';
      if (!this.newPassword() || !this.confirmPassword()) return 'Enter the new password twice.';
      if (this.newPassword() !== this.confirmPassword()) return 'New passwords do not match.';
      if (this.newPassword().length < 8) return 'New password must be at least 8 characters.';
    }
    return null;
  }

  save(): void {
    this.error.set(null);
    this.success.set(null);
    const validationError = this.validate();
    if (validationError) {
      this.error.set(validationError);
      return;
    }

    const update: ProfileUpdate = {};
    const trimmedName = this.name().trim();
    const trimmedEmail = this.email().trim();
    const currentUser = this.auth.currentUserValue;

    if (trimmedName && trimmedName !== currentUser?.name) {
      update.name = trimmedName;
    }
    if (trimmedEmail && trimmedEmail !== currentUser?.email) {
      update.email = trimmedEmail;
    }
    if (this.newPassword() && this.currentPassword()) {
      update.current_password = this.currentPassword();
      update.new_password = this.newPassword();
    }
    if (this.dailyLossLimitPct() !== this.initialDailyLossLimitPct()) {
      update.daily_loss_limit_pct = this.dailyLossLimitPct();
    }

    if (Object.keys(update).length === 0) {
      this.error.set('No changes to save.');
      return;
    }

    this.saving.set(true);
    this.auth.updateProfile(update).subscribe({
      next: () => {
        this.saving.set(false);
        this.dialogRef.close(true);
      },
      error: (err) => {
        this.saving.set(false);
        this.error.set(err?.error?.detail ?? 'Failed to update profile.');
      },
    });
  }

  cancel(): void {
    this.dialogRef.close(false);
  }
}
