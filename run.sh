#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt
if ! python3 -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(p.firefox.executable_path); p.stop()" 2>/dev/null; then
  python3 -m playwright install firefox
fi
if ! ls ~/.cache/ms-playwright 2>/dev/null | grep -qi firefox; then
  python3 -m playwright install firefox
fi
python3 server.py "$@"
