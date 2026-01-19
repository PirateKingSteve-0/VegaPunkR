import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';

@Component({
  selector: 'app-risk',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatTableModule,
    MatChipsModule
  ],
  templateUrl: './risk.component.html',
  styleUrls: ['./risk.component.scss']
})
export class RiskComponent {
  riskMetrics = [
    { label: 'Portfolio Risk', value: 'Low', level: 25, color: 'primary', icon: 'shield' },
    { label: 'Concentration Risk', value: 'Medium', level: 50, color: 'accent', icon: 'pie_chart' },
    { label: 'Leverage', value: '1.0x', level: 10, color: 'primary', icon: 'trending_up' },
    { label: 'VaR (95%)', value: '$0.00', level: 0, color: 'warn', icon: 'warning' }
  ];

  displayedColumns: string[] = ['symbol', 'exposure', 'riskContribution', 'limit', 'status'];
  exposures: any[] = [];

  alerts = [
    { severity: 'info', message: 'No active risk alerts', timestamp: new Date() }
  ];
}
