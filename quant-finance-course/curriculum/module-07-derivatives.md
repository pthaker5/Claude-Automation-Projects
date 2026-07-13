# Module 07 — Derivatives & Stochastic Calculus Essentials

**Status:** stub — deep material generated when you start it.
**Weight (QR, buy-side):** ★★ essentials. Escalate to ★★★ if the target shifts to sell-side,
options market-making, or vol-focused funds — update `progress.md` and re-plan if so.

## Learning objectives

- Understand Brownian motion, Itô's lemma, and geometric Brownian motion at the level quant
  interviews test (derivations sketched, intuition solid — not full measure theory).
- Derive/justify Black–Scholes (replication and risk-neutral arguments), price with it, and
  explain every assumption and how reality violates it.
- Compute and *interpret* the Greeks; delta-hedging intuition and the vol P&L identity
  (gamma vs theta trade-off).
- Price by Monte Carlo with variance reduction, validated against closed form.
- Read an implied volatility surface: smile/skew, term structure, and what they say about the
  risk-neutral distribution.

## Topics

1. Random walks → Brownian motion; quadratic variation; Itô's lemma (used, not worshipped)
2. GBM, risk-neutral pricing, replication argument
3. Black–Scholes formula; the Greeks; delta hedging and where hedging P&L comes from
4. Monte Carlo pricing: discretization, antithetic variates, control variates; standard errors
5. Implied vol: computing it, the surface, skew intuition, put-call parity checks
6. Interview classics: "price a digital", "sign of vega for X", "what happens to delta as vol → ∞"

## Deliverables (planned)

- Feeds **Project 4** (options pricing & Greeks visualizer, MC vs closed-form validation).
- Quiz weighted toward oral derivation sketches and Greek-intuition rapid fire.
