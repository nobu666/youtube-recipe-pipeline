#!/usr/bin/env python3
"""
Convert a document (URL or local file) to Markdown with MarkItDown
and save it to .transcripts/.
Called from the obsidian-import script; joins the same conversion
flow that Claude uses for notes.

Supported sources:
  - URL: Google Docs/Slides, Slideshare, a PDF on the web, any web page
  - File: PDF, PPTX, DOCX, XLSX, images, audio, etc.
"""

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from markitdown import MarkItDown

# Add the real script dir so url_guard resolves even when invoked via a symlink (~/scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from url_guard import UnsafeURLError, assert_safe_url

DEFAULT_OUTPUT_DIR = Path.home() / "Documents/Obsidian/Vault/文字起こしメモ"

SUPPORTED_EXTENSIONS = {
    ".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls",
    ".html", ".htm", ".csv", ".tsv", ".json", ".xml",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp",
    ".mp3", ".wav", ".m4a",
    ".zip",
}


def source_id(source):
    """Generate a unique ID from the source (URL or file path)"""
    return hashlib.md5(source.encode()).hexdigest()[:12]


def _hdr_val(v):
    """Strip newlines from a header value, preventing injection of a fake `---` boundary or key."""
    return str(v).replace("\r", " ").replace("\n", " ")


def is_url(s):
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https")


def title_from_url(url):
    """Guess a title from a URL"""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path and path != "/":
        return Path(path).name or parsed.netloc
    return parsed.netloc


# Zip-bomb defense limits
ZIP_MAX_ENTRIES = 1000
ZIP_MAX_TOTAL_BYTES = 500 * 1024 * 1024   # Total uncompressed size limit: 500MB
ZIP_MAX_RATIO = 100                        # Per-entry uncompressed/compressed ratio limit


def check_zip_safe(path):
    """Check for a zip bomb. Returns a reason string if unsafe, None if safe."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > ZIP_MAX_ENTRIES:
                return f"Too many entries ({len(infos)} > {ZIP_MAX_ENTRIES})"
            total = 0
            for zi in infos:
                total += zi.file_size
                if total > ZIP_MAX_TOTAL_BYTES:
                    return f"Total uncompressed size is too large (> {ZIP_MAX_TOTAL_BYTES} bytes)"
                if zi.compress_size > 0 and zi.file_size / zi.compress_size > ZIP_MAX_RATIO:
                    return f"Suspicious compression ratio (possible zip bomb): {zi.filename}"
    except zipfile.BadZipFile:
        return "Invalid zip file"
    return None


def convert(source, output_dir):
    """Convert the source to Markdown with MarkItDown and save it to .transcripts/"""
    transcript_dir = output_dir / ".transcripts"
    done_dir = transcript_dir / "done"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)

    fid = source_id(source)
    transcript_path = transcript_dir / f"{fid}.txt"

    if transcript_path.exists() or (done_dir / f"{fid}.txt").exists():
        print(f"  Skipping (already processed)")
        return None

    if is_url(source):
        try:
            assert_safe_url(source)
        except UnsafeURLError as e:
            print(f"  Blocked the request: {e}")
            return False
    else:
        # Not just .zip — docx/pptx/xlsx etc. (OOXML) are ZIP archives underneath too,
        # so judge by "is the content a zip" rather than the extension, to catch a
        # zip bomb uniformly.
        import zipfile
        if Path(source).is_file() and zipfile.is_zipfile(source):
            reason = check_zip_safe(source)
            if reason:
                print(f"  Rejected a zip-based file: {reason}")
                return False

    md = MarkItDown()
    try:
        result = md.convert(source)
        text = result.text_content
    except Exception as e:
        print(f"  Conversion error: {e}")
        return False

    if not text or len(text.strip()) < 20:
        print(f"  Conversion failed: content is empty or too short")
        return False

    if is_url(source):
        title = title_from_url(source)
        header = f"title: {_hdr_val(title)}\nurl: {_hdr_val(source)}\nsource: markitdown-url"
    else:
        file_path = Path(source).resolve()
        header = f"title: {_hdr_val(file_path.name)}\nurl: file://{_hdr_val(str(file_path))}\nsource: markitdown-file"

    content = f"{header}\n---\n{text}"

    tmp_fd, tmp_path = tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(transcript_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    return transcript_path


def collect_inputs(args_list):
    """Collect URLs/files from the argument list"""
    inputs = []
    for arg in args_list:
        if is_url(arg):
            inputs.append(arg)
        else:
            p = Path(arg).expanduser()
            if p.is_dir():
                for ext in SUPPORTED_EXTENSIONS:
                    inputs.extend(str(f) for f in p.glob(f"*{ext}"))
            elif p.exists():
                inputs.append(str(p))
            else:
                print(f"Warning: not found: {arg}")
    return inputs


def main():
    parser = argparse.ArgumentParser(description="Convert documents/URLs to Markdown")
    parser.add_argument("inputs", nargs="+", help="URLs or file paths")
    parser.add_argument("-o", "--output-dir", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else DEFAULT_OUTPUT_DIR

    inputs = collect_inputs(args.inputs)
    if not inputs:
        print("Nothing to convert.")
        sys.exit(1)

    print(f"\nConverting {len(inputs)} item(s).\n")

    done = 0
    failed = 0
    skipped = 0

    for i, source in enumerate(inputs, 1):
        label = source if is_url(source) else Path(source).name
        print(f"[{i}/{len(inputs)}] {label}")

        if not is_url(source):
            ext = Path(source).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                print(f"  Skipping (unsupported format: {ext})")
                skipped += 1
                print()
                continue

        result = convert(source, output_dir)
        if result is None:
            skipped += 1
        elif result is False:
            failed += 1
        else:
            done += 1
            print(f"  → Done")
        print()

    print(f"\n{'='*50}")
    print(f"Done! New: {done} / Skipped: {skipped} / Failed: {failed}")


if __name__ == "__main__":
    main()
