"""Mine candidate benchmark cases from Click fix commits.

Output cases have status 'candidate'. A person must review each one and set
status to 'reviewed' (or 'rejected') before it counts in any score.

Label rules:
- relevant_files: files under src/click/ that the fix changed and that exist
  at the pinned commit.
- relevant_symbols: the innermost def/class around each changed line, taken
  from the post-fix version, kept only if it exists at the pinned commit.
Query rule:
- Prefer the linked GitHub issue (it describes the problem, not the fix).
- Follow backport PRs to the original PR. Skip release PRs.
- Try closing references ("fixes #N") first, then plain mentions. The note
  records which one, because a mention can be a related issue only.
- Fall back to PR text, and flag it: PR text often names the fixed code.
- A changed import, blank or comment line outside every symbol is not a label. A file with no label left is dropped.
GitHub responses are cached in .cache/github/, so a re-run is cheap and
gives the same links.

Usage:
  uv run python scripts/mine_click_cases.py --max-cases 15
Set GITHUB_TOKEN to raise the GitHub API rate limit (60/hour without it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from euclidean.dataset.gitrepo import GitRepo
from euclidean.dataset.manifest import Manifest, QuerySource, assign_split
from euclidean.dataset.merge import merge_cases
from euclidean.dataset.linking import LinkStrength, PRKind, backport_source, issue_refs, pr_kind
from euclidean.dataset.symbols import MODULE, enclosing_symbol, extract_symbols, module_noise_lines, symbol_ids

REPO_URL = "https://github.com/pallets/click.git"
API = "https://api.github.com/repos/pallets/click"
SKIP_WORDS = ("typing", "ruff", "pyright", "pre-commit", "documentation", "doc ", "test",
              "cleanup", "rewrap", "deprecate", "type coverage")
PR_IN_SUBJECT = re.compile(r"\(#(\d+)\)\s*$")
MAX_QUERY_CHARS = 1500
MAX_ISSUE_LOOKUPS = 3
CACHE_DIR = Path(".cache/github")
ISSUE_SOURCE = {LinkStrength.CLOSES: QuerySource.ISSUE_CLOSES,
                LinkStrength.MENTIONS: QuerySource.ISSUE_MENTIONS}


def gh(path: str):
    """GET from the GitHub API. Cached on disk; a 404 is cached as None."""
    cache = CACHE_DIR / (hashlib.sha256(path.encode()).hexdigest()[:16] + ".json")
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["data"]
    data = _gh_fetch(path)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"path": path, "data": data}), encoding="utf-8")
    return data


def _gh_fetch(path: str):
    req = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "euclidean-benchmark-miner"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def clean(text: str | None) -> str:
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def find_query(sha: str, subject: str) -> tuple[str, str, QuerySource | None, str]:
    """Return (query, source_ref, query_source, note). An empty query means: skip this commit."""
    m = PR_IN_SUBJECT.search(subject)
    pr = gh(f"/pulls/{m.group(1)}") if m else None
    if pr is None:
        pulls = gh(f"/commits/{sha}/pulls") or []
        # Prefer the PR that merged this exact commit, and avoid release PRs.
        pulls.sort(key=lambda p: (p.get("merge_commit_sha") != sha, pr_kind(p["title"]) is PRKind.RELEASE))
        pr = pulls[0] if pulls else None
    if pr is None:
        return "", f"commit {sha}", None, "no PR found"

    kind = pr_kind(pr["title"])
    if kind is PRKind.BACKPORT:
        src = backport_source(pr["title"], pr.get("body") or "")
        original = gh(f"/pulls/{src}") if src else None
        if original is None:
            return "", pr["html_url"], None, f"backport PR {pr['html_url']} without a reachable original PR"
        pr, kind = original, pr_kind(original["title"])
    if kind is PRKind.RELEASE:
        return "", pr["html_url"], None, f"release PR {pr['html_url']}: no single problem statement"

    pr_text = f"{pr['title']}\n\n{clean(pr.get('body'))}"
    for number, strength in issue_refs(pr_text, exclude={pr["number"]})[:MAX_ISSUE_LOOKUPS]:
        issue = gh(f"/issues/{number}")
        if issue and "pull_request" not in issue:  # '#N' can also be a PR
            query = f"{issue['title']}\n\n{clean(issue.get('body'))}"[:MAX_QUERY_CHARS]
            return query, issue["html_url"], ISSUE_SOURCE[strength], f"query from issue ({strength.value}); fix PR {pr['html_url']}"
    return pr_text[:MAX_QUERY_CHARS], pr["html_url"], QuerySource.PR_TEXT, "LEAKAGE RISK: query from PR text, not an issue"


def candidate_commits(repo: GitRepo, since: str) -> list[tuple[str, str, list[str]]]:
    log = repo._git("log", f"--since={since}", "--no-merges", "-i", "--grep=fix",
                    "--format=@@%H\t%s", "--name-only", "--", "src/click")
    out = []
    for block in log.split("@@")[1:]:
        lines = [x for x in block.splitlines() if x.strip()]
        sha, subject = lines[0].split("\t", 1)
        files = [f for f in lines[1:] if f.startswith("src/click/") and f.endswith(".py")]
        if 1 <= len(files) <= 3 and not any(w in subject.lower() for w in SKIP_WORDS):
            out.append((sha, subject, files))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".cache/repos/click")
    ap.add_argument("--pin", default="2247b35ea1c47c727d7a06e51fa280e12a863ff6")
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--max-cases", type=int, default=15)
    ap.add_argument("--heldout-fraction", type=float, default=0.3)
    ap.add_argument("--out", default="data/click/manifest.yaml")
    args = ap.parse_args()

    repo = GitRepo(args.repo)
    pin = repo.resolve(args.pin)
    pin_files = repo.list_files(pin)
    pin_symbols: set[str] = set()
    for f in pin_files:
        if f.startswith("src/click/") and f.endswith(".py"):
            pin_symbols |= symbol_ids(f, repo.show(pin, f))

    cases, skipped = [], []
    scanned: set[str] = set()  # every commit examined, mined or skipped
    for sha, subject, files in candidate_commits(repo, args.since):
        if len(cases) >= args.max_cases:
            break
        scanned.add(f"click-{sha[:7]}")
        files = [f for f in files if f in pin_files]
        symbols: list[str] = []
        for f in files:
            post_fix = repo.show(sha, f)
            syms, noise = extract_symbols(post_fix), module_noise_lines(post_fix)
            for line in repo.changed_lines(sha, f):
                name = enclosing_symbol(syms, line)
                if name == MODULE and line in noise:
                    continue  # imports, blank lines, comments: not the place of a fix
                sid = f"{f}::{name}"
                if sid in pin_symbols and sid not in symbols:
                    symbols.append(sid)
        files = [f for f in files if any(sym.startswith(f + "::") for sym in symbols)]
        if not files or not symbols:
            skipped.append(f"{sha[:7]} {subject}: labels missing at pinned commit")
            continue
        query, ref, source, note = find_query(sha, subject)
        if not query:
            skipped.append(f"{sha[:7]} {subject}: {note}")
            continue
        case_id = f"click-{sha[:7]}"
        cases.append({
            "id": case_id,
            "query": query,
            "query_source": source.value,
            "relevant_files": files,
            "relevant_symbols": symbols,
            "label_source": "fix_commit",
            "source_ref": ref,
            "status": "candidate",
            "split": assign_split(case_id, args.heldout_fraction).value,
            "notes": f"fix commit {sha}: {subject}. {note}",
        })
        print(f"[ok] {case_id} {subject[:60]} -> {len(symbols)} symbols", file=sys.stderr)

    dataset = {"name": "click", "repo_url": REPO_URL, "commit_sha": pin,
               "corpus_globs": ["src/click/**/*.py"],
               "heldout_fraction": args.heldout_fraction}
    out = Path(args.out)
    existing: list[dict] = []
    if out.exists():
        old = yaml.safe_load(out.read_text(encoding="utf-8"))
        if old["dataset"] != dataset:
            # Reviewed labels were checked against the old pin; merging would mix versions.
            print(f"refusing to merge: dataset in {out} differs from this run\n"
                  f"  existing: {old['dataset']}\n  this run: {dataset}", file=sys.stderr)
            return 2
        existing = old["cases"]
    merged = merge_cases(existing, cases, scanned)
    manifest = {"schema_version": 1, "dataset": dataset, "cases": merged.cases}
    Manifest.model_validate(manifest)  # never write a manifest that would not load

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100),
                   encoding="utf-8")
    for s in skipped:
        print(f"[skip] {s}", file=sys.stderr)
    for label, ids in (("added", merged.added), ("refreshed", merged.refreshed),
                       ("kept (human-owned)", merged.kept), ("dropped candidates", merged.dropped),
                       ("candidates not rescanned (kept)", merged.unscanned),
                       ("kept but no longer mined", merged.orphaned)):
        print(f"{label}: {len(ids)} {ids if ids and label != 'refreshed' else ''}", file=sys.stderr)
    print(f"wrote {len(merged.cases)} cases to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
