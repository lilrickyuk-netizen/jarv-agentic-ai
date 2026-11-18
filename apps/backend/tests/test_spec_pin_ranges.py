"""
18 November, MYCO Phase 1 (mission 77e45dd6): the hard check read a third-party tool's lock (semgrep 1.177.0's,
under .mise/locks) declaring requires-python >=3.10 as "Python 3.10" against the spec's locked 3.14.7. A range the
locked version satisfies contradicts nothing; an exact pin, or a range that excludes it, is still a finding. Pure.
"""
from app.core.verification.checks import check_spec_pins

PINS = {"python": ("3.14.7", "MYCO_V3_SPEC.md")}


def _found(*declarations):
    return {"python": [(f"file{i}", d, d.split()[-1].lstrip("=<>~!^")) for i, d in enumerate(declarations)]}


def test_a_range_the_locked_version_satisfies_is_not_a_finding():
    found = _found("requires-python = >=3.10", "requires-python = >=3.14,<3.15")
    assert check_spec_pins(None, PINS, found) == []


def test_an_exact_pin_or_an_excluding_range_is_still_a_finding():
    found = _found("requires-python = ==3.12.8", "requires-python = >=3.15", "3.12.8")
    files = {f.file for f in check_spec_pins(None, PINS, found)}
    assert files == {"file0", "file1", "file2"}
