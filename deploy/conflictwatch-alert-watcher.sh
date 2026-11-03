#!/usr/bin/env bash
# conflictwatch-alert-watcher.sh — drain the alert inbox and print formatted text
# for the Hermes gateway cron (no_agent mode: stdout is delivered verbatim to the
# configured chat target; empty stdout = no message).
# Place at ~/.hermes/scripts/, chmod +x, and register a Hermes cron job:
#   schedule every 10m, no_agent=true, script=conflictwatch-alert-watcher.sh,
#   deliver=<your chat target — see your gateway's platform:chat_id grammar>
set -uo pipefail
INBOX="${CONFLICTWATCH_INBOX:-$HOME/.hermes/inbox/conflictwatch.jsonl}"
DASH="${CONFLICTWATCH_DASHBOARD:-http://localhost:8220}"
[ -s "$INBOX" ] || exit 0
TMP="$INBOX.processing"
mv "$INBOX" "$TMP"
python3 - "$TMP" "$DASH" <<'EOF'
import json, sys
msgs = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        rec = json.loads(line)
    except Exception:
        continue
    icon = {"critical": "🔴", "high": "🟠", "test": "🧪"}.get(rec.get("severity"), "ℹ️")
    tag = "" if rec.get("kind") in ("initial", None, "test") else f" [{rec.get('kind')}]"
    msgs.append(f"{icon} {rec.get('text','?')}{tag}")
if msgs:
    print("\n\n".join(msgs[:6]))
    print(f"\nDashboard: {sys.argv[2]}")
EOF
rm -f "$TMP"
