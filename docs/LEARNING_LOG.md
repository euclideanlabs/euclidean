# Learning log

## Module 1 — Benchmark labels and metrics (2026-11-04)

**Built and verified**
- Manifest schema with strict validation (`src/euclidean/dataset/manifest.py`).
- File-level and symbol-level labels; Python symbol extraction with AST.
- recall@k, precision@k, MRR@k, nDCG@k with hand-computed unit tests.
- Miner that makes candidate cases from Click fix commits + GitHub text.
- 21 unit tests pass. Miner produced 15 candidates; all labels exist at the
  pinned commit (636 symbols in `src/click`).

**Concepts**
- Labels must come from a source independent of search results.
- A pinned dataset version (full commit SHA) makes runs repeatable.
- Hash-based dev/heldout split prevents hand-moving hard cases.
- Granularity matters: 17 source files is too few to rank; 636 symbols is not.
- Metric conventions change numbers: dedupe of chunks, precision divides by
  k, MRR cutoff, binary nDCG. A report must state them.

**Trade-offs and failure modes**
- Patch files are incomplete labels: a fix changes one place, but other
  files can also be useful to read. Recall against patch labels is a lower
  bound on usefulness, and precision is pessimistic.
- PR text often names the fixed code, so it leaks the answer into the query.
  Issue text describes the symptom. Only 3 of 15 candidates had issue text.
- `commits/{sha}/pulls` can return backport or release PRs, not the fix PR.
- Import edits create `<module>` labels that are noise.
- Single snapshot: the pinned code already contains the fix. Query text may
  match the new code. Per-case base commits (as in SWE-bench) avoid this but
  need one index per base commit.

**Interview explanation**
"I built the evaluation before the search system. Labels come from real fix
commits, so they are independent of any retriever. I score at symbol level
because file level was too coarse: one file held 31% of the code, so a
trivial baseline would look good. Mined cases are candidates until a person
reviews them, and the split is a hash of the case id so I cannot tune on
held-out cases."

**Gaps / next checkpoint**
- Review candidates; improve miner (drop backport PRs, `<module>` noise).
- Module 2: load the Click corpus into Supabase pgvector; exact search
  baseline and trivial baselines.
