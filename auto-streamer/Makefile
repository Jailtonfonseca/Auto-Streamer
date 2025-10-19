# Makefile for Auto-Streamer

# --- Variables ---
IMAGE_NAME := auto-streamer
CONTAINER_NAME := auto-streamer-dev
UI_PORT := 8080

# --- Docker Commands ---

.PHONY: build
build:
	@echo "Building Docker image: $(IMAGE_NAME)..."
	docker build -t $(IMAGE_NAME) .

.PHONY: run
run:
	@echo "Running container $(CONTAINER_NAME) on port $(UI_PORT)..."
	@echo "Make sure to set RTMP_URL, STREAM_KEY, OPENAI_API_KEY, and ADMIN_PASS_HASH in your environment."
	docker run --rm -it \
		-p $(UI_PORT):$(UI_PORT) \
		-e UI_PORT=$(UI_PORT) \
		-e RTMP_URL=${RTMP_URL} \
		-e STREAM_KEY=${STREAM_KEY} \
		-e OPENAI_API_KEY=${OPENAI_API_KEY} \
		-e ADMIN_PASS_HASH=${ADMIN_PASS_HASH} \
		-v $(shell pwd)/output:/app/output \
		-v $(shell pwd)/config.json:/app/config.json \
		--name $(CONTAINER_NAME) \
		$(IMAGE_NAME)

.PHONY: stop
stop:
	@echo "Stopping container $(CONTAINER_NAME)..."
	docker stop $(CONTAINER_NAME)

# --- CLI Commands (run inside the container) ---

.PHONY: shell
shell:
	@echo "Opening a shell inside a new container..."
	docker run --rm -it --entrypoint /bin/bash \
		-v $(shell pwd)/output:/app/output \
		-v $(shell pwd)/config.json:/app/config.json \
		-e OPENAI_API_KEY=${OPENAI_API_KEY} \
		$(IMAGE_NAME)

.PHONY: validate
validate:
	@echo "Validating configuration and environment..."
	docker run --rm -it $(IMAGE_NAME) python -m app.main validate

# --- Pipeline Commands ---

.PHONY: sample
sample:
	@echo "Running a short sample pipeline (ingest -> tts -> render)..."
	docker run --rm -it \
		-v $(shell pwd)/output:/app/output \
		-v $(shell pwd)/config.json:/app/config.json \
		-e OPENAI_API_KEY=${OPENAI_API_KEY} \
		$(IMAGE_NAME) python -m app.main all

.PHONY: stream-dry
stream-dry:
	@echo "Testing stream output without publishing (-f null)..."
	# This requires a more complex command to override the streamer's ffmpeg call.
	# For now, this is a placeholder. A proper dry run would be a feature
	# in the streamer.py module itself.
	@echo "Dry run not implemented yet. This is a placeholder."


.PHONY: clean
clean:
	@echo "Cleaning up output directory..."
	rm -rf output/*
	@echo "To remove the Docker image, run: docker rmi $(IMAGE_NAME)"


.PHONY: help
help:
	@echo "Available commands:"
	@echo "  build         - Build the Docker image"
	@echo "  run           - Run the application in a Docker container"
	@echo "  stop          - Stop the running container"
	@echo "  shell         - Open a bash shell inside the container"
	@echo "  validate      - Validate the application configuration"
	@echo "  sample        - Run a sample pipeline to generate a video"
	@echo "  stream-dry    - (Placeholder) Test the stream without going live"
	@echo "  clean         - Remove all generated files from the output directory"

.DEFAULT_GOAL := help
