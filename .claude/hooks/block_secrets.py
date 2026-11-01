#!/usr/bin/env python3
"""PreToolUse: blocca i file con i segreti del bot. Exit 2 = chiamata negata, stderr spiegato a Claude."""
import json
import os
import re
import sys

SECRET_FILES = {".env", "credenziali.txt", "config.local.json"}
# Nome esatto: .env.example, .environment o my.env non sono segreti
NAME_RE = re.compile(r"(?<![\w.-])(?:[\w./~-]*/)?(\.env|credenziali\.txt|config\.local\.json)(?![\w.-])")
# I test puntano a un config.local.json finto in una cartella temporanea
TEST_CONFIG_RE = re.compile(r"\bBOT_CONFIG_PATH=\S+")


def blocked_name(tool, data):
    if tool == "Bash":
        match = NAME_RE.search(TEST_CONFIG_RE.sub(" ", str(data.get("command") or "")))
        return match.group(1) if match else None
    for key in ("file_path", "notebook_path", "path", "glob"):
        name = os.path.basename(str(data.get(key) or ""))
        if name in SECRET_FILES:
            return name
    return None


def main():
    payload = json.load(sys.stdin)
    name = blocked_name(payload.get("tool_name", ""), payload.get("tool_input") or {})
    if name:
        print(f"Bloccato: {name} contiene segreti del bot. Se serve davvero, lo apre l'utente a mano.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
