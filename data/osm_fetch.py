"""Idempotent download of the Greater London OSM extract (for Valhalla).

This fetches the Geofabrik Greater-London ``.osm.pbf`` extract that the offline
Valhalla routing tile builder consumes. The artifact is ~119 MB, so it is a
Spark-resident cache — **never committed** to the repo. The download is
idempotent: if a cached file already exists and matches the publisher's MD5
checksum, we skip the download entirely.

Source (Geofabrik, free, no key):
  * PBF: https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf
  * MD5: https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf.md5

Everything here is pure stdlib + ``requests`` (no osmnx / gdal / heavy deps),
and is offline-safe: a network failure or ``allow_network=False`` never raises —
it returns a provenance dict describing what (if anything) is cached locally.

CLI: ``python data/osm_fetch.py`` prints the provenance dict.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE_DIR = DATA_DIR / "cache" / "osm"

OSM_URL = (
    "https://download.geofabrik.de/europe/united-kingdom/"
    "england/greater-london-latest.osm.pbf"
)
OSM_MD5_URL = OSM_URL + ".md5"
OSM_FILENAME = "greater-london-latest.osm.pbf"

DEFAULT_TIMEOUT_S = 30.0
_CHUNK_BYTES = 1 << 20  # 1 MiB streaming chunks
_USER_AGENT = "RLJ medical-logistics-demo/1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _md5_of_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_dest_dir(dest_dir: str | Path | None) -> Path:
    if dest_dir is not None:
        return Path(dest_dir)
    env = os.getenv("OSM_DIR")
    if env:
        return Path(env)
    return DEFAULT_CACHE_DIR


def _fetch_published_md5(session: requests.Session) -> str | None:
    """Return the publisher's MD5 hex digest, or None on any failure.

    Geofabrik's ``.md5`` file is of the form ``<md5>  <filename>``.
    """
    try:
        resp = session.get(
            OSM_MD5_URL,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"user-agent": _USER_AGENT},
        )
        resp.raise_for_status()
        token = resp.text.strip().split()
        return token[0].lower() if token else None
    except Exception:
        return None


def _cached_provenance(path: Path, source: str, url: str = OSM_URL) -> dict:
    """Build a provenance dict for an existing cached file."""
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "md5": _md5_of_file(path),
        "sha256": _sha256_of_file(path),
        "source": source,
        "url": url,
        "fetched_at": _now_iso(),
    }


def fetch_osm_london(
    dest_dir: str | Path | None = None,
    *,
    allow_network: bool = True,
) -> dict:
    """Idempotently fetch the Greater London OSM PBF extract.

    Resolution order for the destination directory: explicit ``dest_dir`` ->
    ``$OSM_DIR`` -> ``data/cache/osm/``. The directory is created if missing.

    Behaviour:
      * If the ``.pbf`` already exists and matches the published MD5, skip the
        download and return cached provenance (``source="cache"``).
      * Otherwise stream-download with ``requests``, verify the MD5 (when the
        publisher's checksum is reachable), and return ``source="geofabrik"``.
      * If ``allow_network=False`` or any network error occurs, never raise:
        return cached provenance if a file exists, else
        ``{"available": False, "reason": ...}``.

    Returns a provenance dict:
        {path, bytes, md5, sha256, source, url, fetched_at}
    or, when nothing is available:
        {available: False, reason, url, ...}
    """
    dest = _resolve_dest_dir(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    pbf_path = dest / OSM_FILENAME

    # ----- offline path ---------------------------------------------------- #
    if not allow_network:
        if pbf_path.exists():
            prov = _cached_provenance(pbf_path, source="cache")
            prov["note"] = "network disabled (allow_network=False); using cache"
            return prov
        return {
            "available": False,
            "reason": "network disabled (allow_network=False) and no cached file",
            "path": str(pbf_path),
            "url": OSM_URL,
            "fetched_at": _now_iso(),
        }

    session = requests.Session()
    published_md5 = _fetch_published_md5(session)

    # ----- idempotent skip ------------------------------------------------- #
    if pbf_path.exists():
        local_md5 = _md5_of_file(pbf_path)
        if published_md5 is None:
            # Can't verify against the publisher; trust the existing cache.
            prov = _cached_provenance(pbf_path, source="cache")
            prov["note"] = "publisher md5 unreachable; trusting existing cache"
            return prov
        if local_md5 == published_md5:
            return _cached_provenance(pbf_path, source="cache")
        # else: stale / corrupt -> fall through and re-download.

    # ----- stream download ------------------------------------------------- #
    tmp_path = pbf_path.with_suffix(pbf_path.suffix + ".part")
    try:
        with session.get(
            OSM_URL,
            stream=True,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"user-agent": _USER_AGENT},
        ) as resp:
            resp.raise_for_status()
            with tmp_path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=_CHUNK_BYTES):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:  # pragma: no cover - network failure path
        tmp_path.unlink(missing_ok=True)
        if pbf_path.exists():
            prov = _cached_provenance(pbf_path, source="cache")
            prov["note"] = f"download failed ({exc!r}); using cache"
            return prov
        return {
            "available": False,
            "reason": f"download failed and no cached file: {exc!r}",
            "path": str(pbf_path),
            "url": OSM_URL,
            "fetched_at": _now_iso(),
        }

    # ----- verify + commit ------------------------------------------------- #
    downloaded_md5 = _md5_of_file(tmp_path)
    if published_md5 is not None and downloaded_md5 != published_md5:
        tmp_path.unlink(missing_ok=True)
        if pbf_path.exists():
            prov = _cached_provenance(pbf_path, source="cache")
            prov["note"] = "md5 mismatch on download; kept previous cache"
            return prov
        return {
            "available": False,
            "reason": (
                f"md5 mismatch: published={published_md5} "
                f"downloaded={downloaded_md5}"
            ),
            "path": str(pbf_path),
            "url": OSM_URL,
            "fetched_at": _now_iso(),
        }

    tmp_path.replace(pbf_path)
    prov = _cached_provenance(pbf_path, source="geofabrik")
    prov["verified_md5"] = published_md5 is not None
    return prov


if __name__ == "__main__":
    import json

    provenance = fetch_osm_london()
    print(json.dumps(provenance, indent=2))
