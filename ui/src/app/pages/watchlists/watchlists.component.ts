import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDividerModule } from '@angular/material/divider';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import {
  Quote,
  TradierService,
  Watchlist,
  WatchlistSummary,
} from '../../services/tradier.service';

@Component({
  selector: 'app-watchlists',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatListModule,
    MatFormFieldModule,
    MatInputModule,
    MatChipsModule,
    MatProgressSpinnerModule,
    MatTableModule,
    MatDividerModule,
    MatTooltipModule,
    MatSnackBarModule,
  ],
  templateUrl: './watchlists.component.html',
  styleUrls: ['./watchlists.component.scss'],
})
export class WatchlistsComponent implements OnInit {
  private tradier = inject(TradierService);
  private snackBar = inject(MatSnackBar);

  watchlists = signal<WatchlistSummary[]>([]);
  selected = signal<Watchlist | null>(null);
  quotes = signal<Record<string, Quote>>({});
  loadingList = signal(false);
  loadingDetail = signal(false);
  loadingQuotes = signal(false);
  saving = signal(false);

  quoteColumns = ['symbol', 'last', 'change', 'actions'];

  // create-form state
  showCreate = signal(false);
  newName = '';
  newSymbols = '';

  // edit-form state
  editName = '';
  newSymbolInput = '';

  ngOnInit(): void {
    this.loadWatchlists();
  }

  loadWatchlists(selectId?: string): void {
    this.loadingList.set(true);
    this.tradier.getWatchlists().subscribe({
      next: (lists) => {
        this.watchlists.set(lists);
        this.loadingList.set(false);
        if (selectId) {
          const found = lists.find((l) => l.id === selectId);
          if (found) this.selectWatchlist(found);
        } else if (!this.selected() && lists.length > 0) {
          this.selectWatchlist(lists[0]);
        } else if (this.selected()) {
          // refresh currently-selected to make sure it still exists
          const stillThere = lists.find((l) => l.id === this.selected()!.id);
          if (!stillThere) this.selected.set(null);
        }
      },
      error: (err) => {
        this.loadingList.set(false);
        this.toast(this.errMsg(err, 'Failed to load watchlists'));
      },
    });
  }

  selectWatchlist(w: WatchlistSummary): void {
    this.showCreate.set(false);
    this.loadingDetail.set(true);
    this.quotes.set({});
    this.tradier.getWatchlist(w.id).subscribe({
      next: (detail) => {
        this.selected.set(detail);
        this.editName = detail.name;
        this.newSymbolInput = '';
        this.loadingDetail.set(false);
        this.loadQuotesForSelected();
      },
      error: (err) => {
        this.loadingDetail.set(false);
        this.toast(this.errMsg(err, 'Failed to load watchlist'));
      },
    });
  }

  private loadQuotesForSelected(): void {
    const wl = this.selected();
    if (!wl || wl.items.length === 0) {
      this.quotes.set({});
      return;
    }
    const symbols = wl.items.map((i) => i.symbol);
    this.loadingQuotes.set(true);
    this.tradier.getQuotes(symbols).subscribe({
      next: (rows) => {
        const map: Record<string, Quote> = {};
        for (const q of rows) map[q.symbol] = q;
        this.quotes.set(map);
        this.loadingQuotes.set(false);
      },
      error: () => {
        this.loadingQuotes.set(false);
      },
    });
  }

  refreshQuotes(): void {
    this.loadQuotesForSelected();
  }

  startCreate(): void {
    this.showCreate.set(true);
    this.selected.set(null);
    this.newName = '';
    this.newSymbols = '';
  }

  cancelCreate(): void {
    this.showCreate.set(false);
    if (this.watchlists().length > 0) this.selectWatchlist(this.watchlists()[0]);
  }

  createWatchlist(): void {
    const name = this.newName.trim();
    if (!name) return;
    const symbols = this.parseSymbolsInput(this.newSymbols);
    this.saving.set(true);
    this.tradier.createWatchlist(name, symbols).subscribe({
      next: (created) => {
        this.saving.set(false);
        this.showCreate.set(false);
        this.toast(`Created "${created.name}"`);
        this.loadWatchlists(created.id);
      },
      error: (err) => {
        this.saving.set(false);
        this.toast(this.errMsg(err, 'Failed to create watchlist'));
      },
    });
  }

  renameSelected(): void {
    const current = this.selected();
    const name = this.editName.trim();
    if (!current || !name || name === current.name) return;
    this.saving.set(true);
    this.tradier.updateWatchlist(current.id, name).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.selected.set(updated);
        this.editName = updated.name;
        this.toast('Watchlist renamed');
        // reload list so the sidebar reflects the new name (and possibly new id)
        this.loadWatchlists(updated.id);
      },
      error: (err) => {
        this.saving.set(false);
        this.toast(this.errMsg(err, 'Failed to rename watchlist'));
      },
    });
  }

  addSymbol(): void {
    const current = this.selected();
    if (!current) return;
    const symbols = this.parseSymbolsInput(this.newSymbolInput);
    if (symbols.length === 0) return;
    this.saving.set(true);
    this.tradier.addWatchlistSymbols(current.id, symbols).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.selected.set(updated);
        this.newSymbolInput = '';
        this.toast(`Added ${symbols.join(', ')}`);
        this.loadQuotesForSelected();
      },
      error: (err) => {
        this.saving.set(false);
        this.toast(this.errMsg(err, 'Failed to add symbols'));
      },
    });
  }

  removeSymbol(symbol: string): void {
    const current = this.selected();
    if (!current) return;
    this.saving.set(true);
    this.tradier.removeWatchlistSymbol(current.id, symbol).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.selected.set(updated);
        this.toast(`Removed ${symbol}`);
        this.quotes.update((q) => {
          const next = { ...q };
          delete next[symbol];
          return next;
        });
      },
      error: (err) => {
        this.saving.set(false);
        this.toast(this.errMsg(err, 'Failed to remove symbol'));
      },
    });
  }

  deleteSelected(): void {
    const current = this.selected();
    if (!current) return;
    if (!confirm(`Delete watchlist "${current.name}"? This cannot be undone.`)) return;
    this.saving.set(true);
    this.tradier.deleteWatchlist(current.id).subscribe({
      next: (remaining) => {
        this.saving.set(false);
        this.watchlists.set(remaining);
        this.selected.set(null);
        this.toast(`Deleted "${current.name}"`);
        if (remaining.length > 0) this.selectWatchlist(remaining[0]);
      },
      error: (err) => {
        this.saving.set(false);
        this.toast(this.errMsg(err, 'Failed to delete watchlist'));
      },
    });
  }

  private parseSymbolsInput(raw: string): string[] {
    return raw
      .split(/[\s,]+/)
      .map((s) => s.trim().toUpperCase())
      .filter((s) => s.length > 0);
  }

  private toast(msg: string): void {
    this.snackBar.open(msg, 'Dismiss', { duration: 3500 });
  }

  private errMsg(err: any, fallback: string): string {
    return err?.error?.detail || err?.message || fallback;
  }
}
