.PHONY: validate smoke quality model-smoke install install-force

validate:
	bash scripts/check_structure.sh .

smoke:
	bash scripts/release_smoke.sh .

quality:
	bash scripts/quality_gate.sh .

model-smoke:
	@test -n "$$CODEX_EVAL_AUTH_JSON" || (echo "set CODEX_EVAL_AUTH_JSON to a dedicated low-privilege auth.json" >&2; exit 2)
	@test "$$CODEX_EVAL_AUTH_CLASS" = "dedicated" -o "$$CODEX_EVAL_AUTH_CLASS" = "primary" || (echo "set CODEX_EVAL_AUTH_CLASS to dedicated or primary" >&2; exit 2)
	python3 scripts/run_model_evals.py --root . --out "validation/current/model-smoke-$$(date +%Y%m%d-%H%M%S)" --auth-json "$$CODEX_EVAL_AUTH_JSON" --auth-credential-class "$$CODEX_EVAL_AUTH_CLASS" --acknowledge-auth-readable-to-eval-process

install:
	python3 scripts/install_skill.py

install-force:
	python3 scripts/install_skill.py --force
