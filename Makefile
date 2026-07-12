.PHONY: validate smoke quality model-smoke model-smoke-rc model-smoke-stable install install-force

validate:
	/bin/bash -p scripts/check_structure.sh .

smoke:
	/bin/bash -p scripts/release_smoke.sh .

quality:
	/bin/bash -p scripts/quality_gate.sh .

model-smoke:
	@test -n "$$CODEX_NATIVE_EXECUTABLE" || (echo "set CODEX_NATIVE_EXECUTABLE to the absolute native Codex binary path (not a wrapper or symlink)" >&2; exit 2)
	@test -n "$$CODEX_EVAL_MODEL" || (echo "set CODEX_EVAL_MODEL to an explicit model id" >&2; exit 2)
	@test -n "$$CODEX_EVAL_REASONING_EFFORT" || (echo "set CODEX_EVAL_REASONING_EFFORT to an effort supported by CODEX_EVAL_MODEL; no release model is assumed" >&2; exit 2)
	@test -n "$$CODEX_EVAL_AUTH_JSON" || (echo "set CODEX_EVAL_AUTH_JSON to an eval auth.json" >&2; exit 2)
	@test "$$CODEX_EVAL_AUTH_CLASS" = "dedicated" -o "$$CODEX_EVAL_AUTH_CLASS" = "primary" || (echo "set CODEX_EVAL_AUTH_CLASS to dedicated or primary" >&2; exit 2)
	@test "$$CODEX_EVAL_SOURCE_TRUST" = "reviewed" -o "$$CODEX_EVAL_SOURCE_TRUST" = "untrusted" || (echo "set CODEX_EVAL_SOURCE_TRUST to reviewed or untrusted" >&2; exit 2)
	/bin/bash -p scripts/model_smoke.sh --root . --out "validation/current/model-smoke-$$(/bin/date +%Y%m%d-%H%M%S)" --codex-executable "$$CODEX_NATIVE_EXECUTABLE" --model "$$CODEX_EVAL_MODEL" --reasoning-effort "$$CODEX_EVAL_REASONING_EFFORT" --skill-source verified-installed-snapshot --source-trust "$$CODEX_EVAL_SOURCE_TRUST" --auth-json "$$CODEX_EVAL_AUTH_JSON" --auth-credential-class "$$CODEX_EVAL_AUTH_CLASS" --acknowledge-auth-readable-to-eval-process $(if $(CODEX_REQUIRE_RELEASE_TIER),--require-release-tier "$(CODEX_REQUIRE_RELEASE_TIER)",)

model-smoke-rc:
	@$(MAKE) model-smoke CODEX_REQUIRE_RELEASE_TIER=rc

model-smoke-stable:
	@$(MAKE) model-smoke CODEX_REQUIRE_RELEASE_TIER=stable

install:
	python3 scripts/install_skill.py

install-force:
	python3 scripts/install_skill.py --force
