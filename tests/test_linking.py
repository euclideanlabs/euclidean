from euclidean.dataset.linking import LinkStrength, PRKind, backport_source, issue_refs, pr_kind


def test_pr_kind_from_real_titles():
    assert pr_kind("Backport #3504 from `main` to `stable` branch") is PRKind.BACKPORT
    assert pr_kind("Pre-8.4.2 release changelog and doc fixes") is PRKind.RELEASE
    assert pr_kind("Fix double-bracketing of choices in synopsis") is PRKind.NORMAL


def test_backport_source_takes_first_reference():
    assert backport_source("Backport #3504 from `main` to `stable` branch", "") == 3504
    assert backport_source("Backport to stable", "See https://github.com/pallets/click/pull/3504") == 3504
    assert backport_source("Backport to stable", "") is None


def test_closing_reference_comes_before_mention():
    text = "Related to #2868.\n\nFixes #2994"
    assert issue_refs(text) == [(2994, LinkStrength.CLOSES), (2868, LinkStrength.MENTIONS)]


def test_closing_reference_as_markdown_link():
    # Real PR #3484 (case click-7d05a59): an earlier mention of #3403 (the change
    # that caused the bug) must not beat the closing reference to #3458.
    text = (
        "Click 8.4.0 moved it when fixing flag-group arbitration "
        "([#3403](https://github.com/pallets/click/issues/3403)).\n\n"
        "fixes [#3458](https://github.com/pallets/click/issues/3458)"
    )
    assert issue_refs(text)[0] == (3458, LinkStrength.CLOSES)


def test_plain_issue_url_is_a_mention():
    # Real case click-fc518e4: "This PR address https://github.com/pallets/click/issues/..."
    text = "This PR address https://github.com/pallets/click/issues/3100"
    assert issue_refs(text) == [(3100, LinkStrength.MENTIONS)]


def test_exclude_and_no_false_matches():
    text = "### Summary\nSee #10, pallets/click#11 and #10 again. Self: #99"
    assert [n for n, _ in issue_refs(text, exclude={99})] == [10, 11]
    assert issue_refs("color #fff and a#12") == []
