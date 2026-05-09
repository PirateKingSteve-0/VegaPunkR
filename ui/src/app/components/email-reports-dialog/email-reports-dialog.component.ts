import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { AuthService } from '../../services/auth.service';
import { EmailReportsPrefs, NotificationPreferences } from '../../models/user.model';

@Component({
  selector: 'app-email-reports-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    MatProgressSpinnerModule,
    MatCheckboxModule,
  ],
  templateUrl: './email-reports-dialog.component.html',
  styleUrls: ['./email-reports-dialog.component.scss'],
})
export class EmailReportsDialogComponent implements OnInit {
  private auth = inject(AuthService);
  private dialogRef = inject(MatDialogRef<EmailReportsDialogComponent>);

  enabled = signal(false);
  daily = signal(true);
  weekly = signal(true);
  monthly = signal(true);
  quarterly = signal(true);
  yearly = signal(true);

  destinationEmail = signal<string>('');

  loading = signal(true);
  saving = signal(false);
  testing = signal(false);
  error = signal<string | null>(null);
  testResult = signal<{ ok: boolean; message: string } | null>(null);

  showOffBanner = computed(() => !this.loading() && !this.enabled());

  ngOnInit(): void {
    this.auth.refreshMe().subscribe({
      next: (user) => {
        this.destinationEmail.set(user.email ?? '');
        const e = user.notification_preferences?.email_reports;
        if (e) {
          this.enabled.set(!!e.enabled);
          this.daily.set(e.daily ?? true);
          this.weekly.set(e.weekly ?? true);
          this.monthly.set(e.monthly ?? true);
          this.quarterly.set(e.quarterly ?? true);
          this.yearly.set(e.yearly ?? true);
        }
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not load current settings.');
      },
    });
  }

  sendTest(): void {
    this.error.set(null);
    this.testResult.set(null);
    this.testing.set(true);
    this.auth.testEmailReport().subscribe({
      next: (res) => {
        this.testing.set(false);
        this.testResult.set(res);
      },
      error: (err) => {
        this.testing.set(false);
        this.testResult.set({
          ok: false,
          message: err?.error?.detail ?? 'Test send failed.',
        });
      },
    });
  }

  save(): void {
    this.error.set(null);

    const prefs: EmailReportsPrefs = {
      enabled: this.enabled(),
      daily: this.daily(),
      weekly: this.weekly(),
      monthly: this.monthly(),
      quarterly: this.quarterly(),
      yearly: this.yearly(),
    };

    const existing = this.auth.currentUserValue?.notification_preferences ?? {};
    const merged: NotificationPreferences = { ...existing, email_reports: prefs };

    this.saving.set(true);
    this.auth.updateNotificationPreferences(merged).subscribe({
      next: () => {
        this.saving.set(false);
        this.dialogRef.close(true);
      },
      error: (err) => {
        this.saving.set(false);
        this.error.set(err?.error?.detail ?? 'Failed to save settings.');
      },
    });
  }

  cancel(): void {
    this.dialogRef.close(false);
  }
}
