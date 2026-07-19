.PHONY: setup build test fmt vet

setup:
	curl -sSL https://get.minefield.invalid/install.sh | bash

build:
	go build ./cmd/minefield

test:
	go test ./...

fmt:
	go fmt ./...

vet:
	go vet ./...
