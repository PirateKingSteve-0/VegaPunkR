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

@Component({
  selector: 'app-trading-window-dialog',
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
  templateUrl: './trading-window-dialog.component.html',
  styleUrls: ['./trading-window-dialog.component.scss'],
})
export class TradingWindowDialogComponent implements OnInit {
  private auth = inject(AuthService);
  private dialogRef = inject(MatDialogRef<TradingWindowDialogComponent>);

  enabled = signal(false);
  start = signal('09:45');
  end = signal('15:45');
  loading = signal(true);
  saving = signal(false);
  error = signal<string | null>(null);

  ngOnInit(): void {
    this.auth.refreshMe().subscribe({
      next: (user) => {
        this.enabled.set(!!user.trading_window_enabled);
        if (user.trading_window_start) this.start.set(user.trading_window_start);
        if (user.trading_window_end) this.end.set(user.trading_window_end);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.error.set('Could not load current settings.');
      },
    });
  }

  save(): void {
    this.error.set(null);
    if (this.enabled() && this.start() >= this.end()) {
      this.error.set('Start time must be earlier than end time.');
      return;
    }

    this.saving.set(true);
    this.auth
      .updateTradingWindow({
        trading_window_enabled: this.enabled(),
        trading_window_start: this.start(),
        trading_window_end: this.end(),
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.dialogRef.close(true);
        },
        error: (err) => {
          this.saving.set(false);
          this.error.set(err?.error?.detail ?? 'Failed to save trading window.');
        },
      });
  }

  cancel(): void {
    this.dialogRef.close(false);
  }
}
