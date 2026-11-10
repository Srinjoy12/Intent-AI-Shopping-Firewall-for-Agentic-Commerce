# Intent AI Shopping Firewall — Makefile

.PHONY: benchmark benchmark-gemini benchmark-openai test verify-export tamper-demo scan-secrets verify-e2e help

PYTHON ?= backend/venv/bin/python3
PYTEST ?= backend/venv/bin/pytest

help:
	@echo "Available commands:"
	@echo "  make test               Run full 81-test automated pytest verification suite"
	@echo "  make benchmark          Run deterministic offline adversarial benchmark (CI-ready)"
	@echo "  make benchmark-gemini   Run live benchmark using Google Gemini API"
	@echo "  make benchmark-openai   Run live benchmark using OpenAI API"
	@echo "  make scan-secrets       Audit frontend bundle and source for secret leaks"
	@echo "  make verify-e2e         Run scripted multi-tenant sandbox isolation verification"
	@echo "  make verify-export      Export and verify the cryptographic audit chain offline"
	@echo "  make tamper-demo        Demonstrate tamper detection by altering an audit event"

benchmark:
	PYTHONPATH=backend:. $(PYTHON) benchmark/runner.py --mode offline --runs 3

benchmark-gemini:
	PYTHONPATH=backend:. $(PYTHON) benchmark/runner.py --mode gemini --runs 3

benchmark-openai:
	PYTHONPATH=backend:. $(PYTHON) benchmark/runner.py --mode openai --runs 3

test:
	PYTHONPATH=backend:. $(PYTEST) backend/tests/ -v

scan-secrets:
	bash scripts/check_bundle_secrets.sh

verify-e2e:
	PYTHONPATH=backend:. $(PYTHON) scripts/verify_demo_isolation_e2e.py

verify-export:
	$(PYTHON) scripts/verify_audit_export.py

tamper-demo:
	$(PYTHON) scripts/tamper_demo.py

