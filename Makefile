# =============================================================================
# Tchiko Assistant — Engineering Makefile
# =============================================================================

PYTHON ?= python3

.PHONY: help run chat settings self-test test doctor export-svg clean

help: ## Display available engineering targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

run: ## Launch the floating Tchiko desktop companion
	./run_tchiko.sh

chat: ## Launch Tchiko with the full Chat & System Studio window open
	./run_tchiko.sh --open-chat

settings: ## Launch Tchiko with the Settings & RBAC Permissions window open
	./run_tchiko.sh --open-settings

self-test: ## Run the end-to-end subsystem self-test & export canonical SVGs
	$(PYTHON) main.py --self-test

test: ## Run the automated unit & integration test suite
	$(PYTHON) -m unittest discover -s tests -v

doctor: ## Run the 6-step autonomous IDE/Application Crash Doctor from CLI
	@$(PYTHON) -c "from tchiko.config_manager import ConfigManager; from tchiko.system_tools import LinuxSystemToolkit; tk = LinuxSystemToolkit(ConfigManager()); print(tk.diagnose_and_heal_app('Antigravity Code IDE').output)"

export-svg: ## Re-export all procedural Cairo vector poses to assets/ and landing/assets/
	$(PYTHON) main.py --self-test

clean: ## Remove Python bytecode caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
