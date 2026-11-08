import copy

import pytest
import yaml

from euclidean.dataset.manifest import (
    ManifestError,
    Split,
    assign_split,
    check_against_repo,
    load_manifest,
)

SHA = "2247b35ea1c47c727d7a06e51fa280e12a863ff6"


def make_case(case_id, status="reviewed", **over):
    case = {
        "id": case_id,
        "query": "Help text is wrapped at the wrong width",
        "query_source": "issue_closes",
        "relevant_files": ["src/click/formatting.py"],
        "relevant_symbols": ["src/click/formatting.py::HelpFormatter.write_usage"],
        "label_source": "fix_commit",
        "source_ref": "0551bf5",
        "status": status,
        "split": assign_split(case_id, 0.3).value,
    }
    case.update(over)
    return case


BASE = {
    "schema_version": 1,
    "dataset": {
        "name": "click",
        "repo_url": "https://github.com/pallets/click.git",
        "commit_sha": SHA,
        "corpus_globs": ["src/**/*.py"],
        "heldout_fraction": 0.3,
    },
    "cases": [make_case("c1"), make_case("c2", status="candidate")],
}


def write(tmp_path, data):
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_valid_manifest_loads(tmp_path):
    m = load_manifest(write(tmp_path, BASE))
    assert len(m.cases) == 2


def test_only_reviewed_cases_are_scored(tmp_path):
    m = load_manifest(write(tmp_path, BASE))
    scored = m.scored_cases(Split.DEV) + m.scored_cases(Split.HELDOUT)
    assert [c.id for c in scored] == ["c1"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["dataset"].update(commit_sha="2247b35"), "40-character"),
        (lambda d: d["cases"].append(make_case("c1")), "duplicate case id"),
        (lambda d: d["cases"][0].update(relevant_files=[]), "relevant_files"),
        (lambda d: d["cases"][0].update(relevant_symbols=["src/click/core.py::Option"]), "not in relevant_files"),
        (lambda d: d["cases"][0].update(status="approved"), "status"),
        (lambda d: d["cases"][0].update(extra_field=1), "extra"),
        (lambda d: d["cases"][0].update(query_source="pr_text"), "pr_text query"),
        (lambda d: d["cases"][0].pop("query_source"), "query_source"),
        (lambda d: d["cases"][0].update(split="heldout" if d["cases"][0]["split"] == "dev" else "dev"), "hash split"),
    ],
)
def test_invalid_manifests_are_rejected(tmp_path, mutate, message):
    data = copy.deepcopy(BASE)
    mutate(data)
    with pytest.raises(ManifestError, match=message):
        load_manifest(write(tmp_path, data))


def test_split_is_stable():
    assert assign_split("click-0551bf5", 0.3) == assign_split("click-0551bf5", 0.3)


def test_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "nope.yaml")


def test_check_against_repo_reports_missing_labels(tmp_path):
    m = load_manifest(write(tmp_path, BASE))
    problems = check_against_repo(m, repo_files={"src/click/formatting.py"}, repo_symbols=set())
    assert any("HelpFormatter.write_usage" in p for p in problems)
