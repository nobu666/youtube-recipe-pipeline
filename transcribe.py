#!/usr/bin/env python3
"""
Download a video's audio (any yt-dlp-supported site) and transcribe it with Whisper.
Also handles text extraction from web articles.
Results are saved to .transcripts/ inside the Obsidian Vault.
The obsidian-import script hands off conversion to structured notes to the Claude CLI.
"""

import argparse
import atexit
import hashlib
import os
import re
import shutil
import subprocess
import json
import sys
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlparse

# Add the real script dir so url_guard resolves even when invoked via a symlink (~/scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from url_guard import UnsafeURLError, assert_safe_url, safe_head

os.environ["MALLOC_STACK_LOGGING"] = ""
warnings.filterwarnings("ignore", message=".*unauthenticated.*HF Hub.*")

# === Config ===
DEFAULT_OUTPUT_DIR = Path.home() / "Documents/Obsidian/Vault/文字起こしメモ"
OBSIDIAN_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
TRANSCRIPT_DIR = OBSIDIAN_OUTPUT_DIR / ".transcripts"
# A predictable fixed /tmp path leaves room for symlink pre-planting on a shared
# machine, so use a per-process, user-only temp dir (mode 0700) and clean it up on exit.
AUDIO_TMP_DIR = Path(tempfile.mkdtemp(prefix="yt_obsidian_audio_"))
SUBS_TMP_DIR = Path(tempfile.mkdtemp(prefix="yt_subs_"))
atexit.register(shutil.rmtree, AUDIO_TMP_DIR, ignore_errors=True)
atexit.register(shutil.rmtree, SUBS_TMP_DIR, ignore_errors=True)
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
DONE_DIR = TRANSCRIPT_DIR / "done"

# Extensions for local audio/video files transcribed with Whisper
AUDIO_EXTS = {
    ".mp3", ".m4a", ".m4b", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".mp4", ".mov", ".m4v",
}


def is_youtube_url(url):
    """Is this a YouTube host? (Strict host match, avoiding false positives from a
    partial match like `youtube.com.evil.example`.)"""
    host = urlparse(url).hostname or ""
    hosts = ("youtube.com", "youtu.be", "youtube-nocookie.com")
    return any(host == h or host.endswith("." + h) for h in hosts)


def detect_video_extractor(url):
    """Ask yt-dlp whether it can treat this URL as a video.

    Returns the extractor name (other than generic) if it can, otherwise None.
    The generic extractor's behavior is "hunt for any embedded video on the page,"
    so it's excluded to avoid misclassifying an ordinary article page as a video.
    """
    try:
        assert_safe_url(url)
    except UnsafeURLError:
        return None
    try:
        result = subprocess.run(
            ["yt-dlp", "--quiet", "--no-warnings", "--flat-playlist",
             "--playlist-items", "1", "--print", "%(extractor,ie_key)s",
             "--socket-timeout", "10", "--", url],
            capture_output=True, text=True, timeout=20
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().splitlines()
    name = lines[0].strip() if lines else ""
    if not name or name.lower() == "generic":
        return None
    return name


def is_audio_file(path):
    """Is this a local audio/video file?"""
    p = Path(path).expanduser()
    return p.is_file() and p.suffix.lower() in AUDIO_EXTS


def url_to_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:12]


# Validate the video ID (external input, from yt-dlp's output) before using it in a
# path, to prevent path-traversal writes from a malicious ID (e.g. `../`).
# fullmatch (unanchored) reliably rejects a trailing newline (`abc\n`) too.
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _is_safe_id(vid):
    return bool(vid) and VIDEO_ID_RE.fullmatch(vid) is not None


def _is_x_host(host):
    """Is this x.com / twitter.com or a subdomain of it? (Avoids false positives from a partial match.)"""
    return host in ("x.com", "twitter.com") or host.endswith((".x.com", ".twitter.com"))


def _hdr_val(v):
    """Strip newlines from a header value, preventing injection of a fake `---` boundary or key."""
    return str(v).replace("\r", " ").replace("\n", " ")


def setup_dirs():
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _print_ytdlp_hint():
    """Print yt-dlp's version and nudge the user to update (most failures are yt-dlp lagging a site's changes)"""
    version = None
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
        if v.returncode == 0:
            version = v.stdout.strip()
    except Exception:
        pass
    if version:
        print(f"Using yt-dlp {version}. If a video site's changes broke fetching, updating yt-dlp often fixes it:")
    else:
        print("If a video site's changes broke fetching, updating yt-dlp often fixes it:")
    print("  brew upgrade yt-dlp")


def get_videos(url, allow_no_video_exit=False):
    """Fetch video info from a URL (works for both a single video and a playlist)

    When allow_no_video_exit=True, treat a failed yt-dlp call as "no video was
    found" and exit with code 2, so the caller can fall back to convert.py's
    article processing. For a direct YouTube URL etc., where it's already known
    to be a video, keep the legacy exit code 1.
    """
    print("Fetching video info...")
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", "--", url],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        if allow_no_video_exit:
            print("No video was found (timed out). Trying to process as an article instead.")
            sys.exit(2)
        print("Error: fetching video info timed out")
        sys.exit(1)
    if result.returncode != 0:
        if allow_no_video_exit:
            print("No video was found. Trying to process as an article instead.")
            sys.exit(2)
        print(f"Error: failed to fetch video info\n{result.stderr}")
        _print_ytdlp_hint()
        sys.exit(1)

    data = json.loads(result.stdout)

    # Single video
    if "entries" not in data:
        vid = data.get("id", "")
        if not _is_safe_id(vid):
            print(f"Error: detected an invalid video ID: {vid!r}")
            sys.exit(1)
        return [{
            "id": vid,
            "title": data.get("title", "unknown"),
            "url": url,
            "duration": data.get("duration"),
        }]

    # Playlist
    videos = []
    for entry in data.get("entries", []):
        vid = entry.get("id", "")
        if not _is_safe_id(vid):
            print(f"  Skipping an invalid video ID: {vid!r}")
            continue

        entry_url = entry.get("url")
        if entry_url:
            # An entry's URL is yt-dlp's JSON output — external data — so validate
            # it before use (the legacy YouTube-only construction from a validated
            # ID was structurally safe; this generalization needs its own check)
            try:
                assert_safe_url(entry_url)
            except UnsafeURLError as e:
                print(f"  Skipping an unsafe URL: {e}")
                continue
        elif is_youtube_url(url):
            entry_url = f"https://www.youtube.com/watch?v={vid}"
        else:
            print(f"  Skipping — couldn't get the entry's URL: {vid!r}")
            continue

        videos.append({
            "id": vid,
            "title": entry.get("title", "unknown"),
            "url": entry_url,
            "duration": entry.get("duration"),
        })
    return videos


def download_audio(video):
    """Download the video's audio"""
    output_path = AUDIO_TMP_DIR / f"{video['id']}.mp3"
    if output_path.exists():
        print(f"  Audio already cached")
        return output_path

    print(f"  Downloading audio...")
    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5",
         "-o", str(output_path), "--", video["url"]],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  Download failed: {result.stderr[:200]}")
        _print_ytdlp_hint()
        return None
    return output_path


def is_hallucinated(text, threshold=0.4):
    """Detect a Whisper hallucination (the same phrase repeated)"""
    if len(text) < 50:
        return True
    # Detect a 2-20 character pattern repeating
    match = re.search(r"(.{2,20})\1{4,}", text)
    if match and len(match.group(0)) / len(text) > threshold:
        return True
    # Skewed toward punctuation/symbols
    content_chars = re.sub(r"[\s。、…・！？!?,.\d]", "", text)
    if len(content_chars) < len(text) * 0.2:
        return True
    return False


def get_subtitles(video):
    """Fetch YouTube subtitles (tries Japanese manual -> Japanese auto -> English manual -> English auto, in that order)"""
    for lang, sub_args in [
        ("ja", ["--write-subs", "--sub-langs", "ja"]),
        ("ja", ["--write-auto-subs", "--sub-langs", "ja"]),
        ("en", ["--write-subs", "--sub-langs", "en"]),
        ("en", ["--write-auto-subs", "--sub-langs", "en"]),
    ]:
        result = subprocess.run(
            ["yt-dlp", "--skip-download", *sub_args,
             "--convert-subs", "srt", "-o", str(SUBS_TMP_DIR / "%(id)s"), "--", video["url"]],
            capture_output=True, text=True
        )
        srt_path = SUBS_TMP_DIR / f"{video['id']}.{lang}.srt"
        if srt_path.exists():
            text = srt_path.read_text(encoding="utf-8")
            srt_path.unlink()
            lines = [l.strip() for l in text.splitlines()
                     if l.strip() and not re.match(r"^\d+$", l.strip())
                     and not re.match(r"\d{2}:\d{2}:\d{2}", l.strip())]
            source_lang = "en" if lang == "en" else None
            return " ".join(lines), source_lang
    return None, None


def get_description(video):
    """Fetch the YouTube description"""
    result = subprocess.run(
        ["yt-dlp", "--print", "description", "--", video["url"]],
        capture_output=True, text=True
    )
    if result.returncode == 0 and len(result.stdout.strip()) >= 50:
        return result.stdout.strip()
    return None


def save_transcript(video, text, source="whisper"):
    """Save the transcribed text to a file"""
    transcript_path = TRANSCRIPT_DIR / f"{video['id']}.txt"
    header = (f"title: {_hdr_val(video['title'])}\n"
              f"video_id: {_hdr_val(video['id'])}\n"
              f"url: {_hdr_val(video['url'])}")
    if source != "whisper":
        header += f"\nsource: {_hdr_val(source)}"
    content = f"{header}\n---\n{text}"
    tmp_fd, tmp_path = tempfile.mkstemp(dir=TRANSCRIPT_DIR, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(transcript_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return transcript_path


def _is_js_wall(text):
    if not text:
        return False
    if "JavaScript is disabled" in text:
        return True
    stripped = re.sub(r"(Loading\.{0,3})+", "", text).strip()
    if len(stripped) < 50:
        return True
    return False


def fetch_with_trafilatura(url):
    """Try text extraction with trafilatura. Returns None on failure"""
    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        print(f"  Blocked the request: {e}")
        return None, None
    try:
        import trafilatura
    except ImportError:
        return None, None
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None, None
    text = trafilatura.extract(downloaded, include_links=False, include_images=False)
    if not text or len(text.strip()) < 100 or _is_js_wall(text):
        return None, None
    meta = trafilatura.extract(downloaded, output_format="json")
    title = json.loads(meta).get("title", "") if meta else ""
    return text, title


def fetch_with_playwright(url):
    """Text extraction via a headless browser using Playwright (for JS-required sites)"""
    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        print(f"  Blocked the request: {e}")
        return None, None
    try:
        from playwright.sync_api import sync_playwright
        import trafilatura
    except ImportError as e:
        print(f"  Can't fall back: {e}")
        return None, None
    print(f"  Fetching via headless browser...")
    try:
        cookies = _get_browser_cookies(url)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context()
            if cookies:
                ctx.add_cookies(cookies)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
        text = trafilatura.extract(html, include_links=False, include_images=False)
        if not text or len(text.strip()) < 100:
            return None, None
        meta = trafilatura.extract(html, output_format="json")
        title = json.loads(meta).get("title", "") if meta else ""
        return text, title
    except Exception as e:
        print(f"  Browser fetch error: {e}")
        return None, None


def _get_browser_cookies(url):
    """Fetch cookies from Chrome (via rookiepy; returns an empty list if unavailable)"""
    try:
        import rookiepy
    except ImportError:
        return []
    host = urlparse(url).hostname or ""
    domains = [f".{host}"]
    if host.startswith("www."):
        domains.append(f".{host[4:]}")
    # Handle x.com / twitter.com interchangeably
    if host == "x.com" or host.endswith(".x.com"):
        domains.append(".twitter.com")
    elif host == "twitter.com" or host.endswith(".twitter.com"):
        domains.append(".x.com")
    try:
        raw = rookiepy.chrome(domains)
    except Exception:
        return []
    return [{
        "name": c["name"], "value": c["value"], "domain": c["domain"],
        "path": c.get("path", "/"), "secure": c.get("secure", False),
        "httpOnly": c.get("httpOnly", False),
    } for c in raw]


def resolve_article_url(url):
    """If an X tweet contains a link to an Article, return the Article URL"""
    host = urlparse(url).hostname or ""
    if not _is_x_host(host):
        return url
    if "/article/" in url:
        return url
    try:
        import trafilatura
        html = trafilatura.fetch_url(url)
        if not html:
            return url
        import re as _re
        match = _re.search(r'https://t\.co/[A-Za-z0-9]+', html)
        if match:
            resp = safe_head(match.group())
            resolved = resp.url
            if "/article/" in resolved or "/i/article/" in resolved:
                print(f"  Found an Article URL: {resolved}")
                return resolved
    except Exception:
        # Also lands here if safe_head rejected a redirect to an internal IP with
        # UnsafeURLError. The original url is already validated by the caller
        # (fetch_article), so falling back to it is safe.
        pass
    return url


def fetch_article(url):
    """Extract text from a web page and save it to .transcripts/"""
    article_id = url_to_id(url)
    if is_processed(article_id):
        print(f"  Skipping (already processed)")
        return None

    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        print(f"  Blocked the request: {e}")
        return None

    print(f"  Fetching the article...")
    actual_url = resolve_article_url(url)
    text, title = fetch_with_trafilatura(actual_url)
    if not text:
        text, title = fetch_with_playwright(actual_url)
    if not text:
        print(f"  Couldn't extract any text")
        return None

    if not title:
        first_line = text.strip().split("\n")[0].strip().rstrip(".")
        title = first_line[:100] if len(first_line) > 10 else url
    article = {"id": article_id, "title": title, "url": url}
    path = save_transcript(article, text, source="web-article")
    print(f"  Done: {title[:60]}")
    return path


def _get_whisper_max_minutes():
    """Read WHISPER_MAX_MINUTES (default 20 minutes, 0 = unlimited). Falls back to the default on an invalid value."""
    raw = os.environ.get("WHISPER_MAX_MINUTES", "20")
    try:
        val = int(raw)
        if val < 0:
            raise ValueError
    except ValueError:
        print(f"  Warning: WHISPER_MAX_MINUTES has an invalid value ({raw!r}). Using the default of 20 minutes.")
        return 20
    return val


def transcribe_video(video):
    """Subtitles first; fall back to Whisper only when there are none"""
    # 1. Try YouTube subtitles (fast)
    print(f"  Checking for subtitles...")
    sub_text, source_lang = get_subtitles(video)
    if sub_text:
        source = "youtube-subtitles"
        if source_lang == "en":
            source = "youtube-subtitles-en"
            print(f"  Got them from English subtitles")
        else:
            print(f"  Got them from subtitles")
        return save_transcript(video, sub_text, source=source)

    # 2. Length limit check (Whisper is heavy; this replaces the old YouTube-only
    # proxy constraint with the real one)
    max_minutes = _get_whisper_max_minutes()
    duration = video.get("duration") or None
    if max_minutes > 0 and duration:
        if duration > max_minutes * 60:
            mins = duration // 60
            print(f"  Skipping Whisper — video is too long ({mins}min > {max_minutes}min limit). Checking the description...")
            desc_text = get_description(video)
            if desc_text:
                print(f"  Got it from the description")
                return save_transcript(video, desc_text, source="youtube-description")
            print(f"  Everything failed. Skipping.")
            return None
    elif not duration:
        print(f"  Duration unknown, running Whisper anyway")

    # 3. Transcribe with Whisper (slow)
    print(f"  No subtitles. Transcribing with Whisper...")
    audio_path = download_audio(video)
    if not audio_path:
        return None

    text = None
    try:
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=WHISPER_MODEL,
            language="ja",
            verbose=False
        )
        text = result["text"]
    except Exception as e:
        print(f"  Transcription error: {e}")

    audio_path.unlink(missing_ok=True)

    if text is not None and not is_hallucinated(text):
        return save_transcript(video, text)

    if text is not None:
        print(f"  Detected a hallucination. Checking the description...")
    else:
        print(f"  Checking the description...")
    desc_text = get_description(video)
    if desc_text:
        print(f"  Got it from the description")
        return save_transcript(video, desc_text, source="youtube-description")

    print(f"  Everything failed. Skipping.")
    return None


def transcribe_local_file(path):
    """Transcribe a local audio/video file with Whisper (bypasses yt-dlp)"""
    p = Path(path).expanduser().resolve()
    uri = f"file://{p}"
    video = {"id": url_to_id(uri), "title": p.name, "url": uri}

    if is_processed(video["id"]):
        print(f"  Skipping (already processed)")
        return None

    print(f"  Transcribing with Whisper...")
    text = None
    try:
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(p),
            path_or_hf_repo=WHISPER_MODEL,
            language="ja",
            verbose=False
        )
        text = result["text"]
    except Exception as e:
        print(f"  Transcription error: {e}")
        return None

    if text is None or is_hallucinated(text):
        print(f"  Transcription failed (the content couldn't be read).")
        return None

    return save_transcript(video, text, source="local-audio")


def is_processed(video_id):
    """Has this been transcribed, or already converted to a note (moved to done/)?"""
    return (TRANSCRIPT_DIR / f"{video_id}.txt").exists() or (DONE_DIR / f"{video_id}.txt").exists()


def check_mlx_whisper():
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        print("Error: mlx-whisper is not installed.")
        print("  ~/scripts/.venv/bin/pip install mlx-whisper")
        return False


def main():
    global OBSIDIAN_OUTPUT_DIR, TRANSCRIPT_DIR, DONE_DIR

    parser = argparse.ArgumentParser(description="Transcribe a video (any yt-dlp-supported site) / extract text from a web article")
    parser.add_argument("url", help="A video URL (yt-dlp-supported site), a playlist URL, or a web article URL")
    parser.add_argument("-o", "--output-dir", help="Output directory")
    parser.add_argument("--probe", action="store_true",
                         help="Only judge whether the URL can be treated as a video site (exit 0=video, exit 1=not a video)")
    parser.add_argument("--assume-video", action="store_true",
                         help="Trust that this was already probed and skip re-judging (the SSRF guard still runs)")
    args = parser.parse_args()
    url = args.url

    if args.probe:
        sys.exit(0 if detect_video_extractor(url) is not None else 1)

    if args.output_dir:
        OBSIDIAN_OUTPUT_DIR = Path(args.output_dir).expanduser()
        TRANSCRIPT_DIR = OBSIDIAN_OUTPUT_DIR / ".transcripts"
        DONE_DIR = TRANSCRIPT_DIR / "done"

    setup_dirs()

    if is_audio_file(url):
        print(f"Processing as a local audio/video file: {url}\n")
        if not check_mlx_whisper():
            sys.exit(1)
        result = transcribe_local_file(url)
        if not result:
            sys.exit(1)
        return

    # Decide if it's a video: a YouTube host settles it immediately, --assume-video
    # trusts that it was already probed, otherwise let yt-dlp decide (the generic
    # extractor doesn't count as a video)
    is_video = args.assume_video or is_youtube_url(url)
    if not is_video and detect_video_extractor(url) is not None:
        is_video = True

    if not is_video:
        print(f"Processing as a web article: {url}\n")
        result = fetch_article(url)
        if not result:
            sys.exit(1)
        return

    if not check_mlx_whisper():
        sys.exit(1)

    # For non-YouTube video paths, exit with code 2 when no video is found so the
    # caller can fall back to article processing (X/Instagram etc. claim a URL by
    # domain, so a text-only post can still get classified as a video)
    allow_no_video_exit = not is_youtube_url(url)
    videos = get_videos(url, allow_no_video_exit=allow_no_video_exit)
    print(f"\nFound {len(videos)} video(s).\n")

    done = 0
    failed = 0
    skipped = 0

    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video['title'][:60]}")

        if is_processed(video['id']):
            print(f"  Skipping (already processed)\n")
            skipped += 1
            continue

        result = transcribe_video(video)
        if result:
            done += 1
        else:
            failed += 1
        print()

    print(f"\n{'='*50}")
    print(f"Done! New: {done} / Skipped: {skipped} / Failed: {failed}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
