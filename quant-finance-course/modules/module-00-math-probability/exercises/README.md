# Module 00 — Exercises on Real Market Data

Three exercises connecting the probability/linear-algebra material to actual returns. All use
`lib/quantlab` for data loading — real data via yfinance when online, seeded synthetic GBM
offline (the *contrast* between the two is itself part of Exercise 1).

**Workflow**: fill in the `TODO`s in `ex_starter.py` (or work in your own script/notebook, but
keep functions importable — the tutor reviews code, not screenshots). When done, write your
findings in `findings.md` (3–10 sentences per exercise, written like you're reporting to a PM),
commit, and request review. Review is against the CLAUDE.md §4 checklist — yes, even for
exercises: unvectorized pandas gets flagged here too.

---

## Exercise 1 — Are daily returns normal? (moments & tails)

Data: SPY daily adjusted closes, 2005-01-01 → 2024-12-31 (or synthetic fallback).

1. Compute daily **log returns**. State in one sentence why log returns rather than simple
   returns for this analysis.
2. Compute mean, std, skewness, and excess kurtosis (implement skew/kurtosis with numpy
   yourself — no `scipy.stats` — formulas in the lesson notes; then check against a library if
   you like).
3. Count observations beyond 3σ, 5σ, and compare with the normal-model expectation
   (P(|Z|>3) ≈ 0.0027, P(|Z|>5) ≈ 5.7×10⁻⁷). Report expected vs observed counts.
4. Run the same pipeline on **synthetic GBM data** (`quantlab.data.synthetic_prices`) with
   matched mean/vol. Which statistics distinguish real from synthetic? That difference is the
   fingerprint of fat tails + vol clustering.

*Report*: a table of moments (real vs synthetic vs normal-theory) + your 3-sentence verdict.

## Exercise 2 — Watch the CLT work (and where it stalls)

Same SPY log returns.

1. Aggregate to non-overlapping 5-day, 21-day, and 63-day sums. State why they must be
   **non-overlapping** (what would overlap do to your independence assumption?).
2. For each horizon, compute skew and excess kurtosis. Tabulate kurtosis vs horizon.
3. If daily returns were i.i.d., excess kurtosis should decay like κ/n with aggregation. Compare
   the observed decay to that prediction. Faster or slower? What feature of returns (hint:
   variance autocorrelation) explains the deviation?

*Report*: the decay table + 3 sentences on what this means for, e.g., monthly VaR computed from
daily data.

## Exercise 3 — The covariance matrix and its eigenvalues (PCA preview)

Data: daily returns for 8–10 liquid ETFs spanning asset classes, e.g.
`SPY, QQQ, IWM, EFA, EEM, TLT, IEF, GLD, USO, HYG`, 2015-01-01 → 2024-12-31.

1. Build the (N×N) covariance **and** correlation matrices of daily returns. Verify PSD by
   computing eigenvalues (`np.linalg.eigvalsh`). Any negative? Should there be?
2. Eigendecompose the correlation matrix. What fraction of total variance does the top
   eigenvector explain? Inspect its loadings: which assets load with the same sign? Interpret
   it in one sentence ("the ___ factor").
3. Look at eigenvector 2. Which assets oppose which? (Classic answer: stocks vs bonds/duration.)
4. Portfolio math check: for equal weights w, verify wᵀΣw equals the variance of the equally
   weighted portfolio's return series directly (`np.allclose`). If it doesn't, find your bug —
   it's usually ddof or alignment.
5. **Stress test**: recompute the correlation matrix on 2020-02-15 → 2020-04-30 only. Compare
   average pairwise equity correlation vs your full-sample estimate. Two sentences: what
   happened to diversification exactly when it was needed?

*Report*: eigenvalue spectrum (table or plot), top-2 eigenvector interpretation, the crisis
comparison.

---

## Review checklist the tutor will apply

- [ ] No lookahead (does any statistic use future data relative to its label/date?)
- [ ] Correct ddof choices, stated (sample vs population — know which and why)
- [ ] Vectorized: no `iterrows`, no per-row `apply`
- [ ] NaN policy explicit (aligned multi-asset panel: how were missing days handled and why?)
- [ ] Seeded randomness where synthetic data is used
- [ ] `findings.md` reads like a note to a PM, not a homework answer
