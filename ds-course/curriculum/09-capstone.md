# Module 09 — Capstone

**Estimated time:** ~30 hours (weeks 24–26) · **Working area:** `modules/09-capstone/` + a project folder

## Why this module matters in 2026

The capstone is the interview centerpiece: one end-to-end, product-style project you
can walk through for 30 minutes — problem framing, data decisions, modeling choices,
evaluation, deployment, and what you'd do next. Interviewers probe depth on ONE
project far more than breadth across many.

## What the capstone must include

1. **A real problem statement** framed in business terms, for a stakeholder you name
   (e.g., "reduce support ticket resolution time for a mid-size SaaS").
2. **Real public data** — or data you collect yourself (APIs, scraping within ToS).
3. **The full arc**: EDA → baseline → model → honest evaluation (module 05 rigor)
   → served endpoint or working app (module 08) → monitoring plan.
4. **An LLM component where it genuinely helps** (or a written justification for
   why it doesn't — that judgment is itself a differentiator).
5. **A README** that leads with results, states limitations honestly, and includes
   a 90-second architecture diagram.
6. **Tests + reproducibility**: fresh-clone-to-results in documented commands.

## Process (tutor-enforced)

1. **Week 1 — proposal**: one-page doc: problem, data source (verified downloadable),
   success metric, baseline, risks. Tutor reviews like a hiring manager.
2. **Weeks 1–2 — build**: milestone commits; tutor code-reviews at each milestone
   (leakage, validation, naming, tests, reproducibility).
3. **Week 3 — polish & defense**: README polish, then a mock 30-minute project
   walkthrough where the tutor plays a skeptical senior interviewer.

## Capstone ideas (tailor to career target; pick ONE)

- Support ticket triage & resolution assistant: classifier + RAG over docs + eval harness + API
- Churn-to-action system: churn model + uplift-style targeting + dashboard + served endpoint
- Local-market pricing model (real estate/rentals from open listings data) with drift monitoring
- Product review intelligence: aspect extraction with LLMs, quantified with classical stats, served as an API

## Done when

- [ ] Fresh clone reproduces headline results with documented commands
- [ ] Mock walkthrough passed (tutor as skeptical interviewer)
- [ ] Portfolio README updated with the capstone's result headline
