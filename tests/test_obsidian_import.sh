#!/bin/bash
# obsidian-import シェルスクリプトのファイル名パース・バリデーションのテスト
# 実行: bash tests/test_obsidian_import.sh

PASS=0
FAIL=0

assert_eq() {
  local desc="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  ✓ ${desc}"
    PASS=$((PASS + 1))
  else
    echo "  ✗ ${desc}"
    echo "    expected: '${expected}'"
    echo "    actual:   '${actual}'"
    FAIL=$((FAIL + 1))
  fi
}

# --- FILENAME抽出テスト ---
echo "=== FILENAME抽出 ==="

extract_filename() {
  echo "$1" | grep -m1 '^FILENAME: ' | sed 's/^FILENAME: //' | sed 's/^`//;s/`$//'
}

assert_eq "通常のファイル名" \
  "テスト.md" \
  "$(extract_filename "FILENAME: テスト.md")"

assert_eq "バッククォート付き" \
  "テスト.md" \
  "$(extract_filename 'FILENAME: `テスト.md`')"

assert_eq "前置テキストがある場合" \
  "ノート.md" \
  "$(extract_filename "$(printf '内容を変換しました。\nFILENAME: ノート.md\n---\n本文')")"

assert_eq "FILENAME行がない場合は空" \
  "" \
  "$(extract_filename "ただのテキスト出力")"

# --- ファイル名バリデーションテスト ---
echo ""
echo "=== ファイル名バリデーション ==="

validate_filename() {
  local f="$1"
  if [[ "$f" == *.md ]] && [[ "$f" != */* ]] && [[ "$f" != *..* ]]; then
    echo "valid"
  else
    echo "invalid"
  fi
}

assert_eq "正常なファイル名" "valid" "$(validate_filename "テスト.md")"
assert_eq "英語ファイル名" "valid" "$(validate_filename "test-note.md")"
assert_eq "スペース含むファイル名" "valid" "$(validate_filename "Claude Code まとめ.md")"
assert_eq "拡張子なし → 拒否" "invalid" "$(validate_filename "テスト")"
assert_eq ".txt拡張子 → 拒否" "invalid" "$(validate_filename "テスト.txt")"
assert_eq "パス区切り含む → 拒否" "invalid" "$(validate_filename "../../.zshrc.md")"
assert_eq "パス区切り含む(絶対パス) → 拒否" "invalid" "$(validate_filename "/etc/passwd.md")"
assert_eq "..含む → 拒否" "invalid" "$(validate_filename "..test.md")"
assert_eq "隠しファイル風の..含む → 拒否" "invalid" "$(validate_filename "..zshrc.md")"

# --- ローカル音声/動画判定テスト ---
echo ""
echo "=== ローカル音声/動画判定 ==="

is_audio_file() {
  local lower
  lower=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  [[ -f "$1" && "$lower" =~ \.(mp3|m4a|m4b|wav|aac|flac|ogg|opus|mp4|mov|m4v)$ ]]
}

_AUDIO_TMP=$(mktemp -d)
touch "$_AUDIO_TMP/voice.m4a" "$_AUDIO_TMP/clip.mp4" "$_AUDIO_TMP/doc.pdf" "$_AUDIO_TMP/REC.MP3"
is_audio_file "$_AUDIO_TMP/voice.m4a" && r=yes || r=no
assert_eq "音声ファイル(.m4a) → yes" "yes" "$r"
is_audio_file "$_AUDIO_TMP/clip.mp4" && r=yes || r=no
assert_eq "動画ファイル(.mp4) → yes" "yes" "$r"
is_audio_file "$_AUDIO_TMP/REC.MP3" && r=yes || r=no
assert_eq "大文字拡張子(.MP3) → yes" "yes" "$r"
is_audio_file "$_AUDIO_TMP/doc.pdf" && r=yes || r=no
assert_eq "非音声(.pdf) → no" "no" "$r"
is_audio_file "$_AUDIO_TMP/missing.mp3" && r=yes || r=no
assert_eq "存在しないファイル → no" "no" "$r"
is_audio_file "https://youtu.be/abc" && r=yes || r=no
assert_eq "URL → no" "no" "$r"
rm -rf "$_AUDIO_TMP"

# --- transcribe.py終了コードの解釈テスト ---
echo ""
echo "=== transcribe.py 終了コードの解釈 ==="

# 実体スクリプトから decide_transcribe_outcome を抽出して読み込む（本物を検証）
_SI_SCRIPT_FOR_STATUS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/obsidian-import"
eval "$(awk '/^decide_transcribe_outcome\(\) \{/,/^\}/' "$_SI_SCRIPT_FOR_STATUS")"

assert_eq "終了コード0(成功) → continue" "continue" "$(decide_transcribe_outcome 0)"
assert_eq "終了コード2(動画でない) → fallback" "fallback" "$(decide_transcribe_outcome 2)"
assert_eq "終了コード1(エラー) → continue(縮退続行)" "continue" "$(decide_transcribe_outcome 1)"

# --- シンボリックリンク書き込み拒否テスト ---
echo ""
echo "=== シンボリックリンク書き込み拒否 ==="

# コピーを持たず、実体スクリプトから write_note を抽出して読み込む（本物を検証）
_SI_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/obsidian-import"
eval "$(awk '/^write_note\(\) \{/,/^\}/' "$_SI_SCRIPT")"

_WN_TMP=$(mktemp -d)
_WN_SECRET="$_WN_TMP/secret.txt"
printf 'ORIGINAL\n' > "$_WN_SECRET"
ln -s "$_WN_SECRET" "$_WN_TMP/evil.md"          # 出力先に .md 名のシンボリックリンク
write_note "$_WN_TMP" "evil.md" "PWNED" && r=wrote || r=refused
assert_eq "symlink宛ては拒否(戻り値)" "refused" "$r"
assert_eq "symlinkリンク先は改変されない" "ORIGINAL" "$(cat "$_WN_SECRET")"
# 通常ファイルは書ける
write_note "$_WN_TMP" "normal.md" "HELLO" && r=wrote || r=refused
assert_eq "通常ファイルは書ける(戻り値)" "wrote" "$r"
assert_eq "通常ファイルの内容" "HELLO" "$(cat "$_WN_TMP/normal.md")"
# 既存の通常ファイルは上書きせず連番で保存（P2: 無確認上書き対策）
printf 'KEEP\n' > "$_WN_TMP/dup.md"
write_note "$_WN_TMP" "dup.md" "NEW"
assert_eq "既存ファイルは上書きされない" "KEEP" "$(cat "$_WN_TMP/dup.md")"
assert_eq "新内容は連番ファイルへ" "NEW" "$(cat "$_WN_TMP/dup-1.md")"
# パストラバーサル名は関数自体でも拒否（多層防御）
write_note "$_WN_TMP" "../escape.md" "X" && r=wrote || r=refused
assert_eq "../を含む名前は拒否" "refused" "$r"
write_note "$_WN_TMP" "sub/evil.md" "X" && r=wrote || r=refused
assert_eq "パス区切りを含む名前は拒否" "refused" "$r"
rm -rf "$_WN_TMP"

# --- 本文抽出テスト ---
echo ""
echo "=== 本文抽出 ==="

extract_content() {
  echo "$1" | sed -n '/^FILENAME: /,$p' | tail -n +2
}

OUTPUT="$(printf 'コメント行\nFILENAME: テスト.md\n---\ncreated: 2026-01-01\n---\n# 本文')"
CONTENT="$(extract_content "$OUTPUT")"

assert_eq "FILENAME行の前のテキストが除去される" \
  "" \
  "$(echo "$CONTENT" | grep 'コメント行')"

assert_eq "frontmatterが含まれる" \
  "---" \
  "$(echo "$CONTENT" | head -1)"

assert_eq "本文が含まれる" \
  "# 本文" \
  "$(echo "$CONTENT" | tail -1)"

# --- 複数FILENAMEブロック抽出テスト ---
echo ""
echo "=== 複数FILENAMEブロック抽出 ==="

# シェルスクリプト本体と同じパースロジックを関数化
parse_multi_filename() {
  local output="$1"
  local output_dir="$2"
  local file_count=0
  local current_file=""
  local current_content=""
  while IFS= read -r LINE; do
    if [[ "$LINE" =~ ^FILENAME:\ (.+) ]]; then
      if [ -n "$current_file" ]; then
        echo "$current_content" > "${output_dir}/${current_file}"
        file_count=$((file_count + 1))
      fi
      current_file=$(echo "${BASH_REMATCH[1]}" | sed 's/^`//;s/`$//')
      current_content=""
      if [[ "$current_file" != *.md ]] || [[ "$current_file" == */* ]] || [[ "$current_file" == *..* ]]; then
        current_file=""
      fi
    elif [ -n "$current_file" ]; then
      if [ -z "$current_content" ]; then
        current_content="$LINE"
      else
        current_content="${current_content}
${LINE}"
      fi
    fi
  done <<< "$output"
  if [ -n "$current_file" ]; then
    echo "$current_content" > "${output_dir}/${current_file}"
    file_count=$((file_count + 1))
  fi
  echo "$file_count"
}

TMPDIR_TEST=$(mktemp -d)

# テスト: 単一ファイル
SINGLE_OUTPUT="$(printf 'コメント\nFILENAME: 料理A.md\n---\n# 料理A\n* 材料1')"
COUNT=$(parse_multi_filename "$SINGLE_OUTPUT" "$TMPDIR_TEST")
assert_eq "単一ファイル: 件数" "1" "$COUNT"
assert_eq "単一ファイル: ファイル存在" "true" "$([ -f "$TMPDIR_TEST/料理A.md" ] && echo true || echo false)"
assert_eq "単一ファイル: 本文含む" "# 料理A" "$(grep '# 料理A' "$TMPDIR_TEST/料理A.md")"
rm -f "$TMPDIR_TEST"/*.md

# テスト: 複数ファイル
MULTI_OUTPUT="$(printf 'FILENAME: カレー.md\n---\n# カレー\n* 玉ねぎ\n1. 炒める\nFILENAME: サラダ.md\n---\n# サラダ\n* レタス\n1. 盛る')"
COUNT=$(parse_multi_filename "$MULTI_OUTPUT" "$TMPDIR_TEST")
assert_eq "複数ファイル: 件数" "2" "$COUNT"
assert_eq "複数ファイル: カレー存在" "true" "$([ -f "$TMPDIR_TEST/カレー.md" ] && echo true || echo false)"
assert_eq "複数ファイル: サラダ存在" "true" "$([ -f "$TMPDIR_TEST/サラダ.md" ] && echo true || echo false)"
assert_eq "複数ファイル: カレーの内容にサラダが混入しない" "" "$(grep 'サラダ' "$TMPDIR_TEST/カレー.md" 2>/dev/null)"
assert_eq "複数ファイル: サラダの内容" "# サラダ" "$(grep '# サラダ' "$TMPDIR_TEST/サラダ.md")"
rm -f "$TMPDIR_TEST"/*.md

# テスト: 不正なファイル名を含む複数ブロック
MIXED_OUTPUT="$(printf 'FILENAME: 正常.md\n# OK\nFILENAME: ../../evil.md\n# NG\nFILENAME: 正常2.md\n# OK2')"
COUNT=$(parse_multi_filename "$MIXED_OUTPUT" "$TMPDIR_TEST")
assert_eq "不正ファイル名混在: 有効ファイル数" "2" "$COUNT"
assert_eq "不正ファイル名混在: evil.md は作られない" "false" "$([ -f "$TMPDIR_TEST/../../evil.md" ] && echo true || echo false)"
rm -f "$TMPDIR_TEST"/*.md

# テスト: FILENAME行がない出力
NO_FN_OUTPUT="ただのテキスト出力です"
COUNT=$(parse_multi_filename "$NO_FN_OUTPUT" "$TMPDIR_TEST")
assert_eq "FILENAME行なし: 件数0" "0" "$COUNT"

rm -rf "$TMPDIR_TEST"

# --- 結果 ---
echo ""
echo "=== 結果: ${PASS} passed / ${FAIL} failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
