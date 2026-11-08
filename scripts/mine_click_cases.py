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
- Fall back to PR text, and flag it: PR text often names the fixed code.

Usage:
  uv run python scripts/mine_click_cases.py --max-cases 15
Set GITHUB_TOKEN to raise the GitHub API rate limit (60/hour without it).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from euclidean.dataset.gitrepo import GitRepo
from euclidean.dataset.manifest import assign_split
from euclidean.dataset.symbols import enclosing_symbol, extract_symbols, symbol_ids

REPO_URL = "https://github.com/pallets/click.git"
API = "https://api.github.com/repos/pallets/click"
SKIP_WORDS = ("typing", "ruff", "pyright", "pre-commit", "documentation", "doc ", "test",
              "cleanup", "rewrap", "deprecate", "type coverage")
ISSUE_REF = re.compile(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s*(?:#|pallets/click#|https://github\.com/pallets/click/issues/)(\d+)", re.I)
PR_IN_SUBJECT = re.compile(r"\(#(\d+)\)\s*$")
MAX_QUERY_CHARS = 1500


def gh(path: str):
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


def find_query(sha: str, subject: str) -> tuple[str, str, str]:
    """Return (query, source_ref, note)."""
    m = PR_IN_SUBJECT.search(subject)
    pr = gh(f"/pulls/{m.group(1)}") if m else None
    if pr is None:
        pulls = gh(f"/commits/{sha}/pulls") or []
        pr = pulls[0] if pulls else None
    if pr is None:
        return "", f"commit {sha}", "no PR found"
    pr_text = f"{pr['title']}\n\n{clean(pr.get('body'))}"
    im = ISSUE_REF.search(pr_text)
    if im:
        issue = gh(f"/issues/{im.group(1)}")
        if issue and "pull_request" not in issue:
            query = f"{issue['title']}\n\n{clean(issue.get('body'))}"[:MAX_QUERY_CHARS]
            return query, issue["html_url"], f"query from issue; fix PR {pr['html_url']}"
    return pr_text[:MAX_QUERY_CHARS], pr["html_url"], "LEAKAGE RISK: query from PR text, not an issue"


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
    for sha, subject, files in candidate_commits(repo, args.since):
        if len(cases) >= args.max_cases:
            break
        files = [f for f in files if f in pin_files]
        symbols: list[str] = []
        for f in files:
            syms = extract_symbols(repo.show(sha, f))
            for line in repo.changed_lines(sha, f):
                sid = f"{f}::{enclosing_symbol(syms, line)}"
                if sid in pin_symbols and sid not in symbols:
                    symbols.append(sid)
        if not files or not symbols:
            skipped.append(f"{sha[:7]} {subject}: labels missing at pinned commit")
            continue
        query, ref, note = find_query(sha, subject)
        if not query:
            skipped.append(f"{sha[:7]} {subject}: {note}")
            continue
        case_id = f"click-{sha[:7]}"
        cases.append({
            "id": case_id,
            "query": query,
            "relevant_files": files,
            "relevant_symbols": symbols,
            "label_source": "fix_commit",
            "source_ref": ref,
            "status": "candidate",
            "split": assign_split(case_id, args.heldout_fraction).value,
            "notes": f"fix commit {sha}: {subject}. {note}",
        })
        print(f"[ok] {case_id} {subject[:60]} -> {len(symbols)} symbols", file=sys.stderr)

    manifest = {
        "schema_version": 1,
        "dataset": {"name": "click", "repo_url": REPO_URL, "commit_sha": pin,
                    "corpus_globs": ["src/click/**/*.py"],
                    "heldout_fraction": args.heldout_fraction},
        "cases": cases,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100),
                              encoding="utf-8")
    for s in skipped:
        print(f"[skip] {s}", file=sys.stderr)
    print(f"wrote {len(cases)} candidate cases to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
