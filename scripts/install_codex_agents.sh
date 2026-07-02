#!/usr/bin/env bash
set -euo pipefail

SCOPE="${1:-project}"
FORCE="${2:-}"

if [ "$SCOPE" = "user" ]; then
  TARGET="$HOME/.codex/agents"
elif [ "$SCOPE" = "project" ]; then
  TARGET=".codex/agents"
else
  echo "Usage: install_codex_agents.sh [project|user] [--force]" >&2
  exit 2
fi

mkdir -p "$TARGET"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

conflicts=0
for src in "$SKILL_ROOT"/assets/codex_agents/*.toml; do
  dst="$TARGET/$(basename "$src")"
  if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then
    if [ "$FORCE" = "--force" ]; then
      cp "$src" "$dst"
    else
      echo "CONFLICT: $dst already exists and differs. Re-run with --force to overwrite." >&2
      conflicts=1
    fi
  else
    cp "$src" "$dst"
  fi
done

if [ "$conflicts" -ne 0 ]; then
  exit 1
fi

echo "Installed Codex agents to $TARGET"
find "$TARGET" -maxdepth 1 -type f -name "*.toml" -exec basename {} \; | sort
