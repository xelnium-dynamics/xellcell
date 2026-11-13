#!/bin/bash
# Runs every tool test (macOS bash 3.2 compatible). Exit code 0 = all passed.
cd "$(dirname "$0")" || exit 1
python3 -I -m unittest discover -s tests -p "test_*.py" -v
