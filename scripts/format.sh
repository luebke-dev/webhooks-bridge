#!/bin/sh -e
set -x

poetry run ruff check webhooks_bridge --fix
poetry run black webhooks_bridge