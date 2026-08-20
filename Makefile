# Hack Hydra — top-level targets.
#
# `make eval` is PLAN 7's checkpoint: "reproduces every number and plot from
# scratch". It is deliberately slow, because the scenario tier runs real
# simulations on the live store — that is the point of it. `make eval-fast`
# is the same suite minus those runs, and finishes in seconds.
#
# Before a long run, read infra/README.md "Engine pace and the store-reset
# ritual": per-tick cost grows with the store, and the SAME shape has measured
# 18.5 s/tick fresh and 112 s/tick loaded. `make eval` prints the reminder.

ENGINE  := engine
PY      := $(ENGINE)/.venv/bin/python
PROFILE ?= reference
SEEDS   ?= 11,23,37,53,71
SIZE    ?= 300

.PHONY: help eval eval-fast eval-analytic eval-rank eval-scenarios eval-report \
        eval-clean test test-real

help:
	@echo "make eval           full Phase-7 reproduction (analytic + rank + real runs + report)"
	@echo "make eval-fast      analytic + rank + report only, no database, seconds"
	@echo "make eval-scenarios just the real runs (slow; needs a live HydraDB)"
	@echo "make eval-report    re-assemble /eval from artifacts already on disk"
	@echo "make eval-clean     delete generated eval artifacts (keeps specs + profiles)"
	@echo "make test           unit suite (no database)"
	@echo "make test-real      integration suite against a live HydraDB"
	@echo ""
	@echo "vars: PROFILE=$(PROFILE) SEEDS=$(SEEDS) SIZE=$(SIZE)"

eval:
	@echo "── make eval ─────────────────────────────────────────────────────"
	@echo "The scenario tier runs real simulations. Per-tick cost grows with"
	@echo "the store: if this crawls, archive it (infra/README.md) and retry."
	@echo "──────────────────────────────────────────────────────────────────"
	cd $(ENGINE) && ../$(PY) -m shopsim.eval all --profile $(PROFILE) --seeds $(SEEDS) --size $(SIZE)

eval-fast: eval-analytic eval-rank eval-report

eval-analytic:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval analytic --profile $(PROFILE) --seeds $(SEEDS) --size $(SIZE)

eval-rank:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval rank --profile $(PROFILE) --seeds $(SEEDS) --size $(SIZE)

eval-scenarios:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval scenarios --profile $(PROFILE)

eval-report:
	cd $(ENGINE) && ../$(PY) -m shopsim.eval report --profile $(PROFILE)

eval-clean:
	rm -rf eval/results eval/plots eval/fixtures eval/configs/built
	@echo "cleaned: eval/{results,plots,fixtures,configs/built}"

test:
	cd $(ENGINE) && ../$(PY) -m pytest -q

test-real:
	cd $(ENGINE) && SHOPSIM_HYDRAMEM=real ../$(PY) -m pytest -q -m real
