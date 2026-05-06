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
      gap: 12px;
      margin: 0;
      padding: 20px 24px;
      border-bottom: 1px solid var(--border);
    }

    mat-dialog-content {
      padding: 24px;
      max-height: calc(90vh - 180px);
      overflow-y: auto;
    }

    .subtitle {
      color: var(--text-muted);
      margin-bottom: 24px;
      font-size: 14px;
    }

    .loading-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 60px 0;
      gap: 16px;
    }

    .templates-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
      gap: 20px;
    }

    .template-card {
      position: relative;
      display: flex;
      flex-direction: column;
      transition: transform 0.2s, box-shadow 0.2s;
      border: 2px solid transparent;
    }

    .template-card:hover {
      transform: translateY(-4px);
      box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
    }

    .template-card.recommended {
      border-color: #ff9800;
    }

    .recommended-badge {
      position: absolute;
      top: 12px;
      right: 12px;
      background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
      color: white;
      padding: 4px 12px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 4px;
      z-index: 1;
    }

    .recommended-badge mat-icon {
      font-size: 14px;
      width: 14px;
      height: 14px;
    }

    mat-card-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
    }

    .template-icon {
      width: 48px;
      height: 48px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }

    .template-icon mat-icon {
      font-size: 28px;
      width: 28px;
      height: 28px;
    }

    .icon-beginner {
      background: var(--color-profit);
      color: white;
    }

    .icon-intermediate {
      background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
      color: white;
    }

    .icon-advanced {
      background: var(--color-loss);
      color: white;
    }

    mat-card-title {
      font-size: 18px;
      font-weight: 600;
      margin: 0;
    }

    mat-card-subtitle {
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 4px;
    }

    .description {
      font-size: 14px;
      color: var(--text-muted);
      line-height: 1.5;
      margin-bottom: 16px;
      min-height: 60px;
    }

    .template-details {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 16px;
    }

    .detail-row {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--text-muted);
    }

    .detail-icon {
      font-size: 18px;
      width: 18px;
      height: 18px;
      color: var(--text-faint);
    }

    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 12px;
    }

    mat-chip {
      font-size: 11px;
      min-height: 24px;
      padding: 4px 8px;
    }

    .difficulty-chip {
      font-weight: 600;
    }

    .difficulty-beginner {
      background-color: var(--color-profit-bg);
      color: var(--color-profit);
    }

    .difficulty-intermediate {
      background-color: rgba(25, 118, 210, 0.14);
      color: var(--primary);
    }

    .difficulty-advanced {
      background-color: var(--color-loss-bg);
      color: var(--color-loss);
    }

    mat-card-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      margin-top: auto;
      padding: 16px;
      border-top: 1px solid var(--border);
    }

    mat-card-actions button {
      flex: 1;
    }

    mat-dialog-actions {
      padding: 16px 24px;
      border-top: 1px solid #e0e0e0;
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
