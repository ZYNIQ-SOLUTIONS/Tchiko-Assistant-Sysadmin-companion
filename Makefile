# =============================================================================
# Tchiko Assistant — Engineering Makefile
# =============================================================================

PYTHON ?= python3

.PHONY: help run chat settings remote remote-headless self-test test doctor export-svg lint typecheck install-desktop docker-build docker-run clean

VERSION := $(shell sed -n 's/^version = "\(.*\)"$$/\1/p' pyproject.toml)
IMAGE ?= ghcr.io/zyniq-solutions/tchiko-assistant

help: ## Display available engineering targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

run: ## Launch the floating Tchiko desktop companion
	./run_tchiko.sh

chat: ## Launch Tchiko with the full Chat & System Studio window open
	./run_tchiko.sh --open-chat

settings: ## Launch Tchiko with the Settings & RBAC Permissions window open
	./run_tchiko.sh --open-settings

remote: ## Launch Tchiko with the Tchiko RC Tele-Command Link pairing window open
	./run_tchiko.sh --open-remote

remote-headless: ## Run Tchiko RC in headless HTTPS/WSS server mode (port 8765)
	$(PYTHON) main.py --remote

self-test: ## Run the end-to-end subsystem self-test & export canonical SVGs
	$(PYTHON) main.py --self-test

test: ## Run the automated unit & integration test suite
	$(PYTHON) -m unittest discover -s tests -v

doctor: ## Run the 6-step autonomous IDE/Application Crash Doctor from CLI
	@$(PYTHON) -c "from tchiko.config_manager import ConfigManager; from tchiko.system_tools import LinuxSystemToolkit; tk = LinuxSystemToolkit(ConfigManager()); print(tk.diagnose_and_heal_app('Antigravity Code IDE').output)"

export-svg: ## Re-export all procedural Cairo vector poses to assets/ and landing/assets/
	$(PYTHON) main.py --self-test

lint: ## Run Python syntax check and ruff linter (if installed)
	$(PYTHON) -m compileall -q main.py tchiko tests
	@if command -v ruff >/dev/null 2>&1; then ruff check main.py tchiko tests; fi

typecheck: ## Run mypy type checker (if installed)
	@if command -v mypy >/dev/null 2>&1; then mypy main.py tchiko; fi

install-desktop: ## Install Tchiko-Assistant.desktop into ~/.local/share/applications/
	@mkdir -p ~/.local/share/applications
	@sed -e "s|^Exec=.*|Exec=$(CURDIR)/run_tchiko.sh|" \
	     -e "s|^Icon=.*|Icon=$(CURDIR)/assets/tchiko-logo.svg|" \
	     Tchiko-Assistant.desktop > ~/.local/share/applications/Tchiko-Assistant.desktop
	@echo "Installed ~/.local/share/applications/Tchiko-Assistant.desktop"

docker-build: ## Build the headless Tchiko RC container image ($(IMAGE):$(VERSION))
	docker build --build-arg VERSION=$(VERSION) --build-arg VCS_REF=$$(git rev-parse --short HEAD) -t $(IMAGE):$(VERSION) -t $(IMAGE):latest .

docker-run: ## Run the container image locally on port 8765 with persistent named volumes
	docker run --rm -it --name tchiko -p 8765:8765 \
	  -e TCHIKO_RC_PUBLIC_URL -e GEMINI_API_KEY -e OLLAMA_HOST --add-host=host.docker.internal:host-gateway \
	  -v tchiko-config:/app/config -v tchiko-experiences:/app/experiences \
	  -v tchiko-tls:/home/tchiko/.config/tchiko $(IMAGE):$(VERSION)

clean: ## Remove Python bytecode caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
