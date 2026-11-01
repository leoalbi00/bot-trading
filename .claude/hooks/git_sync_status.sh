#!/usr/bin/env bash
# SessionStart: aggiorna i riferimenti remoti (senza toccare i file) e segnala se main è allineato a origin/main.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

if ! timeout 12 git fetch -q origin 2>/dev/null; then
  msg="Sync GitHub non verificato: git fetch fallito, il main locale potrebbe essere indietro."
else
  read -r ahead behind < <(git rev-list --left-right --count main...origin/main 2>/dev/null)
  if [ -z "$ahead" ]; then
    msg="Sync GitHub non verificato: main o origin/main non trovati."
  elif [ "$behind" -gt 0 ]; then
    msg="ATTENZIONE: main locale indietro di $behind commit e avanti di $ahead rispetto a origin/main. Allinealo prima di analizzare o modificare il codice."
  elif [ "$ahead" -gt 0 ]; then
    msg="main locale avanti di $ahead commit rispetto a origin/main: non ancora pushati."
  else
    msg="main locale allineato a origin/main."
  fi
fi

MSG="$msg" python3 -c '
import json, os
msg = os.environ["MSG"]
out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}
if "allineato" not in msg:
    out["systemMessage"] = msg
print(json.dumps(out, ensure_ascii=False))'
