---
name: obsidian-import
description: YouTube動画・ローカル音声/動画・Web記事・ドキュメント（PDF/スライド等）をObsidianノートに自動変換するスキル。「レシピ化して」「文字起こしをレシピにして」「.transcriptsを処理して」「YouTubeのレシピを整理して」「この記事をノートにして」「X/Twitterの記事を要約して」「PDFを要約して」「スライドをノートにして」「録音を文字起こしして」「音声メモをノート化して」などで起動する。文字起こし済みテキストがない場合はローカル実行スクリプト（yt-dlp + mlx-whisper + markitdown）のセットアップもガイドする。YouTube、レシピ、文字起こし、Obsidian、料理動画、Web記事、X Article、ブログ記事、PDF、スライド、音声メモ、録音、要約、ノート化などのキーワードが出たら積極的にこのスキルの利用を検討すること。
---

# Obsidian Import

YouTube動画の文字起こし・Web記事のテキスト・ドキュメント（PDF/スライド等）を読み取り、Obsidian Vaultの構造化ノートに変換して保存するスキル。

## 全体の流れ

1. **テキスト取得**（Macローカルで実行）:
   - 動画URL（YouTube、TikTok、Instagram、X動画等 yt-dlp対応サイト全般）→ `~/scripts/transcribe.py` で字幕/音声を取得（mlx-whisper）。YouTube以外は自動判定（動画でなければ記事処理にフォールバック）
   - ローカルの音声/動画ファイル（.mp3/.m4a/.wav/.mp4/.mov 等）→ `~/scripts/transcribe.py` で Whisper 文字起こし
   - それ以外のURL・ファイル → `~/scripts/convert.py` で MarkItDown によりMarkdown化
   - 結果は `.transcripts/` フォルダに保存される
2. **ノート化**: `.transcripts/` 内のテキストファイルを読み、プロンプトに応じた形式に変換してObsidianフォルダに保存。

ノート化は以下のどちらでも実行できる:
- **CLIから**: `~/scripts/obsidian-import` を実行（内部で `claude -p` を1件ずつ呼び出す）
- **このスキル**: Coworkや対話セッション内で直接実行

## パス情報

```
リポジトリ:  ~/repos/obsidian-import/
スクリプト:  ~/scripts/obsidian-import    → シンボリックリンク
             ~/scripts/transcribe.py     → シンボリックリンク
             ~/scripts/convert.py        → シンボリックリンク
venv:        ~/scripts/.venv/
Vault:       ~/Documents/Obsidian/Vault/YouTube/レシピ/
文字起こし:  <vault>/.transcripts/*.txt     （未処理）
処理済み:    <vault>/.transcripts/done/     （レシピ変換済み）
```

## セットアップガイド

ユーザーがまだセットアップしていない場合、以下を案内する:

```bash
brew install yt-dlp ffmpeg python@3.12

# venv 作成と依存インストール
python3.12 -m venv ~/scripts/.venv
~/scripts/.venv/bin/pip install mlx-whisper "markitdown[all]"

# リポジトリのクローンとシンボリックリンク
git clone https://github.com/nobu666/obsidian-import.git ~/repos/obsidian-import
ln -s ~/repos/obsidian-import/obsidian-import ~/scripts/obsidian-import
ln -s ~/repos/obsidian-import/transcribe.py ~/scripts/transcribe.py
ln -s ~/repos/obsidian-import/convert.py ~/scripts/convert.py
chmod +x ~/scripts/obsidian-import
```

実行:

```bash
# 再生リストをまとめて処理
~/scripts/obsidian-import https://www.youtube.com/playlist?list=XXXXX

# 単体の動画
~/scripts/obsidian-import https://www.youtube.com/watch?v=XXXXX

# Web記事をノート化
~/scripts/obsidian-import https://x.com/user/status/XXXXX

# ドキュメント（PDF/スライド/Google Docs等）
~/scripts/obsidian-import https://docs.google.com/document/d/XXXXX
~/scripts/obsidian-import ~/Downloads/slides.pdf

# ローカルの音声/動画ファイル（Whisperで文字起こし）
~/scripts/obsidian-import ~/Downloads/voice-memo.m4a
~/scripts/obsidian-import ~/Downloads/recording.mp4

# テキスト取得だけ（ノート変換なし）
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://www.youtube.com/watch?v=XXXXX
~/scripts/.venv/bin/python3 ~/scripts/convert.py https://example.com/paper.pdf
```

## ノート化の手順

### 1. テキストファイルを読む

出力先フォルダ内の `.transcripts/` ディレクトリにある `.txt` ファイルを読む。`done/` サブディレクトリ内のファイルは処理済みなので無視する。各ファイルの形式:

```
title: 動画タイトル
video_id: YouTubeのID
url: https://www.youtube.com/watch?v=...
---
（文字起こし本文）
```

### 2. レシピを抽出する

文字起こしから以下の情報を抽出する:

- **料理名**: 動画タイトルの【】＜＞「」内や、文字起こし本文から判断。簡潔に。
- **材料**: 名前と分量。分量が不明なら「適量」。
- **手順**: 番号付きの簡潔なステップ。

動画内で複数レシピが紹介されている場合は、メインのレシピを1ファイルとして作成し、アレンジやサブレシピは `##` セクションで同じファイル内に含める。

文字起こしの品質が低い場合（Whisperのハルシネーション等）でも、読み取れる範囲で最善のレシピを作る。内容が全く読み取れない場合だけスキップし、その旨を報告する。質問や確認はせず、自分で判断して進めること。

### 3. 出力フォーマット

既存のレシピノートに厳密に合わせる。以下がテンプレート:

```markdown
---
created: YYYY-MM-DD HH:MM
updated: YYYY-MM-DD HH:MM
source: https://www.youtube.com/watch?v=VIDEO_ID
---

# 料理名

* 材料1 分量
* 材料2 分量
* 材料3 分量

1. 手順1
2. 手順2
3. 手順3
```

重要なポイント:
- frontmatterの `source` には動画URLを入れる
- `created` / `updated` は現在日時
- 材料は `* ` で始まる箇条書き（サブグループがあればインデント）
- 手順は `1. ` で始まる番号付きリスト
- 余計な説明・感想・宣伝・チャンネル登録の案内は一切含めない
- 簡潔に。文は短く。

### 4. ファイル名の決定

料理名をそのままファイル名にする。例:
- `トマトと卵の炒め物.md`
- `かぼちゃのそぼろ煮.md`
- `自家製たくあん.md`

動画タイトルではなく、抽出した料理名を使うこと。

### 5. 保存

Obsidianレシピフォルダに直接保存する:

```
~/Documents/Obsidian/Vault/YouTube/レシピ/料理名.md
```

### 6. 処理済みファイルの扱い

ノート化が完了したテキストファイルは `.transcripts/done/` に移動する。これにより次回実行時に重複処理を防ぐ。

## 既存レシピの例

参考として、ユーザーのVaultにある実際のレシピ:

```markdown
---
created: 2021-10-15 10:02
updated: 2021-10-15 10:02
source: google-keep
---

# ガリバタチキン

* もも肉 2枚
* にんにく 1-2片
* 酒 大さじ2
* みりん 大さじ2
* 醤油 大さじ2
* 砂糖 小さじ2/3
* バター 20g

1. 肉は一口大に切り軽く塩コショウ
2. 油少量を温め、皮目から炒める
3. にんにくすりおろし、調味料、うま味調味料3振りを入れて煮詰める
4. バターを溶かす
```

```markdown
---
created: 2021-10-15 10:20
updated: 2021-10-15 10:20
source: google-keep
---

# 麻婆豆腐

* ザージャン
    * 粗挽き豚ひき肉120g
    * 紹興酒・醤油 15cc
    * 甜麺醤 10g
* 本体
    * 豆腐 1丁
    * にんにく・生姜 大さじ山盛り2
    * 刻み豆鼓 大さじ山盛り1
    * 唐辛子適当
    * 豆板醤 小さじ2
    * 水 300cc
    * 鶏ガラスープのもと 小さじ2
    * 紹興酒・醤油 20cc
* 仕上げ
    * 刻みネギ
    * にんにくの芽 1本
    * 水溶き片栗粉 大さじ1+1
    * ホアジャオ
    * ラー油

1. 鍋を熱して油を入れ、ひき肉を炒める
2. 火が通ったら紹興酒と醤油を入れ、水分が飛ぶまで炒め、甜麺醤を混ぜる
3. 鍋を一度掃除し、油でにんにく・生姜・豆板醤・豆鼓・唐辛子を弱火で炒めて香りを出す
4. 油に色がついてきたら強火にしてザージャンを加えて混ぜ炒める
5. スープ・醤油・紹興酒を入れて混ぜる
6. 豆腐は適当な大きさに切って一度別鍋で茹でてから加える
7. 豆腐を入れたら2-3分煮込む
8. にんにくの芽をネギをいれ、火を落として水溶き片栗粉を少しずつ入れて絡める
9. いい固さになったら強火にしてラー油を鍋肌にいれ、掬うように混ぜる
10. バチバチに熱して完成
```

このように、材料のサブグループ化やシンプルな手順記述のスタイルを踏襲すること。
