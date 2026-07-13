# Module 02 — Statistics & Probability

**Estimated time:** ~25 hours (weeks 6–8) · **Working area:** `modules/02-statistics-probability/`

## Why this module matters in 2026

This is the most heavily interviewed module for product-company DS roles. A/B testing
design questions ("how would you test this feature?", "your metric moved but the test
isn't significant — now what?") appear in nearly every loop. Weak stats is the #1
reason otherwise-strong candidates fail DS onsites.

## Learning objectives

1. Work with core distributions (Bernoulli/binomial, Poisson, normal, exponential)
   and know which real processes they model.
2. Explain and compute: sampling distributions, standard error, CLT, confidence
   intervals (and what they do NOT mean).
3. Run and critique hypothesis tests: t-tests, proportion tests, chi-square;
   p-values, power, effect size, multiple-comparison corrections.
4. **Design an A/B test end-to-end**: metric choice, unit of randomization, power
   analysis / sample size, duration, guardrail metrics, novelty effects, peeking
   and sequential-testing pitfalls, network interference.
5. Bayesian basics: priors/posteriors, Beta-binomial conversion example, when a
   Bayesian framing communicates better than a p-value.

## Curated free resources

- [Seeing Theory (Brown University)](https://seeing-theory.brown.edu/) — visual probability foundations
- [StatQuest playlists](https://www.youtube.com/@statquest) — hypothesis testing, p-values, power
- [Trustworthy Online Controlled Experiments — first chapters free / paper summaries](https://exp-platform.com/) (Kohavi et al.) — the A/B testing bible
- [Evan Miller — How Not To Run an A/B Test](https://www.evanmiller.org/how-not-to-run-an-ab-test.html) + his [sample size calculator](https://www.evanmiller.org/ab-testing/sample-size.html)
- [Think Bayes 2 (free online)](https://allendowney.github.io/ThinkBayes2/) — chapters 1–4
- Practice: probability brainteasers from [Brainstellar](https://brainstellar.com/) (easy/medium tiers)

## Exercises (generated in depth when you reach this module)

1. Simulation-first probability: verify 10 classic results by Monte Carlo in numpy.
2. Hypothesis-testing lab on a real dataset — includes one deliberately underpowered
   test you must diagnose.
3. **A/B test design doc** for a realistic product change (this becomes a portfolio
   artifact and interview talking point).
4. Bayesian conversion-rate analysis; compare conclusions with the frequentist version.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
- [ ] Can answer "design an A/B test for X" out loud in under 5 minutes, structured
