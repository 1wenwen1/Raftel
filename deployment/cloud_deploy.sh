#!/usr/bin/env bash
# AE FIX: derive local paths and propagate every transfer failure.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${REPO}/deployment/transfer.py"
