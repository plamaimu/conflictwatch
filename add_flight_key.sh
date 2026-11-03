#!/usr/bin/env bash
# Register your free AeroDataBox RapidAPI key for conflictwatch "My flights".
# Steps before running: sign up at https://rapidapi.com (free), open
# https://rapidapi.com/caasdev/api/aerodatabox and click "Subscribe to a Free
# Plan" (Basic, $0, ~500 calls/month), then copy your X-RapidAPI-Key from
# the "Code" tab.
set -euo pipefail
mkdir -p ~/.conflictwatch
read -rs "k?Paste AeroDataBox RapidAPI key (hidden): "
[ -n "$k" ] || { echo "empty key, aborted"; exit 1; }
umask 077
printf '%s' "$k" > ~/.conflictwatch/rapidapi_key
chmod 600 ~/.conflictwatch/rapidapi_key
echo "Saved to ~/.conflictwatch/rapidapi_key (mode 600). Next fetch cycle will pick it up."
echo "Now add flights to ~/Projects/conflictwatch/config.json -> flights.list, e.g.:"
echo '  {"flight": "TG935", "date": "2026-11-10"}   (date may be omitted = today)'
