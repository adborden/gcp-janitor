.PHONY: build setup

CONTAINER_NAME ?= ghcr.io/adborden/gcp-janitor
CONTAINER_TAG ?= latest

build:
	docker buildx build --platform linux/amd64 --platform linux/arm64 . --tag $(CONTAINER_NAME):$(CONTAINER_TAG) $(DOCKER_BUILD_ARGS)

DOCKER_BUILD_ARGS = --push
push: build


setup:
	uv sync

run:
	uv run gcp-janitor --dry-run --project cloud-294216 --keyring vault-fl-a14n-net --key vault-fl-a14n-net
