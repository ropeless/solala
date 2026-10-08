#!/usr/bin/sh

project="$HOME/Development/solala"
python="$project/.venv314/bin/python"

export PYTHONPATH="$project/src:$project/private/config:${PYTHONPATH:+:$PYTHONPATH}"

# Try to automatically upgrade (is this okay?)
cd "$project"
git pull origin main

exec "$python" -m solala_demo.demo_server
