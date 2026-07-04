#!/usr/bin/env bash
#
# promote-to-main.sh — promote dev -> main while stripping dev-only docs/tooling
# so `main` stays a clean, deployable branch: no .claude/, no workspace/, no
# CLAUDE.md / AGENTS.md. README.md is intentionally kept.
#
# WHY a script instead of a plain merge:
#   Keeping docs on `dev` but absent from `main` cannot be done with a
#   `.gitattributes merge=ours` driver — that driver is never consulted for the
#   modify/delete case, so every dev->main merge that touched a tracked doc
#   would raise a modify/delete conflict (and workspace/ changes almost every
#   step). A *normal* merge advances the merge base, so real code files merge
#   cleanly on every promotion; this script then unconditionally removes the
#   doc paths and commits. Proven clean and repeatable.
#
# IMPORTANT: dev -> main must ALWAYS go through this script. A plain
#   `git merge dev` into main pulls the docs back onto main.
#
# The script does NOT push. Review the result, then: git push origin main
#
# Usage:  scripts/promote-to-main.sh
set -euo pipefail

SRC="dev"
DST="main"

# Directories that live on dev but must never appear on main (removed wholesale).
DOC_DIRS=(".claude" "workspace")
# Doc files stripped at any depth (README.md is deliberately NOT in this list).
DOC_FILE_RE='(^|/)(CLAUDE|AGENTS)\.md$'

cd "$(git rev-parse --show-toplevel)"

# --- safety checks -----------------------------------------------------------
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree not clean — commit or stash first." >&2
  exit 1
fi
git show-ref --verify --quiet "refs/heads/$SRC" || { echo "ERROR: branch '$SRC' not found." >&2; exit 1; }
git show-ref --verify --quiet "refs/heads/$DST" || { echo "ERROR: branch '$DST' not found." >&2; exit 1; }

start_branch="$(git rev-parse --abbrev-ref HEAD)"
restore() { git checkout -q "$start_branch" 2>/dev/null || true; }

echo ">> Promoting $SRC -> $DST (stripping docs). Tip: ensure both branches are current with origin first."
git checkout -q "$DST"

# Normal merge. Doc paths may raise modify/delete conflicts — expected, resolved below.
git merge --no-commit --no-ff "$SRC" || true

# Strip doc directories (also resolves any doc modify/delete conflicts as "delete").
git rm -r --cached --ignore-unmatch "${DOC_DIRS[@]}" >/dev/null 2>&1 || true
rm -rf "${DOC_DIRS[@]}" 2>/dev/null || true

# Strip CLAUDE.md / AGENTS.md at any depth (tracked + any left in the worktree).
# NOTE: `while read` reading from a pipe always exits 1 on EOF (a classic bash
# gotcha) regardless of how many lines it processed — under `set -e` that was
# silently killing the script here on every run, right before the final commit,
# with no error message. The trailing `|| true` is REQUIRED, not decorative.
{ git ls-files; git ls-files --others --exclude-standard; } | grep -Ei "$DOC_FILE_RE" | sort -u | while read -r f; do
  git rm --cached --ignore-unmatch "$f" >/dev/null 2>&1 || true
  rm -f "$f" 2>/dev/null || true
done || true

# Bail on any real (non-doc) conflicts.
if git diff --name-only --diff-filter=U | grep -q .; then
  echo "ERROR: unresolved non-doc conflicts remain — resolve, then 'git commit':" >&2
  git diff --name-only --diff-filter=U >&2
  exit 1
fi

# Nothing to promote?
if git diff --cached --quiet; then
  echo ">> Nothing to promote — $DST already up to date."
  git merge --abort 2>/dev/null || true
  restore
  exit 0
fi

git commit -q --no-edit -m "promote: $SRC -> $DST (docs stripped)"

# --- verify main is doc-free -------------------------------------------------
leaks="$(git ls-tree -r "$DST" --name-only | grep -E "^\.claude/|^workspace/|$DOC_FILE_RE" || true)"
if [[ -n "$leaks" ]]; then
  echo "ERROR: docs leaked onto $DST:" >&2
  echo "$leaks" >&2
  exit 1
fi

echo ">> Done. $DST is clean. Review, then push:  git push origin $DST"
restore
