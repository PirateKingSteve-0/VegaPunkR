import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTableModule } from '@angular/material/table';

@Component({
  selector: 'app-performance',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatTabsModule,
    MatTableModule
  ],
  templateUrl: './performance.component.html',
  styleUrls: ['./performance.component.scss']
})
export class PerformanceComponent {
  metrics = [
    { label: 'Total Return', value: '$0.00', change: '0.00%', icon: 'trending_up' },
    { label: 'Win Rate', value: '0%', change: '-', icon: 'check_circle' },
    { label: 'Sharpe Ratio', value: '0.00', change: '-', icon: 'analytics' },
    { label: 'Max Drawdown', value: '0.00%', change: '-', icon: 'trending_down' }
  ];

  displayedColumns: string[] = ['strategy', 'trades', 'winRate', 'avgProfit', 'totalReturn'];
  strategyPerformance: any[] = [];
}
