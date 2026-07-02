#!/usr/bin/env python3
"""
動画（yt-dlp対応サイト全般）の音声をダウンロードし、Whisperで文字起こしする。
Web記事のテキスト抽出にも対応。
結果はObsidian Vault内の .transcripts/ に保存される。
構造化ノートへの変換は obsidian-import スクリプト経由で Claude CLI が担当する。
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

# symlink 経由（~/scripts/）で起動されても url_guard を解決できるよう実体dirを通す
sys.path.insert(0, str(Path(__file__).resolve().parent))
from url_guard import UnsafeURLError, assert_safe_url, safe_head

os.environ["MALLOC_STACK_LOGGING"] = ""
warnings.filterwarnings("ignore", message=".*unauthenticated.*HF Hub.*")

# === 設定 ===
DEFAULT_OUTPUT_DIR = Path.home() / "Documents/Obsidian/Vault/YouTube"
OBSIDIAN_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
TRANSCRIPT_DIR = OBSIDIAN_OUTPUT_DIR / ".transcripts"
# 予測可能な /tmp 固定パスは共有マシンで symlink 先取りの余地があるため、
# プロセスごとのユーザー専用一時dir(mode 0700)を使う。終了時に後始末する。
AUDIO_TMP_DIR = Path(tempfile.mkdtemp(prefix="yt_obsidian_audio_"))
SUBS_TMP_DIR = Path(tempfile.mkdtemp(prefix="yt_subs_"))
atexit.register(shutil.rmtree, AUDIO_TMP_DIR, ignore_errors=True)
atexit.register(shutil.rmtree, SUBS_TMP_DIR, ignore_errors=True)
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
DONE_DIR = TRANSCRIPT_DIR / "done"

# Whisperで文字起こしするローカル音声/動画の拡張子
AUDIO_EXTS = {
    ".mp3", ".m4a", ".m4b", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".mp4", ".mov", ".m4v",
}


def is_youtube_url(url):
    """YouTube系ホストか（厳密なホスト一致。`youtube.com.evil.example` 等の
    部分一致による誤判定を避ける）"""
    host = urlparse(url).hostname or ""
    hosts = ("youtube.com", "youtu.be", "youtube-nocookie.com")
    return any(host == h or host.endswith("." + h) for h in hosts)


def detect_video_extractor(url):
    """yt-dlpがこのURLを動画として扱えるか判定する。

    扱えるextractor名（generic以外）を返せば動画扱い、None なら動画でない。
    generic extractor は「ページ内の埋め込み動画を無理やり探す」挙動なので、
    通常の記事ページを誤って動画扱いしないよう除外する。
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
    """ローカルの音声/動画ファイルか判定"""
    p = Path(path).expanduser()
    return p.is_file() and p.suffix.lower() in AUDIO_EXTS


def url_to_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:12]


# yt-dlp の出力（外部入力）由来の動画IDをパスに使う前に検証する。
# 不正なID（`../` 等）によるパストラバーサル書き込みを防ぐ。
# fullmatch + アンカーなしで、末尾改行（`abc\n`）も確実に弾く。
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _is_safe_id(vid):
    return bool(vid) and VIDEO_ID_RE.fullmatch(vid) is not None


def _is_x_host(host):
    """x.com / twitter.com とそのサブドメインか（部分一致による誤判定を避ける）"""
    return host in ("x.com", "twitter.com") or host.endswith((".x.com", ".twitter.com"))


def _hdr_val(v):
    """ヘッダ値の改行を除去し、本文との `---` 境界やキーの偽装注入を防ぐ"""
    return str(v).replace("\r", " ").replace("\n", " ")


def setup_dirs():
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _print_ytdlp_hint():
    """yt-dlpのバージョンを表示し、更新を促す（取得失敗の多くはyt-dlp側の追従遅れのため）"""
    version = None
    try:
        v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, timeout=10)
        if v.returncode == 0:
            version = v.stdout.strip()
    except Exception:
        pass
    if version:
        print(f"yt-dlp {version} を使用中。動画サイト側の仕様変更で取得できない場合、yt-dlp の更新で直ることが多い:")
    else:
        print("動画サイト側の仕様変更で取得できない場合、yt-dlp の更新で直ることが多い:")
    print("  brew upgrade yt-dlp")


def get_videos(url, allow_no_video_exit=False):
    """URLから動画情報を取得（再生リストでも単体でもOK）

    allow_no_video_exit=True の場合、yt-dlp呼び出し自体が失敗したときに
    「動画が見つからない」とみなし exit code 2 で終了する（呼び出し元が
    convert.py の記事処理へフォールバックできるように）。YouTube直URL等、
    動画であることが確定している経路では従来どおり exit code 1。
    """
    print("動画情報を取得中...")
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", "--", url],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        if allow_no_video_exit:
            print("動画が見つかりませんでした（タイムアウト）。記事として処理を試みます。")
            sys.exit(2)
        print("エラー: 動画情報の取得がタイムアウトしました")
        sys.exit(1)
    if result.returncode != 0:
        if allow_no_video_exit:
            print("動画が見つかりませんでした。記事として処理を試みます。")
            sys.exit(2)
        print(f"エラー: 動画情報の取得失敗\n{result.stderr}")
        _print_ytdlp_hint()
        sys.exit(1)

    data = json.loads(result.stdout)

    # 単体動画の場合
    if "entries" not in data:
        vid = data.get("id", "")
        if not _is_safe_id(vid):
            print(f"エラー: 不正な動画IDを検出: {vid!r}")
            sys.exit(1)
        return [{
            "id": vid,
            "title": data.get("title", "unknown"),
            "url": url,
            "duration": data.get("duration"),
        }]

    # 再生リストの場合
    videos = []
    for entry in data.get("entries", []):
        vid = entry.get("id", "")
        if not _is_safe_id(vid):
            print(f"  不正な動画IDをスキップ: {vid!r}")
            continue

        entry_url = entry.get("url")
        if entry_url:
            # entryのURLはyt-dlpのJSON出力＝外部データなので、使う前に検証する
            # （従来はYouTube形式を検証済みIDから組み立てていたため構造的に安全だった）
            try:
                assert_safe_url(entry_url)
            except UnsafeURLError as e:
                print(f"  安全でないURLのためスキップ: {e}")
                continue
        elif is_youtube_url(url):
            entry_url = f"https://www.youtube.com/watch?v={vid}"
        else:
            print(f"  entryのURLが取得できないためスキップ: {vid!r}")
            continue

        videos.append({
            "id": vid,
            "title": entry.get("title", "unknown"),
            "url": entry_url,
            "duration": entry.get("duration"),
        })
    return videos


def download_audio(video):
    """動画の音声をダウンロード"""
    output_path = AUDIO_TMP_DIR / f"{video['id']}.mp3"
    if output_path.exists():
        print(f"  音声キャッシュあり")
        return output_path

    print(f"  音声ダウンロード中...")
    result = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", "5",
         "-o", str(output_path), "--", video["url"]],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ダウンロード失敗: {result.stderr[:200]}")
        _print_ytdlp_hint()
        return None
    return output_path


def is_hallucinated(text, threshold=0.4):
    """Whisperハルシネーション検出（同一フレーズの繰り返し）"""
    if len(text) < 50:
        return True
    # 2〜20文字の繰り返しパターンを検出
    match = re.search(r"(.{2,20})\1{4,}", text)
    if match and len(match.group(0)) / len(text) > threshold:
        return True
    # 文字種の偏り（句読点・記号だらけ）
    content_chars = re.sub(r"[\s。、…・！？!?,.\d]", "", text)
    if len(content_chars) < len(text) * 0.2:
        return True
    return False


def get_subtitles(video):
    """YouTube字幕を取得（日本語手動 → 日本語自動 → 英語手動 → 英語自動の順で試行）"""
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
    """YouTube説明欄を取得"""
    result = subprocess.run(
        ["yt-dlp", "--print", "description", "--", video["url"]],
        capture_output=True, text=True
    )
    if result.returncode == 0 and len(result.stdout.strip()) >= 50:
        return result.stdout.strip()
    return None


def save_transcript(video, text, source="whisper"):
    """文字起こしテキストをファイルに保存"""
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
    """trafilaturaでテキスト抽出を試みる。失敗時はNone"""
    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        print(f"  アクセスをブロックしました: {e}")
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
    """Playwrightでヘッドレスブラウザ経由のテキスト抽出（JS必須サイト用）"""
    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        print(f"  アクセスをブロックしました: {e}")
        return None, None
    try:
        from playwright.sync_api import sync_playwright
        import trafilatura
    except ImportError as e:
        print(f"  フォールバック不可: {e}")
        return None, None
    print(f"  ヘッドレスブラウザで取得中...")
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
        print(f"  ブラウザ取得エラー: {e}")
        return None, None


def _get_browser_cookies(url):
    """ChromeからCookieを取得（rookiepy利用、なければ空リスト）"""
    try:
        import rookiepy
    except ImportError:
        return []
    host = urlparse(url).hostname or ""
    domains = [f".{host}"]
    if host.startswith("www."):
        domains.append(f".{host[4:]}")
    # x.com / twitter.com の相互対応
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
    """X のツイートが Article へのリンクを含む場合、Article URL を返す"""
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
                print(f"  Article URL検出: {resolved}")
                return resolved
    except Exception:
        # safe_head が内部IPへのリダイレクトを UnsafeURLError で弾いた場合もここに来る。
        # 元の url は呼び出し側(fetch_article)で検証済みのため、フォールバックは安全。
        pass
    return url


def fetch_article(url):
    """Webページからテキストを抽出して .transcripts/ に保存"""
    article_id = url_to_id(url)
    if is_processed(article_id):
        print(f"  スキップ（処理済み）")
        return None

    try:
        assert_safe_url(url)
    except UnsafeURLError as e:
        print(f"  アクセスをブロックしました: {e}")
        return None

    print(f"  記事を取得中...")
    actual_url = resolve_article_url(url)
    text, title = fetch_with_trafilatura(actual_url)
    if not text:
        text, title = fetch_with_playwright(actual_url)
    if not text:
        print(f"  テキストを抽出できませんでした")
        return None

    if not title:
        first_line = text.strip().split("\n")[0].strip().rstrip(".")
        title = first_line[:100] if len(first_line) > 10 else url
    article = {"id": article_id, "title": title, "url": url}
    path = save_transcript(article, text, source="web-article")
    print(f"  完了: {title[:60]}")
    return path


def _get_whisper_max_minutes():
    """WHISPER_MAX_MINUTES（デフォルト20分、0で無制限）を読む。不正値はデフォルトにフォールバック。"""
    raw = os.environ.get("WHISPER_MAX_MINUTES", "20")
    try:
        val = int(raw)
        if val < 0:
            raise ValueError
    except ValueError:
        print(f"  警告: WHISPER_MAX_MINUTES の値が不正です（{raw!r}）。デフォルトの20分を使用します。")
        return 20
    return val


def transcribe_video(video):
    """字幕優先で文字起こし（字幕なし時のみWhisperにフォールバック）"""
    # 1. YouTube字幕を試す（高速）
    print(f"  字幕を確認中...")
    sub_text, source_lang = get_subtitles(video)
    if sub_text:
        source = "youtube-subtitles"
        if source_lang == "en":
            source = "youtube-subtitles-en"
            print(f"  英語字幕から取得しました")
        else:
            print(f"  字幕から取得しました")
        return save_transcript(video, sub_text, source=source)

    # 2. 長さ上限チェック（Whisperが重いことへの対処。YouTube限定だった代理制約を本体化）
    max_minutes = _get_whisper_max_minutes()
    duration = video.get("duration") or None
    if max_minutes > 0 and duration:
        if duration > max_minutes * 60:
            mins = duration // 60
            print(f"  動画が長いためWhisperをスキップ（{mins}分 > 上限{max_minutes}分）。説明欄を確認中...")
            desc_text = get_description(video)
            if desc_text:
                print(f"  説明欄から取得しました")
                return save_transcript(video, desc_text, source="youtube-description")
            print(f"  すべて失敗。スキップします。")
            return None
    elif not duration:
        print(f"  長さ不明のためWhisperを実行します")

    # 3. Whisperで文字起こし（低速）
    print(f"  字幕なし。Whisperで文字起こし中...")
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
        print(f"  文字起こしエラー: {e}")

    audio_path.unlink(missing_ok=True)

    if text is not None and not is_hallucinated(text):
        return save_transcript(video, text)

    if text is not None:
        print(f"  ハルシネーション検出。説明欄を確認中...")
    else:
        print(f"  説明欄を確認中...")
    desc_text = get_description(video)
    if desc_text:
        print(f"  説明欄から取得しました")
        return save_transcript(video, desc_text, source="youtube-description")

    print(f"  すべて失敗。スキップします。")
    return None


def transcribe_local_file(path):
    """ローカルの音声/動画ファイルをWhisperで文字起こし（yt-dlpを経由しない）"""
    p = Path(path).expanduser().resolve()
    uri = f"file://{p}"
    video = {"id": url_to_id(uri), "title": p.name, "url": uri}

    if is_processed(video["id"]):
        print(f"  スキップ（処理済み）")
        return None

    print(f"  Whisperで文字起こし中...")
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
        print(f"  文字起こしエラー: {e}")
        return None

    if text is None or is_hallucinated(text):
        print(f"  文字起こしに失敗しました（内容が読み取れません）。")
        return None

    return save_transcript(video, text, source="local-audio")


def is_processed(video_id):
    """文字起こし済み or ノート変換済み（done/に移動済み）か判定"""
    return (TRANSCRIPT_DIR / f"{video_id}.txt").exists() or (DONE_DIR / f"{video_id}.txt").exists()


def check_mlx_whisper():
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        print("エラー: mlx-whisper がインストールされていません。")
        print("  ~/scripts/.venv/bin/pip install mlx-whisper")
        return False


def main():
    global OBSIDIAN_OUTPUT_DIR, TRANSCRIPT_DIR, DONE_DIR

    parser = argparse.ArgumentParser(description="動画（yt-dlp対応サイト全般）の文字起こし / Web記事のテキスト抽出")
    parser.add_argument("url", help="動画URL（yt-dlp対応サイト）、再生リストURL、またはWeb記事のURL")
    parser.add_argument("-o", "--output-dir", help="出力先ディレクトリ")
    parser.add_argument("--probe", action="store_true",
                         help="URLが動画サイトとして扱えるか判定するのみ（exit 0=動画, exit 1=非動画）")
    parser.add_argument("--assume-video", action="store_true",
                         help="probe済みとして扱い、動画判定を再実行しない（SSRFガードは実行する）")
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
        print(f"ローカル音声/動画として処理: {url}\n")
        if not check_mlx_whisper():
            sys.exit(1)
        result = transcribe_local_file(url)
        if not result:
            sys.exit(1)
        return

    # 動画判定: YouTube系ホストは即決、--assume-video はprobe済みとして信頼、
    # それ以外は yt-dlp に判定させる（generic extractorは動画扱いしない）
    is_video = args.assume_video or is_youtube_url(url)
    if not is_video and detect_video_extractor(url) is not None:
        is_video = True

    if not is_video:
        print(f"Web記事として処理: {url}\n")
        result = fetch_article(url)
        if not result:
            sys.exit(1)
        return

    if not check_mlx_whisper():
        sys.exit(1)

    # YouTube以外の動画経路は「動画が見つからない」場合に exit 2 で記事処理へ
    # フォールバックできるようにする（X/Instagram等はドメイン単位でextractorが
    # 請け負うため、テキストのみの投稿でも動画扱いになりうる）
    allow_no_video_exit = not is_youtube_url(url)
    videos = get_videos(url, allow_no_video_exit=allow_no_video_exit)
    print(f"\n{len(videos)}本の動画が見つかりました。\n")

    done = 0
    failed = 0
    skipped = 0

    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {video['title'][:60]}")

        if is_processed(video['id']):
            print(f"  スキップ（処理済み）\n")
            skipped += 1
            continue

        result = transcribe_video(video)
        if result:
            done += 1
        else:
            failed += 1
        print()

    print(f"\n{'='*50}")
    print(f"完了！ 新規: {done}本 / スキップ: {skipped}本 / 失敗: {failed}本")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
