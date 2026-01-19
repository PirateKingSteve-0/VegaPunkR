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
export enum StrategyType {
  SCALPING_0DTE = 'scalping_0dte',
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
