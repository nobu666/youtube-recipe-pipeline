import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import transcribe


@pytest.fixture(autouse=True)
def override_dirs(tmp_path, monkeypatch):
    transcript_dir = tmp_path / "_transcripts"
    transcript_dir.mkdir()
    done_dir = transcript_dir / "done"
    done_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    subs_dir = tmp_path / "subs"
    subs_dir.mkdir()

    monkeypatch.setattr(transcribe, "DEFAULT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(transcribe, "OBSIDIAN_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(transcribe, "TRANSCRIPT_DIR", transcript_dir)
    monkeypatch.setattr(transcribe, "DONE_DIR", done_dir)
    monkeypatch.setattr(transcribe, "AUDIO_TMP_DIR", audio_dir)
    monkeypatch.setattr(transcribe, "SUBS_TMP_DIR", subs_dir)


# --- get_videos ---


def _make_run_result(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class TestGetVideos:
    def test_single_video(self, monkeypatch):
        data = {"id": "abc123", "title": "テスト動画"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/watch?v=abc123")
        assert len(videos) == 1
        assert videos[0]["id"] == "abc123"
        assert videos[0]["url"] == "https://www.youtube.com/watch?v=abc123"

    def test_playlist(self, monkeypatch):
        data = {
            "entries": [
                {"id": "v1", "title": "動画1"},
                {"id": "v2", "title": "動画2"},
            ]
        }
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/playlist?list=PL123")
        assert len(videos) == 2
        assert videos[1]["url"] == "https://www.youtube.com/watch?v=v2"

    def test_yt_dlp_failure(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1, stderr="not found"),
        )
        with pytest.raises(SystemExit):
            transcribe.get_videos("https://invalid")


# --- is_processed ---


class TestIsProcessed:
    def test_not_processed(self):
        assert transcribe.is_processed("new_video") is False

    def test_transcript_exists(self):
        (transcribe.TRANSCRIPT_DIR / "vid1.txt").write_text("test")
        assert transcribe.is_processed("vid1") is True

    def test_done_exists(self):
        (transcribe.DONE_DIR / "vid2.txt").write_text("test")
        assert transcribe.is_processed("vid2") is True



# --- download_audio ---


class TestDownloadAudio:
    def test_cached(self):
        video = {"id": "cached1", "url": "https://example.com"}
        cached_path = transcribe.AUDIO_TMP_DIR / "cached1.mp3"
        cached_path.write_text("fake audio")
        result = transcribe.download_audio(video)
        assert result == cached_path

    def test_success(self, monkeypatch):
        video = {"id": "dl1", "url": "https://example.com"}
        expected_path = transcribe.AUDIO_TMP_DIR / "dl1.mp3"

        def fake_run(cmd, **kw):
            expected_path.write_text("audio data")
            return _make_run_result("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = transcribe.download_audio(video)
        assert result == expected_path

    def test_failure(self, monkeypatch):
        video = {"id": "fail1", "url": "https://example.com"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1, stderr="error"),
        )
        assert transcribe.download_audio(video) is None


# --- is_hallucinated ---


class TestIsHallucinated:
    def test_normal_text(self):
        text = "今日は鶏肉を使った料理を紹介します。材料は鶏もも肉二枚と塩コショウです。まず鶏肉を一口大に切って、塩コショウで下味をつけます。フライパンに油を熱して中火で焼いていきます。"
        assert transcribe.is_hallucinated(text) is False

    def test_repeated_phrase(self):
        assert transcribe.is_hallucinated("なんなん" * 50) is True

    def test_repeated_dots(self):
        assert transcribe.is_hallucinated("222" * 100) is True

    def test_too_short(self):
        assert transcribe.is_hallucinated("短い") is True

    def test_mostly_punctuation(self):
        text = "。、…・！？" * 30 + "あ"
        assert transcribe.is_hallucinated(text) is True


# --- transcribe_audio ---


class TestGetSubtitles:
    def test_found(self, monkeypatch, tmp_path):
        video = {"id": "sub1", "url": "https://example.com"}
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nこんにちは\n\n2\n00:00:03,000 --> 00:00:05,000\n今日は料理します\n"

        def fake_run(cmd, **kw):
            (transcribe.SUBS_TMP_DIR / f"{video['id']}.ja.srt").write_text(srt_content)
            return _make_run_result("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, lang = transcribe.get_subtitles(video)
        assert "こんにちは" in text
        assert "今日は料理します" in text
        assert lang is None

    def test_found_english(self, monkeypatch, tmp_path):
        video = {"id": "sub_en", "url": "https://example.com"}
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n2\n00:00:03,000 --> 00:00:05,000\nToday we cook\n"

        def fake_run(cmd, **kw):
            if "en" in cmd:
                (transcribe.SUBS_TMP_DIR / f"{video['id']}.en.srt").write_text(srt_content)
            return _make_run_result("")

        monkeypatch.setattr(subprocess, "run", fake_run)
        text, lang = transcribe.get_subtitles(video)
        assert "Hello" in text
        assert lang == "en"

    def test_not_found(self, monkeypatch):
        video = {"id": "nosub1", "url": "https://example.com"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(""),
        )
        text, lang = transcribe.get_subtitles(video)
        assert text is None
        assert lang is None


class TestGetDescription:
    def test_found(self, monkeypatch):
        video = {"id": "desc1", "url": "https://example.com"}
        desc = "材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1、塩小さじ1/3、かつお出汁大さじ4"
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(desc),
        )
        assert transcribe.get_description(video) == desc

    def test_too_short(self, monkeypatch):
        video = {"id": "desc2", "url": "https://example.com"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("短い"),
        )
        assert transcribe.get_description(video) is None


class TestSaveTranscript:
    def test_save_whisper(self):
        video = {"id": "sv1", "title": "テスト", "url": "https://example.com"}
        result = transcribe.save_transcript(video, "テキスト内容")
        assert result.exists()
        content = result.read_text()
        assert "title: テスト" in content
        assert "source:" not in content
        assert "テキスト内容" in content

    def test_save_with_source(self):
        video = {"id": "sv2", "title": "テスト", "url": "https://example.com"}
        result = transcribe.save_transcript(video, "説明欄", source="youtube-description")
        content = result.read_text()
        assert "source: youtube-description" in content


class TestIsAudioFile:
    def test_audio_extension(self, tmp_path):
        f = tmp_path / "voice.m4a"
        f.write_text("x")
        assert transcribe.is_audio_file(str(f)) is True

    def test_video_extension(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_text("x")
        assert transcribe.is_audio_file(str(f)) is True

    def test_uppercase_extension(self, tmp_path):
        f = tmp_path / "VOICE.MP3"
        f.write_text("x")
        assert transcribe.is_audio_file(str(f)) is True

    def test_non_audio_extension(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_text("x")
        assert transcribe.is_audio_file(str(f)) is False

    def test_missing_file(self, tmp_path):
        assert transcribe.is_audio_file(str(tmp_path / "nope.mp3")) is False

    def test_url_is_not_file(self):
        assert transcribe.is_audio_file("https://youtu.be/abc.mp3") is False


class TestTranscribeLocalFile:
    def _mock_mlx_whisper(self, monkeypatch, text):
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(return_value={"text": text})
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)
        return mock_module

    def test_local_audio_transcribed(self, monkeypatch, tmp_path):
        self._mock_mlx_whisper(monkeypatch, "これはローカル音声ファイルの文字起こし結果です。会議では新機能の方針について話し合い、来週までに試作を作ることになりました。担当は山田さんです。")
        audio = tmp_path / "会議メモ.m4a"
        audio.write_text("fake")

        result = transcribe.transcribe_local_file(str(audio))
        assert result is not None
        content = result.read_text()
        assert "source: local-audio" in content
        assert "title: 会議メモ.m4a" in content
        assert "url: file://" in content
        assert "ローカル音声ファイルの文字起こし" in content

    def test_id_is_hashed_not_stem(self, monkeypatch, tmp_path):
        """ファイル名そのものでなくハッシュIDで保存される（ファイル名安全性）"""
        self._mock_mlx_whisper(monkeypatch, "これはテスト用の文字起こし結果です。ファイル名ではなくハッシュからIDを生成することを確認するための十分な長さの本文を用意しています。")
        audio = tmp_path / "a b_c.mp3"
        audio.write_text("fake")
        result = transcribe.transcribe_local_file(str(audio))
        expected_id = transcribe.url_to_id(f"file://{audio.resolve()}")
        assert result.name == f"{expected_id}.txt"

    def test_skips_when_processed(self, monkeypatch, tmp_path):
        self._mock_mlx_whisper(monkeypatch, "一回目の文字起こし結果です。同じファイルを二回処理したときに二回目がスキップされることを確認するための十分な長さの本文を含めています。")
        audio = tmp_path / "dup.wav"
        audio.write_text("fake")
        first = transcribe.transcribe_local_file(str(audio))
        assert first is not None
        # 2回目は処理済みでスキップ（None）
        second = transcribe.transcribe_local_file(str(audio))
        assert second is None

    def test_hallucination_returns_none(self, monkeypatch, tmp_path):
        self._mock_mlx_whisper(monkeypatch, "ああ" * 50)
        audio = tmp_path / "noise.mp3"
        audio.write_text("fake")
        result = transcribe.transcribe_local_file(str(audio))
        assert result is None


class TestSafeId:
    def test_valid_youtube_id(self):
        assert transcribe._is_safe_id("dQw4w9WgXcQ") is True

    def test_underscore_dash(self):
        assert transcribe._is_safe_id("a_b-c123") is True

    def test_traversal_rejected(self):
        assert transcribe._is_safe_id("../../etc/passwd") is False

    def test_slash_rejected(self):
        assert transcribe._is_safe_id("a/b") is False

    def test_empty_rejected(self):
        assert transcribe._is_safe_id("") is False
        assert transcribe._is_safe_id(None) is False

    def test_trailing_newline_rejected(self):
        # 正規表現の `$` だと許してしまう末尾改行を fullmatch で弾く
        assert transcribe._is_safe_id("abc\n") is False
        assert transcribe._is_safe_id("abc\n../evil") is False


class TestIsXHost:
    def test_exact(self):
        assert transcribe._is_x_host("x.com") is True
        assert transcribe._is_x_host("twitter.com") is True

    def test_subdomain(self):
        assert transcribe._is_x_host("mobile.twitter.com") is True

    def test_lookalike_rejected(self):
        # 部分一致なら通ってしまう攻撃者ドメインを弾く
        assert transcribe._is_x_host("x.com.evil.io") is False
        assert transcribe._is_x_host("notx.com") is False


class TestGetVideosIdValidation:
    def test_single_malicious_id_exits(self, monkeypatch):
        data = {"id": "../../tmp/evil", "title": "x"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        with pytest.raises(SystemExit):
            transcribe.get_videos("https://www.youtube.com/watch?v=x")

    def test_playlist_skips_bad_id(self, monkeypatch):
        data = {"entries": [{"id": "../evil"}, {"id": "goodVideoID1"}]}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/playlist?list=x")
        assert [v["id"] for v in videos] == ["goodVideoID1"]


class TestGetVideosNoVideoExit:
    def test_allow_no_video_exit_exits_2(self, monkeypatch):
        """probe済みの非YouTube動画経路でyt-dlpが失敗したら exit 2（記事フォールバック用）"""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1, stderr="no video"),
        )
        with pytest.raises(SystemExit) as exc_info:
            transcribe.get_videos("https://example.com/text-only-post", allow_no_video_exit=True)
        assert exc_info.value.code == 2

    def test_default_still_exits_1(self, monkeypatch):
        """allow_no_video_exit未指定（YouTube等）は従来どおり exit 1"""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1, stderr="not found"),
        )
        with pytest.raises(SystemExit) as exc_info:
            transcribe.get_videos("https://www.youtube.com/watch?v=x")
        assert exc_info.value.code == 1


class TestGetVideosDuration:
    def test_duration_captured_single(self, monkeypatch):
        data = {"id": "abc123", "title": "テスト動画", "duration": 125}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/watch?v=abc123")
        assert videos[0]["duration"] == 125

    def test_duration_captured_playlist(self, monkeypatch):
        data = {"entries": [{"id": "v1", "title": "動画1", "duration": 300}]}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/playlist?list=PL123")
        assert videos[0]["duration"] == 300

    def test_duration_missing_is_none(self, monkeypatch):
        data = {"id": "abc123", "title": "テスト動画"}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/watch?v=abc123")
        assert videos[0]["duration"] is None


class TestGetVideosEntryUrl:
    """R4: 非YouTubeプレイリストのentry URL（yt-dlp由来の外部データ）の扱い"""

    def test_uses_entry_url_when_present(self, monkeypatch):
        data = {"entries": [
            {"id": "abc123XYZ01", "title": "動画", "url": "https://www.tiktok.com/@user/video/abc123XYZ01"}
        ]}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        monkeypatch.setattr(transcribe, "assert_safe_url", lambda url: None)
        videos = transcribe.get_videos("https://www.tiktok.com/@user")
        assert videos[0]["url"] == "https://www.tiktok.com/@user/video/abc123XYZ01"

    def test_unsafe_entry_url_is_skipped(self, monkeypatch):
        data = {"entries": [
            {"id": "evilentry1", "title": "evil", "url": "http://169.254.169.254/latest/meta-data"},
            {"id": "goodentry1", "title": "good", "url": "https://www.tiktok.com/@user/video/goodentry1"},
        ]}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )

        def fake_assert_safe_url(url):
            if "169.254.169.254" in url:
                raise transcribe.UnsafeURLError(f"blocked: {url}")

        monkeypatch.setattr(transcribe, "assert_safe_url", fake_assert_safe_url)
        videos = transcribe.get_videos("https://www.tiktok.com/@user")
        assert [v["id"] for v in videos] == ["goodentry1"]

    def test_youtube_falls_back_to_watch_url_when_entry_url_missing(self, monkeypatch):
        data = {"entries": [{"id": "v2", "title": "動画2"}]}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.youtube.com/playlist?list=PL123")
        assert videos[0]["url"] == "https://www.youtube.com/watch?v=v2"

    def test_non_youtube_missing_entry_url_is_skipped(self, monkeypatch):
        data = {"entries": [{"id": "novurl1", "title": "no-url"}]}
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(json.dumps(data)),
        )
        videos = transcribe.get_videos("https://www.tiktok.com/@user")
        assert videos == []


class TestIsYoutubeUrlStrict:
    def test_exact_hosts(self):
        assert transcribe.is_youtube_url("https://www.youtube.com/watch?v=x") is True
        assert transcribe.is_youtube_url("https://youtu.be/x") is True
        assert transcribe.is_youtube_url("https://youtube-nocookie.com/embed/x") is True

    def test_subdomain(self):
        assert transcribe.is_youtube_url("https://m.youtube.com/watch?v=x") is True

    def test_lookalike_rejected(self):
        # 部分一致なら通ってしまう攻撃者ドメインを弾く
        assert transcribe.is_youtube_url("https://youtube.com.evil.example/watch?v=x") is False
        assert transcribe.is_youtube_url("https://notyoutube.com/x") is False


class TestDetectVideoExtractor:
    def test_extractor_found(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("TikTok\n"),
        )
        assert transcribe.detect_video_extractor("https://www.tiktok.com/@user/video/1") == "TikTok"

    def test_generic_rejected(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("generic\n"),
        )
        assert transcribe.detect_video_extractor("https://example.com/article") is None

    def test_generic_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("Generic\n"),
        )
        assert transcribe.detect_video_extractor("https://example.com/article") is None

    def test_na_is_treated_as_video(self, monkeypatch):
        """flat-playlistでextractorフィールドが欠損しNAが返る場合は動画扱い"""
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("NA\n"),
        )
        assert transcribe.detect_video_extractor("https://example.com/x") == "NA"

    def test_ytdlp_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result("", returncode=1),
        )
        assert transcribe.detect_video_extractor("https://example.com/x") is None

    def test_empty_output_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: _make_run_result(""),
        )
        assert transcribe.detect_video_extractor("https://example.com/x") is None

    def test_unsafe_url_returns_none_without_calling_ytdlp(self, monkeypatch):
        def fail_if_called(*a, **kw):
            raise AssertionError("URLが安全でない場合、yt-dlpを呼んではいけない")

        monkeypatch.setattr(subprocess, "run", fail_if_called)
        monkeypatch.setattr(
            transcribe, "assert_safe_url",
            lambda url: (_ for _ in ()).throw(transcribe.UnsafeURLError("blocked")),
        )
        assert transcribe.detect_video_extractor("http://127.0.0.1/x") is None


class TestWhisperMaxMinutes:
    def test_default_is_20(self, monkeypatch):
        monkeypatch.delenv("WHISPER_MAX_MINUTES", raising=False)
        assert transcribe._get_whisper_max_minutes() == 20

    def test_zero_is_unlimited(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "0")
        assert transcribe._get_whisper_max_minutes() == 0

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "5")
        assert transcribe._get_whisper_max_minutes() == 5

    def test_invalid_value_falls_back_to_default(self, monkeypatch, capsys):
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "banana")
        assert transcribe._get_whisper_max_minutes() == 20
        assert "警告" in capsys.readouterr().out

    def test_negative_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "-5")
        assert transcribe._get_whisper_max_minutes() == 20


class TestYtdlpHint:
    def test_hint_printed_on_get_videos_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **kw: _make_run_result("2025.01.01") if "--version" in cmd
            else _make_run_result("", returncode=1, stderr="not found"),
        )
        with pytest.raises(SystemExit):
            transcribe.get_videos("https://www.youtube.com/watch?v=x")
        out = capsys.readouterr().out
        assert "brew upgrade yt-dlp" in out

    def test_hint_printed_on_download_audio_failure(self, monkeypatch, capsys):
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **kw: _make_run_result("2025.01.01") if "--version" in cmd
            else _make_run_result("", returncode=1, stderr="error"),
        )
        video = {"id": "fail2", "url": "https://example.com"}
        assert transcribe.download_audio(video) is None
        out = capsys.readouterr().out
        assert "brew upgrade yt-dlp" in out


class TestHeaderSanitization:
    def test_newline_in_title_does_not_inject_header(self):
        video = {"id": "h1", "title": "evil\n---\ninjected: pwned", "url": "https://e.com"}
        result = transcribe.save_transcript(video, "本文テキスト")
        content = result.read_text()
        header, body = content.split("\n---\n", 1)
        # title の改行はスペース化され、ヘッダに偽の境界/キー行が入らない
        assert "\ninjected: pwned" not in content
        assert body == "本文テキスト"
        # title 値は1行に収まっている
        assert header.split("\n")[0] == "title: evil --- injected: pwned"


class TestTranscribeVideo:
    def _mock_mlx_whisper(self, monkeypatch, text="今日は鶏肉を使った料理を紹介します。材料は鶏もも肉二枚と塩コショウです。まず鶏肉を一口大に切ってフライパンで焼いていきます。"):
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(return_value={"text": text})
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)
        return mock_module

    def _mock_download(self, monkeypatch):
        def fake_download(video):
            path = transcribe.AUDIO_TMP_DIR / f"{video['id']}.mp3"
            path.write_text("fake")
            return path
        monkeypatch.setattr(transcribe, "download_audio", fake_download)

    def test_subtitles_preferred(self, monkeypatch):
        """字幕があればWhisperを使わず字幕を使う"""
        video = {"id": "t_sub", "title": "テスト", "url": "https://example.com"}
        sub_text = "字幕からの内容です。今日はもずく酢を作ります。材料はもずく280グラムとお酢大さじ2です。"
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (sub_text, None))

        result = transcribe.transcribe_video(video)
        assert result is not None
        content = result.read_text()
        assert "source: youtube-subtitles" in content
        assert "字幕からの内容" in content

    def test_whisper_fallback_on_no_subtitles(self, monkeypatch):
        """字幕がない場合はWhisperにフォールバック"""
        self._mock_mlx_whisper(monkeypatch, text="材料は卵2個と砂糖大さじ1と醤油小さじ1です。まず卵をボウルに割り入れてよく溶きほぐします。フライパンに油を熱して中火で焼いていきます。表面が固まったら巻いていきましょう。")
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        video = {"id": "t1", "title": "卵焼き", "url": "https://example.com/t1"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        content = result.read_text()
        assert "title: 卵焼き" in content
        assert "材料は卵2個" in content

    def test_hallucination_fallback_to_description(self, monkeypatch):
        """Whisperがハルシネーションした場合は説明欄にフォールバック"""
        self._mock_mlx_whisper(monkeypatch, text="なんなん" * 50)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        desc = "説明欄の内容です。材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1"
        monkeypatch.setattr(transcribe, "get_description", lambda v: desc)
        video = {"id": "t_desc", "title": "test", "url": "https://example.com"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source: youtube-description" in result.read_text()

    def test_all_fallbacks_fail(self, monkeypatch):
        """字幕なし・Whisperハルシネーション・説明欄なし → None"""
        self._mock_mlx_whisper(monkeypatch, text="なんなん" * 50)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        monkeypatch.setattr(transcribe, "get_description", lambda v: None)
        video = {"id": "t_fail", "title": "test", "url": "https://example.com"}

        assert transcribe.transcribe_video(video) is None

    def test_whisper_error_fallback(self, monkeypatch):
        """Whisperエラー時は説明欄にフォールバック"""
        mock_module = types.ModuleType("mlx_whisper")
        mock_module.transcribe = MagicMock(side_effect=RuntimeError("GPU error"))
        monkeypatch.setitem(sys.modules, "mlx_whisper", mock_module)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        desc = "説明欄フォールバック。材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1"
        monkeypatch.setattr(transcribe, "get_description", lambda v: desc)
        video = {"id": "t3", "title": "test", "url": "https://example.com"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source: youtube-description" in result.read_text()

    def test_duration_over_limit_skips_whisper(self, monkeypatch):
        """長さ上限超過時はWhisperを呼ばず説明欄にフォールバックする"""
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "20")
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        desc = "長尺動画の説明欄です。材料：もずく280g、お酢大さじ2、黒糖粉大さじ1、醤油大さじ1"
        monkeypatch.setattr(transcribe, "get_description", lambda v: desc)

        called = {"download": False}

        def fake_download(video):
            called["download"] = True
            return None

        monkeypatch.setattr(transcribe, "download_audio", fake_download)
        video = {"id": "long1", "title": "長尺", "url": "https://example.com", "duration": 30 * 60}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source: youtube-description" in result.read_text()
        assert called["download"] is False, "Whisperの音声ダウンロードが呼ばれてはいけない"

    def test_duration_unlimited_when_zero(self, monkeypatch):
        """WHISPER_MAX_MINUTES=0なら長尺でもWhisperを実行する"""
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "0")
        self._mock_mlx_whisper(monkeypatch)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        video = {"id": "long2", "title": "長尺2", "url": "https://example.com", "duration": 999 * 60}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source:" not in result.read_text()

    def test_duration_unknown_runs_whisper(self, monkeypatch):
        """durationが不明（キーなし）ならfail-openでWhisperを実行する"""
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "20")
        self._mock_mlx_whisper(monkeypatch)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        video = {"id": "unknown1", "title": "不明", "url": "https://example.com"}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source:" not in result.read_text()

    def test_duration_within_limit_runs_whisper(self, monkeypatch):
        """上限以内の長さならWhisperを普通に実行する"""
        monkeypatch.setenv("WHISPER_MAX_MINUTES", "20")
        self._mock_mlx_whisper(monkeypatch)
        self._mock_download(monkeypatch)
        monkeypatch.setattr(transcribe, "get_subtitles", lambda v: (None, None))
        video = {"id": "short1", "title": "短尺", "url": "https://example.com", "duration": 5 * 60}

        result = transcribe.transcribe_video(video)
        assert result is not None
        assert "source:" not in result.read_text()


# --- check_mlx_whisper ---


class TestCheckMlxWhisper:
    def test_available(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "mlx_whisper", types.ModuleType("mlx_whisper"))
        assert transcribe.check_mlx_whisper() is True

    def test_missing(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "mlx_whisper", raising=False)
        with patch.dict(sys.modules, {"mlx_whisper": None}):
            # importing a module mapped to None in sys.modules raises ImportError
            assert transcribe.check_mlx_whisper() is False


# --- main ---


class TestMain:
    def _setup_mocks(self, monkeypatch, videos, transcribe_results=None):
        monkeypatch.setattr(transcribe, "check_mlx_whisper", lambda: True)
        monkeypatch.setattr(transcribe, "get_videos", lambda url, **kw: videos)
        if transcribe_results is None:
            transcribe_results = [True] * len(videos)

        results_iter = iter(transcribe_results)
        def fake_transcribe(video):
            if next(results_iter):
                path = transcribe.TRANSCRIPT_DIR / f"{video['id']}.txt"
                path.write_text("content")
                return path
            return None
        monkeypatch.setattr(transcribe, "transcribe_video", fake_transcribe)

    def test_all_success(self, monkeypatch):
        videos = [{"id": "v1", "title": "t1", "url": "u1"}]
        self._setup_mocks(monkeypatch, videos)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        # main() should return normally on full success
        transcribe.main()

    def test_partial_failure_exits_1(self, monkeypatch):
        videos = [
            {"id": "v1", "title": "t1", "url": "u1"},
            {"id": "v2", "title": "t2", "url": "u2"},
        ]
        self._setup_mocks(monkeypatch, videos, transcribe_results=[True, False])
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1

    def test_skips_processed(self, monkeypatch):
        videos = [{"id": "already", "title": "t", "url": "u"}]
        (transcribe.TRANSCRIPT_DIR / "already.txt").write_text("done")
        self._setup_mocks(monkeypatch, videos)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        transcribe.main()

    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["transcribe.py"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 2

    def test_missing_mlx_whisper_exits(self, monkeypatch):
        monkeypatch.setattr(transcribe, "check_mlx_whisper", lambda: False)
        monkeypatch.setattr(sys, "argv", ["transcribe.py", "https://www.youtube.com/watch?v=test"])
        with pytest.raises(SystemExit) as exc_info:
            transcribe.main()
        assert exc_info.value.code == 1
