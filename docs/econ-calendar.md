# Economic-event calendar — transcribed source data

Working transcription for the economic-event awareness feature (see `BRAINSTORM.md`,
"Economic-event awareness", and the `TODO.md` entry). **This is source data, not a seeded
artifact** — nothing consumes it yet.

All times Eastern. **"Held through"** means the release fires while this book has positions open:
we enter after `entry_after_open_minutes` and are flat by 15:45, so an 08:30 print resolves before
we ever have a position, while 10:00 and 14:00 releases land mid-trade. Per the BRAINSTORM decision,
danger ranks **FOMC 14:00 > 10:00 releases >> 08:30 releases**.

---

## Two classes of event, and why it matters

**Transcribable** — the agency publishes an exact annual schedule. Dates below are copied from those
pages and are high confidence.

**Rule-derived** — no public annual calendar exists; the date follows a rule and must be computed,
then holiday-adjusted. Lower confidence, needs per-month verification.

| Event | Time | Held through? | Class |
|---|---|---|---|
| FOMC decision | 14:00 | **Yes** | Transcribable |
| FOMC press conference | 14:30 | **Yes** | Transcribable (follows decision) |
| JOLTS | 10:00 | **Yes** | Transcribable |
| ISM Manufacturing PMI | 10:00 | **Yes** | Rule-derived |
| ISM Services PMI | 10:00 | **Yes** | Rule-derived |
| UMich Consumer Sentiment | 10:00 | **Yes** | Rule-derived |
| CPI | 08:30 | No | Transcribable |
| PPI | 08:30 | No | Transcribable |
| Employment Situation (NFP) | 08:30 | No | Transcribable |

---

## FOMC — 2026 *(decision 14:00, press conference 14:30)*

Source: <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm>

| Meeting | Decision day | SEP + projections |
|---|---|---|
| Jan 27–28 | **Wed Jan 28, 2026** | — |
| Mar 17–18 | **Wed Mar 18, 2026** | Yes |
| Apr 28–29 | **Wed Apr 29, 2026** | — |
| Jun 16–17 | **Wed Jun 17, 2026** | Yes |
| Jul 28–29 | **Wed Jul 29, 2026** | — |
| Sep 15–16 | **Wed Sep 16, 2026** | Yes |
| Oct 27–28 | **Wed Oct 28, 2026** | — |
| Dec 8–9 | **Wed Dec 9, 2026** | Yes |

## FOMC — 2027 *(tentative)*

The Fed marks these "tentative until confirmed at the meeting immediately preceding" — re-transcribe
before relying on them.

Jan 26–27 · Mar 16–17 (SEP) · Apr 27–28 · Jun 8–9 (SEP) · Jul 27–28 · Sep 14–15 (SEP) ·
Oct 26–27 · Dec 7–8 (SEP). Decision lands on the **second** day of each.

---

## JOLTS — 2026 *(10:00, held through)*

Source: <https://www.bls.gov/schedule/news_release/jolts.htm>

Jan 7 · Feb 5 · Mar 13 · Mar 31 · May 5 · Jun 2 · Jun 30 · Aug 4 · Sep 1 · **Sep 29** ·
**Nov 3** · **Dec 1**

Note the irregular cadence — two releases in March and two in June, none in April, July or October.
Not a transcription error; do not "fix" it into a monthly rule.

---

## CPI — 2026 *(08:30)*

Source: <https://www.bls.gov/schedule/news_release/cpi.htm>

Jan 13 · Feb 13 · Mar 11 · Apr 10 · May 12 · Jun 10 · Jul 14 · Aug 12 · **Sep 11** · **Oct 14** ·
**Nov 10** · **Dec 10**

## PPI — 2026 *(08:30)*

Source: <https://www.bls.gov/schedule/news_release/ppi.htm>

Jan 14 · Jan 30 · Feb 27 · Mar 18 · Apr 14 · May 13 · Jun 11 · Jul 15 · Aug 13 · **Sep 10** ·
**Oct 15** · **Nov 13** · **Dec 15**

## Employment Situation — 2026 *(08:30)*

Source: <https://www.bls.gov/schedule/news_release/empsit.htm>

Jan 9 · Feb 11 · Mar 6 · Apr 3 · May 8 · Jun 5 · Jul 2 · Aug 7 · Sep 4 · **Oct 2** · **Nov 6**

⚠️ **Verify this one before seeding.** The reference-month column as extracted looked shifted by a
month, and several dates are off the usual first-Friday pattern (Jan 9, Feb 11, May 8). The dates may
well be right — BLS schedules genuinely slip — but the extraction was not clean enough to trust
blind. The December 2026 release is also missing from the range captured.

---

## Rule-derived events — no public annual schedule

**ISM Manufacturing PMI** — first business day of the month, 10:00.
**ISM Services PMI** — third business day of the month, 10:00.

ISM's official release-date calendar (`ismworld.org/.../rob-report-calendar/`) redirects to a member
login, so exact dates cannot be transcribed from a public page. The rule is documented publicly and
holiday exceptions are announced per-release (e.g. the Dec-2025 Manufacturing report moved to Mon
Jan 5, 2026 for an ISM holiday; Services moved in July 2026 around the observed 4th).

**UMich Consumer Sentiment** — preliminary around the second Friday, final around the last Friday,
both 10:00. No clean public annual calendar found; <https://www.sca.isr.umich.edu/> is the source of
truth per-release.

**Consequence for the seed:** these three are the *most* relevant events (all 10:00, all held
through) and the *least* reliably schedulable. Either compute them from the rule and accept
occasional holiday drift, or verify the coming month's dates on a monthly cadence.

---

## Remaining 2026 releases, from 2026-09-08

Bold = held through.

| Date | Time | Event |
|---|---|---|
| Thu Sep 10 | 08:30 | PPI |
| Fri Sep 11 | 08:30 | CPI |
| Fri Sep 11 | 10:00 | **UMich preliminary** *(rule-derived)* |
| **Wed Sep 16** | **14:00** | **FOMC decision + SEP, presser 14:30** |
| Tue Sep 29 | 10:00 | **JOLTS** |
| Thu Oct 1 | 10:00 | **ISM Manufacturing** *(rule-derived)* |
| Fri Oct 2 | 08:30 | Employment Situation |
| Mon Oct 5 | 10:00 | **ISM Services** *(rule-derived)* |
| Wed Oct 14 | 08:30 | CPI |
| Thu Oct 15 | 08:30 | PPI |
| **Wed Oct 28** | **14:00** | **FOMC decision, presser 14:30** |
| Tue Nov 3 | 10:00 | **JOLTS** |
| Fri Nov 6 | 08:30 | Employment Situation |
| Tue Nov 10 | 08:30 | CPI |
| Fri Nov 13 | 08:30 | PPI |
| Tue Dec 1 | 10:00 | **JOLTS** |
| **Wed Dec 9** | **14:00** | **FOMC decision + SEP, presser 14:30** |
| Thu Dec 10 | 08:30 | CPI |
| Tue Dec 15 | 08:30 | PPI |

**Nearest held-through event: FOMC, Wed Sep 16 2026, 14:00 ET** — decision, projections and a press
conference at 14:30, all inside the trading window, with the book long premium and not flat until
15:45.
