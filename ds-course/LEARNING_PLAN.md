# Personalized Learning Plan

> Built assuming the default profile (basic Python, no ML, 8–10 hrs/week, targeting a
> product-company data scientist role). **Edit your profile in `CLAUDE.md` and
> `progress.md`, then ask the tutor to re-tailor this plan.**

## The 6-month map (8–10 hrs/week ≈ 220 hours total)

| Weeks | Module | Hours | Deliverable |
|---|---|---|---|
| 1–3 | 00 Python for data work | ~25 | Tested data pipeline exercise, quiz ≥ 80% |
| 4–5 | 01 SQL + data modeling | ~18 | DuckDB analytics exercise set |
| 6–8 | 02 Statistics & probability | ~25 | A/B test design write-up (interview staple) |
| 9–10 | 03 Data wrangling & EDA | ~18 | EDA notebook that tells a story → **start Project 1** |
| 11–14 | 04 Classical ML | ~35 | **Project 1 (churn) modeling + SHAP** |
| 15–16 | 05 ML evaluation & experimentation | ~18 | Project 1 evaluation section + calibration |
| 17–18 | 06 Deep learning essentials | ~16 | PyTorch fundamentals, know when NOT to use DL |
| 19–21 | 07 LLM & GenAI engineering | ~28 | **Project: RAG system + eval harness** |
| 22–23 | 08 MLOps & production | ~20 | **Project: FastAPI + Docker deployment** |
| 24–26 | 09 Capstone | ~30 | End-to-end capstone, portfolio README polished |

## Weekly rhythm (example for 9 hrs/week)

| Day | Time | Activity |
|---|---|---|
| Weekday A | 2 hrs | New material: read curriculum resources, take notes |
| Weekday B | 2 hrs | Exercises (with tutor hints — no solutions) |
| Weekday C | 1 hr | Spaced-repetition quiz + flashcard review of older modules |
| Weekend | 4 hrs | Project work block + code review with tutor + git commit |

## Rules of engagement

1. **Every session starts and ends the same way** — the tutor quizzes you on the last
   module, and updates `progress.md` before you stop. Consistency beats intensity.
2. **Commit after every work block.** A months-long local commit history is your study log.
3. **Projects are the point.** Modules exist to make the projects good. If time is
   short in a week, cut module reading before cutting project work.
4. **Resist "show solution."** The portfolio only has value if you can defend every
   line in an interview.
5. **Interview checkpoints:** after modules 02, 04, and 07, do a mock-interview
   session (use the chat app for orals; this repo for take-home style questions).

## First session checklist (do this now)

- [ ] Edit the three profile lines in `CLAUDE.md`, `progress.md`, and the README header
- [ ] `python -m venv .venv && source .venv/bin/activate`
- [ ] `pip install -r requirements.txt`
- [ ] Open `modules/00-python-foundations/exercises/exercise-01.md` and start
