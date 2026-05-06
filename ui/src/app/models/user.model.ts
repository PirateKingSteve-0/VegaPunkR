export interface User {
  id: string;
  email: string;
  username: string;
  role?: string;
  trading_window_enabled?: boolean;
  trading_window_start?: string;
  trading_window_end?: string;
}

export interface TradingWindowUpdate {
  trading_window_enabled: boolean;
  trading_window_start: string;
  trading_window_end: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}
