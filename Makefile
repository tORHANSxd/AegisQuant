.PHONY: bootstrap test verify security

bootstrap:
	uv sync --all-groups --frozen
	pnpm install --frozen-lockfile

test:
	uv run pytest
	pnpm test

security:
	uv run python scripts/security_scan.py

verify:
	uv run python scripts/ci.py
