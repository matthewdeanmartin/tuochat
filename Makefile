.EXPORT_ALL_VARIABLES:
SHELL := bash


LOGS_DIR := .build_logs
VERIFY_TARGETS := ruff mypy ty pylint bandit smoke pytest
NO_COLOR_ENV := NO_COLOR=1 CLICOLOR=0 FORCE_COLOR=0 PY_COLORS=0

# if you wrap everything in uv run, it runs slower.
ifeq ($(origin VIRTUAL_ENV),undefined)
    VENV := uv run
else
    VENV :=
endif

uv.lock: pyproject.toml
	@echo "Installing dependencies"
	@uv sync --all-extras

.PHONY: uv-lock
uv-lock: uv.lock

.PHONY: help
help:
	@echo "Build targets:"
	@echo "  help                 List build targets and descriptions"
	@echo "  list-jobs            Alias for help"
	@echo "  fix                  Run source-mutating fixers in canonical order"
	@echo "  fix-ci               Read-only formatter drift checks"
	@echo "  verify               Run read-only verification targets"
	@echo "  triage               Alias for fast-verify"
	@echo "  repro                Run serial verification for easier debugging"
	@echo "  bugs                 Run bug-finding focused checks"
	@echo "  check-human          Run fix, then verify with human-friendly sequencing"
	@echo "  check                Alias for check-human"
	@echo "  check-ci             Run non-mutating CI-safe verification and docs checks"
	@echo "  check-llm            Run compact token-efficient verification"
	@echo "  full-verify          Run verify plus docs checks"
	@echo "  ruff                 Run read-only ruff checks"
	@echo "  mypy                 Run mypy"
	@echo "  ty                   Run ty"
	@echo "  pylint               Run pylint"
	@echo "  bandit               Run bandit"
	@echo "  pytest               Run the Python test suite"
	@echo "  smoke                Run CLI smoke tests"
	@echo "  test                 Run pytest plus smoke tests"
	@echo "  benchmark            Run performance benchmarks"
	@echo "  docker-test          Build test image and run pytest in Docker (3.14, no tox)"
	@echo "  pre-commit           Run pre-commit hooks"
	@echo "  check-docs           Run documentation checks"
	@echo "  check-md             Run markdown checks in read-only mode"
	@echo "  check-spelling       Run spelling checks"
	@echo "  check-changelog      Validate changelog format"
	@echo "  check-all-docs       Run all documentation checks"
	@echo "  metadata-sync-check  Check generated metadata is in sync with pyproject.toml"
	@echo "  version-check        Check version sources are consistent"
	@echo "  dev-status-check     Verify Development Status classifier"
	@echo "  prerelease           Run all pre-release checks (metadata, version, docs, tests)"
	@echo "  prerelease-llm       Run compact pre-release checks (token-efficient)"
	@echo "  build-dist           Build the distribution package"
	@echo "  publish              Run prerelease checks then build the distribution"
	@echo "  tuochat-status        Show .tuochat/ folder size breakdown"
	@echo "  clean-tuochat         Clean all .tuochat/ workspace content"
	@echo "  clean-tuochat-dry     Preview what clean-tuochat would remove"
	@echo "  tuochat-logs          List recent pipeline run logs"

.PHONY: list-jobs
list-jobs: help

clean-pyc:
	@echo "Removing compiled files"


clean-test:
	@echo "Removing coverage data"
	@rm -f .coverage || true
	@rm -f .coverage.* || true

clean: clean-pyc clean-test

install_plugins:
	@echo "N/A"

.PHONY: install-plugins
install-plugins: install_plugins

$(LOGS_DIR):
	@mkdir -p $(LOGS_DIR)

.PHONY: isort
isort: uv.lock pyproject.toml
	@echo "Formatting imports"
	# $(VENV) isort .
	$(VENV) python scripts/gen_tamper_manifest.py

.PHONY: black
black:
	@echo "Formatting code"
	$(VENV) black tuochat
	$(VENV) black test
	$(VENV) mdformat *.md README.md docs/*.md
	$(VENV) python scripts/gen_tamper_manifest.py

.PHONY: ruff-fix
ruff-fix:
	@echo "Auto-fixing with ruff"
	$(VENV) ruff check --fix .
	$(VENV) python scripts/gen_tamper_manifest.py

.PHONY: sync-metadata
sync-metadata:
	@echo "Syncing generated metadata"
	$(VENV) metametameta pep621
	$(VENV) python -c "with open('tuochat/__about__.py', 'a') as f: f.write('\n')"


.PHONY: fix
fix: uv-lock install-plugins ruff-fix isort black sync-metadata

.PHONY: format-check
format-check: uv-lock install-plugins
	@echo "Checking formatter drift"
	# $(NO_COLOR_ENV) $(VENV) isort --check-only .
	$(NO_COLOR_ENV) $(VENV) black --check tuochat test
	$(NO_COLOR_ENV) $(VENV) ruff check .

.PHONY: fix-ci
fix-ci: format-check

.PHONY: ruff-only
ruff-only:
	@echo "Running ruff"
	$(VENV) ruff check .

.PHONY: ruff
ruff: uv-lock install-plugins ruff-only

.PHONY: mypy-only
mypy-only:
	@echo "Running mypy"
	$(VENV) mypy tuochat --ignore-missing-imports --check-untyped-defs

.PHONY: mypy
mypy: uv-lock install-plugins mypy-only

.PHONY: ty-only
ty-only:
	@echo "Running ty"
	$(VENV) ty check tuochat

.PHONY: ty
ty: uv-lock install-plugins ty-only

.PHONY: pylint-only
pylint-only:
	@echo "Running pylint"
	$(VENV) pylint tuochat --fail-under 9.8 --rcfile .pylintrc

.PHONY: pylint
pylint: uv-lock install-plugins pylint-only

.PHONY: bandit-only
bandit-only:
	@echo "Running bandit"
	$(VENV) bandit -c pyproject.toml tuochat -r --quiet

.PHONY: bandit
bandit: uv-lock install-plugins bandit-only

PERF_TESTS := test_perf/test_perf.py test_perf/test_perf_fast.py

.PHONY: pytest-unit-only
pytest-unit-only:
	@echo "Running unit tests"
	$(VENV) pytest test -q -n 5  --dist=loadfile --cov=tuochat --cov-fail-under=35 -p no:benchmark --cov-report=html --junitxml=junit.xml -o junit_family=legacy --timeout=15 --session-timeout=600



.PHONY: pytest-perf-only
pytest-perf-only:
	@echo "Running performance benchmarks"
	$(VENV) python scripts/run_benchmarks.py $(PERF_TESTS) --benchmark-min-rounds=5 --benchmark-min-time=0.1 -p no:xdist --benchmark-compare=auto

.PHONY: pytest-perf-only
pytest-perf-only-with-fail:
	@echo "Running performance benchmarks"
	$(VENV) python scripts/run_benchmarks.py $(PERF_TESTS) --benchmark-min-rounds=5 --benchmark-min-time=0.1 -p no:xdist --benchmark-compare=auto --benchmark-compare-fail=mean:15%

.PHONY: pytest-only
pytest-only: pytest-unit-only

.PHONY: pytest
pytest: clean uv-lock install-plugins pytest-only


.PHONY: smoke-only
smoke-only:
	@echo "Running CLI smoke checks"
	$(VENV) bash ./scripts/basic_checks.sh

.PHONY: smoke
smoke: uv-lock install-plugins smoke-only

.PHONY: test
test: pytest smoke

.PHONY: verify
verify: ruff mypy pylint bandit test


.PHONY: repro
repro: clean uv-lock install-plugins
	@echo "Running serial reproduction-friendly verification"
	$(VENV) pytest test -n 0 -vv --maxfail=1 --cov=tuochat --cov-report=xml --cov-branch --junitxml=junit.xml -o junit_family=legacy --timeout=15 --session-timeout=600
	$(VENV) bash ./scripts/basic_checks.sh

.PHONY: bugs
bugs: fix-ci ruff mypy pylint bandit repro smoke

.PHONY: benchmark
benchmark: uv-lock install-plugins
	@echo "Running performance benchmarks"
	$(VENV) python scripts/run_benchmarks.py $(PERF_TESTS) --benchmark-min-rounds=5 --benchmark-min-time=0.1 -p no:xdist --benchmark-compare=auto

DOCKER_TEST_IMAGE := tuochat-test
DOCKER_TEST_TAG := $(shell git rev-parse --short HEAD 2>/dev/null || echo latest)

.PHONY: docker-test
docker-test:
	@echo "Building test image"
	docker build -f Dockerfile.test -t $(DOCKER_TEST_IMAGE):$(DOCKER_TEST_TAG) .
	@echo "Running tests in container"
	docker run --rm $(DOCKER_TEST_IMAGE):$(DOCKER_TEST_TAG)

.PHONY: pre-commit
pre-commit: uv-lock install-plugins
	@echo "Running pre-commit hooks"
	$(VENV) pre-commit run --all-files

.PHONY: check-human
check-human: fix verify

.PHONY: check
check: check-human

.PHONY: check-ci
check-ci: fix-ci full-verify check-all-docs

.PHONY: full-verify
full-verify: verify check-all-docs

.PHONY: test-llm
test-llm: clean uv-lock install-plugins
	@echo "=== pytest (errors only) ==="
	@$(NO_COLOR_ENV) $(VENV) pytest test -q --tb=short --no-header --cov=tuochat --cov-fail-under 35 --cov-branch --timeout=15 --session-timeout=600 --color=no 2>&1 | tail -40

.PHONY: lint-llm
lint-llm: uv-lock install-plugins
	@echo "=== ruff ==="
	@$(NO_COLOR_ENV) $(VENV) ruff check . 2>&1 | head -50
	@echo "=== ty ==="
	@$(NO_COLOR_ENV) $(VENV) ty check --output-format concise tuochat 2>&1 | grep -v "^All checks passed" | head -60
	@echo "=== pylint ==="
	@$(NO_COLOR_ENV) $(VENV) pylint tuochat  --rcfile .pylintrc --fail-under 9.8 --output-format=text 2>&1 | grep -E "^tuochat|^E|^W|^C|Your code|[Ee]rror" | head -60

.PHONY: mypy-llm
mypy-llm: uv-lock install-plugins
	@echo "=== mypy ==="
	@$(NO_COLOR_ENV) $(VENV) mypy tuochat --ignore-missing-imports --check-untyped-defs --no-error-summary 2>&1 | grep -v "^Success" | head -60

.PHONY: bandit-llm
bandit-llm: uv-lock install-plugins
	@echo "=== bandit ==="
	@$(NO_COLOR_ENV) $(VENV) bandit tuochat -r --severity-level medium 2>&1 | grep -E "Issue|Severity|>>|^$$" | head -40

.PHONY: smoke-llm
smoke-llm: uv-lock install-plugins
	@echo "=== smoke ==="
	@$(NO_COLOR_ENV) $(VENV) bash ./scripts/basic_checks.sh 2>&1 | tail -30

.PHONY: check-llm
check-llm: mypy-llm lint-llm bandit-llm test-llm smoke-llm
	@echo "=== check-llm done ==="

check_docs:
	$(NO_COLOR_ENV) $(VENV) interrogate tuochat --verbose --fail-under 70
	$(NO_COLOR_ENV) $(VENV) pydoctest --config .pydoctest.json | grep -v "__init__" | grep -v "__main__" | grep -v "Unable to parse"

.PHONY: check-docs
check-docs: check_docs

make_docs:
	$(VENV) mkdocs build --strict

.PHONY: make-docs
make-docs: make_docs

check_md:
	# $(NO_COLOR_ENV) $(VENV) linkcheckMarkdown README.md
	# $(NO_COLOR_ENV) $(VENV) markdownlint README.md --config .markdownlintrc
	$(NO_COLOR_ENV) $(VENV) mdformat --check README.md docs/*.md

.PHONY: check-md
check-md: check_md

check_spelling:
	$(NO_COLOR_ENV) $(VENV) pylint tuochat --enable C0402 --rcfile=.pylintrc_spell
	$(NO_COLOR_ENV) $(VENV) pylint docs --enable C0402 --rcfile=.pylintrc_spell
	$(NO_COLOR_ENV) $(VENV) codespell README.md --ignore-words=private_dictionary.txt
	$(NO_COLOR_ENV) $(VENV) codespell tuochat --ignore-words=private_dictionary.txt
	$(NO_COLOR_ENV) $(VENV) codespell docs --ignore-words=private_dictionary.txt

.PHONY: check-spelling
check-spelling: check_spelling

check_changelog:
	$(NO_COLOR_ENV) $(VENV) changelogmanager validate

.PHONY: check-changelog
check-changelog: check_changelog

check_all_docs: check_docs check_md check_spelling check_changelog

.PHONY: check-all-docs
check-all-docs: check_all_docs

check_self:
	$(NO_COLOR_ENV) $(VENV) ./scripts/dog_food.sh

.PHONY: check-own-ver
check-own-ver: check_self

.PHONY: metadata-sync-check
metadata-sync-check:
	@echo "Checking generated metadata is in sync"
	$(VENV) metametameta sync-check

.PHONY: version-check
version-check:
	@echo "Checking version sources and PyPI ordering"
	$(VENV) metametameta sync-check

.PHONY: dev-status-check
dev-status-check:
	@echo "Verifying Development Status classifier"
	uvx --from troml-dev-status troml-dev-status validate .

.PHONY: gha-validate
gha-validate:
	@echo "Validating GitHub Actions workflows"
#	$(VENV) python -c "import pathlib, yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]; print('YAML parse OK')"
#	$(VENV) python -c "from pathlib import Path; import yaml; data=yaml.safe_load(Path('.github/workflows/publish_to_pypi.yml').read_text(encoding='utf-8')); build_steps=data['jobs']['build']['steps']; publish_steps=data['jobs']['pypi-publish']['steps']; up=next(s for s in build_steps if s.get('uses','').startswith('actions/upload-artifact@')); down=next(s for s in publish_steps if s.get('uses','').startswith('actions/download-artifact@')); assert up['with']['name']==down['with']['name']=='packages'; assert up['with']['path']==down['with']['path']=='dist/'; print('Artifact handoff OK:', up['uses'], '->', down['uses'])"
#	uvx zizmor --no-progress --no-exit-codes .


.PHONY: prerelease
prerelease: metadata-sync-check version-check dev-status-check check-all-docs test
	@echo "Pre-release checks complete"

.PHONY: prerelease-llm
prerelease-llm: metadata-sync-check version-check dev-status-check test-llm
	@echo "Quiet pre-release checks complete"

.PHONY: build-dist
build-dist:
	$(VENV) python scripts/gen_tamper_manifest.py
	rm -rf dist && hatch build

.PHONY: publish
publish: prerelease build-dist

.PHONY: issues
issues:
	@echo "N/A"

core_all_tests:
	./scripts/exercise_core_all.sh tuochat "compile --in examples/compile/src --out examples/compile/out --dry-run"
	uv sync --all-extras



.PHONY: tuochat-status
tuochat-status:
	@echo "Checking .tuochat/ folder status"
	$(VENV) tuochat folder

.PHONY: clean-tuochat
clean-tuochat:
	@echo "Cleaning .tuochat/ workspace"
	$(VENV) tuochat folder clean

.PHONY: clean-tuochat-dry
clean-tuochat-dry:
	@echo "Preview: what would be cleaned from .tuochat/"
	$(VENV) tuochat folder clean --dry-run

.PHONY: tuochat-logs
tuochat-logs:
	@echo "Recent pipeline runs:"
	$(VENV) tuochat logs
