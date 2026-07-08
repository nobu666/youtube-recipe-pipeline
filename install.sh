#!/bin/bash
set -euo pipefail

REPO_DIR="${INSTALL_DIR:-$HOME/repos}/obsidian-import"
SCRIPTS_DIR="$HOME/scripts"
VENV_DIR="$SCRIPTS_DIR/.venv"

echo "=== obsidian-import install ==="

# Dependencies
echo ""
echo "--- brew packages ---"
brew install yt-dlp ffmpeg python@3.12 2>/dev/null || brew upgrade yt-dlp ffmpeg python@3.12 2>/dev/null || true

# Repository
echo ""
echo "--- Repository ---"
if [ -d "$REPO_DIR/.git" ]; then
  echo "Updating the existing repository..."
  git -C "$REPO_DIR" pull
else
  echo "Cloning..."
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone https://github.com/nobu666/obsidian-import.git "$REPO_DIR"
fi

# venv
echo ""
echo "--- Python venv ---"
if [ ! -d "$VENV_DIR" ]; then
  python3.12 -m venv "$VENV_DIR"
fi
# Direct dependencies are version-pinned (reproducibility / supply-chain hygiene;
# updates are bumped deliberately). markitdown installs only the extras needed for
# the types this tool actually handles rather than [all], to avoid pulling in
# unnecessary dependencies (attack surface) like the Azure SDK.
"$VENV_DIR/bin/pip" install -q \
  "mlx-whisper==0.4.3" \
  "markitdown[pdf,docx,pptx,xlsx,xls,audio-transcription]==0.1.6"

# Symlinks
echo ""
echo "--- Symlinks ---"
mkdir -p "$SCRIPTS_DIR"
ln -sf "$REPO_DIR/obsidian-import" "$SCRIPTS_DIR/obsidian-import"
ln -sf "$REPO_DIR/transcribe.py" "$SCRIPTS_DIR/transcribe.py"
ln -sf "$REPO_DIR/convert.py" "$SCRIPTS_DIR/convert.py"

# Claude Code skill
echo ""
echo "--- Claude Code skill ---"
mkdir -p "$HOME/.claude/skills/obsidian-import"
cp "$REPO_DIR/SKILL.md" "$HOME/.claude/skills/obsidian-import/SKILL.md"
# Remove the legacy commands-format copy to avoid double registration
rm -f "$HOME/.claude/commands/obsidian-import.md"

echo ""
echo "=== Done ==="
echo "Usage: ~/scripts/obsidian-import <URL or file>"
echo "Skill: /obsidian-import in Claude Code"
