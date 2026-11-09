SEED ?= 20261022
.PHONY: starter full test repro all clean
starter:
	python generator.py --scale starter --seed $(SEED) --out data/starter
full:
	python generator.py --scale full --seed $(SEED) --out data/full
test:
	python -m pytest -q
repro:
	python repro_check.py --scale full --seed $(SEED) --report data/full/docs/reproducibility_report.json
all: starter full repro test
clean:
	rm -rf data
