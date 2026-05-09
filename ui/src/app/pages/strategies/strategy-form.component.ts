import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { MatChipInputEvent } from '@angular/material/chips';
import { StrategyType } from '../../models/strategy.model';
import { StrategyService } from '../../services/strategy.service';

@Component({
  selector: 'app-strategy-form',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatCheckboxModule
  ],
  templateUrl: './strategy-form.component.html',
  styleUrls: ['./strategy-form.component.scss']
})
export class StrategyFormComponent implements OnInit {
  private fb = inject(FormBuilder);
  private strategyService = inject(StrategyService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);

  strategyForm: FormGroup;
  isEditMode = false;
  strategyId: number | null = null;
  isLoading = false;
  isSaving = false;

  strategyTypes = Object.values(StrategyType);

  instruments: string[] = [];
  readonly separatorKeysCodes = [ENTER, COMMA] as const;

  constructor() {
    this.strategyForm = this.fb.group({
      name: ['', [Validators.required, Validators.minLength(3)]],
      strategy_type: [StrategyType.MOMENTUM, [Validators.required]],
      timeframe: ['1h', [Validators.required]],
      max_positions: [5, [Validators.required, Validators.min(1)]],
      stop_loss_percentage: [2, [Validators.min(0.1), Validators.max(20)]],
      take_profit_percentage: [4, [Validators.min(0.1), Validators.max(50)]],
      max_hold_time_minutes: [0, [Validators.min(0)]],
      entry_after_open_minutes: [0, [Validators.min(0)]],
      exit_before_close_minutes: [0, [Validators.min(0)]],
      trailing_stop: [false],
      trailing_stop_activation: [0, [Validators.min(0)]],
      trailing_stop_distance: [0, [Validators.min(0)]],
      is_active: [false],
      is_paper_trading: [true]
    });
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    this.strategyId = id ? parseInt(id, 10) : null;
    this.isEditMode = !!this.strategyId;

    if (this.isEditMode && this.strategyId) {
      this.loadStrategy(this.strategyId);
    }
  }

  loadStrategy(id: number): void {
    this.isLoading = true;
    this.strategyService.getStrategy(id).subscribe({
      next: (strategy) => {
        this.instruments = strategy.instruments || [];
        const p: Record<string, any> = strategy.params_json || {};
        this.strategyForm.patchValue({
          name: strategy.name,
          strategy_type: strategy.strategy_type,
          timeframe: strategy.timeframe,
          max_positions: strategy.max_positions,
          stop_loss_percentage: strategy.stop_loss_percentage,
          take_profit_percentage: strategy.take_profit_percentage,
          max_hold_time_minutes: p['max_hold_time_minutes'] ?? 0,
          entry_after_open_minutes: p['entry_after_open_minutes'] ?? 0,
          exit_before_close_minutes: p['exit_before_close_minutes'] ?? 0,
          trailing_stop: p['trailing_stop'] ?? false,
          trailing_stop_activation: p['trailing_stop_activation'] ?? 0,
          trailing_stop_distance: p['trailing_stop_distance'] ?? 0,
          is_active: strategy.is_active,
          is_paper_trading: strategy.is_paper_trading
        });
        this.isLoading = false;
      },
      error: (error) => {
        console.error('Error loading strategy:', error);
        alert('Failed to load strategy');
        this.router.navigate(['/dashboard/strategies']);
        this.isLoading = false;
      }
    });
  }

  addInstrument(event: MatChipInputEvent): void {
    const value = (event.value || '').trim().toUpperCase();

    if (value && !this.instruments.includes(value)) {
      this.instruments.push(value);
    }

    event.chipInput!.clear();
  }

  removeInstrument(instrument: string): void {
    const index = this.instruments.indexOf(instrument);
    if (index >= 0) {
      this.instruments.splice(index, 1);
    }
  }

  onSubmit(): void {
    if (this.strategyForm.invalid) {
      return;
    }

    if (this.instruments.length === 0) {
      alert('Please add at least one instrument/symbol');
      return;
    }

    this.isSaving = true;

    const formValue = this.strategyForm.value;

    // Create params_json from form values. Backend merges this with the
    // existing params_json server-side, so unspecified keys (delta_min,
    // ema_period, etc.) are preserved.
    const params_json = {
      stop_loss_percentage: formValue.stop_loss_percentage,
      take_profit_percentage: formValue.take_profit_percentage,
      max_hold_time_minutes: formValue.max_hold_time_minutes,
      entry_after_open_minutes: formValue.entry_after_open_minutes,
      exit_before_close_minutes: formValue.exit_before_close_minutes,
      trailing_stop: formValue.trailing_stop,
      trailing_stop_activation: formValue.trailing_stop_activation,
      trailing_stop_distance: formValue.trailing_stop_distance,
    };

    const strategyData = this.isEditMode ? {
      name: formValue.name,
      strategy_type: formValue.strategy_type,
      params_json: params_json,
      instruments: this.instruments,
      timeframe: formValue.timeframe,
      max_positions: formValue.max_positions,
      stop_loss_percentage: formValue.stop_loss_percentage,
      take_profit_percentage: formValue.take_profit_percentage,
      is_active: formValue.is_active,
      is_paper_trading: formValue.is_paper_trading
    } : {
      name: formValue.name,
      strategy_type: formValue.strategy_type,
      params_json: params_json,
      instruments: this.instruments,
      timeframe: formValue.timeframe,
      max_positions: formValue.max_positions,
      stop_loss_percentage: formValue.stop_loss_percentage,
      take_profit_percentage: formValue.take_profit_percentage,
      is_paper_trading: formValue.is_paper_trading
    };

    const request = this.isEditMode && this.strategyId
      ? this.strategyService.updateStrategy(this.strategyId, strategyData)
      : this.strategyService.createStrategy(strategyData);

    request.subscribe({
      next: () => {
        this.isSaving = false;
        this.router.navigate(['/dashboard/strategies']);
      },
      error: (error) => {
        console.error('Error saving strategy:', error);
        alert('Failed to save strategy. Please check the console for details.');
        this.isSaving = false;
      }
    });
  }

  cancel(): void {
    this.router.navigate(['/dashboard/strategies']);
  }
}
