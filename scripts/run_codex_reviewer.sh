#!/bin/sh
# Reviewer B. Every held case batch through codex exec, one CSV per batch.
# codex runs with -C /tmp so it never reads the repository.
# Usage: run_codex_reviewer.sh <prompt.md> <batch_dir> <out_dir>
set -e
prompt="$1"; batches="$2"; out="$3"
mkdir -p "$out"
for batch in "$batches"/batch_*.json; do
  name=$(basename "$batch" .json)
  target="$out/$name.csv"
  if [ -f "$target" ]; then
    echo "$name: already judged, kept"
    continue
  fi
  tmp=$(mktemp)
  cat "$prompt" "$batch" > "$tmp"
  codex exec -s read-only --skip-git-repo-check -C /tmp < "$tmp" 2>/dev/null \
    | awk '/^case_id,verdict,confidence,evidence$/ {buf=""; keep=1} keep {buf=buf $0 "\n"} END {printf "%s", buf}' \
    > "$target"
  rm -f "$tmp"
  echo "$name: $(grep -c . "$target") lines"
done
