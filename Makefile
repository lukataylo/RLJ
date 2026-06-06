PY  := ./.venv/bin/python
PIP := ./.venv/bin/pip

.PHONY: install verify verify-core quality-gate data demo e2e-install clean

install:
	$(PIP) install -r requirements-test.txt -r orchestrator/requirements.txt -r routing/requirements.txt

# Full gate: runs every external test suite, maps to the claims ledger, writes
# verification/STATUS.json + VERIFICATION.md. Exits non-zero unless every
# must_pass claim is verified. THIS is the definition of done.
verify:
	$(PY) verification/run.py

# Core gate without the browser e2e (fast inner loop).
verify-core:
	$(PY) verification/run.py --core

# Objective local release gate: Python claim verification + frontend type/build.
# This is intentionally machine-judged; no manual/self grading is part of the gate.
quality-gate:
	$(PY) verification/run.py
	cd frontend && npm run build

# Build + verify all datasets, writing data/manifest.json (dq_passed flags).
data:
	$(PY) data/build.py

# One-time: download the Playwright browser used by the e2e suite.
e2e-install:
	$(PY) -m playwright install chromium

demo:
	./scripts/dev.sh

clean:
	rm -f verification/.report.json verification/STATUS.json frontend/public/status.json
