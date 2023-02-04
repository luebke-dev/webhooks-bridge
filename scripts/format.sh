#!/bin/sh -e
set -x

autoflake --remove-all-unused-imports --recursive --remove-unused-variables --in-place webhooks_bridge --exclude=__init__.py
black webhooks_bridge
isort webhooks_bridge