# Progress

## Calibration (student profile) — ⚠️ CONFIRM AT FIRST SESSION

The kickoff prompt's background/time/target fields were left as placeholders, so the tutor
assumed defaults. **First session: correct these, then re-cut `weekly-plan.md` if needed.**

- **Math level**: **CONFIRMED (2026-07-14)** — engineering undergrad; probability/statistics
  coursework ~7–8 years ago; can't attempt interview problems cold, needs refreshers first.
  Module 00 runs refresher-first, open-notes, with closed-notes only at the quiz gate.
- **Coding level**: _assumed_ working Python, limited numpy/pandas performance experience
- **Finance knowledge**: _assumed_ light/informal
- **Time budget**: _assumed_ ~10 hrs/week
- **Career target**: _assumed_ **Quant Researcher (buy-side)** — drives module weighting
  (see `curriculum/overview.md`); tell the tutor if it's QD or QT instead.

## Current status

- **Module**: 00 — Math & Probability Foundations (worked-example-first mode)
- **Warm-up set**: student invoked "show solution" for all 8 problems without attempting
  (2026-07-14); tutor delivered full worked solutions in chat. The set is therefore **spent as
  an assessment** — no placement signal was collected from it.
- **Teaching mode going forward**: worked-example-first. Tutor demonstrates techniques on
  solved problems; active recall is reintroduced gradually via short oral reps on *fresh
  variants* of the same techniques at the start of later sessions (warm-up question protocol,
  CLAUDE.md §1). Fresh variants are mandatory — the original 8 are burned.
- **Next gate**: lesson notes review → Exercises 1–3 (coding, can't be passively absorbed) →
  Module 00 quiz (**closed notes, fresh questions** — the quiz remains the real gate).

## Warm-up interview question log

One per session, served before anything else; no repeats. Format:
`date | question (short) | topic | result (clean / hinted / missed) | notes`

| Date | Question | Topic | Result | Notes |
|------|----------|-------|--------|-------|
| — | *first question served at next session; the warm-up problem set covers session 1* | | | |

## Session log

### Session 0 — 2026-07-13 (scaffold)

- Repo scaffolded: README, CLAUDE.md (tutor rules), curriculum 00–09, Module 00 deep material
  (lesson notes, warm-up set, real-data exercises, quiz), 5 project charters with rigor markers,
  `lib/quantlab` v0.1.0 (data loaders + metrics, 19 tests passing), weekly plan.
- Assumptions recorded above pending student calibration.
- Assigned: Module 00 warm-up problem set.

### Session 1 — 2026-07-14 (calibration)

- Student calibration: engineering-undergrad probability, ~7–8 years dormant; cannot attempt
  the warm-up cold. Exactly what placement was for — no penalty, plan adjusted.
- Tutor delivered an 8-tool probability refresher in chat (conditioning, complement,
  indicators/linearity, first-step recursion, Bayes, PSD correlation bounds, normal tails,
  fair-game reasoning), each with a micro-example distinct from the assigned problems.
- Warm-up converted from closed-notes placement to open-refresher working session.
- Plan impact: Module 00 now spans ~weeks 1–3; later modules shift back accordingly
  (`weekly-plan.md` updated; full re-cut at the week-4 checkpoint).

## Strengths / weaknesses (tutor's honest running assessment)

- **Known gap (2026-07-14)**: probability recall is dormant; retrieval-under-pressure is the
  skill to rebuild, not comprehension. Expect heavy spaced re-drilling of the same techniques
  across sessions until answers come without notes. Quiz stays closed-notes — no bar-lowering.
- **Engagement pattern to watch (2026-07-14, blunt by design)**: student requested full
  solutions before attempting any problem. Understandable while rusty, but if it persists past
  the refresher phase it becomes the #1 risk to interview readiness — oral screens cannot be
  passed by recognition. Tutor: keep sessions active (short reps, perturbed variants), and
  raise this directly if the pattern holds at the Module 00 quiz.

## Configurations-tried counters (multiple-testing honesty, per project)

*Every parameter/config attempt on a project gets tallied here (or in the project README) so
deflated Sharpe calculations use the true trial count.*

- Project 1: n/a (no fitted parameters)
- Projects 2–5: not started
