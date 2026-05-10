#!/bin/bash
cd "$(dirname "$0")"

PORT=5001 python -u main.py &
FLASK_PID=$!

pnpm run dev &
VITE_PID=$!

wait $FLASK_PID $VITE_PID

