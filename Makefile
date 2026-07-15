.PHONY: validate smoke quality model-smoke install install-force

validate:
	bash scripts/check_structure.sh .

smoke:
	bash scripts/release_smoke.sh .

quality:
	bash scripts/quality_gate.sh .

model-smoke:
	@test -n "$$CODEX_EVAL_AUTH_JSON" || (echo "set CODEX_EVAL_AUTH_JSON to a dedicated low-privilege auth.json" >&2; exit 2)
	@test -n "$$CODEX_EVAL_CODEX" || (echo "set CODEX_EVAL_CODEX to an absolute native Codex executable" >&2; exit 2)
	@test -n "$$CODEX_EVAL_MODEL" || (echo "set CODEX_EVAL_MODEL to an exact current-catalog OpenAI judgment model" >&2; exit 2)
	@test -n "$$CODEX_EVAL_REASONING_EFFORT" || (echo "set CODEX_EVAL_REASONING_EFFORT to an effort supported by CODEX_EVAL_MODEL" >&2; exit 2)
	@test -n "$$CODEX_EVAL_CATALOG" || (echo "set CODEX_EVAL_CATALOG to a fresh requested-thread catalog receipt" >&2; exit 2)
	@test -n "$$CODEX_EVAL_STATE_DB" || (echo "set CODEX_EVAL_STATE_DB to the canonical state_5.sqlite path" >&2; exit 2)
	@test -n "$$CODEX_EVAL_THREAD_ID" || (echo "set CODEX_EVAL_THREAD_ID to the requested root task id" >&2; exit 2)
	@test -n "$$CODEX_EVAL_CATALOG_CWD" || (echo "set CODEX_EVAL_CATALOG_CWD to the existing project directory used for live readback" >&2; exit 2)
	@test "$$CODEX_EVAL_AUTH_CLASS" = "dedicated" -o "$$CODEX_EVAL_AUTH_CLASS" = "primary" || (echo "set CODEX_EVAL_AUTH_CLASS to dedicated or primary" >&2; exit 2)
	@set -- \
		--root . \
		--out "validation/current/model-smoke-$$(date +%Y%m%d-%H%M%S)" \
		--codex-executable "$$CODEX_EVAL_CODEX" \
		--model "$$CODEX_EVAL_MODEL" \
		--reasoning-effort "$$CODEX_EVAL_REASONING_EFFORT" \
		--catalog "$$CODEX_EVAL_CATALOG" \
		--catalog-state-db "$$CODEX_EVAL_STATE_DB" \
		--catalog-thread-id "$$CODEX_EVAL_THREAD_ID" \
		--catalog-cwd "$$CODEX_EVAL_CATALOG_CWD"; \
	if test -n "$$CODEX_HOME"; then \
		set -- "$$@" --catalog-codex-home "$$CODEX_HOME"; \
	fi; \
	set -- "$$@" \
		--auth-json "$$CODEX_EVAL_AUTH_JSON" \
		--auth-credential-class "$$CODEX_EVAL_AUTH_CLASS" \
		--acknowledge-auth-readable-to-eval-process; \
	python3 -I -S scripts/run_model_evals.py "$$@"

install:
	python3 scripts/install_skill.py

install-force:
	python3 scripts/install_skill.py --force
