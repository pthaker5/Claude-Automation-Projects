# Module 09 — Capstone: A Full Research Project

**Status:** stub — scoped with the tutor when Modules 00–08 are (mostly) closed.
**Weight (QR):** ★★★ — this is the interview centerpiece.

## Goal

One complete research cycle, written up **like an internal research note** at a fund: question →
data → methodology → results → robustness → limitations → conclusion. The note, not the Sharpe,
is the deliverable. It must survive a hostile methodology review by the tutor (acting as PM).

## Requirements

1. A falsifiable research question stated *before* looking at results.
2. Pre-registered evaluation plan: universe, dates, in-sample/out-of-sample split, costs,
   success criteria — committed to git before the first full-sample run.
3. Run on the `lib/quantlab` engine with the documented cost model.
4. Robustness section: parameter sensitivity, subperiod analysis, deflated Sharpe given the
   number of trials actually run (count them honestly).
5. "Why this might not work" section: capacity, crowding, regime dependence, data caveats.
6. Reproducible: one command regenerates every figure and table in the note.

## Candidate directions (choose with tutor)

- Extend Project 2: does adding a second, weakly-correlated signal improve the momentum book
  after costs, judged out of sample?
- Extend Project 3: does the best vol forecast translate into a better vol-targeted portfolio?
- Extend Project 5: regime-filtering pairs — can cointegration breakdown be detected early enough
  to matter after costs?
- A fresh question the student proposes (preferred if genuinely motivated).

## Format

`projects/09-capstone/` — self-contained; research note as `NOTE.md` (or PDF) with figures;
appendix with negative results and everything that was tried.
