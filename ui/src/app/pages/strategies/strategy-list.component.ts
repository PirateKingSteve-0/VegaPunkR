import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDividerModule } from '@angular/material/divider';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { Strategy } from '../../models/strategy.model';
import { StrategyService } from '../../services/strategy.service';
import { TemplateGalleryModalComponent } from './template-gallery-modal.component';

@Component({
  selector: 'app-strategy-list',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatMenuModule,
    MatTooltipModule,
    MatDividerModule,
    MatDialogModule
  ],
  templateUrl: './strategy-list.component.html',
  styleUrls: ['./strategy-list.component.scss']
})
export class StrategyListComponent implements OnInit {
  private strategyService = inject(StrategyService);
  private router = inject(Router);
  private dialog = inject(MatDialog);

  strategies: Strategy[] = [];
  isLoading = true;
  displayedColumns: string[] = ['name', 'type', 'status', 'symbols', 'updated', 'actions'];

  ngOnInit(): void {
    this.loadStrategies();
  }

  loadStrategies(): void {
    this.isLoading = true;
    this.strategyService.getStrategies().subscribe({
      next: (strategies) => {
        this.strategies = strategies;
        this.isLoading = false;
      },
      error: (error) => {
        console.error('Error loading strategies:', error);
        this.isLoading = false;
      }
    });
  }

  createStrategy(): void {
    this.router.navigate(['/dashboard/strategies/new']);
  }

  browseTemplates(): void {
    const dialogRef = this.dialog.open(TemplateGalleryModalComponent, {
      width: '90vw',
      maxWidth: '1200px',
      maxHeight: '90vh',
      panelClass: 'template-gallery-dialog'
    });

    dialogRef.afterClosed().subscribe((clonedStrategy) => {
      if (clonedStrategy) {
        // Template was cloned, refresh the list
        this.loadStrategies();
      }
    });
  }

  viewStrategy(strategy: Strategy): void {
    this.router.navigate(['/dashboard/strategies', strategy.id]);
  }

  editStrategy(strategy: Strategy): void {
    this.router.navigate(['/dashboard/strategies', strategy.id, 'edit']);
  }

  deleteStrategy(strategy: Strategy): void {
    if (confirm(`Are you sure you want to delete "${strategy.name}"?`)) {
      this.strategyService.deleteStrategy(strategy.id).subscribe({
        next: () => {
          this.loadStrategies();
        },
        error: (error) => {
          console.error('Error deleting strategy:', error);
          alert('Failed to delete strategy');
        }
      });
    }
  }

  toggleStrategyStatus(strategy: Strategy): void {
    this.strategyService.toggleStrategy(strategy.id).subscribe({
      next: () => {
        this.loadStrategies();
      },
      error: (error) => {
        console.error('Error updating strategy:', error);
        alert('Failed to update strategy status');
      }
    });
  }

  getStatusColor(isActive: boolean): string {
    return isActive ? 'primary' : 'accent';
  }

  getSymbolsList(strategy: Strategy): string {
    return strategy.instruments?.join(', ') || 'N/A';
  }
}
