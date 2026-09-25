#!/usr/bin/env bash
set -Eeuo pipefail
command -v chromium >/dev/null || { echo "web environment requires Chromium" >&2; exit 2; }
chromium --version
echo "web_browser=chromium"
