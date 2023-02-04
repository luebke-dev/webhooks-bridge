#!/usr/bin/env bash

set -x

mypy webhooks_bridges
black webhooks_bridges --check
isort --recursive --check-only webhooks_bridges
flake8 webhooks_bridges