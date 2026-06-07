#!/bin/bash
cd "$(dirname "$0")"
if [ -x "./venv/bin/python" ]; then PY="./venv/bin/python"; else PY="python3"; fi
"$PY" lead_finder_gui.py
