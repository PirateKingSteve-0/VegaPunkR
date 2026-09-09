#!/usr/bin/env python3
"""
Parse an Apex Clearing trade-confirmation PDF into normalised fill rows.

Tradier clears through Apex, so the confirms downloaded from the Tradier portal
(Documents -> Confirmations) are Apex "Postedge" documents. They are the only
INDEPENDENT record we have of our fills: `trades` rows are written by our own
engine, so an engine bug corrupts the evidence and the record of it at the same
time. See TODO.md stream I.

Layout (verified against 2026-09-02 and 2026-09-04 confirms):

    Acct                                              Add'l    Tag
    Type  B/S  TradeDate  SettleDate  QTY  SYM  PRICE  Principal  COMM  TranFee  Fees  Number  NetAmount  Trade#  M/K  C/A
    1     B    09/02/26   09/03/26    1         3.2700000  327.00  0.00  0.02    0.09  S6637   327.11     TNB0903  5   1
    Desc:  CALL SPY  09/02/26 760 STATE STREET SPDR S&P 500 ETF UNSOLICITED OPEN CONTRACT   Interest/STTax: 0.00  CUSIP: 8GTXKB7
    Currency: USD   ReportedPX:                        MarkUp/Down:
    Trailer:  UNSOLICITED, OPEN CONTRACT

Four lines per fill. Things the layout forces on us:

  * The SYM column is EMPTY for options — the contract lives in the Desc line
    ("CALL SPY 09/02/26 760"), so the OCC symbol has to be reconstructed.
  * There is NO broker order id anywhere on the confirm. "Tag Number" (S6637)
    and "Trade#" (TNB0903) are Apex's own identifiers, unrelated to the Tradier
    order id we store in `Trade.notes['order_id']`. Matching is therefore a
    composite on (trade date, contract, side, qty, price) — see TODO.md I3.
  * There is no execution TIME, only a trade date. Fills are grouped by contract,
    not ordered chronologically, so a day reconciles as a multiset.
  * Page 1 is a cover sheet (clearing-firm address block only); the fills are on
    the following page(s). Pages are therefore parsed by content, not position.
    Identical pages are dropped as insurance against a duplicated customer/firm
    copy — not an observed condition in the 2026-09 confirms, but cheap.

The SUMMARY block at the foot of each page gives TOTAL DOLLARS BOUGHT/SOLD,
which is a free checksum on the parse — --strict turns a mismatch into an error.

Read-only. This script never touches `trades` or `positions`.

Usage:
    python3 scripts/parse_broker_confirm.py ~/Downloads/Doc_*CONFIRMATION*.pdf
    python3 scripts/parse_broker_confirm.py --json confirm.pdf > fills.json
"""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

# A fill's main line: acct type, then B or S, then two dates.
MAIN_RE = re.compile(r"^\s*(\d+)\s+([BS])\s+(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})\s+")
DESC_RE = re.compile(
    r"^Desc:\s+(?P<kind>CALL|PUT)\s+(?P<root>[A-Z][A-Z0-9.]*)\s+"
    r"(?P<expiry>\d{2}/\d{2}/\d{2})\s+(?P<strike>[\d.]+)\s+(?P<rest>.*)$",
    re.MULTILINE,
)
CUSIP_RE = re.compile(r"CUSIP:\s*(\S+)")
OPENCLOSE_RE = re.compile(r"\b(OPEN|CLOSING) CONTRACT\b")
SUMMARY_DATE_RE = re.compile(r"SUMMARY FOR CURRENT TRADE DATE:\s*(\d{2}/\d{2}/\d{2})")
TOTAL_BOUGHT_RE = re.compile(r"TOTAL DOLLARS BOUGHT:\s*(-?[\d,]+\.\d{2})")
TOTAL_SOLD_RE = re.compile(r"TOTAL DOLLARS SOLD:\s*(-?[\d,]+\.\d{2})")
ACCOUNT_RE = re.compile(r"Account Number:\s*(\S+)")


def _num(tok: str) -> float:
    return float(tok.replace(",", "").replace("$", ""))


def _date(tok: str) -> str:
    """MM/DD/YY -> ISO. Confirms are contemporary, so pivot on 2000."""
    return datetime.strptime(tok, "%m/%d/%y").date().isoformat()


@dataclass
class Fill:
    trade_date: str
    settle_date: str
    side: str                 # 'buy' | 'sell'
    action: str               # buy_to_open | sell_to_close | buy_to_close | sell_to_open
    qty: int
    price: float
    principal: float
    commission: float
    tran_fee: float
    fees: float
    net_amount: float
    instrument_type: str      # 'option' | 'equity'
    underlying: str | None = None
    option_symbol: str | None = None   # reconstructed OCC
    expiry: str | None = None
    strike: float | None = None
    right: str | None = None           # 'C' | 'P'
    cusip: str | None = None
    tag_number: str | None = None      # Apex tag, NOT a Tradier order id
    trade_number: str | None = None
    raw_line: str = ""

    @property
    def total_fees(self) -> float:
        return round(self.commission + self.tran_fee + self.fees, 4)


@dataclass
class Confirm:
    source_file: str
    account_last: str | None
    trade_dates: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)   # trade_date -> {bought, sold}
    pages_parsed: int = 0
    pages_skipped_duplicate: int = 0


def pdf_pages(path: Path) -> list[str]:
    """Text per page, layout preserved. poppler's pdftotext; swap for pdfplumber
    if this ever moves into the API container and poppler isn't available."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True, text=True, check=True,
        ).stdout
    except FileNotFoundError:
        sys.exit("pdftotext not found — install poppler-utils")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"pdftotext failed on {path.name}: {exc.stderr.strip()}")
    return out.split("\f")


def occ_symbol(root: str, expiry_iso: str, right: str, strike: float) -> str:
    y, m, d = expiry_iso.split("-")
    return f"{root}{y[2:]}{m}{d}{right}{int(round(strike * 1000)):08d}"


def parse_main_line(line: str) -> dict | None:
    """Anchor on the head (acct, B/S, two dates) and the tail (fixed 10 numeric
    /id columns). Whatever sits between is the SYM column, which options leave
    blank — so it cannot be located positionally from the left."""
    if not MAIN_RE.match(line):
        return None
    t = line.split()
    if len(t) < 15:
        return None
    try:
        head = {
            "side": "buy" if t[1] == "B" else "sell",
            "trade_date": _date(t[2]),
            "settle_date": _date(t[3]),
            "qty": int(_num(t[4])),
        }
        tail = {
            "price": _num(t[-10]),
            "principal": _num(t[-9]),
            "commission": _num(t[-8]),
            "tran_fee": _num(t[-7]),
            "fees": _num(t[-6]),
            "tag_number": t[-5],
            "net_amount": _num(t[-4]),
            "trade_number": t[-3],
        }
    except (ValueError, IndexError):
        return None
    sym = [tok for tok in t[5:-10] if any(c.isalpha() for c in tok)]
    head["sym"] = sym[0] if sym else None
    return {**head, **tail, "raw_line": line.rstrip()}


def parse(path: Path) -> Confirm:
    conf = Confirm(source_file=path.name, account_last=None)
    seen_pages: set[str] = set()

    for page in pdf_pages(path):
        if not page.strip():
            continue
        key = " ".join(page.split())
        if key in seen_pages:
            conf.pages_skipped_duplicate += 1
            continue
        seen_pages.add(key)
        conf.pages_parsed += 1

        lines = page.splitlines()
        for i, line in enumerate(lines):
            if conf.account_last is None:
                if m := ACCOUNT_RE.search(line):
                    conf.account_last = m.group(1)
            if m := SUMMARY_DATE_RE.search(line):
                conf.summary.setdefault(_date(m.group(1)), {})
            if m := TOTAL_BOUGHT_RE.search(line):
                for d in conf.summary:
                    conf.summary[d].setdefault("bought", abs(_num(m.group(1))))
            if m := TOTAL_SOLD_RE.search(line):
                for d in conf.summary:
                    conf.summary[d].setdefault("sold", abs(_num(m.group(1))))

            base = parse_main_line(line)
            if not base:
                continue

            # The three continuation lines belong to this fill.
            block = "\n".join(lines[i + 1 : i + 4])
            sym = base.pop("sym")
            fill = Fill(
                **base,
                action=base["side"] + "_to_open",   # provisional; fixed below
                instrument_type="equity" if sym else "option",
                underlying=sym,
            )

            if m := DESC_RE.search(block):
                fill.instrument_type = "option"
                fill.underlying = m.group("root")
                fill.right = "C" if m.group("kind") == "CALL" else "P"
                fill.expiry = _date(m.group("expiry"))
                fill.strike = float(m.group("strike"))
                fill.option_symbol = occ_symbol(
                    fill.underlying, fill.expiry, fill.right, fill.strike
                )
            if m := CUSIP_RE.search(block):
                fill.cusip = m.group(1)
            oc = OPENCLOSE_RE.search(block)
            suffix = "to_close" if oc and oc.group(1) == "CLOSING" else "to_open"
            fill.action = f"{fill.side}_{suffix}"

            conf.fills.append(fill)

    conf.trade_dates = sorted({f.trade_date for f in conf.fills})
    return conf


def checksum(conf: Confirm) -> list[str]:
    """Compare parsed net amounts against the confirm's own SUMMARY totals."""
    problems = []
    for date, totals in conf.summary.items():
        day = [f for f in conf.fills if f.trade_date == date]
        bought = round(sum(f.net_amount for f in day if f.side == "buy"), 2)
        sold = round(sum(f.net_amount for f in day if f.side == "sell"), 2)
        if "bought" in totals and abs(bought - totals["bought"]) > 0.005:
            problems.append(
                f"{date}: parsed bought {bought:.2f} != summary {totals['bought']:.2f}"
            )
        if "sold" in totals and abs(sold - totals["sold"]) > 0.005:
            problems.append(
                f"{date}: parsed sold {sold:.2f} != summary {totals['sold']:.2f}"
            )
    if not conf.fills:
        problems.append("no fills parsed — layout may have changed")
    return problems


def report(conf: Confirm) -> None:
    print(f"\n{conf.source_file}")
    print(f"  account ...{conf.account_last}   pages {conf.pages_parsed} parsed, "
          f"{conf.pages_skipped_duplicate} duplicate skipped")
    print(f"  trade dates: {', '.join(conf.trade_dates) or '(none)'}   fills: {len(conf.fills)}")
    print()
    hdr = f"  {'date':<11}{'settle':<11}{'action':<15}{'contract':<20}{'qty':>4}{'price':>9}{'net':>11}{'fees':>7}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for f in conf.fills:
        contract = f.option_symbol or f.underlying or "?"
        print(f"  {f.trade_date:<11}{f.settle_date:<11}{f.action:<15}{contract:<20}"
              f"{f.qty:>4}{f.price:>9.2f}{f.net_amount:>11.2f}{f.total_fees:>7.2f}")

    for date in conf.trade_dates:
        day = [f for f in conf.fills if f.trade_date == date]
        bought = sum(f.net_amount for f in day if f.side == "buy")
        sold = sum(f.net_amount for f in day if f.side == "sell")
        fees = sum(f.total_fees for f in day)
        print(f"\n  {date}: bought {bought:,.2f}  sold {sold:,.2f}  "
              f"net {sold - bought:+,.2f}  fees {fees:.2f}")

    problems = checksum(conf)
    print()
    if problems:
        for p in problems:
            print(f"  CHECKSUM FAIL: {p}")
    else:
        print("  checksum OK (parsed net amounts match the confirm's SUMMARY totals)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="+", type=Path)
    ap.add_argument("--json", action="store_true", help="emit normalised fills as JSON")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on a checksum failure")
    args = ap.parse_args()

    failed = False
    payload = []
    for path in args.pdfs:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            failed = True
            continue
        conf = parse(path)
        problems = checksum(conf)
        failed = failed or bool(problems)
        if args.json:
            payload.append({
                "source_file": conf.source_file,
                "account_last": conf.account_last,
                "trade_dates": conf.trade_dates,
                "summary": conf.summary,
                "checksum_problems": problems,
                "fills": [asdict(f) for f in conf.fills],
            })
        else:
            report(conf)

    if args.json:
        print(json.dumps(payload, indent=2))
    return 1 if (failed and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
