import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { RiskService, TradingHaltMode } from '../../services/risk.service';

/**
 * "Done for the day" — stop new entries for the rest of the market day.
 *
 * The choice presented here is only about positions that are ALREADY OPEN;
 * both options stop new entries. `flatten` is the destructive one (it turns
 * open paper P&L into realised P&L and ends any trailing stop), so it is
 * never the default and never a single click — the user picks it explicitly.
 */
@Component({
  selector: 'app-trading-halt-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './trading-halt-dialog.component.html',
  styleUrls: ['./trading-halt-dialog.component.scss'],
})
export class TradingHaltDialogComponent {
  private riskService = inject(RiskService);
  private dialogRef = inject(MatDialogRef<TradingHaltDialogComponent>);

  selected = signal<TradingHaltMode | null>(null);
  submitting = signal(false);
  error = signal<string | null>(null);

  /** Already halted? Then this dialog is also the way back out. */
  readonly current = this.riskService.haltStatus;

  choose(mode: TradingHaltMode): void {
    if (this.submitting()) return;
    this.selected.set(mode);
  }

  confirm(): void {
    const mode = this.selected();
    if (!mode || this.submitting()) return;

    this.submitting.set(true);
    this.error.set(null);
    this.riskService.setTradingHalt(mode).subscribe({
      next: () => {
        this.submitting.set(false);
        this.dialogRef.close(mode);
      },
      error: (err) => {
        this.submitting.set(false);
        this.error.set(err?.error?.detail ?? 'Could not stop trading. Please try again.');
      },
    });
  }

  resume(): void {
    if (this.submitting()) return;
    this.submitting.set(true);
    this.error.set(null);
    this.riskService.clearTradingHalt().subscribe({
      next: () => {
        this.submitting.set(false);
        this.dialogRef.close('resumed');
      },
      error: (err) => {
        this.submitting.set(false);
        this.error.set(err?.error?.detail ?? 'Could not resume trading. Please try again.');
      },
    });
  }

  cancel(): void {
    this.dialogRef.close();
  }
}
