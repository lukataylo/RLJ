"""Verified-only dataset loader.

The app must REFUSE to load any dataset whose data-quality suite did not pass.
``load_dataset`` reads ``data/manifest.json`` and raises ``DataNotVerifiedError``
unless the dataset is marked ``dq_passed: true`` AND the file's sha256 still
matches the recorded hash (tamper detection).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"


class DataNotVerifiedError(Exception):
    """Raised when a dataset is not verified (dq failed / missing / tampered)."""


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def _load_manifest(manifest_path: Path | str | None) -> tuple[Path, dict]:
    mp = Path(manifest_path) if manifest_path else MANIFEST_PATH
    if not mp.exists():
        raise DataNotVerifiedError(f"manifest not found: {mp}")
    return mp, json.loads(mp.read_text())


def _resolve_path(base: Path, entry: dict) -> Path:
    p = Path(str(entry["path"]).replace("\\", "/"))
    return p if p.is_absolute() else (base / p)


def load_dataset(name: str, manifest_path: Path | str | None = None):
    """Return the parsed dataset content, or raise ``DataNotVerifiedError``.

    Paths in the manifest are resolved relative to the repo root (the manifest's
    parent's parent), so a manifest copied into a temp dir still resolves.
    """
    mp, manifest = _load_manifest(manifest_path)
    datasets = manifest.get("datasets", {})
    if name not in datasets:
        raise DataNotVerifiedError(f"unknown dataset: {name!r}")
    entry = datasets[name]

    if not entry.get("dq_passed", False):
        raise DataNotVerifiedError(
            f"dataset {name!r} did not pass its data-quality suite "
            f"({entry.get('dq_suite', '?')}); refusing to load"
        )

    base = ROOT
    path = _resolve_path(base, entry)
    if not path.exists():
        raise DataNotVerifiedError(f"dataset {name!r} file missing: {path}")

    actual = sha256_file(path)
    expected = entry.get("sha256")
    if expected and actual != expected:
        raise DataNotVerifiedError(
            f"dataset {name!r} hash mismatch (tampered?): "
            f"expected {expected[:12]}…, got {actual[:12]}…"
        )

    return json.loads(path.read_text())


def verified_datasets(manifest_path: Path | str | None = None) -> list[str]:
    """Names of datasets that are currently loadable (dq passed + hash matches)."""
    try:
        _, manifest = _load_manifest(manifest_path)
    except DataNotVerifiedError:
        return []
    out = []
    for name in manifest.get("datasets", {}):
        try:
            load_dataset(name, manifest_path=manifest_path)
            out.append(name)
        except DataNotVerifiedError:
            continue
    return out


if __name__ == "__main__":
    print("verified datasets:", verified_datasets())
