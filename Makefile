# Hack Hydra — top-level targets.
#
# `make eval` is PLAN 7's checkpoint: "reproduces every number and plot from
# scratch". It is deliberately slow, because the scenario tier runs real
# simulations on the live store — that is the point of it. `make eval-fast`
# is the same suite minus those runs, and finishes in seconds.
#
# "From scratch" has one data prerequisite: the calibration tier replays a
# TRACED reference run, and /runs/ is gitignored, so a fresh clone has none.
# `make eval-reference` produces it (a real run, minutes) and `make eval`
# invokes it only when one is missing — so the checkpoint is true on a clone
# and cheap on a machine that already has one.
#
# Before a long run, read infra/README.md "Engine pace and the store-reset
# ritual": per-tick cost grows with the store, and the SAME shape has measured
# 18.5 s/tick fresh and 112 s/tick loaded. `make eval` prints the reminder.

ENGINE  := engine
PY      := $(ENGINE)/.venv/bin/python
PROFILE ?= reference
SEEDS   ?= 11,23,37,53,71
SIZE    ?= 300

.PHONY: help eval eval-fast eval-analytic eval-calibrate eval-rank \
        eval-scenarios eval-reference eval-report eval-clean test test-real

help:
	@echo "make eval           full Phase-7 reproduction (reference run + analytic + calibration + rank + real runs + report)"
	@echo "make eval-fast      every database-free tier: analytic + calibration + rank + report, seconds"
	@echo "make eval-analytic  just the analytic laws (F1/F2/F3/F6/F8/F10)"
	@echo "make eval-calibrate just 7.2, replayed offline from a traced reference run"
	@echo "make eval-rank      just 7.3 rank agreement"
	@echo "make eval-scenarios just the real runs (slow; needs a live HydraDB); always on the demo profile"
	@echo "make eval-reference produce the traced reference run the calibration tier replays (real run)"
	@echo "make eval-report    re-assemble /eval from artifacts already on disk"
	@echo "make eval-clean     delete generated eval artifacts (keeps specs + profiles)"
	@echo "make test           unit suite (no database)"
	@echo "make test-real      integration suite against a live HydraDB"
	@echo ""
	@echo "vars: PROFILE=$(PROFILE) SEEDS=$(SEEDS) SIZE=$(SIZE)"

eval: eval-reference
	@echo "── make eval ─────────────────────────────────────────────────────"
	@echo "The scenario tier runs real simulations. Per-tick cost grows with"
	@echo "the store: if this crawls, archive it (infra/README.md) and retry."
	@echo "──────────────────────────────────────────────────────────────────"
	cd $(ENGINE) && ../$(PY) -m shopsim.eval all --profile $(PROFILE) --seeds $(SEEDS) --size $(SIZE)

# Every tier that needs no database. Calibration belongs here: it REPLAYS a
# trace already on disk, in milliseconds. Leaving it out is how the committed
# calibration.json drifted out of step with eval/profiles/demo.json.
eval-fast: eval-analytic eval-calibrate eval-rank eval-report

eval-analytic:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval analytic --profile $(PROFILE) --seeds $(SEEDS) --size $(SIZE)

eval-calibrate:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval calibrate --profile $(PROFILE)

eval-rank:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval rank --profile $(PROFILE) --seeds $(SEEDS) --size $(SIZE)

# No --profile: the scenario tier picks its own (SCENARIO_PROFILE = demo) and
# says why. Passing PROFILE=reference here is what produced seventeen page
# visits across both F5 variants — a coin flip reported as a failed law.
eval-scenarios:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval scenarios

# Idempotent: only runs the simulation when no traced reference run is on disk.
eval-reference:
	@cd $(ENGINE) && if ../$(PY) -c "import sys; from shopsim.eval.__main__ import _reference_run_dir; sys.exit(0 if _reference_run_dir() else 1)"; then \
	    echo "traced reference run present — skipping (delete it or use eval-clean to force)"; \
	else \
	    echo "no traced reference run — producing one (real run, minutes)"; \
	    ../$(PY) -m shopsim.runner run --config ../eval/configs/reference.json --trace-decisions; \
	fi

eval-report:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval report --profile $(PROFILE)

eval-clean:
	rm -rf eval/results eval/plots eval/fixtures eval/configs/built
	@echo "cleaned: eval/{results,plots,fixtures,configs/built}"

test:
	cd $(ENGINE) && ../$(PY) -m pytest -q

test-real:
	cd $(ENGINE) && SHOPSIM_HYDRAMEM=real ../$(PY) -m pytest -q -m real
