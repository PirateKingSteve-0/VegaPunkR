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

/**
 * Hard floor on the forced end-of-day exit, in minutes before the bell.
 * Mirrors `FORCED_EOD_EXIT_FLOOR_MINUTES` in api/engine/signal_generator.py.
 * The backend rejects anything lower (schemas._validate_time_exit_params) and
 * the engine clamps it regardless — this constant only keeps the form honest.
 * Keep the two in sync if the floor ever moves.
 */
const EOD_EXIT_FLOOR_MIN = 15;

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
  // Exposed to the template so the hint/error text and the `min` binding
  // all read from the single constant rather than a hardcoded 15.
  readonly EOD_EXIT_FLOOR_MIN = EOD_EXIT_FLOOR_MIN;

  instruments: string[] = [];
  readonly separatorKeysCodes = [ENTER, COMMA] as const;

  constructor() {
    this.strategyForm = this.fb.group({
      name: ['', [Validators.required, Validators.minLength(3)]],
      strategy_type: [StrategyType.MOMENTUM, [Validators.required]],
      // Which side of the option chain to BUY. Both sides are opened with
      // buy_to_open and closed with sell_to_close — 'put' means buying puts,
      // never selling calls. Mirrors resolve_direction() in the engine.
      direction: ['call', [Validators.required]],
      timeframe: ['1h', [Validators.required]],
      max_positions: [5, [Validators.required, Validators.min(1)]],
      // Max raised from 20 to 100: a 50% stop is a legitimate 0DTE setting and
      // prod strategy 3 already stores one. The old cap made that value fail
      // validation on load, so the form could not round-trip it.
      stop_loss_percentage: [2, [Validators.min(0.1), Validators.max(100)]],
      take_profit_percentage: [4, [Validators.min(0.1), Validators.max(100)]],
      // Half of the position-size calculation. risk_manager.calculate_position_size
      // uses min(user.max_trade_percentage, this) — so raising only one has no
      // effect. Was previously unreachable from the UI at all.
      risk_per_trade_pct: [1.5, [Validators.min(0.1), Validators.max(100)]],
      // Hard ceiling on contracts per entry, applied after the risk maths.
      max_contracts: [3, [Validators.min(1), Validators.max(50)]],
      // Contract selection band. Deep-ITM (high delta) costs more premium and
      // carries far less open interest than at-the-money — these two settings
      // and min_open_interest together decide whether anything arms at all.
      delta_min: [0.6, [Validators.min(0.01), Validators.max(1)]],
      delta_max: [0.85, [Validators.min(0.01), Validators.max(1)]],
      min_open_interest: [3000, [Validators.min(0)]],
      max_hold_time_minutes: [0, [Validators.min(0)]],
      entry_after_open_minutes: [0, [Validators.min(0)]],
      // Minimum 15, never 0. Mirrors the engine's hard floor
      // (signal_generator.FORCED_EOD_EXIT_FLOOR_MINUTES); the API rejects
      // anything lower. Counts BACKWARDS from the bell, so a bigger number
      // exits EARLIER — which is why the floor is a minimum, not a maximum.
      exit_before_close_minutes: [EOD_EXIT_FLOOR_MIN, [Validators.required, Validators.min(EOD_EXIT_FLOOR_MIN)]],
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
          // Mirror resolve_direction() in api/engine/signal_generator.py:
          // explicit `direction` wins, else infer from the entry_signal wording,
          // else 'call'. Defaulting flatly to 'call' here would mean opening a
          // legacy "below" strategy and pressing Save silently pinned it to
          // calls while its entry trigger stayed bearish — the form would have
          // written a direction the user never chose.
          direction: p['direction']
            ?? (String(p['entry_signal'] ?? '').toLowerCase().includes('above')
                  ? 'call'
                  : String(p['entry_signal'] ?? '').toLowerCase().includes('below')
                      ? 'put'
                      : 'call'),
          timeframe: strategy.timeframe,
          max_positions: strategy.max_positions,
          // Show what the ENGINE uses, not the column. signal_generator.py:549
          // reads params_json['stop_loss_pct'] FIRST and only falls back to
          // ...['stop_loss_percentage']; the column is read by neither. On prod
          // those disagreed (column 15, params 50) so the form displayed a stop
          // the engine was not applying.
          stop_loss_percentage:
            p['stop_loss_pct'] ?? p['stop_loss_percentage'] ?? strategy.stop_loss_percentage,
          take_profit_percentage:
            p['take_profit_pct'] ?? p['take_profit_percentage'] ?? strategy.take_profit_percentage,
          risk_per_trade_pct: p['risk_per_trade_pct'] ?? 1.5,
          max_contracts: p['max_contracts'] ?? 3,
          delta_min: p['delta_min'] ?? 0.6,
          delta_max: p['delta_max'] ?? 0.85,
          min_open_interest: p['min_open_interest'] ?? 3000,
          max_hold_time_minutes: p['max_hold_time_minutes'] ?? 0,
          entry_after_open_minutes: p['entry_after_open_minutes'] ?? 0,
          // Clamp up, don't just default: legacy strategies stored 0, and
          // `??` does not fire on 0 — it would load 0 and then fail to save.
          exit_before_close_minutes: Math.max(
            p['exit_before_close_minutes'] ?? EOD_EXIT_FLOOR_MIN, EOD_EXIT_FLOOR_MIN),
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
      direction: formValue.direction,
      // Write BOTH spellings. The engine prefers the `_pct` key, so writing
      // only `_percentage` (as this did) left a stale `_pct` in charge and the
      // edit silently did nothing.
      stop_loss_pct: formValue.stop_loss_percentage,
      stop_loss_percentage: formValue.stop_loss_percentage,
      take_profit_pct: formValue.take_profit_percentage,
      take_profit_percentage: formValue.take_profit_percentage,
      risk_per_trade_pct: formValue.risk_per_trade_pct,
      max_contracts: formValue.max_contracts,
      delta_min: formValue.delta_min,
      delta_max: formValue.delta_max,
      min_open_interest: formValue.min_open_interest,
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
