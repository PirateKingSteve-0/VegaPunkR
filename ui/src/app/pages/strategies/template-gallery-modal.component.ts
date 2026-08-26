import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { StrategyService } from '../../services/strategy.service';
import { StrategyTemplate } from '../../models/strategy.model';

@Component({
  selector: 'app-template-gallery-modal',
  standalone: true,
  imports: [
    CommonModule,
    MatDialogModule,
    MatCardModule,
    MatButtonModule,
    MatChipsModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSnackBarModule
  ],
  templateUrl: './template-gallery-modal.component.html',
  styles: [`
    .template-gallery {
      width: 90vw;
      max-width: 1200px;
      max-height: 90vh;
    }

    h2[mat-dialog-title] {
      display: flex;
      align-items: center;
      gap: var(--sp-3);
      margin: 0;
      padding: var(--sp-5) var(--sp-6);
      font-size: var(--fs-lg);
      font-weight: var(--fw-semibold);
      letter-spacing: var(--ls-tight);
      border-bottom: 1px solid var(--border);
    }

    mat-dialog-content {
      padding: var(--sp-6);
      max-height: calc(90vh - 180px);
      overflow-y: auto;
    }

    .subtitle {
      color: var(--text-muted);
      margin-bottom: var(--sp-6);
      font-size: var(--fs-sm);
    }

    .loading-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: var(--sp-16) 0;
      gap: var(--sp-4);
    }

    .templates-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: var(--sp-4);
    }

    /* Flat: hover firms up the border instead of lifting the card. */
    .template-card {
      position: relative;
      display: flex;
      flex-direction: column;
      transition: border-color var(--dur) var(--ease);
    }

    .template-card:hover {
      border-color: var(--border-strong);
    }

    .template-card.recommended {
      border-color: var(--color-warning);
    }

    .recommended-badge {
      position: absolute;
      top: var(--sp-3);
      right: var(--sp-3);
      background: var(--color-warning-bg);
      color: var(--color-warning-strong);
      padding: 2px var(--sp-2);
      border-radius: var(--radius-pill);
      font-size: var(--fs-micro);
      font-weight: var(--fw-semibold);
      text-transform: uppercase;
      letter-spacing: var(--ls-eyebrow);
      display: flex;
      align-items: center;
      gap: var(--sp-1);
      z-index: 1;
    }

    .recommended-badge mat-icon {
      font-size: 13px;
      width: 13px;
      height: 13px;
    }

    mat-card-header {
      display: flex;
      align-items: center;
      gap: var(--sp-3);
      margin-bottom: var(--sp-4);
    }

    .template-icon {
      width: 38px;
      height: 38px;
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .template-icon mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
    }

    /* Difficulty is a tinted glyph, not a saturated disc. */
    .icon-beginner {
      background: var(--color-profit-bg);
      color: var(--color-profit-strong);
    }

    .icon-intermediate {
      background: var(--primary-bg);
      color: var(--primary);
    }

    .icon-advanced {
      background: var(--color-loss-bg);
      color: var(--color-loss-strong);
    }

    mat-card-title {
      font-size: var(--fs-md);
      font-weight: var(--fw-semibold);
      letter-spacing: var(--ls-tight);
      margin: 0;
    }

    mat-card-subtitle {
      font-size: var(--fs-xs);
      color: var(--text-muted);
      margin-top: 2px;
    }

    .description {
      font-size: var(--fs-sm);
      color: var(--text-muted);
      line-height: 1.55;
      margin-bottom: var(--sp-4);
      min-height: 58px;
    }

    .template-details {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--sp-2);
      margin-bottom: var(--sp-4);
    }

    .detail-row {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      font-size: var(--fs-xs);
      color: var(--text-muted);
    }

    .detail-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      color: var(--text-faint);
    }

    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: var(--sp-1);
      margin-bottom: var(--sp-3);
    }

    mat-chip {
      font-size: var(--fs-micro);
      min-height: 22px;
      padding: 2px var(--sp-2);
    }

    .difficulty-chip {
      font-weight: var(--fw-semibold);
      text-transform: uppercase;
      letter-spacing: var(--ls-eyebrow);
    }

    .difficulty-beginner {
      background-color: var(--color-profit-bg);
      color: var(--color-profit-strong);
    }

    .difficulty-intermediate {
      background-color: var(--primary-bg);
      color: var(--primary);
    }

    .difficulty-advanced {
      background-color: var(--color-loss-bg);
      color: var(--color-loss-strong);
    }

    mat-card-actions {
      display: flex;
      gap: var(--sp-2);
      justify-content: flex-end;
      margin-top: auto;
      padding: var(--sp-4);
      border-top: 1px solid var(--border);
    }

    mat-card-actions button {
      flex: 1;
    }

    mat-dialog-actions {
      padding: var(--sp-4) var(--sp-6);
      border-top: 1px solid var(--border);
    }
  `]
})
export class TemplateGalleryModalComponent implements OnInit {
  private strategyService = inject(StrategyService);
  private dialogRef = inject(MatDialogRef<TemplateGalleryModalComponent>);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  templates: StrategyTemplate[] = [];
  loading = true;
  cloning: string | null = null;

  ngOnInit() {
    this.loadTemplates();
  }

  loadTemplates() {
    this.loading = true;
    this.strategyService.getTemplates().subscribe({
      next: (templates) => {
        // Sort templates by recommended order (SPY first)
        this.templates = templates.sort((a, b) => {
          if (a.template_id === 'spy_0dte_scalping') return -1;
          if (b.template_id === 'spy_0dte_scalping') return 1;
          return 0;
        });
        this.loading = false;
      },
      error: (error) => {
        console.error('Error loading templates:', error);
        this.snackBar.open('Failed to load templates', 'Close', { duration: 3000 });
        this.loading = false;
      }
    });
  }

  getTemplateIcon(template: StrategyTemplate): string {
    if (template.template_id.includes('spy')) return 'show_chart';
    if (template.template_id.includes('tsla')) return 'electric_car';
    if (template.template_id.includes('qqq')) return 'computer';
    if (template.template_id.includes('nvda')) return 'memory';
    if (template.template_id.includes('aapl')) return 'phone_iphone';
    if (template.template_id.includes('amd')) return 'developer_board';
    if (template.template_id.includes('meta')) return 'groups';
    if (template.template_id.includes('amzn')) return 'shopping_cart';
    return 'trending_up';
  }

  viewDetails(template: StrategyTemplate) {
    // Show detailed view in a snackbar or expand the card
    const details = `
      Strategy Type: ${template.strategy_type}
      Asset Type: ${template.asset_type}

      Parameters:
      - EMA Period: ${template.params_json['ema_period']}
      - Use VWAP: ${template.params_json['use_vwap'] ? 'Yes' : 'No'}
      - Delta Range: ${template.params_json['delta_min']} - ${template.params_json['delta_max']}
      - Min OI: ${template.params_json['min_open_interest']}
      - Max Spread: $${template.params_json['max_bid_ask_spread']}
    `;

    this.snackBar.open(details, 'Close', {
      duration: 10000,
      verticalPosition: 'top'
    });
  }

  cloneTemplate(template: StrategyTemplate) {
    this.cloning = template.template_id;

    this.strategyService.cloneTemplate(template.template_id).subscribe({
      next: (strategy) => {
        this.snackBar.open(
          `Successfully cloned "${template.name}"! Redirecting to edit...`,
          'Close',
          { duration: 3000 }
        );

        // Close modal and navigate to edit page
        setTimeout(() => {
          this.dialogRef.close(strategy);
          this.router.navigate(['/dashboard/strategies', strategy.id, 'edit']);
        }, 1000);
      },
      error: (error) => {
        console.error('Error cloning template:', error);
        this.snackBar.open(
          'Failed to clone template. Please try again.',
          'Close',
          { duration: 3000 }
        );
        this.cloning = null;
      }
    });
  }
}
