# CLAUDE.md

A tool that automatically converts videos (YouTube, TikTok, Instagram, X video, and any other yt-dlp-supported site), web articles, and documents (PDF/slides, etc.) into structured Obsidian notes.

## Project layout

```
obsidian-import        # Main script (a bash wrapper that calls claude -p)
transcribe.py          # Video transcription (any yt-dlp-supported site) / web article text extraction
convert.py             # Document conversion (MarkItDown: PDF, PPTX, DOCX, URL, etc.)
prompts/               # Prompt files (switched via the -p option)
tests/                 # pytest tests
install.sh             # One-shot curl setup
SKILL.md               # Claude Code skill definition
```

## Install / symlinks

`install.sh` creates:
- `~/scripts/obsidian-import` -> this repo's `obsidian-import`
- `~/scripts/transcribe.py` -> this repo's `transcribe.py`
- `~/scripts/convert.py` -> this repo's `convert.py`
- `~/scripts/.venv/` — a Python venv (mlx-whisper, markitdown, etc.)

## Tests

```bash
~/scripts/.venv/bin/python3 -m pytest tests/ -v   # Python tests
bash tests/test_obsidian_import.sh                 # Shell script parsing/validation tests
```

External dependencies (yt-dlp, mlx-whisper, the filesystem) are all mocked. mlx-whisper is Apple Silicon only, so it isn't installed in CI.

## Security model

Uses layered defenses since it handles external content (URLs, files, subtitles). **See README.md's security model for details.** Key points:

- **Prompt injection**: `claude -p` runs without tools / the shell writes only under `OUTPUT_DIR` / filename validation (`.md`, no path separator, no `..`) / external content has an explicit `<transcript>` boundary
- **SSRF**: `url_guard.py` (restricted to http/https + blocks internal-facing resolved IPs + closes numeric-IP/IPv4-mapped parser gaps + re-validates every redirect hop) is applied to every fetch path
- **Resource exhaustion / local**: zip bomb inspection (if the content is a ZIP, check limits before extraction) / the temp dir uses `mkdtemp` (0700) / `write_note` refuses a symlink, never overwrites (uses a numbered name instead), and rejects path traversal

## 【MUST】Security review before push

Since this tool handles external content (URLs, files, video subtitles), **you must always run a security review before pushing a code change**.

- Review the diff (`git diff <base>..HEAD`) by dimension, using a Subagent or the `/differential-review` skill
- Focus areas: **SSRF** (URL fetch paths), **command injection** (yt-dlp/subprocess), **path traversal** (write destinations/filenames), **prompt injection** (external input into `claude -p`), **resource exhaustion** (zip/archive bombs, huge inputs), **temp-file pre-planting** (symlink/TOCTOU)
- **Don't push while a Critical/High finding remains.** For a Low/Medium you choose to accept, document why
- After the review, confirm all tests (pytest + shell) pass before pushing

## Notes

- Don't replace `mlx-whisper` with `openai-whisper` (Apple Silicon optimization is a hard requirement)
- Prompt files use the format: `output_dir:` header + `---` + body
- A prompt must instruct the `FILENAME: name.md` output format (the shell script parses it)
- Write comments and prompts in English
