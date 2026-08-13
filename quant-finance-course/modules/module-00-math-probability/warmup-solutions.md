# Module 00 — Warm-Up Solutions

**Provenance note (tutor):** the student invoked "show solution" for the full set before
attempting it (logged in `progress.md`, 2026-08). These are the tutor's worked solutions,
written the way an interviewer wants reasoning *spoken*. The set is spent as an assessment;
future drilling uses fresh variants of the same techniques.

---

## P1 — Two dice: **1/11**

The sample space is 36 equally likely ordered pairs. "At least one 6" contains 11 outcomes
(6 with a six on the first die + 6 with a six on the second − 1 double-counted (6,6)). Exactly
one of them is (6,6), so P = 1/11.

*Trap:* answering 1/6 by silently converting the condition into "a particular die shows 6."
Conditioning on "at least one" leaves a lopsided 11-outcome world; count inside it.

## P2 — At least one head: **1023/1024**. At least one HH run: **55/64 ≈ 0.86**

Part 1 is the complement trick: 1 − (1/2)¹⁰ = 1023/1024.

Part 2: count sequences with **no** two consecutive heads. Let aₙ be their number at length n.
A valid sequence ends in T (append T to any valid length-(n−1) sequence) or in H (which must be
preceded by T — append TH to any valid length-(n−2) sequence):

    aₙ = aₙ₋₁ + aₙ₋₂,   a₁ = 2, a₂ = 3   (Fibonacci)

Rolling forward: 2, 3, 5, 8, 13, 21, 34, 55, 89, **144**. So P(no HH) = 144/1024 = 9/64 and
P(at least one HH) = **55/64 ≈ 0.859**.

*Toolbox:* "at least one" → complement; "avoid a pattern" → recursion on how a valid string ends.

## P3 — Expected tosses: **HH = 6, HT = 4**

**HH.** States: S₀ (no progress), S₁ (just saw H).
E₀ = 1 + ½E₁ + ½E₀ and E₁ = 1 + ½·0 + ½E₀ (a T after your H **resets to S₀**).
From the first: E₀ = 2 + E₁. Substituting: E₁ = 4, E₀ = **6**.

**HT.** E₀ = 2 + E₁ as before, but from S₁ a head **keeps you in S₁**:
E₁ = 1 + ½·0 + ½E₁ → E₁ = 2, so E₀ = **4**.

*Interview English:* progress toward HT is never lost — holding an H, every toss either
finishes or leaves you holding an H. Progress toward HH is fragile — the failing toss destroys
it. Wasted work makes HH slower. (General fact: patterns that overlap themselves take longer
to first appear.)

## P4 — The noisy signal: **P(up | fired) ≈ 66%** — modestly useful

P(up) = 0.55, P(fire|up) = 0.12, P(fire|down) = 0.075.
P(fire) = 0.12·0.55 + 0.075·0.45 = 0.09975 ≈ 10% ✓ (matches "fires 10% of days" — always run
the consistency check). P(up|fire) = 0.066/0.09975 ≈ **0.662**.

Odds form — the right frame for signals: prior odds 55/45 ≈ 1.22; **likelihood ratio
0.12/0.075 = 1.6**; posterior odds ≈ 1.96 → p ≈ 0.66. The LR isolates the signal's strength
from the base rate.

*Useful? Quantified:* +11 points over base rate, but on only ~25 days/yr. Symmetric-payoff edge
2(0.66)−1 = 0.32 per unit staked on fire days vs 0.10 otherwise. Silence is mildly informative
too: P(up|no fire) ≈ 0.54. The unprompted-skepticism point interviewers reward: a
25-obs/yr signal takes years to validate statistically.

## P5 — Business cards: **E = 1, Var = 1**

X = Σ 1_{Aᵢ}, Aᵢ = "person i draws own card". P(Aᵢ) = 1/n → E[X] = 1 by linearity, dependence
irrelevant.

Variance needs pair terms: E[X²] = Σᵢ P(Aᵢ) + Σᵢ≠ⱼ P(Aᵢ∩Aⱼ). For ordered i ≠ j,
P(both own) = 1/[n(n−1)]; with n(n−1) ordered pairs the cross-sum is exactly 1.
E[X²] = 2, Var = 2 − 1 = **1** — for every n ≥ 2.

*Epilogue:* mean = variance = 1 hints at the truth: X → Poisson(1), so P(no one draws their own)
→ 1/e ≈ 37%.

## P6 — Gambler's ruin: **(a) 1/10; (b) ≈ 98%**

**(a)** Fair game → expected wealth conserved: 100 = p·1000 → p = **1/10**. No path counting.

**(b)** With p = 0.51 the conserved object is (q/p)^wealth. Standard result: starting at k with
absorbing barriers 0 and N, P(reach N) = (1 − (q/p)ᵏ)/(1 − (q/p)ᴺ). Here q/p = 49/51 ≈ 0.961,
(q/p)¹⁰⁰ ≈ e⁻⁴ ≈ 0.018, (q/p)¹⁰⁰⁰ ≈ e⁻⁴⁰ ≈ 0. So P ≈ **98.2%**.

*Why so violent:* fair games scale linearly with bankroll; any drift makes ruin decay
**exponentially** — each extra dollar of cushion multiplies ruin odds by q/p. Small edge + many
bets + adequate bankroll = near-certainty: the business model of a trading firm, and why sizing
discipline is sacred.

## P7 — Minimum correlation: **0.62**

Correlation matrices must be PSD: wᵀCw is a portfolio variance, so it can't be negative ⟺ all
eigenvalues ≥ 0 ⟺ (for 3×3, given |ρ| ≤ 1) det(C) ≥ 0, with
det(C) = 1 + 2ρ_AB ρ_AC ρ_BC − ρ_AB² − ρ_AC² − ρ_BC².

With ρ_AC = ρ_BC = 0.9: ρ_AB² − 1.62ρ_AB + 0.62 ≤ 0, roots (1.62 ± 0.38)/2 = {0.62, 1}, so
ρ_AB ∈ [**0.62**, 1].

*Attained, not just bounded:* at 0.62 the determinant is exactly 0 — a valid rank-2 matrix
(three assets, two factors). Geometric view: correlations are cosines; A and B each sit
arccos(0.9) ≈ 25.8° from C, hence at most ~51.7° apart: cos = 2(0.9²) − 1 = 0.62.
*Market translation:* two assets highly correlated with the market cannot hedge each other.

## P8 — The 20σ day: **~10⁻⁶⁴/day under normality → the model is rejected**

−20%/1.2% ≈ −17σ. Tail bound P(Z > z) ≈ φ(z)/z: e^(−17²/2) = e^(−144.5) ≈ 10^(−62.8); after
dividing by √(2π)·17, roughly **4×10⁻⁶⁵ ≈ 10⁻⁶⁴**. Over ~25,000 trading days the expected count
is ~10⁻⁶⁰. Yet 1987-10-19 happened (S&P −20.5%). One observation of likelihood 10⁻⁶⁴ is not bad
luck; it rejects the model at any confidence level.

*The two distinct i.i.d.-normal failures (name both, separately):*
1. **Marginal normality** — daily returns are fat-tailed (excess kurtosis ~5–30; Student-t with
   ν ≈ 3–5 fits far better).
2. **Independence / identical distribution over time** — volatility clusters; σ is
   regime-dependent. The "17σ" is measured in *unconditional* σ; conditional σ that week was
   several times higher. (Random-variance mixtures generate fat tails, so the failures are
   linked — but they are logically distinct assumptions.)

---

## Technique index (what future fresh-variant drills will re-test)

conditioning (P1) · complement + recursion (P2) · first-step state equations (P3) ·
Bayes in odds form / likelihood ratios (P4) · indicator variables incl. variance (P5) ·
conserved quantities / martingale reasoning (P6) · PSD geometry of correlations (P7) ·
Gaussian tail scaling + model criticism (P8)
