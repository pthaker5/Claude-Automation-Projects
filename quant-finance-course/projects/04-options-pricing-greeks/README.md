# Project 4 — Options Pricing & Greeks Visualizer (Monte Carlo vs Closed-Form)

**Status: OPTIONAL** — gated on Module 07. Elevated to core if the career target shifts toward
options/sell-side. Charter below.

<!-- RESULTS PLOTS GO HERE WHEN REAL: MC-vs-BS convergence, Greeks surfaces, vol smile -->

## What this is

A correctness-obsessed pricing lab: Black–Scholes closed form, binomial trees, and Monte Carlo
(with variance reduction) priced against each other, plus interactive-ish visualizations of the
Greeks across spot/vol/time and an implied-vol solver applied to real option chains (yfinance).

## Planned scope & validation

- BS closed form + Greeks (analytic); binomial tree converging to BS as steps → ∞ (rate shown).
- Monte Carlo: Euler vs exact GBM simulation; antithetic + control variates; **standard errors
  reported on every MC estimate** and convergence to closed form demonstrated (this is the
  validation, and the test suite enforces it).
- Greeks by finite difference and pathwise/likelihood-ratio MC estimators, cross-checked
  against analytic values.
- Implied vol: robust solver (bracketed Newton), applied to a real chain; smile/term structure
  plotted; put-call parity residuals as a data-quality check.

## Why this might not work / Limitations (drafted up front)

GBM is the *model*, not the market — this project validates numerics against the model, and says
so; free option-chain data is noisy (stale quotes, wide spreads) so smiles will be ragged;
American-exercise features of listed equity options vs European BS treated explicitly.

## Reproduce

*(one command, filled in when the code exists)*
