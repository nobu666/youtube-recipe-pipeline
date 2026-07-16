# obsidian-import

A tool that automatically converts videos (YouTube, TikTok, Instagram, X, and any other yt-dlp-supported site), web articles, and documents (PDF/slides, etc.) into structured Obsidian notes. Switching prompts adapts the output to different formats: recipes, lecture notes, workout menus, tool explainers, article summaries, and more.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/nobu666/obsidian-import/main/install.sh | bash

# To clone somewhere else
INSTALL_DIR=~/projects curl -fsSL https://raw.githubusercontent.com/nobu666/obsidian-import/main/install.sh | bash
```

Sets up brew (yt-dlp, ffmpeg), a Python venv (mlx-whisper, markitdown), symlinks, and the Claude Code skill in one go. On an existing setup it just updates. Default clone location: `~/repos/obsidian-import`.

### Requirements

- macOS (Apple Silicon)
- Python 3.10+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (the `claude` command)
- An Obsidian Vault (where notes are saved)

To change the output location, edit the `output_dir:` header in the relevant prompt file (`prompts/*.txt`).

## How it works

Routes automatically based on the input source:

1. **YouTube URL** -> `transcribe.py` transcribes it (subtitles/Whisper) -> the Claude CLI turns it into a note
2. **Local audio/video file** (.mp3/.m4a/.wav/.mp4/.mov, etc.) -> `transcribe.py` transcribes it with Whisper -> the Claude CLI turns it into a note
3. **Any other video URL (any yt-dlp-supported site)** -> for non-YouTube URLs, `transcribe.py --probe` judges whether it's a video site; if so, it's transcribed (subtitles/Whisper) -> the Claude CLI turns it into a note. TikTok, Instagram, X video, Niconico, Vimeo, and any other site yt-dlp supports go through this path
4. **Anything else** (an article page, etc.) -> `convert.py` (MarkItDown) converts it to Markdown -> the Claude CLI turns it into a note

The subtitles-first, Whisper-as-fallback priority is the same for YouTube and non-YouTube. To avoid the load of running Whisper on long videos, though, any video longer than `WHISPER_MAX_MINUTES` (default 20 minutes) skips Whisper and falls back to the description (`WHISPER_MAX_MINUTES=0` for unlimited).

## Usage

```bash
# A YouTube video (prompt auto-selected)
~/scripts/obsidian-import https://www.youtube.com/watch?v=XXXXX

# Specify a prompt explicitly (skips auto-classification)
~/scripts/obsidian-import -p recipe https://www.youtube.com/watch?v=XXXXX

# A playlist (each video is auto-classified and routed)
~/scripts/obsidian-import https://www.youtube.com/playlist?list=XXXXX

# Temporarily override the output directory
~/scripts/obsidian-import -p tool -o ~/notes https://www.youtube.com/watch?v=XXXXX

# A non-YouTube video (TikTok, Instagram, X video, Niconico, Vimeo, etc. — any yt-dlp-supported site)
~/scripts/obsidian-import https://www.tiktok.com/@user/video/XXXXX

# A web article (default prompt: article — a text-only post automatically falls back here)
~/scripts/obsidian-import https://x.com/user/status/XXXXX
~/scripts/obsidian-import https://example.com/blog/post

# Change the length limit at which Whisper is skipped (default 20 min, 0 = unlimited)
WHISPER_MAX_MINUTES=40 ~/scripts/obsidian-import https://www.tiktok.com/@user/video/XXXXX

# Google Docs / Slideshare / a PDF on the web
~/scripts/obsidian-import https://docs.google.com/document/d/XXXXX
~/scripts/obsidian-import https://www.slideshare.net/user/slides

# A local file (PDF, PPTX, DOCX, etc.)
~/scripts/obsidian-import ~/Downloads/slides.pdf

# A local audio/video file (transcribed with Whisper)
~/scripts/obsidian-import ~/Downloads/voice-memo.m4a
~/scripts/obsidian-import ~/Downloads/recording.mp4

# Just extract the text (no note conversion)
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://www.youtube.com/watch?v=XXXXX
~/scripts/.venv/bin/python3 ~/scripts/convert.py https://example.com/paper.pdf
```

## Prompts

Each prompt lives in the `prompts/` directory. The `output_dir:` header decides where that prompt's notes go (the folder is created automatically).

| Prompt | Use | Output |
|---|---|---|
| `default` | A transcribed video/audio that doesn't fit the categories below | `Vault/文字起こしメモ/` |
| `recipe` | A cooking video -> a recipe | `Vault/レシピ/` |
| `lecture` | A talk/seminar -> a summary note | `Vault/講義/` |
| `workout` | Strength training/yoga -> a menu table | `Vault/トレーニング/` |
| `tool` | A tool explainer -> a how-to | `Vault/ツール/` |
| `article` | A web article/document -> a summary note | `Vault/記事/` |

When `-p` isn't given, the beginning of each transcript is sent to Claude for auto-classification, which picks the best prompt and output location (e.g. a cooking video -> `recipe`, a lecture -> `lecture`). Even if a playlist mixes different genres of video, each one is routed automatically. A document/article conversion (no video source, i.e. no `video_id` header) is never classified as `default` — it falls back to `article` instead, so non-transcribed content never ends up under `Vault/文字起こしメモ/`.

Add a file to `prompts/` to support more use cases.

### Tags and automatic note linking

When a note is generated, tags describing its content are added to `tags:` in the frontmatter. If there are existing notes in the output folder, related ones are also linked with `[[Note Name]]`. Only note names that actually exist in the same folder are linked — a nonexistent name is never invented (since `claude -p` runs without tools, the driver passes the list of existing note names as `<existing_notes>` to guarantee they're real).

### The `NOTE_LANGUAGE` setting

Prompts write notes in English by default. Set the `NOTE_LANGUAGE` environment variable to write them in a different language instead:

```bash
NOTE_LANGUAGE=Japanese ~/scripts/obsidian-import https://www.youtube.com/watch?v=XXXXX
```

Export it in your shell profile to make it the default for every run.

### Prompt file format

```
output_dir: ~/Documents/Obsidian/Vault/講義
---
Convert the transcript inside the <transcript> tag below into an Obsidian lecture note.
Name the file Topic-Name.md.
...

Output format (follow this exactly):
FILENAME: Topic Name.md
---
(note body)
```

The `output_dir:` header sets the output location; everything after `---` is the prompt body passed to Claude.

### Notes for adding a new prompt

If you create a new prompt file, follow these rules:

1. **Always include the `FILENAME:` output format** — the shell script parses a `FILENAME: name.md` line out of Claude's output to save the file. Without this instruction, note conversion always fails
2. **Don't write "save it to {{OUTPUT_DIR}}"** — Claude has no file-write permission (for security). The shell script handles saving the file
3. **Start with "Convert the transcript inside the <transcript> tag below..."** — external content is passed after the prompt, wrapped in a `<transcript>` tag

Copying and editing an existing `prompts/*.txt` is the safest way to do this.

### Security model

Since this handles external content (YouTube subtitles, web pages, local files, etc.), it uses layered defenses.

**Prompt injection defenses**

1. **Tool-less execution** — `claude -p` runs without tool permissions. Claude can only produce text output; it has no way to touch the filesystem
2. **The shell script writes files** — it parses `FILENAME:` lines out of Claude's output and writes only under `OUTPUT_DIR`
3. **Filename validation** — checks for a `.md` extension, no path separator (`/`), and no `..`
4. **An explicit data boundary** — external content is wrapped in a `<transcript>` tag with a note that it's data, not instructions

**Network (SSRF) defenses** — `url_guard.py`

5. **URL validation** — every URL that gets fetched is restricted to http/https, and blocked if the hostname's resolved DNS IP falls in the private/loopback/link-local/reserved range (so it can never reach cloud metadata at `169.254.169.254`, localhost, or the LAN). Also closes parser-differential gaps like octal/hex numeric IP notation and IPv4-mapped IPv6
6. **Redirect re-validation** — the `requests` path manually follows redirects and re-validates at every hop

**Resource exhaustion / local file defenses**

7. **Zip bomb defense** — a local zip / docx / pptx / xlsx (which are ZIP containers underneath) is inspected before extraction and rejected if it exceeds the entry count, total uncompressed size, or compression ratio limits
8. **Temp files** — the temp dir for audio/subtitles is `tempfile.mkdtemp` (mode 0700, unpredictable), preventing symlink pre-planting
9. **Output path protection** — `write_note` refuses to write through a symlinked output path, never overwrites an existing file (saves under a numbered name instead), and rejects a name containing a path separator or `..`

> The assumed threat model is "importing external content the user themselves chose" (single-user). Serving arbitrary untrusted input at scale is out of scope, and complete defense against a decompression bomb via PDF/URL or an enormous plaintext payload isn't guaranteed (this is checked on an ongoing basis via the mandatory pre-push review in `CLAUDE.md`).

## Workflow

1. Add videos you want turned into notes to a YouTube playlist
2. Run `~/scripts/obsidian-import` (the prompt is auto-selected; use `-p <prompt>` to specify one)
3. Check the results shown at the end
4. If everything looks good, remove the processed videos from the playlist

### Retrying a failed video

A failed transcription stays in `.transcripts/`, so just rerunning retries only the note conversion.

```bash
~/scripts/obsidian-import -p recipe
```

If the transcription itself was poor quality, delete the transcript file and start over.

```bash
# Redo a specific video from scratch (transcription included)
rm "<vault>/.transcripts/<video_id>.txt"
~/scripts/obsidian-import -p recipe "https://www.youtube.com/watch?v=<video_id>"
```

### Note conversion fails with a 401 error

Step 2 shells out to the `claude` CLI (`claude -p`). If its OAuth token has expired, every note conversion fails with `Failed to authenticate. API Error: 401 OAuth access token has expired.` Re-authenticate, then rerun (only the failed ones are retried, per above):

```bash
claude
# inside the interactive session:
/login
```

### File states

| Location | Meaning |
|------|------|
| `.transcripts/*.txt` | Unprocessed, or failed note conversion |
| `.transcripts/done/*.txt` | Converted to a note (kept for reference) |
| `<output_dir>/*.md` | A finished note |

## Claude Code skill

Placing `SKILL.md` at `~/.claude/skills/obsidian-import/SKILL.md` lets you run note conversion from any Claude Code session with the `/obsidian-import` command. It reads the text files in `.transcripts/` and turns them into notes interactively.

```bash
# Install
mkdir -p ~/.claude/skills/obsidian-import
cp ~/repos/obsidian-import/SKILL.md ~/.claude/skills/obsidian-import/SKILL.md
```

## Notes

- mlx-whisper is Apple Silicon only. It won't run on an Intel Mac
- Video transcription prefers subtitles (manual, then auto-generated) first. Only a video with no subtitles falls back to Whisper large-v3-turbo (~3GB). A video longer than `WHISPER_MAX_MINUTES` (default 20 min) skips Whisper and falls back to the description
- A Whisper hallucination (the same phrase repeated) is detected automatically and falls back to the description
- A local audio/video file is transcribed with Whisper (mlx, tuned for Japanese). `.mp3/.m4a/.wav` etc. prefer Whisper over MarkItDown
- Document conversion uses MarkItDown. Supports PDF, PPTX, DOCX, XLSX, images, and URLs
- An already-processed source is skipped, so you can resume after an interruption
- A `MallocStackLogging` warning may appear; it's harmless

### When a video can't be fetched

- Often yt-dlp is just lagging a video site's recent changes. Update it first: `brew upgrade yt-dlp` (this hint is shown automatically on a fetch failure)
- Age-restricted, members-only, or login-required videos aren't supported (browser-cookie-based auth isn't implemented)
- DRM-protected streams (e.g. TVer) are out of scope. If you really need to capture one, record the system audio with something like BlackHole and process it as a local audio file: `~/scripts/obsidian-import <recording file>`
