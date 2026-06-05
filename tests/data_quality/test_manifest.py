"""Manifest gate — the app only loads datasets whose DQ suite passed."""
from __future__ import annotations

import json

import build as build_mod
import pytest
from loader import DataNotVerifiedError, load_dataset, verified_datasets


def test_only_verified_data_loadable(tmp_path):
    manifest = build_mod.build()

    # at least facilities + demand should have passed and be loadable.
    passed = [n for n, d in manifest["datasets"].items() if d["dq_passed"]]
    assert "facilities" in passed and "demand" in passed

    for name in passed:
        data = load_dataset(name)
        assert data, f"{name} loaded empty"

    loadable = set(verified_datasets())
    assert set(passed) <= loadable

    # ---- a deliberately UNVERIFIED dataset must NOT load ------------------ #
    tampered = json.loads(json.dumps(manifest))  # deep copy
    # (a) dq_passed = false
    tampered["datasets"]["facilities"]["dq_passed"] = False
    # (b) hash mismatch on a still-"passed" dataset
    tampered["datasets"]["demand"]["sha256"] = "0" * 64

    tmp_manifest = tmp_path / "manifest.json"
    tmp_manifest.write_text(json.dumps(tampered))

    with pytest.raises(DataNotVerifiedError):
        load_dataset("facilities", manifest_path=tmp_manifest)  # dq_passed False
    with pytest.raises(DataNotVerifiedError):
        load_dataset("demand", manifest_path=tmp_manifest)  # hash mismatch
    with pytest.raises(DataNotVerifiedError):
        load_dataset("does-not-exist", manifest_path=tmp_manifest)

    # the loader should report neither tampered dataset as verified.
    still_verified = set(verified_datasets(manifest_path=tmp_manifest))
    assert "facilities" not in still_verified
    assert "demand" not in still_verified


def test_signal_datasets_gated(tmp_path):
    """The new signal datasets (towerbridge, events) are manifest-gated too."""
    manifest = build_mod.build()
    datasets = manifest["datasets"]

    # both new datasets exist, passed DQ, and are loadable
    for name in ("towerbridge", "events"):
        assert name in datasets, f"{name} missing from manifest"
        assert datasets[name]["dq_passed"], f"{name} did not pass DQ"
        assert datasets[name]["dq_suite"] == "tests/data_quality/test_signals.py"
        data = load_dataset(name)
        assert data, f"{name} loaded empty"

    assert {"towerbridge", "events"} <= set(verified_datasets())

    # an unverified signal dataset must NOT load
    tampered = json.loads(json.dumps(manifest))
    tampered["datasets"]["towerbridge"]["dq_passed"] = False
    tampered["datasets"]["events"]["sha256"] = "0" * 64
    tmp_manifest = tmp_path / "manifest.json"
    tmp_manifest.write_text(json.dumps(tampered))

    with pytest.raises(DataNotVerifiedError):
        load_dataset("towerbridge", manifest_path=tmp_manifest)  # dq_passed False
    with pytest.raises(DataNotVerifiedError):
        load_dataset("events", manifest_path=tmp_manifest)  # hash mismatch
