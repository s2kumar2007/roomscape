.PHONY: setup run viewer build test health
setup:
	bash scripts/setup_env.sh
run:
	python pipeline/run_pipeline.py --video test/sample_video --out out --mode fast --resume
viewer:
	cd viewer && npm install && npm run dev
build:
	cd viewer && npm ci && npm run build && python ../scripts/check_dist.py
test:
	pytest -q && cd viewer && npm test
health:
	python scripts/health_check.py --url $(URL)
