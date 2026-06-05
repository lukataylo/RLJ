"""Completeness gate: fail if forbidden stub/placeholder patterns exist in source.

Written by an independent completeness auditor. These tests scan *source* (not test
files) for signs of unfinished work: NotImplementedError, TODO/FIXME/XXX markers,
"stub"/"not implemented" prose, and unwired UI controls.

The allowlist is explicit and minimal. The only sanctioned stubs are the two
documented GB10/road-graph SEAMS in ``routing/traveltime.py`` (``gpu_sssp_matrix``,
``osmnx_matrix``) which raise ``NotImplementedError`` by design on this dev box.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Source trees to audit (Python).
PY_SOURCE_DIRS = ["orchestrator", "routing", "voice", "data", "scripts"]
# Frontend source trees (TS/TSX).
WEB_SOURCE_DIRS = ["frontend/src", "driver-app/src"]

# --- Allowlist (explicit + minimal) ------------------------------------------
# The documented intentional stubs live ONLY here. Anything else is a real gap.
ALLOWED_NOTIMPLEMENTED = {"routing/traveltime.py"}
# "stub" / "not implemented" prose is allowed only in the documented SEAM file.
ALLOWED_STUB_PROSE = {"routing/traveltime.py"}


def _py_files(dirs: list[str]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def _web_files(dirs: list[str]) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        base = ROOT / d
        if not base.exists():
            continue
        for ext in ("*.ts", "*.tsx"):
            out.extend(base.rglob(ext))
    return [p for p in out if "node_modules" not in p.parts and not p.name.endswith(".d.ts")]


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# ----------------------------------------------------------------------------
# 1. No NotImplementedError outside the documented SEAMs.
# ----------------------------------------------------------------------------
def test_no_notimplemented_outside_allowlist():
    offenders = []
    for p in _py_files(PY_SOURCE_DIRS):
        rel = _rel(p)
        if rel in ALLOWED_NOTIMPLEMENTED:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if "NotImplementedError" in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "Unexpected NotImplementedError in source:\n" + "\n".join(offenders)


# ----------------------------------------------------------------------------
# 2. No TODO / FIXME / XXX markers anywhere in source (py + web).
# ----------------------------------------------------------------------------
def test_no_todo_fixme_in_source():
    marker = re.compile(r"\b(TODO|FIXME|XXX)\b")
    offenders = []
    for p in _py_files(PY_SOURCE_DIRS) + _web_files(WEB_SOURCE_DIRS):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if marker.search(line):
                offenders.append(f"{_rel(p)}:{i}: {line.strip()}")
    assert not offenders, "TODO/FIXME/XXX markers in source:\n" + "\n".join(offenders)


# ----------------------------------------------------------------------------
# 3. No "stub" / "not implemented" prose outside the documented SEAM file.
# ----------------------------------------------------------------------------
def test_no_stub_prose_outside_allowlist():
    marker = re.compile(r"\bstub\b|not implemented", re.IGNORECASE)
    offenders = []
    for p in _py_files(PY_SOURCE_DIRS) + _web_files(WEB_SOURCE_DIRS):
        rel = _rel(p)
        if rel in ALLOWED_STUB_PROSE:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if marker.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "Stub/not-implemented prose in source:\n" + "\n".join(offenders)


# ----------------------------------------------------------------------------
# 4. No bare placeholder bodies: a standalone `...` ellipsis statement.
#    (Bare `pass` is excluded because it is legitimately used in exception
#    fallback ladders here; `...` is never legitimate in this codebase.)
# ----------------------------------------------------------------------------
def test_no_ellipsis_placeholder_bodies():
    offenders = []
    bare_ellipsis = re.compile(r"^\s*\.\.\.\s*$")
    for p in _py_files(PY_SOURCE_DIRS):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if bare_ellipsis.match(line):
                offenders.append(f"{_rel(p)}:{i}")
    assert not offenders, "Bare `...` placeholder bodies in source:\n" + "\n".join(offenders)


# ----------------------------------------------------------------------------
# 5. No unwired UI: every <button> must have a real handler (onClick) or be a
#    form submit (type="submit"). Empty / no-op onClick handlers are forbidden.
# ----------------------------------------------------------------------------
def _opening_button_tags(text: str):
    """Yield (line_no, tag_text) for each <button ...> opening tag (may span lines)."""
    for m in re.finditer(r"<button\b", text):
        start = m.start()
        depth = 0
        end = None
        i = start
        # walk forward to the closing '>' of this opening tag, honouring braces
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ">" and depth == 0:
                end = i
                break
            i += 1
        tag = text[start : (end + 1) if end is not None else len(text)]
        line_no = text.count("\n", 0, start) + 1
        yield line_no, tag


EMPTY_ONCLICK = re.compile(r"onClick=\{\s*\(\s*\)\s*=>\s*\{\s*\}\s*\}")
CONSOLE_ONLY_ONCLICK = re.compile(r"onClick=\{\s*\(\s*\)\s*=>\s*console\.\w+\([^)]*\)\s*\}")


def test_no_unwired_buttons():
    offenders = []
    for p in _web_files(WEB_SOURCE_DIRS):
        text = p.read_text()
        for line_no, tag in _opening_button_tags(text):
            has_onclick = "onClick" in tag
            is_submit = re.search(r'type=["\']submit["\']', tag) is not None
            if not has_onclick and not is_submit:
                offenders.append(f"{_rel(p)}:{line_no}: <button> with no onClick and not type=submit")
            elif has_onclick and (EMPTY_ONCLICK.search(tag) or CONSOLE_ONLY_ONCLICK.search(tag)):
                offenders.append(f"{_rel(p)}:{line_no}: <button> onClick is empty / console.log-only")
    assert not offenders, "Unwired buttons:\n" + "\n".join(offenders)


def test_no_dead_hash_links():
    offenders = []
    dead = re.compile(r'href=["\']#["\']')
    for p in _web_files(WEB_SOURCE_DIRS):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if dead.search(line):
                offenders.append(f"{_rel(p)}:{i}: {line.strip()}")
    assert not offenders, "Dead href=\"#\" links:\n" + "\n".join(offenders)
