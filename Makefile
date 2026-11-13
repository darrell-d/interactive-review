.PHONY: help test build run workflow end clean

SERVICE_NAME ?= "interactive-review"

.DEFAULT: help

help:
	@echo "Make Help for $(SERVICE_NAME)"
	@echo ""
	@echo "make test   - run the unit tests (needs: pip install -r processor/requirements.txt)"
	@echo "make build  - build the Docker image"
	@echo "make run    - run the session locally behind the platform's auth proxy (http://localhost:8080)"
	@echo "make workflow - a local stand-in for a workflow: two batch steps, this step (it waits for you), one more step"
	@echo "make end    - end the running session the way the run page's End Session does"
	@echo "make clean  - remove data/output/"

test:
	python3 -m unittest discover -s tests -v

build:
	docker build -t $(SERVICE_NAME) .

# Exits with the app's exit code: 0 is "the workflow continues".
run: clean
	docker compose down --remove-orphans
	docker compose build
	docker compose up --exit-code-from app

workflow:
	./local-workflow.sh

end:
	curl -s -X POST http://localhost:8080/pennsieve/close

clean:
	rm -rf data/output
