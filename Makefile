.PHONY: validate smoke quality pilot install install-force agents

validate:
	bash scripts/check_structure.sh .

smoke:
	bash scripts/release_smoke.sh .

quality:
	bash scripts/quality_gate.sh .

pilot:
	python3 scripts/pilot_harness.py --root . --out /tmp/agency-thread-pilot

install:
	python3 scripts/install_skill.py

install-force:
	python3 scripts/install_skill.py --force

agents:
	bash scripts/install_codex_agents.sh project
