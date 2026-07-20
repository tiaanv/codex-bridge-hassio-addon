#!/usr/bin/env bash
set -euo pipefail

export GPTMOCK_HOME="/data"
export GPTMOCK_HOST="127.0.0.1"
export GPTMOCK_PORT="8001"
export GPTMOCK_LOGIN_BIND="127.0.0.1"

exec /app/.venv/bin/python /opt/codex-bridge/manager.py
