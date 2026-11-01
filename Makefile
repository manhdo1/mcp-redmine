SHELL := /bin/bash
.SHELLFLAGS := -ec

.PHONY: run check tests-run

run:
	uv run mcp-redmine

check:
	uv run mcp-redmine --check

tests-run:
	env -u REDMINE_URL -u REDMINE_API_KEY -u REDMINE_HEADERS -u REDMINE_READ_ONLY \
		-u REDMINE_CA_BUNDLE -u REDMINE_DANGEROUSLY_ACCEPT_INVALID_CERTS \
		-u ALLOWED_PROJECT_IDS \
		uv run --group dev python -m pytest tests/ -q
