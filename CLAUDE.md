# CLAUDE.md

動画（YouTube・TikTok・Instagram・X動画等 yt-dlp対応サイト全般）・Web記事・ドキュメント（PDF/スライド等）をObsidianの構造化ノートに自動変換するツール。

## プロジェクト構成

```
obsidian-import        # メインスクリプト（bashラッパー、claude -p を呼ぶ）
transcribe.py          # 動画文字起こし（yt-dlp対応サイト全般） / Web記事テキスト抽出
convert.py             # ドキュメント変換（MarkItDown: PDF, PPTX, DOCX, URL等）
prompts/               # プロンプトファイル（-p オプションで切り替え）
tests/                 # pytest テスト
install.sh             # curl一発セットアップ
SKILL.md               # Claude Code スキル定義
```

## インストール・シンボリックリンク

`install.sh` が以下を作成する:
- `~/scripts/obsidian-import` → このリポジトリの `obsidian-import`
- `~/scripts/transcribe.py` → このリポジトリの `transcribe.py`
- `~/scripts/convert.py` → このリポジトリの `convert.py`
- `~/scripts/.venv/` — Python venv（mlx-whisper, markitdown 等）

## テスト

```bash
~/scripts/.venv/bin/python3 -m pytest tests/ -v   # Python テスト
bash tests/test_obsidian_import.sh                 # シェルスクリプトのパース・バリデーションテスト
```

外部依存（yt-dlp, mlx-whisper, ファイルシステム）はすべてモック。mlx-whisper は Apple Silicon 専用のため CI 上ではインストールしない。

## セキュリティモデル

外部コンテンツ（URL・ファイル・字幕）を処理するため多層防御を採用。**詳細は README.md のセキュリティモデルを参照**。要点:

- **プロンプトインジェクション**: `claude -p` をツールなし実行／書き込みはシェル側で `OUTPUT_DIR` 配下のみ／ファイル名検証（`.md`・パス区切りなし・`..` なし）／外部コンテンツは `<transcript>` で境界明示
- **SSRF**: `url_guard.py`（http/https限定＋解決IPの内部帯ブロック＋数値IP/IPv4-mapped差分封鎖、リダイレクト各ホップ再検証）を全fetch経路に適用
- **リソース枯渇/ローカル**: zip爆弾検査（中身がZIPなら展開前に上限チェック）／一時dirは `mkdtemp`(0700)／`write_note` は symlink拒否・既存上書きせず連番・パストラバーサル拒否

## 【MUST】push 前のセキュリティレビュー

外部コンテンツ（URL・ファイル・動画字幕）を処理するツールのため、**コードを変更したら push する前に必ずセキュリティレビューを行う**こと。

- 変更差分（`git diff <base>..HEAD`）を対象に、Subagent または `/differential-review` スキルで観点別にレビューする
- 重点観点: **SSRF**（URL fetch 経路）、**コマンドインジェクション**（yt-dlp/subprocess）、**パストラバーサル**（書き込み先・ファイル名）、**プロンプトインジェクション**（`claude -p` への外部入力）、**リソース枯渇**（zip/アーカイブ爆弾・巨大入力）、**一時ファイルの先取り**（symlink/TOCTOU）
- **Critical/High が残っている間は push しない**。Low/Medium は受容するなら理由を明記する
- レビュー後、テスト（pytest + シェル）が全パスすることを確認してから push する

## 注意事項

- `mlx-whisper` を `openai-whisper` に差し替えないこと（Apple Silicon 最適化が前提）
- プロンプトファイルは `output_dir:` ヘッダ + `---` + 本文の形式
- プロンプト内で `FILENAME: ファイル名.md` 形式の出力を指示すること（シェルスクリプトがパースする）
- コメントとプロンプトは日本語で書くこと
