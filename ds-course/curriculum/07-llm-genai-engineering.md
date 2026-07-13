# Module 07 — LLM & GenAI Engineering

**Estimated time:** ~28 hours (weeks 19–21) · **Working area:** `modules/07-llm-genai-engineering/`

## Why this module matters in 2026

This is the biggest hiring delta right now: most DS candidates list "GenAI" on their
resume, very few can show a working RAG system **with an eval harness**. Evaluation
is the differentiator — anyone can call an API; measuring whether the system is
actually good is the data-science skill. This module produces the RAG portfolio
project.

## Learning objectives

1. **Embeddings**: what they are, similarity metrics, chunking strategies and their
   failure modes, vector stores (a local one — e.g., FAISS/DuckDB/pgvector-style —
   is fine; no cloud dependency needed).
2. **RAG pipelines**: retrieval → reranking → generation; where each stage fails;
   hybrid (keyword + vector) search; citing sources to reduce hallucination.
3. **Prompt engineering** as engineering: structured outputs, few-shot examples,
   system prompts, prompt versioning and regression testing.
4. **LLM evals** (the core skill): golden sets, retrieval metrics (recall@k, MRR),
   answer grading with rubrics, LLM-as-judge and its biases, human spot-checks,
   regression testing when you change a prompt or model.
5. Build a **small agent**: tool use / function calling loop, guardrails, when
   agentic complexity is and isn't warranted.
6. Cost/latency engineering: caching, model-size selection, batching.

## Curated free resources

- Provider docs are the primary source here and change fast — the tutor will pull
  current links at module start. Anchors:
- [Anthropic docs — prompt engineering & tool use](https://docs.claude.com/) (the tutor should fetch the current best pages)
- [Hugging Face — sentence-transformers docs](https://www.sbert.net/) — embeddings & semantic search
- [FAISS wiki/getting started](https://github.com/facebookresearch/faiss/wiki) — local vector search
- Eugene Yan, [Patterns for LLM Systems](https://eugeneyan.com/writing/llm-patterns/) — evals, RAG, guardrails survey
- [Hamel Husain — Your AI product needs evals](https://hamel.dev/blog/posts/evals/) — the eval-harness mindset

## Exercises (generated in depth when you reach this module)

1. Embeddings lab: chunk a real document corpus, build local vector search, measure
   retrieval quality (recall@k) against a hand-labeled golden set — before any LLM.
2. RAG v0 → v1: baseline pipeline, then one improvement (reranking or hybrid search),
   with the eval harness proving the improvement.
3. Prompt regression suite: change a prompt, show the eval catches the regression.
4. Mini-agent: a two-tool agent (e.g., search + calculator) with a transcript log
   and failure analysis.
5. **RAG portfolio project** (`projects/rag-doc-assistant/`) is built during this module.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
- [ ] RAG project has a README with eval results table at the top
