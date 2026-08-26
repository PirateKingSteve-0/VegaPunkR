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

type PaletteKey = ThemeMode | 'light-cb' | 'dark-cb';

const STORAGE_KEY_THEME = 'vp.theme';
const STORAGE_KEY_CB = 'vp.colorblind';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly theme = signal<ThemeMode>(this.loadTheme());
  readonly colorblind = signal<boolean>(this.loadColorblind());

  /**
   * Chart libraries (Chart.js, lightweight-charts) take colors as JS values, not
   * CSS, so the token palette has to be mirrored here.
   *
   * These four rows are the JS counterpart of the `--color-*` / `--text*` /
   * `--surface` custom properties in `src/styles.scss`. If you change a value
   * there, change the matching row here — they are meant to be identical.
   */
  private static readonly PALETTES: Record<PaletteKey, ChartPalette> = {
    light: {
      profit: '#06894c',
      loss: '#d92d20',
      profitFill: 'rgba(6, 137, 76, 0.12)',
      lossFill: 'rgba(217, 45, 32, 0.12)',
      primary: '#2563eb',
      text: '#0e1626',
      textMuted: '#58637a',
      grid: 'rgba(14, 22, 38, 0.08)',
      surface: '#ffffff',
    },
    dark: {
      profit: '#2bc77e',
      loss: '#f4695e',
      profitFill: 'rgba(43, 199, 126, 0.16)',
      lossFill: 'rgba(244, 105, 94, 0.16)',
      primary: '#6ea3f7',
      text: '#e4e9f1',
      textMuted: '#949eae',
      grid: 'rgba(255, 255, 255, 0.07)',
      surface: '#13181f',
    },
    // Colorblind mode: blue = profit, orange = loss. The accent drops to
    // graphite so chrome never reads as a profit figure.
    'light-cb': {
      profit: '#1d6fe0',
      loss: '#e06316',
      profitFill: 'rgba(29, 111, 224, 0.12)',
      lossFill: 'rgba(224, 99, 22, 0.13)',
      primary: '#344054',
      text: '#0e1626',
      textMuted: '#58637a',
      grid: 'rgba(14, 22, 38, 0.08)',
      surface: '#ffffff',
    },
    'dark-cb': {
      profit: '#5aa5ff',
      loss: '#ff9445',
      profitFill: 'rgba(90, 165, 255, 0.16)',
      lossFill: 'rgba(255, 148, 69, 0.16)',
      primary: '#c3cddb',
      text: '#e4e9f1',
      textMuted: '#949eae',
      grid: 'rgba(255, 255, 255, 0.07)',
      surface: '#13181f',
    },
  };

  readonly chartColors = computed<ChartPalette>(() => {
    const mode: ThemeMode = this.theme() === 'dark' ? 'dark' : 'light';
    const key: PaletteKey = this.colorblind() ? (`${mode}-cb` as PaletteKey) : mode;
    return ThemeService.PALETTES[key];
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
