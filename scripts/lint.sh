#!/usr/bin/env bash

set -x

poetry run mypy webhooks_bridge
poetry run black webhooks_bridge --check
poetry run ruff check webhooks_bridge