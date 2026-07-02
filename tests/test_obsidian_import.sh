#!/bin/bash
# Tests for the obsidian-import shell script's filename parsing/validation
# Run: bash tests/test_obsidian_import.sh

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

# --- FILENAME extraction tests ---
echo "=== FILENAME extraction ==="

extract_filename() {
  echo "$1" | grep -m1 '^FILENAME: ' | sed 's/^FILENAME: //' | sed 's/^`//;s/`$//'
}

assert_eq "a normal filename" \
  "test.md" \
  "$(extract_filename "FILENAME: test.md")"

assert_eq "with backticks" \
  "test.md" \
  "$(extract_filename 'FILENAME: `test.md`')"

assert_eq "with leading text before it" \
  "note.md" \
  "$(extract_filename "$(printf 'Converted the content.\nFILENAME: note.md\n---\nBody')")"

assert_eq "empty when there is no FILENAME line" \
  "" \
  "$(extract_filename "just plain text output")"

# --- Filename validation tests ---
echo ""
echo "=== Filename validation ==="

validate_filename() {
  local f="$1"
  if [[ "$f" == *.md ]] && [[ "$f" != */* ]] && [[ "$f" != *..* ]]; then
    echo "valid"
  else
    echo "invalid"
  fi
}

assert_eq "a normal filename" "valid" "$(validate_filename "test.md")"
assert_eq "an English filename" "valid" "$(validate_filename "test-note.md")"
assert_eq "a filename with spaces" "valid" "$(validate_filename "Claude Code Summary.md")"
assert_eq "no extension -> rejected" "invalid" "$(validate_filename "test")"
assert_eq ".txt extension -> rejected" "invalid" "$(validate_filename "test.txt")"
assert_eq "contains a path separator -> rejected" "invalid" "$(validate_filename "../../.zshrc.md")"
assert_eq "contains a path separator (absolute path) -> rejected" "invalid" "$(validate_filename "/etc/passwd.md")"
assert_eq "contains .. -> rejected" "invalid" "$(validate_filename "..test.md")"
assert_eq "dotfile-like name containing .. -> rejected" "invalid" "$(validate_filename "..zshrc.md")"

# --- Local audio/video detection tests ---
echo ""
echo "=== Local audio/video detection ==="

is_audio_file() {
  local lower
  lower=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  [[ -f "$1" && "$lower" =~ \.(mp3|m4a|m4b|wav|aac|flac|ogg|opus|mp4|mov|m4v)$ ]]
}

_AUDIO_TMP=$(mktemp -d)
touch "$_AUDIO_TMP/voice.m4a" "$_AUDIO_TMP/clip.mp4" "$_AUDIO_TMP/doc.pdf" "$_AUDIO_TMP/REC.MP3"
is_audio_file "$_AUDIO_TMP/voice.m4a" && r=yes || r=no
assert_eq "audio file (.m4a) -> yes" "yes" "$r"
is_audio_file "$_AUDIO_TMP/clip.mp4" && r=yes || r=no
assert_eq "video file (.mp4) -> yes" "yes" "$r"
is_audio_file "$_AUDIO_TMP/REC.MP3" && r=yes || r=no
assert_eq "uppercase extension (.MP3) -> yes" "yes" "$r"
is_audio_file "$_AUDIO_TMP/doc.pdf" && r=yes || r=no
assert_eq "non-audio (.pdf) -> no" "no" "$r"
is_audio_file "$_AUDIO_TMP/missing.mp3" && r=yes || r=no
assert_eq "a missing file -> no" "no" "$r"
is_audio_file "https://youtu.be/abc" && r=yes || r=no
assert_eq "URL → no" "no" "$r"
rm -rf "$_AUDIO_TMP"

# --- transcribe.py exit code interpretation tests ---
echo ""
echo "=== transcribe.py exit code interpretation ==="

# Extract and load decide_transcribe_outcome from the real script (tests the real thing)
_SI_SCRIPT_FOR_STATUS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/obsidian-import"
eval "$(awk '/^decide_transcribe_outcome\(\) \{/,/^\}/' "$_SI_SCRIPT_FOR_STATUS")"

assert_eq "exit code 0 (success) -> continue" "continue" "$(decide_transcribe_outcome 0)"
assert_eq "exit code 2 (not a video) -> fallback" "fallback" "$(decide_transcribe_outcome 2)"
assert_eq "exit code 1 (error) -> continue (degrade and proceed)" "continue" "$(decide_transcribe_outcome 1)"

# --- Symlink write rejection tests ---
echo ""
echo "=== Symlink write rejection ==="

# Don't keep a copy; extract and load write_note from the real script (tests the real thing)
_SI_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/obsidian-import"
eval "$(awk '/^write_note\(\) \{/,/^\}/' "$_SI_SCRIPT")"

_WN_TMP=$(mktemp -d)
_WN_SECRET="$_WN_TMP/secret.txt"
printf 'ORIGINAL\n' > "$_WN_SECRET"
ln -s "$_WN_SECRET" "$_WN_TMP/evil.md"          # a symlink named .md at the output path
write_note "$_WN_TMP" "evil.md" "PWNED" && r=wrote || r=refused
assert_eq "a symlink target is refused (return value)" "refused" "$r"
assert_eq "the symlink target is unmodified" "ORIGINAL" "$(cat "$_WN_SECRET")"
# A regular file can be written
write_note "$_WN_TMP" "normal.md" "HELLO" && r=wrote || r=refused
assert_eq "a regular file can be written (return value)" "wrote" "$r"
assert_eq "the regular file's content" "HELLO" "$(cat "$_WN_TMP/normal.md")"
# An existing regular file isn't overwritten; it's saved under a numbered name (P2: no-confirmation-overwrite defense)
printf 'KEEP\n' > "$_WN_TMP/dup.md"
write_note "$_WN_TMP" "dup.md" "NEW"
assert_eq "an existing file is not overwritten" "KEEP" "$(cat "$_WN_TMP/dup.md")"
assert_eq "new content goes to a numbered file" "NEW" "$(cat "$_WN_TMP/dup-1.md")"
# A path-traversal name is rejected by the function itself too (defense in depth)
write_note "$_WN_TMP" "../escape.md" "X" && r=wrote || r=refused
assert_eq "a name containing ../ is rejected" "refused" "$r"
write_note "$_WN_TMP" "sub/evil.md" "X" && r=wrote || r=refused
assert_eq "a name containing a path separator is rejected" "refused" "$r"
rm -rf "$_WN_TMP"

# --- Body extraction tests ---
echo ""
echo "=== Body extraction ==="

extract_content() {
  echo "$1" | sed -n '/^FILENAME: /,$p' | tail -n +2
}

OUTPUT="$(printf 'A comment line\nFILENAME: test.md\n---\ncreated: 2026-01-01\n---\n# Body')"
CONTENT="$(extract_content "$OUTPUT")"

assert_eq "text before the FILENAME line is stripped" \
  "" \
  "$(echo "$CONTENT" | grep 'A comment line')"

assert_eq "frontmatter is included" \
  "---" \
  "$(echo "$CONTENT" | head -1)"

assert_eq "the body is included" \
  "# Body" \
  "$(echo "$CONTENT" | tail -1)"

# --- Multiple FILENAME block extraction tests ---
echo ""
echo "=== Multiple FILENAME block extraction ==="

# The same parsing logic as the main shell script, extracted into a function
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

# Test: a single file
SINGLE_OUTPUT="$(printf 'A comment\nFILENAME: Dish A.md\n---\n# Dish A\n* Ingredient 1')"
COUNT=$(parse_multi_filename "$SINGLE_OUTPUT" "$TMPDIR_TEST")
assert_eq "single file: count" "1" "$COUNT"
assert_eq "single file: file exists" "true" "$([ -f "$TMPDIR_TEST/Dish A.md" ] && echo true || echo false)"
assert_eq "single file: body is included" "# Dish A" "$(grep '# Dish A' "$TMPDIR_TEST/Dish A.md")"
rm -f "$TMPDIR_TEST"/*.md

# Test: multiple files
MULTI_OUTPUT="$(printf 'FILENAME: Curry.md\n---\n# Curry\n* Onion\n1. Saute\nFILENAME: Salad.md\n---\n# Salad\n* Lettuce\n1. Plate it')"
COUNT=$(parse_multi_filename "$MULTI_OUTPUT" "$TMPDIR_TEST")
assert_eq "multiple files: count" "2" "$COUNT"
assert_eq "multiple files: Curry exists" "true" "$([ -f "$TMPDIR_TEST/Curry.md" ] && echo true || echo false)"
assert_eq "multiple files: Salad exists" "true" "$([ -f "$TMPDIR_TEST/Salad.md" ] && echo true || echo false)"
assert_eq "multiple files: Salad doesn't leak into Curry's content" "" "$(grep 'Salad' "$TMPDIR_TEST/Curry.md" 2>/dev/null)"
assert_eq "multiple files: Salad's content" "# Salad" "$(grep '# Salad' "$TMPDIR_TEST/Salad.md")"
rm -f "$TMPDIR_TEST"/*.md

# Test: multiple blocks including an invalid filename
MIXED_OUTPUT="$(printf 'FILENAME: ok.md\n# OK\nFILENAME: ../../evil.md\n# NG\nFILENAME: ok2.md\n# OK2')"
COUNT=$(parse_multi_filename "$MIXED_OUTPUT" "$TMPDIR_TEST")
assert_eq "mixed with an invalid filename: valid file count" "2" "$COUNT"
assert_eq "mixed with an invalid filename: evil.md is not created" "false" "$([ -f "$TMPDIR_TEST/../../evil.md" ] && echo true || echo false)"
rm -f "$TMPDIR_TEST"/*.md

# Test: output with no FILENAME line
NO_FN_OUTPUT="just plain text output"
COUNT=$(parse_multi_filename "$NO_FN_OUTPUT" "$TMPDIR_TEST")
assert_eq "no FILENAME line: count is 0" "0" "$COUNT"

rm -rf "$TMPDIR_TEST"

# --- Results ---
echo ""
echo "=== Results: ${PASS} passed / ${FAIL} failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
