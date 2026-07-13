# Module 00 — Warm-Up Problem Set

**Rules of engagement**
- Closed notes. Timebox: ~90 minutes for the set. These are calibrated to real first-round
  screens (easiest ≈ phone-screen opener, hardest ≈ onsite).
- Write your answers *with reasoning* in `answers.md` in this directory (gitignored? no — commit
  it; your reasoning history is course material).
- Stuck ≠ failed. Ask the tutor for **Hint 1** before giving up; hints escalate only on request.
- The tutor will not confirm/deny answers until you commit to one — just like an interviewer.
- After grading, expect Socratic follow-ups on every problem, including the ones you got right.

---

### P1 — Two dice (opener)
You roll two fair six-sided dice. Given that at least one die shows a 6, what is the probability
that both show 6?

### P2 — At least one head
A fair coin is tossed 10 times. What is the probability of at least one head? Now: what is the
probability of at least one run of two consecutive heads? (Exact answer for the second part —
set up the recursion.)

### P3 — Expected tosses
What is the expected number of fair-coin tosses to see the pattern **HH** for the first time?
And for **HT**? Explain, in words an interviewer would accept, why the two answers differ.

### P4 — The noisy signal (Bayes)
A trading signal fires on 10% of days. On days the market goes up (which happens 55% of days),
the signal fired that morning with probability 12%; on down days, with probability 7.5%.
Given the signal fired this morning, what is the probability the market goes up today?
Follow-up you should pre-empt: is this signal *useful*? Quantify.

### P5 — Broken sticks (indicators)
100 people put their (distinct) business cards in a hat; each then draws one uniformly at
random. What is the expected number of people who draw their own card? What is the variance?
(Variance is the interview separator — indicators, not combinatorics.)

### P6 — Gambler's ruin, trader's edition
You have \$100 and bet \$1 on fair coin flips. You stop at \$0 or \$1,000. (a) Probability you
reach \$1,000? (b) Now each flip wins with p = 0.51. Roughly what happens, and why is the
qualitative change so violent? (Exact formula optional; reasoning mandatory.)

### P7 — Correlation sanity check
Assets A and B each have correlation 0.9 with asset C. What is the *minimum* possible
correlation between A and B? How do you know your bound is right (what property of correlation
matrices are you using)?

### P8 — The 20σ day
Daily S&P returns have σ ≈ 1.2%. Under a normal model, estimate the probability of a single-day
−20% move (roughly −17σ; use a bound or known tail values — no calculator precision needed).
Given ~25,000 trading days in a century, what does the 1987 crash tell you about the model?
State the *two* distinct i.i.d.-normal assumptions that fail for real returns.

---

## Scoring rubric (tutor fills in `progress.md`)

| Problem | Skill probed | Clean solve | Solved w/ hints | Miss |
|---|---|---|---|---|
| P1 | conditioning trap | | | |
| P2 | complement + recursion | | | |
| P3 | conditioning on first step | | | |
| P4 | Bayes, likelihood ratios | | | |
| P5 | indicators, linearity, variance of dependent sum | | | |
| P6 | martingale/fair-game reasoning | | | |
| P7 | PSD constraint on correlations | | | |
| P8 | tails, model criticism | | | |

**Passing bar**: 6/8 with sound reasoning, and survives oral follow-ups. Below that, the tutor
assigns targeted drills before Module 00 exercises begin.
