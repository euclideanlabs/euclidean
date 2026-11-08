# euclidean

Diagnose retrieval problems in pgvector, using code search for AI agents as
the workload. Compares exact vector, approximate vector, and lexical search.

Status: Module 1 (benchmark labels and metrics). See `PROGRESS.MD`.

```
uv run pytest
uv run python scripts/mine_click_cases.py --max-cases 15
```
The miner needs a clone of Click at `.cache/repos/click`:
`git clone --filter=blob:none https://github.com/pallets/click.git .cache/repos/click`
