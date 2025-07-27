#!/bin/sh -e
set -x

# Format imports and code
poetry run ruff check webhooks_bridge --fix --select I
bash ./scripts/format.sh