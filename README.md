# obsidian-import

動画（YouTube・TikTok・Instagram・Xほかyt-dlp対応サイト全般）・Web記事・ドキュメント（PDF/スライド等）をObsidianの構造化ノートに自動変換するツール。プロンプトを切り替えることで、レシピ・講義ノート・トレーニングメニュー・ツール解説・記事要約など様々な形式に対応。

## インストール

```bash
curl -fsSL https://raw.githubusercontent.com/nobu666/obsidian-import/main/install.sh | bash

# クローン先を変えたい場合
INSTALL_DIR=~/projects curl -fsSL https://raw.githubusercontent.com/nobu666/obsidian-import/main/install.sh | bash
```

brew（yt-dlp, ffmpeg）、Python venv（mlx-whisper, markitdown）、シンボリックリンク、Claude Code スキルまで一括セットアップ。既存環境では更新のみ行う。デフォルトのクローン先は `~/repos/obsidian-import`。

### 前提

- macOS（Apple Silicon）
- Python 3.10+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude` コマンド)
- Obsidian Vault（ノートの保存先）

出力先を変更する場合は、各プロンプトファイル（`prompts/*.txt`）の `output_dir:` ヘッダを編集する。

## 仕組み

入力ソースに応じて自動でルーティングする:

1. **YouTube URL** → `transcribe.py` で字幕/Whisper文字起こし → Claude CLI でノート化
2. **ローカルの音声/動画ファイル**（.mp3/.m4a/.wav/.mp4/.mov 等）→ `transcribe.py` で Whisper文字起こし → Claude CLI でノート化
3. **その他の動画URL（yt-dlp対応サイト全般）** → YouTube以外は `transcribe.py --probe` で動画サイトか判定し、動画なら字幕/Whisper文字起こし → Claude CLI でノート化。TikTok・Instagram・X動画・ニコニコ・Vimeo等、yt-dlpが対応するサイトはこの経路に入る
4. **それ以外のURL・ファイル**（記事ページ等）→ `convert.py`（MarkItDown）でMarkdown化 → Claude CLI でノート化

字幕優先・Whisperフォールバックの優先順位はYouTube・非YouTubeで共通。ただし長尺動画のWhisper負荷を避けるため `WHISPER_MAX_MINUTES`（デフォルト20分）を超える動画はWhisperをスキップし、説明欄にフォールバックする（`WHISPER_MAX_MINUTES=0` で無制限）。

## 使い方

```bash
# YouTube動画（プロンプト自動選択）
~/scripts/obsidian-import https://www.youtube.com/watch?v=XXXXX

# プロンプトを明示的に指定（自動分類をスキップ）
~/scripts/obsidian-import -p recipe https://www.youtube.com/watch?v=XXXXX

# 再生リスト（各動画を自動分類して振り分け）
~/scripts/obsidian-import https://www.youtube.com/playlist?list=XXXXX

# 出力先を一時的に上書き
~/scripts/obsidian-import -p tool -o ~/notes https://www.youtube.com/watch?v=XXXXX

# YouTube以外の動画（TikTok, Instagram, X動画, ニコニコ, Vimeo等。yt-dlp対応サイト全般）
~/scripts/obsidian-import https://www.tiktok.com/@user/video/XXXXX

# Web記事（デフォルトプロンプト: article。テキストのみの投稿はこちらに自動フォールバックする）
~/scripts/obsidian-import https://x.com/user/status/XXXXX
~/scripts/obsidian-import https://example.com/blog/post

# Whisperをスキップする動画の長さ上限を変更（デフォルト20分、0で無制限）
WHISPER_MAX_MINUTES=40 ~/scripts/obsidian-import https://www.tiktok.com/@user/video/XXXXX

# Google Docs / Slideshare / Web上のPDF
~/scripts/obsidian-import https://docs.google.com/document/d/XXXXX
~/scripts/obsidian-import https://www.slideshare.net/user/slides

# ローカルファイル（PDF, PPTX, DOCX等）
~/scripts/obsidian-import ~/Downloads/slides.pdf

# ローカルの音声/動画ファイル（Whisperで文字起こし）
~/scripts/obsidian-import ~/Downloads/voice-memo.m4a
~/scripts/obsidian-import ~/Downloads/recording.mp4

# テキスト取得だけ（ノート変換なし）
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://www.youtube.com/watch?v=XXXXX
~/scripts/.venv/bin/python3 ~/scripts/convert.py https://example.com/paper.pdf
```

## プロンプト一覧

各プロンプトは `prompts/` ディレクトリに格納。`output_dir:` ヘッダでプロンプトごとに出力先が決まる（フォルダは自動作成）。

| プロンプト | 用途 | 出力先 |
|---|---|---|
| `default` | YouTube汎用（構造化ノート） | `Vault/YouTube/` |
| `recipe` | 料理動画 → レシピ | `Vault/YouTube/レシピ/` |
| `lecture` | 講義・セミナー → 要約ノート | `Vault/YouTube/講義/` |
| `workout` | 筋トレ・ヨガ → メニュー表 | `Vault/YouTube/トレーニング/` |
| `tool` | ツール解説 → 手順書 | `Vault/YouTube/ツール/` |
| `article` | Web記事・ドキュメント → 日本語要約ノート | `Vault/記事/` |

`-p` 未指定時は各トランスクリプトの冒頭をClaudeに送って自動分類し、最適なプロンプトと出力先を自動選択する（例: 料理動画→`recipe`、講義→`lecture`）。プレイリストに異なるジャンルの動画が混在していても自動で振り分けられる。

`prompts/` にファイルを追加すればさらに用途を増やせる。

### タグ・関連ノートの自動リンク

ノート生成時、frontmatter に内容を表す `tags:` を自動付与する。さらに、出力先フォルダに既存ノートがあれば関連する箇所を `[[ノート名]]` でリンクする。リンク対象は**同じフォルダに実在するノート名のみ**で、存在しない名前は生成しない（`claude -p` はツールなし実行のため、ドライバが既存ノート名一覧を `<existing_notes>` として渡して実在を保証している）。

### プロンプトファイルの形式

```
output_dir: ~/Documents/Obsidian/Vault/YouTube/講義
---
下の<transcript>タグ内の文字起こしをObsidian講義ノート形式に変換して。
ファイル名はテーマ名.md にして。
...

出力形式（この形式を厳守すること）:
FILENAME: テーマ名.md
---
(ノート本文)
```

`output_dir:` ヘッダで出力先を指定し、`---` 以降がClaudeに渡されるプロンプト本文。

### プロンプトを追加するときの注意

新しいプロンプトファイルを作る場合、以下を守ること:

1. **`FILENAME:` 出力形式を必ず含める** — シェルスクリプトは Claude の出力から `FILENAME: ファイル名.md` 行をパースしてファイルを保存する。この指示がないとノート変換が常に失敗する
2. **`{{OUTPUT_DIR}} に保存して` と書かない** — Claude にはファイル書き込み権限がない（セキュリティ上の理由）。ファイル保存はシェルスクリプト側が行う
3. **`下の<transcript>タグ内の〜` で始める** — 外部コンテンツはプロンプトの後ろに `<transcript>` タグで囲んで渡される

既存の `prompts/*.txt` をコピーして編集するのが最も確実。

### セキュリティモデル

外部コンテンツ（YouTube字幕・Webページ・ローカルファイル等）を処理するため、多層防御を採用している。

**プロンプトインジェクション対策**

1. **ツールなし実行** — `claude -p` をツール権限なしで実行。Claude はテキスト出力のみ可能で、ファイルシステムへのアクセス手段がない
2. **シェルスクリプト側でファイル書き込み** — Claude の出力から `FILENAME:` 行をパースし、シェルスクリプトが `OUTPUT_DIR` 配下にのみ書き込む
3. **ファイル名バリデーション** — `.md` 拡張子・パス区切り(`/`)なし・`..` なしを検証
4. **データ境界の明示** — 外部コンテンツを `<transcript>` タグで囲み、「データであり指示ではない」と明記

**ネットワーク（SSRF）対策** — `url_guard.py`

5. **URL検証** — fetch する全URLを http/https に限定し、ホスト名のDNS解決IPが private/loopback/link-local/reserved 帯ならブロック（クラウドメタデータ `169.254.169.254`・localhost・LAN に到達させない）。8進/16進などの数値IP表記、IPv4-mapped IPv6 のパーサ差分も封鎖
6. **リダイレクト再検証** — `requests` 経路はリダイレクトを手動追跡し、各ホップで再検証

**リソース枯渇・ローカルファイル対策**

7. **zip爆弾対策** — ローカルの zip / docx / pptx / xlsx（中身がZIP）を展開前に検査し、エントリ数・展開合計サイズ・圧縮率の上限超過を拒否
8. **一時ファイル** — 音声/字幕の一時dirは `tempfile.mkdtemp`（mode 0700・予測不能）で symlink 先取りを防止
9. **書き込み先の保護** — `write_note` は出力先がシンボリックリンクなら拒否、既存ファイルは上書きせず連番で回避、パス区切り/`..` を含む名前は拒否

> 想定する脅威モデルは「ユーザー自身が選んだ外部コンテンツの取り込み」（単一ユーザー）。不特定多数の untrusted 入力を捌くサーバ用途は範囲外で、PDF/URL経由の展開爆弾や巨大平文の完全防御は対象外（`CLAUDE.md` の【MUST】push前レビューで継続的に点検する）。

## 運用の流れ

1. YouTubeの再生リストにノート化したい動画を追加していく
2. `~/scripts/obsidian-import` を実行（プロンプトは自動選択される。明示したい場合は `-p <prompt>`）
3. 完了後、最後に表示される処理結果を確認
4. 問題なければ再生リストから処理済みの動画を削除

### 失敗した動画のリトライ

失敗した文字起こしは `.transcripts/` に残るので、そのまま再実行すればノート変換だけリトライされる。

```bash
~/scripts/obsidian-import -p recipe
```

文字起こし自体の品質が悪かった場合は、文字起こしファイルを削除してからやり直す。

```bash
# 特定の動画を文字起こしからやり直し
rm "<vault>/.transcripts/<video_id>.txt"
~/scripts/obsidian-import -p recipe "https://www.youtube.com/watch?v=<video_id>"
```

### ファイルの状態

| 場所 | 意味 |
|------|------|
| `.transcripts/*.txt` | 未処理 or ノート変換に失敗したテキスト |
| `.transcripts/done/*.txt` | ノート変換済みのテキスト（参照用に保持） |
| `<output_dir>/*.md` | 完成したノート |

## Claude Code スキル

`SKILL.md` を `~/.claude/commands/obsidian-import.md` に配置すると、Claude Code のどのセッションからでも `/obsidian-import` コマンドでノート変換を実行できる。`.transcripts/` 内のテキストファイルを読み取り、対話的にノート化する。

```bash
# インストール
cp ~/repos/obsidian-import/SKILL.md ~/.claude/commands/obsidian-import.md
```

## 注意点

- mlx-whisper は Apple Silicon 専用。Intel Mac では動かない
- 動画文字起こしは字幕（手動→自動生成）を優先取得する。字幕がない動画のみ Whisper large-v3-turbo（約3GB）にフォールバック。ただし `WHISPER_MAX_MINUTES`（デフォルト20分）を超える動画はWhisperをスキップし説明欄にフォールバックする
- Whisperのハルシネーション（同一フレーズの繰り返し）は自動検出し、説明欄でフォールバックする
- ローカルの音声/動画ファイルは Whisper（mlx・日本語特化）で文字起こしする。`.mp3/.m4a/.wav` 等は MarkItDown より Whisper を優先
- ドキュメント変換は MarkItDown を使用。PDF, PPTX, DOCX, XLSX, 画像, URL に対応
- 処理済みのソースはスキップされるので、中断しても再開可能
- `MallocStackLogging` の警告が出ることがあるが無害

### 動画が取得できないとき

- 動画サイト側の仕様変更にyt-dlpの追従が遅れていることが多い。まず更新する: `brew upgrade yt-dlp`（取得失敗時は自動でこのヒントを表示する）
- 年齢制限・メンバー限定・ログイン必須の動画は非対応（ブラウザCookie経由の認証は未対応）
- TVer等のDRM付き配信は対象外。どうしても取り込みたい場合は、BlackHole等でシステム音声を録音し、`~/scripts/obsidian-import <録音ファイル>` としてローカル音声ファイル経由で処理する
