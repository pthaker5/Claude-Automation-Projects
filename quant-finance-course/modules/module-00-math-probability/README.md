# Module 00 — Math & Probability Foundations (Lesson Notes)

These notes are deliberately compact: the module is 70% problem-solving. Read a section, then
immediately do the matching warm-up problems and drill orally with the tutor. Interviewers don't
ask you to recite — they ask you to *solve, out loud, right now*.

**Contents**
1. [Probability spaces & counting](#1-probability-spaces--counting)
2. [Conditional probability & Bayes](#2-conditional-probability--bayes)
3. [Random variables & expectation](#3-random-variables--expectation)
4. [Common distributions & where they live in markets](#4-common-distributions)
5. [Joint behavior: covariance & correlation](#5-covariance--correlation)
6. [LLN, CLT — and why returns break your intuition](#6-lln-clt-and-real-returns)
7. [Linear algebra refresher](#7-linear-algebra-refresher)
8. [The brainteaser toolbox](#8-the-brainteaser-toolbox)

---

## 1. Probability spaces & counting

A probability space is (Ω, ℱ, P): outcomes, events, and a measure with P(Ω)=1 that is additive
over disjoint events. For interviews the working skills are:

- **Complement trick**: P(at least one …) = 1 − P(none). Reach for it *first* on "at least one" problems.
- **Counting**: permutations n!, combinations C(n,k) = n!/(k!(n−k)!). Know when order matters.
  Stars-and-bars for "how many ways to split n identical items into k bins": C(n+k−1, k−1).
- **Inclusion–exclusion** for unions of overlapping events.
- **Independence** means P(A∩B) = P(A)P(B) — it is an assumption about the *measure*, not about
  causality. Pairwise independence does not imply mutual independence (interviewers love this).

Market hook: "independent bets" is the mental model behind diversification and the Fundamental
Law of Active Management (IR ≈ IC·√breadth). Almost nothing in markets is truly independent —
which is why breadth is always overestimated.

## 2. Conditional probability & Bayes

P(A|B) = P(A∩B)/P(B). Bayes' rule is just this twice:

    P(H|E) = P(E|H) P(H) / P(E),   P(E) = Σᵢ P(E|Hᵢ)P(Hᵢ)

- **Base-rate neglect** is the classic trap: a 99%-accurate test for a 1-in-10,000 condition
  yields mostly false positives. Redo this until it's reflexive.
- **Law of total probability / conditioning**: the single most powerful brainteaser technique —
  condition on the first step (first toss, first card, first arrival) and recurse.
- **Signal analogy**: a trading signal is evidence E about future return H. Its value is the
  *likelihood ratio* P(E|up)/P(E|down), not its accuracy in isolation. A signal that fires
  rarely but with a high LR beats a chatty mediocre one — same math as the medical test.

## 3. Random variables & expectation

E[X] = Σ x·p(x) or ∫ x f(x) dx. Var(X) = E[X²] − (E[X])². Key operational facts:

- **Linearity of expectation needs NO independence**: E[ΣXᵢ] = ΣE[Xᵢ], always. Combined with
  **indicator variables** (E[1_A] = P(A)) it demolishes "expected number of …" problems:
  expected fixed points of a random permutation = n · (1/n) = 1, no combinatorics needed.
- Variance of a sum needs covariances: Var(ΣXᵢ) = ΣVar(Xᵢ) + 2ΣᵢΣⱼ<ᵢCov(Xᵢ,Xⱼ). Portfolio risk
  *is* this formula.
- **Law of iterated expectations**: E[X] = E[E[X|Y]]. Tower property. Underlies "my expected
  P&L given my forecast" reasoning and martingale arguments.
- **Jensen's inequality**: for convex φ, E[φ(X)] ≥ φ(E[X]). Why E[max(S−K,0)] > max(E[S]−K,0)
  (options have time value), and why volatility drags geometric returns: geometric mean ≈
  arithmetic mean − σ²/2.

## 4. Common distributions

| Distribution | Story | Mean / Var | Shows up as |
|---|---|---|---|
| Bernoulli(p) | one trial | p / p(1−p) | win/lose a trade, direction call |
| Binomial(n,p) | n independent trials | np / np(1−p) | # winning days; binomial trees |
| Geometric(p) | trials to first success | 1/p | "expected tosses until…" problems |
| Poisson(λ) | rare-event counts | λ / λ | order arrivals, jumps, defaults |
| Exponential(λ) | waiting time, memoryless | 1/λ / 1/λ² | time between trades/quotes |
| Uniform(a,b) | total ignorance | (a+b)/2 / (b−a)²/12 | Monte Carlo inputs; stick-breaking problems |
| Normal(μ,σ²) | sums of many small shocks | μ / σ² | the *assumption* under Black–Scholes, VaR |
| Lognormal | exp(Normal) | e^{μ+σ²/2} / … | price *levels* under GBM |
| Student-t(ν) | normal with fat tails | 0 / ν/(ν−2) | daily returns empirically (ν ≈ 3–5!) |

Memorize the memorylessness of the exponential/geometric — interviewers probe it constantly
("you've waited 5 minutes; expected additional wait?").

## 5. Covariance & correlation

Cov(X,Y) = E[XY] − E[X]E[Y]; ρ = Cov/(σ_X σ_Y) ∈ [−1,1] measures **linear** association only.

Traps you must be able to recite:
- ρ = 0 does NOT imply independence (X uniform on [−1,1], Y = X²: dependent, ρ = 0).
- Correlation is not transitive: ρ(A,B) > 0 and ρ(B,C) > 0 do not force ρ(A,C) > 0.
- Correlation matrices must be positive semi-definite — you cannot freely choose pairwise
  correlations. (Given ρ(A,B)=ρ(B,C)=0.9, ρ(A,C) ≥ 2(0.9²)−1 = 0.62.)
- Sample correlations of *prices* (nonstationary) are garbage; correlate *returns*.
- Empirical: equity correlations spike toward 1 in crises — exactly when diversification is
  needed most. Any "market-neutral" claim gets stress-tested on this.

## 6. LLN, CLT, and real returns

- **LLN**: sample mean → true mean (i.i.d., finite mean). Justifies estimating anything by
  simulation/averaging. Convergence is slow: standard error of a mean shrinks as 1/√n. This is
  why estimating expected *returns* is hopeless (σ ≈ 20%/yr means a 1%-precision estimate of an
  annual mean needs ~1600 years) while estimating *volatility* is feasible (more data per unit
  time helps).
- **CLT**: (Σ Xᵢ − nμ)/(σ√n) → N(0,1) for i.i.d. finite-variance Xᵢ. Sums of many small
  independent shocks look normal *in the middle of the distribution*.
- **Why daily returns still aren't normal**: excess kurtosis 5–30 (fat tails), mild negative
  skew for equities, volatility clustering (returns aren't i.i.d. — variance is autocorrelated
  even when returns aren't), and tail events far beyond Gaussian reach: a "−20σ day" under
  normality has probability ~10⁻⁸⁹; the S&P has had one (1987). One useful reconciliation:
  returns ≈ normal with *randomly varying variance* — a mixture, which is automatically fat-tailed.
- Aggregation: as you sum daily → monthly → annual returns, CLT slowly pulls the distribution
  toward normal. You will *measure* this in Exercise 2.

## 7. Linear algebra refresher

The subset quant work actually uses daily:

- Vectors/matrices as data: a return panel R is (T × N). Portfolio returns are R·w. Mean vector
  μ, covariance Σ = E[(r−μ)(r−μ)ᵀ]; portfolio variance is **wᵀΣw** — the most important
  quadratic form in finance.
- Matrix multiplication = composition of linear maps; it is associative, not commutative.
- Rank & invertibility: Σ estimated from T days of N assets has rank ≤ min(T−1, N). With
  N > T it is singular — one reason naive Markowitz explodes on big universes.
- **Eigendecomposition**: symmetric Σ = QΛQᵀ with orthonormal Q, real Λ. Eigenvectors are
  uncorrelated portfolio directions; eigenvalues their variances. Largest eigenvector of an
  equity covariance matrix ≈ "the market" (you'll verify this in Exercise 3 — this is PCA).
- **Positive semi-definite**: wᵀΣw ≥ 0 for all w ⟺ all eigenvalues ≥ 0. Every valid covariance
  matrix is PSD; a "correlation matrix" someone hands you with a negative eigenvalue is not one.
- Solving Ax = b: never invert explicitly in code — `np.linalg.solve` (or Cholesky for PSD).
  Conditioning: nearly-collinear assets → tiny eigenvalues → wild optimizer weights.

## 8. The brainteaser toolbox

Techniques, in the order you should try them:

1. **Symmetry** — "by symmetry, each of the n! orderings is equally likely…" Kills problems in
   one line (e.g., P(last card is an ace) = 4/52).
2. **Complement** — "at least one" → 1 − P(none).
3. **Indicators + linearity** — "expected number of X" → sum of P(each X happens).
4. **Condition on the first step & recurse** — expected tosses to HH: set up E via first-toss cases.
5. **Small cases & sanity limits** — compute n=1,2,3; check p→0, p→1, n→∞ behavior.
6. **Fair-game (martingale) reasoning** — gambler's ruin: P(hit A before −B) = B/(A+B) for a
   fair walk, because expected value is conserved.
7. **Say your reasoning out loud** — in the interview, a clean wrong-then-corrected path beats
   silent correctness. Practice speaking these solutions; that's what quiz orals are for.

---

**Next steps**: do [warmup.md](warmup.md) (no notes open), then
[exercises/](exercises/) on real market data, then request the quiz.
