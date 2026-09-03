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
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { AuthService } from '../../services/auth.service';
import {
  DiscordPrefs,
  EmailReportsPrefs,
  NotificationPreferences,
  ProfileUpdate,
} from '../../models/user.model';

const DISCORD_HOSTS = [
  'https://discord.com/api/webhooks/',
  'https://discordapp.com/api/webhooks/',
  'https://canary.discord.com/api/webhooks/',
  'https://ptb.discord.com/api/webhooks/',
];

function looksLikeDiscordWebhook(url: string): boolean {
  return !!url && DISCORD_HOSTS.some(h => url.startsWith(h));
}

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
    MatSlideToggleModule,
    MatCheckboxModule,
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
  accountSizeUsd = signal<number>(0);
  initialAccountSizeUsd = signal<number>(0);
  maxTradePercentage = signal<number>(2);
  initialMaxTradePercentage = signal<number>(2);

  // Trading window
  windowEnabled = signal<boolean>(false);
  initialWindowEnabled = signal<boolean>(false);
  windowStart = signal<string>('09:45');
  initialWindowStart = signal<string>('09:45');
  windowEnd = signal<string>('15:45');
  initialWindowEnd = signal<string>('15:45');

  // Discord notifications
  discordEnabled = signal<boolean>(false);
  discordWebhookUrl = signal<string>('');
  discordNotifyOpen = signal<boolean>(true);
  discordNotifyClose = signal<boolean>(true);
  initialDiscord = signal<DiscordPrefs | null>(null);
  discordTesting = signal(false);
  discordTestResult = signal<{ ok: boolean; message: string } | null>(null);

  // Email reports
  emailEnabled = signal<boolean>(false);
  emailDaily = signal<boolean>(true);
  emailWeekly = signal<boolean>(true);
  emailMonthly = signal<boolean>(true);
  emailQuarterly = signal<boolean>(true);
  emailYearly = signal<boolean>(true);
  initialEmailReports = signal<EmailReportsPrefs | null>(null);
  emailTesting = signal(false);
  emailTestResult = signal<{ ok: boolean; message: string } | null>(null);

  loading = signal(true);
  saving = signal(false);
  error = signal<string | null>(null);

  emailChanged = computed(() => this.email().trim() !== this.initialEmail());

  ngOnInit(): void {
    this.auth.refreshMe().subscribe({
      next: (user) => {
        this.name.set(user.name ?? '');
        this.email.set(user.email ?? '');
        this.initialEmail.set(user.email ?? '');

        const dailyPct = user.daily_loss_limit_pct ?? 5;
        this.dailyLossLimitPct.set(dailyPct);
        this.initialDailyLossLimitPct.set(dailyPct);

        const acctSize = user.account_size_usd ?? 0;
        this.accountSizeUsd.set(acctSize);
        this.initialAccountSizeUsd.set(acctSize);

        // Stored as a PERCENT: risk_manager.py:71 reads this value and then
        // divides by 100, so 2.0 means 2%. This used to treat it as a fraction
        // — multiply by 100 on read, divide on write — which made the DB's 2.0
        // display as 200%, and made typing 45 save 0.45 that the engine then
        // read as 0.45%. Position sizing silently collapsed to zero contracts.
        const maxTradePct = user.max_trade_percentage ?? 2;
        this.maxTradePercentage.set(maxTradePct);
        this.initialMaxTradePercentage.set(maxTradePct);

        const winEnabled = !!user.trading_window_enabled;
        this.windowEnabled.set(winEnabled);
        this.initialWindowEnabled.set(winEnabled);
        const winStart = user.trading_window_start ?? '09:45';
        this.windowStart.set(winStart);
        this.initialWindowStart.set(winStart);
        const winEnd = user.trading_window_end ?? '15:45';
        this.windowEnd.set(winEnd);
        this.initialWindowEnd.set(winEnd);

        const discord = user.notification_preferences?.discord ?? null;
        if (discord) {
          this.discordEnabled.set(!!discord.enabled);
          this.discordWebhookUrl.set(discord.webhook_url ?? '');
          this.discordNotifyOpen.set(discord.notify_open ?? true);
          this.discordNotifyClose.set(discord.notify_close ?? true);
        }
        this.initialDiscord.set(discord);

        const emailReports = user.notification_preferences?.email_reports ?? null;
        if (emailReports) {
          this.emailEnabled.set(!!emailReports.enabled);
          this.emailDaily.set(emailReports.daily ?? true);
          this.emailWeekly.set(emailReports.weekly ?? true);
          this.emailMonthly.set(emailReports.monthly ?? true);
          this.emailQuarterly.set(emailReports.quarterly ?? true);
          this.emailYearly.set(emailReports.yearly ?? true);
        }
        this.initialEmailReports.set(emailReports);

        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not load profile.');
      },
    });
  }

  private currentDiscordPrefs(): DiscordPrefs {
    return {
      enabled: this.discordEnabled(),
      webhook_url: this.discordWebhookUrl().trim() || null,
      notify_open: this.discordNotifyOpen(),
      notify_close: this.discordNotifyClose(),
    };
  }

  private currentEmailPrefs(): EmailReportsPrefs {
    return {
      enabled: this.emailEnabled(),
      daily: this.emailDaily(),
      weekly: this.emailWeekly(),
      monthly: this.emailMonthly(),
      quarterly: this.emailQuarterly(),
      yearly: this.emailYearly(),
    };
  }

  private discordChanged(): boolean {
    const cur = this.currentDiscordPrefs();
    const prev = this.initialDiscord();
    if (!prev) return cur.enabled || !!cur.webhook_url;
    return (
      cur.enabled !== prev.enabled ||
      cur.webhook_url !== (prev.webhook_url ?? null) ||
      cur.notify_open !== (prev.notify_open ?? true) ||
      cur.notify_close !== (prev.notify_close ?? true)
    );
  }

  private emailReportsChanged(): boolean {
    const cur = this.currentEmailPrefs();
    const prev = this.initialEmailReports();
    if (!prev) return cur.enabled;
    return (
      cur.enabled !== prev.enabled ||
      cur.daily !== (prev.daily ?? true) ||
      cur.weekly !== (prev.weekly ?? true) ||
      cur.monthly !== (prev.monthly ?? true) ||
      cur.quarterly !== (prev.quarterly ?? true) ||
      cur.yearly !== (prev.yearly ?? true)
    );
  }

  private validate(): string | null {
    const trimmedEmail = this.email().trim();
    if (!trimmedEmail) return 'Email is required.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) return 'Email is not valid.';
    if (!this.name().trim()) return 'Name is required.';

    const dailyPct = this.dailyLossLimitPct();
    if (dailyPct < 0.5 || dailyPct > 20 || Number.isNaN(dailyPct)) {
      return 'Daily loss limit must be between 0.5% and 20%.';
    }
    const acctSize = this.accountSizeUsd();
    if (acctSize < 0 || Number.isNaN(acctSize)) {
      return 'Account size must be zero or greater.';
    }
    const maxTradePct = this.maxTradePercentage();
    if (maxTradePct <= 0 || maxTradePct > 100 || Number.isNaN(maxTradePct)) {
      return 'Max trade size must be between 0% and 100% of account.';
    }

    if (this.windowEnabled() && this.windowStart() >= this.windowEnd()) {
      return 'Trading window start must be earlier than end.';
    }

    if (this.discordEnabled()) {
      const url = this.discordWebhookUrl().trim();
      if (!url) return 'Discord webhook URL is required when enabled.';
      if (!looksLikeDiscordWebhook(url)) {
        return 'Discord webhook URL must start with https://discord.com/api/webhooks/.';
      }
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

  sendDiscordTest(): void {
    this.error.set(null);
    this.discordTestResult.set(null);
    const url = this.discordWebhookUrl().trim();
    if (!looksLikeDiscordWebhook(url)) {
      this.error.set('Enter a Discord webhook URL before testing.');
      return;
    }
    this.discordTesting.set(true);
    this.auth.testDiscordWebhook(url).subscribe({
      next: (res) => {
        this.discordTesting.set(false);
        this.discordTestResult.set(res);
      },
      error: (err) => {
        this.discordTesting.set(false);
        this.discordTestResult.set({
          ok: false,
          message: err?.error?.detail ?? 'Test message failed.',
        });
      },
    });
  }

  sendEmailTest(): void {
    this.error.set(null);
    this.emailTestResult.set(null);
    this.emailTesting.set(true);
    this.auth.testEmailReport().subscribe({
      next: (res) => {
        this.emailTesting.set(false);
        this.emailTestResult.set(res);
      },
      error: (err) => {
        this.emailTesting.set(false);
        this.emailTestResult.set({
          ok: false,
          message: err?.error?.detail ?? 'Test send failed.',
        });
      },
    });
  }

  save(): void {
    this.error.set(null);
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
    if (this.accountSizeUsd() !== this.initialAccountSizeUsd()) {
      update.account_size_usd = this.accountSizeUsd();
    }
    if (this.maxTradePercentage() !== this.initialMaxTradePercentage()) {
      // Stored as a percent — see the note in the load path.
      update.max_trade_percentage = this.maxTradePercentage();
    }

    const winChanged =
      this.windowEnabled() !== this.initialWindowEnabled() ||
      this.windowStart() !== this.initialWindowStart() ||
      this.windowEnd() !== this.initialWindowEnd();
    if (winChanged) {
      update.trading_window_enabled = this.windowEnabled();
      update.trading_window_start = this.windowStart();
      update.trading_window_end = this.windowEnd();
    }

    if (this.discordChanged() || this.emailReportsChanged()) {
      const existing = currentUser?.notification_preferences ?? {};
      const prefs: NotificationPreferences = {
        ...existing,
        discord: this.currentDiscordPrefs(),
        email_reports: this.currentEmailPrefs(),
      };
      update.notification_preferences = prefs;
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
        this.error.set(err?.error?.detail ?? 'Failed to update settings.');
      },
    });
  }

  cancel(): void {
    this.dialogRef.close(false);
  }
}
