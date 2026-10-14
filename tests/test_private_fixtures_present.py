"""Every private fixture a committed manifest names is present and intact.

The real-plan regression tests skip when their private payload (client data,
outside git) is absent, so a run without it looks green. The publication gate
sets ``PP1_REQUIRE_PRIVATE=1``: then an absent payload fails here (and in
``snapshot_fixture.load_payload``). Without it the absence is a visible skip.
"""

from __future__ import annotations

import gzip
import hashlib

import pytest

from tests.snapshot_fixture import (
    REQUIRE_PRIVATE_ENV,
    expected_private_fixtures,
    read_manifest,
    skip_or_fail_absent,
)

EXPECTED = expected_private_fixtures()


def test_manifests_name_every_known_real_plan():
    # A deleted manifest would silently drop its fixture from this check.
    known = {"rev82", "rev85", "rev87", "rev90", "rev91_compact", "rev121", "rev124", "rev128",
             "rev142"}
    assert known <= set(EXPECTED)
    for name, path in EXPECTED.items():
        assert path.name == f"{name}.json.gz"
        assert path.parent.name == "private"


@pytest.mark.needs_private
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_private_fixture_is_present_and_matches_its_manifest(name):
    path = EXPECTED[name]
    if not path.exists():
        skip_or_fail_absent(path)
    raw = gzip.decompress(path.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == read_manifest(name)["payload_sha256"]


def test_absent_fixture_fails_only_when_required(monkeypatch, tmp_path):
    absent = tmp_path / "absent.json.gz"
    monkeypatch.setenv(REQUIRE_PRIVATE_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match="absent"):
        skip_or_fail_absent(absent)
    for value in ("0", ""):
        monkeypatch.setenv(REQUIRE_PRIVATE_ENV, value)
        with pytest.raises(pytest.skip.Exception, match="absent"):
            skip_or_fail_absent(absent)
    monkeypatch.delenv(REQUIRE_PRIVATE_ENV)
    with pytest.raises(pytest.skip.Exception, match="absent"):
        skip_or_fail_absent(absent)
