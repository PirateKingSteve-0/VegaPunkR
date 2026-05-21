export interface DiscordPrefs {
  enabled: boolean;
  webhook_url?: string | null;
  notify_open: boolean;
  notify_close: boolean;
}

export interface EmailReportsPrefs {
  enabled: boolean;
  daily: boolean;
  weekly: boolean;
  monthly: boolean;
  quarterly: boolean;
  yearly: boolean;
}

export interface NotificationPreferences {
  discord?: DiscordPrefs;
  email_reports?: EmailReportsPrefs;
  [key: string]: unknown;
}

export interface ProfileUpdate {
  name?: string;
  email?: string;
  current_password?: string;
  new_password?: string;
  daily_loss_limit_pct?: number;
  account_size_usd?: number;
  max_trade_percentage?: number;
  trading_window_enabled?: boolean;
  trading_window_start?: string;
  trading_window_end?: string;
  notification_preferences?: NotificationPreferences;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role?: string;
  daily_loss_limit_pct?: number;
  account_size_usd?: number;
  max_trade_percentage?: number;
  trading_window_enabled?: boolean;
  trading_window_start?: string;
  trading_window_end?: string;
  notification_preferences?: NotificationPreferences;
}

export interface TradingWindowUpdate {
  trading_window_enabled: boolean;
  trading_window_start: string;
  trading_window_end: string;
}

export interface NotificationPreferencesUpdate {
  notification_preferences: NotificationPreferences;
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
