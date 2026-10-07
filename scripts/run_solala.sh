#!/usr/bin/sh

project="$HOME/Development/solala"
python="$project/.venv314/bin/python"

export PYTHONPATH="$project/src:$project/private/config:${PYTHONPATH:+:$PYTHONPATH}"

exec "$python" -m solala_demo.demo_server
