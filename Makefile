# Conjur3 — dev + deploy tasks. Run `make help`.
.DEFAULT_GOAL := help
SHELL := /bin/bash
CONJUR3_PILOT_DIR ?= conjur3/conjur3-pilot

.PHONY: help install freecad-setup connector-dist build dev redis emulators seed web gateway freecad stop \
        deploy-firebase deploy-vps deploy-cloudrun logs

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

install: ## Install all workspaces (app, functions, gateway, connector) + conjur3-pilot venv
	npm install && npm --prefix functions install && npm --prefix mcp-gateway install && npm --prefix connector install
	$(MAKE) freecad-setup

connector-dist: ## Bundle the connector + FreeCAD addon; stage for the gateway to serve
	npm --prefix connector run bundle
	mkdir -p mcp-gateway/public
	cp connector/dist/conjur3-connector.js mcp-gateway/public/conjur3-connector.js
	cp connector/install.sh mcp-gateway/public/install.sh
	@rm -rf /tmp/Conjur3 && cp -r $(CONJUR3_PILOT_DIR)/addon/conjur3_pilot /tmp/Conjur3 \
	  && find /tmp/Conjur3 -name __pycache__ -type d -prune -exec rm -rf {} + \
	  && tar -czf mcp-gateway/public/conjur3-addon.tar.gz -C /tmp Conjur3 && rm -rf /tmp/Conjur3
	@echo "staged connector + FreeCAD addon → mcp-gateway/public/"

freecad-setup: ## Create the in-repo conjur3-pilot venv (the canonical MCP)
	@if command -v uv >/dev/null 2>&1; then \
	  cd $(CONJUR3_PILOT_DIR) && uv venv --clear .venv && uv pip install -q --python .venv/bin/python -e . ; \
	else \
	  python3 -m venv $(CONJUR3_PILOT_DIR)/.venv && $(CONJUR3_PILOT_DIR)/.venv/bin/pip install -q -e $(CONJUR3_PILOT_DIR) ; \
	fi
	@echo "conjur3-pilot ready at $(CONJUR3_PILOT_DIR)/.venv"

build: ## Type-build app, functions, gateway
	npm run build && npm --prefix functions run build && npm --prefix mcp-gateway run build

dev: ## Full local stack (Redis, emulators, seed, freecad, gateway, web)
	./scripts/dev.sh

# ── individual pieces (separate terminals) ──────────────────────────────────
redis: ## Local Redis + commander UI
	docker compose up -d redis redis-commander
emulators: ## Firebase emulators (auth/firestore/functions)
	firebase emulators:start --only auth,firestore,functions --project demo-conjur3
seed: ## Seed the emulator with a demo org + logins + keys
	npm --prefix functions run seed
web: ## Next.js dev server
	npm run dev
gateway: ## MCP gateway (dev, emulator-backed)
	cd mcp-gateway && PORT=8090 UPSTREAM_MCP_URL=http://127.0.0.1:8765/mcp \
	  FIREBASE_PROJECT_ID=demo-conjur3 FIRESTORE_EMULATOR_HOST=127.0.0.1:8088 \
	  REDIS_URL=redis://localhost:6379 npm run dev
freecad: ## conjur3-pilot in Streamable-HTTP mode (needs the conjur3-pilot venv)
	cd $(CONJUR3_PILOT_DIR) && ./.venv/bin/conjur3-pilot --http --http-host 127.0.0.1 --http-port 8765

stop: ## Kill local dev services by port
	@for p in 3000 8090 8765 5001 9099 8088 4000; do \
	  for pid in $$(ss -ltnp 2>/dev/null | grep ":$$p " | grep -oP 'pid=\K[0-9]+' | sort -u); do \
	    kill $$pid 2>/dev/null && echo "killed $$pid on :$$p"; done; done

# ── deploy ───────────────────────────────────────────────────────────────────
deploy-firebase: ## Deploy rules + indexes + functions + hosting to Firebase
	./scripts/deploy-firebase.sh
deploy-vps: ## Ship + (re)start the VPS Docker Compose stack
	./scripts/deploy-vps.sh
deploy-cloudrun: ## Build images + deploy autoscaling Cloud Run service
	./scripts/deploy-cloudrun.sh
logs: ## Tail local dev logs
	tail -f .dev-logs/*.log
