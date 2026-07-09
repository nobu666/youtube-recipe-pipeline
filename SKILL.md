---
name: obsidian-import
description: Converts a YouTube video, local audio/video, a web article, or a document (PDF/slides, etc.) into an Obsidian note. Triggers on phrases like "turn this into a recipe," "process .transcripts," "summarize this PDF/article," "transcribe this recording," or "make a note from this voice memo." If there's no transcribed text yet, it also guides setup of the local execution scripts (yt-dlp + mlx-whisper + markitdown). / YouTube動画・ローカル音声/動画・Web記事・ドキュメント（PDF/スライド等）をObsidianノートに自動変換するスキル。「レシピ化して」「文字起こしをレシピにして」「.transcriptsを処理して」「この記事をノートにして」「PDFを要約して」「録音を文字起こしして」「音声メモをノート化して」などで起動する。文字起こし済みテキストがない場合はローカル実行スクリプトのセットアップもガイドする。
---

# Obsidian Import

A skill that reads a YouTube video's transcript, a web article's text, or a document (PDF/slides, etc.), converts it into a structured Obsidian note, and saves it to the Vault.

## Overall flow

1. **Text extraction** (runs locally on the Mac):
   - A video URL (YouTube, TikTok, Instagram, X video, or any other yt-dlp-supported site) -> `~/scripts/transcribe.py` fetches subtitles/audio (mlx-whisper). For non-YouTube URLs it auto-detects whether it's actually a video (falling back to article processing if not)
   - A local audio/video file (.mp3/.m4a/.wav/.mp4/.mov, etc.) -> `~/scripts/transcribe.py` transcribes it with Whisper
   - Any other URL/file -> `~/scripts/convert.py` converts it to Markdown with MarkItDown
   - The result is saved to the `.transcripts/` folder
2. **Note conversion**: read the text files in `.transcripts/`, convert each into the format the prompt calls for, and save it to the Obsidian folder.

Note conversion can be run either way:
- **From the CLI**: run `~/scripts/obsidian-import` (internally calls `claude -p` once per item)
- **This skill**: run it directly inside Cowork or an interactive session

## Path reference

```
Repository:     ~/repos/obsidian-import/
Scripts:        ~/scripts/obsidian-import    -> symlink
                ~/scripts/transcribe.py     -> symlink
                ~/scripts/convert.py        -> symlink
venv:           ~/scripts/.venv/
Vault:          ~/Documents/Obsidian/Vault/YouTube/レシピ/
Transcripts:    <vault>/.transcripts/*.txt     (unprocessed)
Done:           <vault>/.transcripts/done/     (already converted to a recipe)
```

## Setup guide

If the user hasn't set this up yet, walk them through:

```bash
brew install yt-dlp ffmpeg python@3.12

# Create the venv and install dependencies
python3.12 -m venv ~/scripts/.venv
~/scripts/.venv/bin/pip install mlx-whisper "markitdown[all]"

# Clone the repo and set up the symlinks
git clone https://github.com/nobu666/obsidian-import.git ~/repos/obsidian-import
ln -s ~/repos/obsidian-import/obsidian-import ~/scripts/obsidian-import
ln -s ~/repos/obsidian-import/transcribe.py ~/scripts/transcribe.py
ln -s ~/repos/obsidian-import/convert.py ~/scripts/convert.py
chmod +x ~/scripts/obsidian-import
```

Running it:

```bash
# Process a whole playlist
~/scripts/obsidian-import https://www.youtube.com/playlist?list=XXXXX

# A single video
~/scripts/obsidian-import https://www.youtube.com/watch?v=XXXXX

# Turn a web article into a note
~/scripts/obsidian-import https://x.com/user/status/XXXXX

# A document (PDF/slides/Google Docs, etc.)
~/scripts/obsidian-import https://docs.google.com/document/d/XXXXX
~/scripts/obsidian-import ~/Downloads/slides.pdf

# A local audio/video file (transcribed with Whisper)
~/scripts/obsidian-import ~/Downloads/voice-memo.m4a
~/scripts/obsidian-import ~/Downloads/recording.mp4

# Just extract the text (no note conversion)
~/scripts/.venv/bin/python3 ~/scripts/transcribe.py https://www.youtube.com/watch?v=XXXXX
~/scripts/.venv/bin/python3 ~/scripts/convert.py https://example.com/paper.pdf
```

## Note conversion steps

### 1. Read the text file

Read the `.txt` files in the `.transcripts/` directory inside the output folder. Ignore files in the `done/` subdirectory — they're already processed. Each file has this format:

```
title: Video title
video_id: YouTube ID
url: https://www.youtube.com/watch?v=...
---
(transcript body)
```

### 2. Extract the recipe

Extract the following from the transcript:

- **Dish name**: judge from anything in 【】<>「」 in the video title, or from the transcript body. Keep it concise.
- **Ingredients**: name and amount. If the amount is unclear, use "to taste."
- **Steps**: concise, numbered steps.

If multiple recipes are introduced in the video, create the main recipe as one file, and fold in arrangements/sub-recipes as `##` sections within the same file.

Even if the transcript quality is poor (e.g. a Whisper hallucination), produce the best possible recipe from what can be read. Only skip a note if the content is completely unreadable, and report that. Don't ask questions or seek confirmation — decide for yourself and proceed.

### 3. Output format

Match the existing recipe notes exactly. Here's the template:

```markdown
---
created: YYYY-MM-DD HH:MM
updated: YYYY-MM-DD HH:MM
source: https://www.youtube.com/watch?v=VIDEO_ID
---

# Dish Name

* Ingredient 1 Amount
* Ingredient 2 Amount
* Ingredient 3 Amount

1. Step 1
2. Step 2
3. Step 3
```

Key points:
- Put the video URL in frontmatter's `source`
- `created` / `updated` are the current date/time — run `date '+%Y-%m-%d %H:%M'` to get it, don't guess (the system prompt's date context has no time component)
- Ingredients are a bulleted list starting with `* ` (indent for subgroups)
- Steps are a numbered list starting with `1. `
- Never include extraneous commentary, impressions, promotion, or a call to subscribe
- Keep it concise. Short sentences.

### 4. Decide the filename

Use the dish name as-is for the filename. Examples:
- `Stir-fried tomato and egg.md`
- `Simmered kabocha with ground meat.md`
- `Homemade takuan pickles.md`

Use the extracted dish name, not the video's title.

### 5. Save it

Save it directly to the Obsidian recipe folder:

```
~/Documents/Obsidian/Vault/YouTube/レシピ/Dish Name.md
```

### 6. Handling processed files

Move a text file to `.transcripts/done/` once it's been converted to a note. This prevents it from being processed again next time.

## Existing recipe examples

For reference, actual recipes from the user's Vault:

```markdown
---
created: 2021-10-15 10:02
updated: 2021-10-15 10:02
source: google-keep
---

# Garlic Butter Chicken

* Chicken thigh 2 pieces
* Garlic 1-2 cloves
* Sake 2 tbsp
* Mirin 2 tbsp
* Soy sauce 2 tbsp
* Sugar 2/3 tsp
* Butter 20g

1. Cut the meat into bite-sized pieces and season lightly with salt and pepper
2. Heat a little oil and start cooking skin-side down
3. Grate in the garlic, add the seasonings and a few dashes of umami seasoning, and reduce
4. Melt in the butter
```

```markdown
---
created: 2021-10-15 10:20
updated: 2021-10-15 10:20
source: google-keep
---

# Mapo Tofu

* Zhajiang (fried sauce)
    * Coarsely ground pork 120g
    * Shaoxing wine + soy sauce 15cc
    * Sweet bean sauce (tianmianjiang) 10g
* Main
    * Tofu 1 block
    * Grated garlic + ginger 2 heaping tbsp
    * Chopped fermented black beans (douchi) 1 heaping tbsp
    * Chili pepper to taste
    * Doubanjiang 2 tsp
    * Water 300cc
    * Chicken stock powder 2 tsp
    * Shaoxing wine + soy sauce 20cc
* Finishing
    * Chopped scallion
    * Garlic scape 1 stalk
    * Water-dissolved potato starch 1+1 tbsp
    * Sichuan pepper
    * Chili oil

1. Heat the pot, add oil, and stir-fry the ground pork
2. Once cooked through, add the Shaoxing wine and soy sauce, stir-fry until the liquid evaporates, then mix in the sweet bean sauce
3. Clean the pot once, then gently stir-fry the garlic, ginger, doubanjiang, douchi, and chili pepper in oil over low heat to release the aroma
4. Once the oil takes on color, turn up the heat, add the zhajiang, and stir-fry together
5. Add the stock, soy sauce, and Shaoxing wine and mix in
6. Cut the tofu into pieces, parboil it separately, then add it in
7. Once the tofu is in, simmer for 2-3 minutes
8. Add the garlic scape and scallion, lower the heat, and stir in the water-dissolved potato starch a little at a time
9. Once it reaches the right thickness, turn up the heat, pour chili oil around the edge of the pot, and fold it in with a scooping motion
10. Bring it to a sizzling finish
```

Follow this same style: group ingredients into subgroups where relevant, and keep the steps simply written.
