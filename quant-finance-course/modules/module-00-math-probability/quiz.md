# Module 00 — Quiz

Taken when you believe the module is done. Two parts. The tutor grades; passing both closes the
module (gate criteria in `curriculum/overview.md`). **Do not read this before you're ready to
take it — treat it as the interview.**

## Part A — Written (60 min, closed notes)

1. A fair die is rolled repeatedly. What is the expected number of rolls until two consecutive
   sixes appear?

2. X ~ Uniform(0,1) and Y ~ Uniform(0,1), independent. What is P(X + Y < 1) — and E[|X − Y|]?

3. You're shown a correlation matrix for 3 assets with ρ₁₂ = 0.8, ρ₁₃ = 0.8, ρ₂₃ = −0.5.
   Accept or reject it, with proof.

4. Daily returns are i.i.d. with mean μ = 0.04% and σ = 1.2%. (a) Give the mean and σ of the
   252-day compounded return under a log-return approximation. (b) An investor says "positive
   expected daily return means I almost surely make money over 40 years." Assess, quantitatively.

5. A permutation of {1,…,52} is drawn uniformly (a shuffled deck). Let N be the number of cards
   in their original position. Give E[N], Var(N), and P(N = 0) approximately. What distribution
   does N approach for large decks, and why is that "surprising"?

6. Σ is a valid covariance matrix of daily returns for 50 assets, estimated from 40 days of
   data. An optimizer using Σ⁻¹ returns weights of ±4000%. Explain the linear-algebra root cause
   and name two fixes.

7. Signal S predicts tomorrow's direction with 52% accuracy, independently each day, and you can
   make one bet per day. Signal T predicts with 60% accuracy but only fires 10 times a year.
   Which do you want, and under what sizing/horizon assumptions? (There is no single right
   answer — the grading is on your framework.)

## Part B — Oral drill (tutor-administered, ~30 min)

The tutor runs this live, interview-style: think aloud, no long silences, partial credit for
recovering from errors. Sample stems (tutor rotates, doesn't reuse logged ones):

- Rapid fire: memorylessness, birthday-problem scale, expected max of two dice, P(two heads in
  a row before two tails in a row)?
- Perturbations of written answers ("your #1 — now the die is biased toward six; direction of change?")
- Market intuition: "Why can you estimate vol so much better than the mean?" "Your backtest
  Sharpe doubled when you shortened the window — reactions?" "Correlations went to 1 in the
  crash — what does that do to your 'diversified' book, mechanically?"
- One estimation Fermi: "Roughly how many independent bets does a monthly-rebalanced 100-stock
  long-short book make per year? Defend your independence assumption."

## Grading

- Part A: 5/7 to pass; #3 and #6 are non-negotiable (core PSD/linear-algebra literacy).
- Part B: pass/fail on *process* — clear reasoning, error recovery, no bluffing. Bluffing an
  answer you can't defend is an automatic fail (as it is on-site).
- Results and weak spots logged in `progress.md`; failed parts retaken after targeted drills
  with fresh questions.
