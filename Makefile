# Lint targets mirror the CI ruff command exactly so `make lint` == what CI runs.
# Keep RUFF_TARGETS in sync with .github/workflows/ci.yml "Lint (ruff)" step.
RUFF_TARGETS = agenda frontend launcher notes-mvp presenter researcher tests \
               bootstrap_env.py install.py launch.py

.PHONY: lint lint-fix install-hooks

lint:
	ruff check $(RUFF_TARGETS)

lint-fix:
	ruff check --fix $(RUFF_TARGETS)

# Write (or overwrite) the pre-commit hook so `git commit` auto-lints.
install-hooks:
	@printf '#!/usr/bin/env bash\nset -e\n# Find ruff: prefer venv (bin on Linux/macOS, Scripts on Windows), fall back to PATH.\nRUFF=$$(command -v .venv/bin/ruff 2>/dev/null || command -v .venv/Scripts/ruff 2>/dev/null || command -v ruff)\nexec "$$RUFF" check $(RUFF_TARGETS)\n' \
		> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "pre-commit hook installed — ruff will run before every commit."
