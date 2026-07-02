import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import convert


@pytest.fixture(autouse=True)
def override_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "DEFAULT_OUTPUT_DIR", tmp_path)


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch):
    # Stub the SSRF guard's DNS resolution so tests are isolated from the real network (treated as a public IP)
    import socket
    monkeypatch.setattr(
        "url_guard.socket.getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))],
    )


# --- source_id ---


class TestSourceId:
    def test_deterministic(self):
        assert convert.source_id("https://example.com") == convert.source_id("https://example.com")

    def test_different_for_different_sources(self):
        assert convert.source_id("https://a.com") != convert.source_id("https://b.com")

    def test_length(self):
        assert len(convert.source_id("test")) == 12


# --- is_url ---


class TestIsUrl:
    def test_http(self):
        assert convert.is_url("https://example.com/doc.pdf") is True

    def test_http_no_s(self):
        assert convert.is_url("http://example.com") is True

    def test_file_path(self):
        assert convert.is_url("/tmp/test.pdf") is False

    def test_relative_path(self):
        assert convert.is_url("slides.pptx") is False


# --- title_from_url ---


class TestTitleFromUrl:
    def test_with_path(self):
        assert convert.title_from_url("https://example.com/paper.pdf") == "paper.pdf"

    def test_with_nested_path(self):
        assert convert.title_from_url("https://slideshare.net/user/my-slides") == "my-slides"

    def test_root_only(self):
        assert convert.title_from_url("https://example.com/") == "example.com"

    def test_no_path(self):
        assert convert.title_from_url("https://example.com") == "example.com"


# --- convert ---


class TestConvert:
    def _mock_markitdown(self, monkeypatch, text="This is a test Markdown conversion result. It needs to be long enough."):
        mock_md = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = text
        mock_md.convert.return_value = mock_result
        monkeypatch.setattr(convert, "MarkItDown", lambda: mock_md)
        return mock_md

    def test_url_success(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        result = convert.convert("https://example.com/doc.pdf", tmp_path)
        assert result is not None and result is not False
        content = result.read_text()
        assert "url: https://example.com/doc.pdf" in content
        assert "source: markitdown-url" in content

    def test_file_success(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        test_file = tmp_path / "test.pdf"
        test_file.write_text("dummy")
        result = convert.convert(str(test_file), tmp_path)
        assert result is not None and result is not False
        content = result.read_text()
        assert "title: test.pdf" in content
        assert "source: markitdown-file" in content

    def test_skip_processed(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        source = "https://example.com/doc.pdf"
        fid = convert.source_id(source)
        transcript_dir = tmp_path / ".transcripts"
        transcript_dir.mkdir()
        (transcript_dir / "done").mkdir()
        (transcript_dir / f"{fid}.txt").write_text("already done")
        assert convert.convert(source, tmp_path) is None

    def test_skip_done(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch)
        source = "https://example.com/doc.pdf"
        fid = convert.source_id(source)
        transcript_dir = tmp_path / ".transcripts"
        transcript_dir.mkdir()
        done_dir = transcript_dir / "done"
        done_dir.mkdir()
        (done_dir / f"{fid}.txt").write_text("already done")
        assert convert.convert(source, tmp_path) is None

    def test_empty_content(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch, text="")
        assert convert.convert("https://example.com/empty.pdf", tmp_path) is False

    def test_short_content(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch, text="short")
        assert convert.convert("https://example.com/short.pdf", tmp_path) is False

    def test_none_content(self, monkeypatch, tmp_path):
        self._mock_markitdown(monkeypatch, text=None)
        assert convert.convert("https://example.com/null.pdf", tmp_path) is False

    def test_markitdown_exception(self, monkeypatch, tmp_path):
        mock_md = MagicMock()
        mock_md.convert.side_effect = RuntimeError("parse error")
        monkeypatch.setattr(convert, "MarkItDown", lambda: mock_md)
        assert convert.convert("https://example.com/bad.pdf", tmp_path) is False


# --- collect_inputs ---


class TestCollectInputs:
    def test_url(self):
        inputs = convert.collect_inputs(["https://example.com/doc.pdf"])
        assert inputs == ["https://example.com/doc.pdf"]

    def test_file(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_text("dummy")
        inputs = convert.collect_inputs([str(f)])
        assert str(f) in inputs[0]

    def test_directory(self, tmp_path):
        (tmp_path / "a.pdf").write_text("dummy")
        (tmp_path / "b.pptx").write_text("dummy")
        (tmp_path / "c.txt").write_text("dummy")
        inputs = convert.collect_inputs([str(tmp_path)])
        assert len(inputs) == 2

    def test_missing_file(self):
        inputs = convert.collect_inputs(["/nonexistent/file.pdf"])
        assert inputs == []

    def test_mixed(self, tmp_path):
        f = tmp_path / "local.pdf"
        f.write_text("dummy")
        inputs = convert.collect_inputs(["https://example.com", str(f)])
        assert len(inputs) == 2


# --- main ---


class TestMain:
    def test_no_args_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["convert.py"])
        with pytest.raises(SystemExit) as exc_info:
            convert.main()
        assert exc_info.value.code == 2

    def test_no_valid_inputs_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["convert.py", "/nonexistent/file.pdf"])
        with pytest.raises(SystemExit) as exc_info:
            convert.main()
        assert exc_info.value.code == 1

    def test_success(self, monkeypatch, tmp_path):
        mock_md = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = "This is the converted Markdown text. It needs to be long enough, so here's a bit more."
        mock_md.convert.return_value = mock_result
        monkeypatch.setattr(convert, "MarkItDown", lambda: mock_md)
        monkeypatch.setattr(sys, "argv", ["convert.py", "-o", str(tmp_path), "https://example.com/doc.pdf"])
        convert.main()
        transcript_dir = tmp_path / ".transcripts"
        assert len(list(transcript_dir.glob("*.txt"))) == 1


class TestZipBomb:
    def test_rejects_high_ratio_bomb(self, tmp_path):
        import zipfile
        bomb = tmp_path / "bomb.zip"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.txt", b"\0" * (5 * 1024 * 1024))  # 5MB of zeros -> a high compression ratio
        assert convert.check_zip_safe(str(bomb)) is not None

    def test_rejects_too_many_entries(self, tmp_path):
        import zipfile
        many = tmp_path / "many.zip"
        with zipfile.ZipFile(many, "w") as zf:
            for i in range(convert.ZIP_MAX_ENTRIES + 5):
                zf.writestr(f"f{i}.txt", "x")
        assert convert.check_zip_safe(str(many)) is not None

    def test_allows_normal_zip(self, tmp_path):
        import zipfile
        ok = tmp_path / "ok.zip"
        with zipfile.ZipFile(ok, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("a.txt", "hello world, this is normal short content")
        assert convert.check_zip_safe(str(ok)) is None

    def test_convert_rejects_bomb_file(self, tmp_path, monkeypatch):
        import zipfile
        bomb = tmp_path / "bomb.zip"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.txt", b"\0" * (5 * 1024 * 1024))
        # Reject before ever touching MarkItDown (fail the test if it's called)
        monkeypatch.setattr(convert, "MarkItDown", lambda: (_ for _ in ()).throw(AssertionError("a zip should be rejected before extraction")))
        assert convert.convert(str(bomb), tmp_path) is False

    def test_convert_rejects_ooxml_bomb_by_content(self, tmp_path, monkeypatch):
        # Reject a zip bomb even with a .docx extension (OOXML is a ZIP container)
        import zipfile
        bomb = tmp_path / "evil.docx"
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", b"\0" * (5 * 1024 * 1024))
        monkeypatch.setattr(convert, "MarkItDown", lambda: (_ for _ in ()).throw(AssertionError("should be rejected before extraction")))
        assert convert.convert(str(bomb), tmp_path) is False
