#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
python "$DIR/poll_until_done.py" "$@"

