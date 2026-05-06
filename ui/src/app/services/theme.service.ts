import { Injectable, computed, effect, signal } from '@angular/core';

export type ThemeMode = 'light' | 'dark';

export interface ChartPalette {
  profit: string;
  loss: string;
  profitFill: string;
  lossFill: string;
  primary: string;
  text: string;
  textMuted: string;
  grid: string;
  surface: string;
}

const STORAGE_KEY_THEME = 'vp.theme';
const STORAGE_KEY_CB = 'vp.colorblind';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly theme = signal<ThemeMode>(this.loadTheme());
  readonly colorblind = signal<boolean>(this.loadColorblind());

  readonly chartColors = computed<ChartPalette>(() => {
    const dark = this.theme() === 'dark';
    const cb = this.colorblind();

    if (cb) {
      return dark
        ? {
            profit: '#64b5f6',
            loss: '#ffa726',
            profitFill: 'rgba(100, 181, 246, 0.18)',
            lossFill: 'rgba(255, 167, 38, 0.18)',
            primary: '#90caf9',
            text: 'rgba(255, 255, 255, 0.87)',
            textMuted: 'rgba(255, 255, 255, 0.55)',
            grid: 'rgba(255, 255, 255, 0.08)',
            surface: '#1e1e1e',
          }
        : {
            profit: '#1976d2',
            loss: '#ef6c00',
            profitFill: 'rgba(25, 118, 210, 0.14)',
            lossFill: 'rgba(239, 108, 0, 0.14)',
            primary: '#1976d2',
            text: 'rgba(0, 0, 0, 0.87)',
            textMuted: 'rgba(0, 0, 0, 0.55)',
            grid: 'rgba(0, 0, 0, 0.08)',
            surface: '#ffffff',
          };
    }

    return dark
      ? {
          profit: '#66bb6a',
          loss: '#ef5350',
          profitFill: 'rgba(102, 187, 106, 0.18)',
          lossFill: 'rgba(239, 83, 80, 0.18)',
          primary: '#90caf9',
          text: 'rgba(255, 255, 255, 0.87)',
          textMuted: 'rgba(255, 255, 255, 0.55)',
          grid: 'rgba(255, 255, 255, 0.08)',
          surface: '#1e1e1e',
        }
      : {
          profit: '#2e7d32',
          loss: '#c62828',
          profitFill: 'rgba(46, 125, 50, 0.14)',
          lossFill: 'rgba(198, 40, 40, 0.14)',
          primary: '#1976d2',
          text: 'rgba(0, 0, 0, 0.87)',
          textMuted: 'rgba(0, 0, 0, 0.55)',
          grid: 'rgba(0, 0, 0, 0.08)',
          surface: '#ffffff',
        };
  });

  constructor() {
    effect(() => {
      const t = this.theme();
      const cb = this.colorblind();
      if (typeof document === 'undefined') return;
      document.body.setAttribute('data-theme', t);
      if (cb) document.body.setAttribute('data-colorblind', 'true');
      else document.body.removeAttribute('data-colorblind');
      try {
        localStorage.setItem(STORAGE_KEY_THEME, t);
        localStorage.setItem(STORAGE_KEY_CB, cb ? '1' : '0');
      } catch {
        // localStorage may be unavailable (private mode) — non-fatal
      }
    });
  }

  setTheme(t: ThemeMode): void {
    this.theme.set(t);
  }

  toggleTheme(): void {
    this.theme.set(this.theme() === 'dark' ? 'light' : 'dark');
  }

  setColorblind(on: boolean): void {
    this.colorblind.set(on);
  }

  toggleColorblind(): void {
    this.colorblind.set(!this.colorblind());
  }

  private loadTheme(): ThemeMode {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_THEME);
      if (stored === 'dark' || stored === 'light') return stored;
    } catch {
      // ignore
    }
    if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  }

  private loadColorblind(): boolean {
    try {
      return localStorage.getItem(STORAGE_KEY_CB) === '1';
    } catch {
      return false;
    }
  }
}
