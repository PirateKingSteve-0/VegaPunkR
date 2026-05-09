import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { AuthService } from '../../services/auth.service';
import { DiscordPrefs, NotificationPreferences } from '../../models/user.model';

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
  selector: 'app-discord-notifications-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatSlideToggleModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './discord-notifications-dialog.component.html',
  styleUrls: ['./discord-notifications-dialog.component.scss'],
})
export class DiscordNotificationsDialogComponent implements OnInit {
  private auth = inject(AuthService);
  private dialogRef = inject(MatDialogRef<DiscordNotificationsDialogComponent>);

  enabled = signal(false);
  webhookUrl = signal('');
  notifyOpen = signal(true);
  notifyClose = signal(true);

  loading = signal(true);
  saving = signal(false);
  testing = signal(false);
  error = signal<string | null>(null);
  testResult = signal<{ ok: boolean; message: string } | null>(null);

  ngOnInit(): void {
    this.auth.refreshMe().subscribe({
      next: (user) => {
        const d = user.notification_preferences?.discord;
        if (d) {
          this.enabled.set(!!d.enabled);
          this.webhookUrl.set(d.webhook_url ?? '');
          this.notifyOpen.set(d.notify_open ?? true);
          this.notifyClose.set(d.notify_close ?? true);
        }
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not load current settings.');
      },
    });
  }

  private validate(): string | null {
    if (!this.enabled()) return null;
    const url = this.webhookUrl().trim();
    if (!url) return 'Webhook URL is required when enabled.';
    if (!looksLikeDiscordWebhook(url)) {
      return 'Webhook URL must start with https://discord.com/api/webhooks/.';
    }
    return null;
  }

  sendTest(): void {
    this.error.set(null);
    this.testResult.set(null);
    const url = this.webhookUrl().trim();
    if (!looksLikeDiscordWebhook(url)) {
      this.error.set('Enter a Discord webhook URL before testing.');
      return;
    }
    this.testing.set(true);
    this.auth.testDiscordWebhook(url).subscribe({
      next: (res) => {
        this.testing.set(false);
        this.testResult.set(res);
      },
      error: (err) => {
        this.testing.set(false);
        this.testResult.set({
          ok: false,
          message: err?.error?.detail ?? 'Test message failed.',
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

    const discord: DiscordPrefs = {
      enabled: this.enabled(),
      webhook_url: this.webhookUrl().trim() || null,
      notify_open: this.notifyOpen(),
      notify_close: this.notifyClose(),
    };

    const existing = this.auth.currentUserValue?.notification_preferences ?? {};
    const prefs: NotificationPreferences = { ...existing, discord };

    this.saving.set(true);
    this.auth.updateNotificationPreferences(prefs).subscribe({
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
