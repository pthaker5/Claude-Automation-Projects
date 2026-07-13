# Module 06 — Deep Learning Essentials

**Estimated time:** ~16 hours (weeks 17–18) · **Working area:** `modules/06-deep-learning-essentials/`

## Why this module matters in 2026

You need working PyTorch literacy to be credible — to read model code, fine-tune
something small, and hold your own in the LLM module — but for most product-DS
roles, depth here matters less than modules 04/05/07. The highest-value skill is
judgment: **knowing when NOT to use deep learning** (small tabular data, latency
budgets, interpretability requirements) and saying so with reasons.

## Learning objectives

1. Tensors, autograd, and the training loop: write one from scratch once
   (data → forward → loss → backward → step) so nothing is magic.
2. Build an MLP in PyTorch; understand initialization, learning rate, batch size,
   overfitting vs underfitting diagnostics, early stopping.
3. Recognize the standard architectures at a reading level: CNNs (locality),
   transformers (attention, why they scaled) — enough to reason, not to derive.
4. Fine-tune a small pretrained model (e.g., a sentence-transformer or small vision
   model) rather than training from scratch — the 2026-realistic workflow.
5. Articulate the "when NOT to use DL" checklist and defend it in interview terms.

## Curated free resources

- [PyTorch — Learn the Basics](https://pytorch.org/tutorials/beginner/basics/intro.html) (official 8-part tutorial)
- [Andrej Karpathy — Neural Networks: Zero to Hero](https://karpathy.ai/zero-to-hero.html) — at minimum the micrograd + makemore intros
- [3Blue1Brown — Neural networks series](https://www.3blue1brown.com/topics/neural-networks) — intuition, including the transformer/attention chapters
- [The Illustrated Transformer (Jay Alammar)](https://jalammar.github.io/illustrated-transformer/)
- [Hugging Face course](https://huggingface.co/learn/nlp-course) — chapters 1–3 (pipeline, fine-tuning)

## Exercises (generated in depth when you reach this module)

1. Training loop from scratch on a real tabular/text dataset; log train/valid curves.
2. Overfit on purpose, then fix it: dropout, weight decay, early stopping — measure each.
3. Fine-tune a small pretrained text model on a real labeled dataset; compare against
   the LightGBM + TF-IDF baseline from module 04 skills. **Write up which wins and why.**
4. "Should we use DL here?" — three scenario memos (one yes, two no), interview-style.

## Done when

- [ ] Exercises complete · [ ] Quiz ≥ 80% · [ ] Socratic check passed
