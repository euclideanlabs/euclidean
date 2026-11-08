"""Benchmark manifest: a fixed dataset version plus labeled query cases.

Design rules:
- Labels come from an independent source (a fix commit or a human review),
  never from search results. Each case records where its labels came from.
- The corpus is one pinned commit. Labels must point at files and symbols
  that exist in that commit, or the case cannot be scored.
- The dev/heldout split is a deterministic hash of the case id, so nobody
  can move a hard case to the other split by hand.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ManifestError(ValueError):
    """The manifest file is missing, malformed, or breaks a benchmark rule."""


class LabelSource(str, Enum):
    FIX_COMMIT = "fix_commit"      # files/symbols changed by a real fix
    AUTHOR_REVIEW = "author_review"  # labeled by hand before seeing results


class QuerySource(str, Enum):
    """Where the query text came from. Independent of where the labels came from.

    Report scores per query source: if pr_text cases score much higher, the
    difference is leakage, not retrieval quality.
    """
    ISSUE_CLOSES = "issue_closes"      # issue the fix PR says it closes
    ISSUE_MENTIONS = "issue_mentions"  # issue the fix PR only mentions; check it by hand
    PR_TEXT = "pr_text"                # PR text; often names the fixed code (leakage)
    AUTHOR_REWRITE = "author_rewrite"  # symptom-only text written by a person


class ReviewStatus(str, Enum):
    CANDIDATE = "candidate"  # mined automatically, not checked by a person
    REVIEWED = "reviewed"    # a person checked query and labels
    REJECTED = "rejected"    # kept for the record, never scored


class Split(str, Enum):
    DEV = "dev"
    HELDOUT = "heldout"


def symbol_file(symbol_id: str) -> str:
    """'src/click/core.py::Option.get_default' -> 'src/click/core.py'."""
    return symbol_id.split("::", 1)[0]


def assign_split(case_id: str, heldout_fraction: float) -> Split:
    """Stable hash split. The same id always lands in the same split."""
    digest = hashlib.sha256(case_id.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / 2**64
    return Split.HELDOUT if bucket < heldout_fraction else Split.DEV


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetSpec(_Strict):
    name: str
    repo_url: str
    commit_sha: str
    corpus_globs: list[str] = Field(min_length=1)
    heldout_fraction: float = Field(gt=0.0, lt=1.0)

    @field_validator("commit_sha")
    @classmethod
    def _full_sha(cls, v: str) -> str:
        if not SHA_RE.match(v):
            raise ValueError("commit_sha must be a full 40-character lowercase hex SHA")
        return v


class BenchmarkCase(_Strict):
    id: str
    query: str = Field(min_length=10)
    query_source: QuerySource
    relevant_files: list[str] = Field(min_length=1)
    relevant_symbols: list[str] = Field(default_factory=list)
    label_source: LabelSource
    source_ref: str  # fix commit SHA, PR/issue URL, or reviewer note
    status: ReviewStatus
    split: Split
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not CASE_ID_RE.match(v):
            raise ValueError("id must be lowercase letters, digits, '_', '.', '-'")
        return v

    @field_validator("relevant_files", "relevant_symbols")
    @classmethod
    def _no_duplicates(cls, v: list[str]) -> list[str]:
        if len(v) != len(set(v)):
            raise ValueError("labels must not repeat")
        return v

    @model_validator(mode="after")
    def _symbols_inside_files(self) -> "BenchmarkCase":
        files = set(self.relevant_files)
        for sym in self.relevant_symbols:
            if "::" not in sym:
                raise ValueError(f"symbol {sym!r} must look like 'path::Qualified.name'")
            if symbol_file(sym) not in files:
                raise ValueError(f"symbol {sym!r} is in a file that is not in relevant_files")
        if self.status == ReviewStatus.REVIEWED and self.query_source == QuerySource.PR_TEXT:
            raise ValueError("a reviewed case cannot use a pr_text query (it leaks the fix); "
                             "rewrite it (author_rewrite) or reject the case")
        return self


class Manifest(_Strict):
    schema_version: Literal[1]
    dataset: DatasetSpec
    cases: list[BenchmarkCase]

    @model_validator(mode="after")
    def _benchmark_rules(self) -> "Manifest":
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"duplicate case id {case.id!r}")
            seen.add(case.id)
            expected = assign_split(case.id, self.dataset.heldout_fraction)
            if case.split != expected:
                raise ValueError(
                    f"case {case.id!r} has split {case.split.value!r}, "
                    f"but the hash split is {expected.value!r}"
                )
        return self

    def scored_cases(self, split: Split) -> list[BenchmarkCase]:
        """Only reviewed cases count in a score."""
        return [c for c in self.cases if c.status == ReviewStatus.REVIEWED and c.split == split]


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"manifest is not valid YAML: {exc}") from exc
    try:
        return Manifest.model_validate(raw)
    except ValidationError as exc:
        raise ManifestError(f"manifest {path} is invalid:\n{exc}") from exc


def check_against_repo(manifest: Manifest, repo_files: set[str], repo_symbols: set[str]) -> list[str]:
    """Return problems where labels point at things missing from the pinned commit.

    The caller lists files and symbols at dataset.commit_sha. Keeping git and
    parsing out of this function makes it easy to test.
    """
    problems = []
    for case in manifest.cases:
        if case.status == ReviewStatus.REJECTED:
            continue
        for f in case.relevant_files:
            if f not in repo_files:
                problems.append(f"{case.id}: file {f} is not in the pinned commit")
        for s in case.relevant_symbols:
            if s not in repo_symbols:
                problems.append(f"{case.id}: symbol {s} is not in the pinned commit")
    return problems
