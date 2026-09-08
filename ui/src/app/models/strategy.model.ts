/** Why the engine would refuse a new entry for this strategy right now.
 *  Computed per-request by the API (RiskManager.get_entry_block_status), not a
 *  stored column — so it is absent on create/update responses. */
export interface EntryBlockStatus {
  blocked: boolean;
  code: string | null;
  reason: string | null;
}

// Backend-aligned strategy interface
export interface Strategy {
  id: number;
  user_id: number;
  name: string;
  strategy_type: string;
  params_json: Record<string, any>;
  instruments: string[];
  timeframe: string;
  max_positions: number;
  stop_loss_percentage: number | null;
  take_profit_percentage: number | null;
  backtest_results: Record<string, any> | null;
  is_active: boolean;
  is_paper_trading: boolean;
  created_at: string;
  updated_at: string;
  /** Absent when not evaluated (create/update responses) — treated the same as
   *  "not blocked", because an unknown badge must never look alarming. */
  entry_block?: EntryBlockStatus | null;
}

// Strategy template interface (read-only)
export interface StrategyTemplate {
  template_id: string;
  name: string;
  strategy_type: string;
  description: string;
  is_template: boolean;
  instruments: string[];
  asset_type: string;
  timeframe: string;
  params_json: Record<string, any>;
  max_positions: number;
  stop_loss_percentage: number;
  take_profit_percentage: number;
  recommended_min_account_size: number;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  tags: string[];
}

// Strategy type enum
/** WARNING — this is not a cosmetic label. The engine decides whether a strategy
 *  trades OPTIONS or SHARES by looking for 'option', '0dte' or 'scalping' in this
 *  string (`risk_manager.py:282`, `strategy_executor.py:303`). A type without one
 *  of those words sizes as shares: on a $1,214 account a $3.00 contract goes from
 *  1 contract to 3, because the share formula reads "$3.00" as $3 rather than $300.
 *  Any options strategy MUST use a type containing one of those three words. */
export enum StrategyType {
  SCALPING_0DTE = 'scalping_0dte',
  MOMENTUM_0DTE = 'momentum_0dte',
  GAMMA_SCALPING = 'gamma_scalping',
  MOMENTUM_SCALPING = 'momentum_scalping',
  MEAN_REVERSION = 'mean_reversion',
  MOMENTUM = 'momentum',
  BREAKOUT = 'breakout',
  ARBITRAGE = 'arbitrage',
  ML_BASED = 'ml_based',
  CUSTOM = 'custom'
}

// Request/Response types aligned with backend
export interface CreateStrategyRequest {
  name: string;
  strategy_type?: string;
  params_json: Record<string, any>;
  instruments: string[];
  timeframe: string;
  max_positions: number;
  stop_loss_percentage?: number;
  take_profit_percentage?: number;
  is_paper_trading: boolean;
}

export interface UpdateStrategyRequest {
  name?: string;
  strategy_type?: string;
  params_json?: Record<string, any>;
  instruments?: string[];
  timeframe?: string;
  max_positions?: number;
  stop_loss_percentage?: number;
  take_profit_percentage?: number;
  is_active?: boolean;
  is_paper_trading?: boolean;
}
