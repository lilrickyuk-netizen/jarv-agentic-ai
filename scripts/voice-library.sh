#!/usr/bin/env bash
# Builds JAI's narration voice library: real human voices for Chatterbox Turbo to speak in, instead of a reference
# made with a text-to-speech voice. Downloads LibriTTS-R's clean test set (CC BY 4.0, openslr.org/141, 1.2 GB, kept in
# ~/.cache/jai-voice-library so a rerun does not download it again) and its documentation (the speakers' list),
# checks them against the dataset's own md5 sums,
# chooses one clean 9 to 15 second clip per speaker (scripts/voice_library_pick.py, up to 8 women and 8 men across
# calm to lively), and copies them with library.json into Chatterbox's voice folder (the jai_voice_refs volume),
# beside George. Run again to rebuild it; nothing else in the folder is touched.
set -euo pipefail
cd "$(dirname "$0")/.."
CACHE="${HOME}/.cache/jai-voice-library"
VOLUME="${VOICE_VOLUME:-jai_voice_refs}"
mkdir -p "$CACHE"
MIRRORS="https://openslr.elda.org/resources/141 https://openslr.trmal.net/resources/141 https://www.openslr.org/resources/141"
fetch() {
  for base in $MIRRORS; do
    curl -fL --retry 3 --retry-delay 5 -C - -o "$CACHE/$1" "$base/$1" && return 0
    rm -f "$CACHE/$1"
  done
  return 1
}
rm -f "$CACHE/md5sum.txt"
fetch md5sum.txt || { echo "   The dataset's md5sum.txt could not be downloaded"; exit 1; }
md5_of() { awk -v f="$1" '{n=$2; sub(/^\*/, "", n); sub(/.*\//, "", n); if (n == f) print $1}' "$CACHE/md5sum.txt" | head -1; }
get() {
  local file=$1 expected
  expected=$(md5_of "$file")
  if [ -f "$CACHE/$file" ] && { [ -z "$expected" ] || [ "$(md5sum "$CACHE/$file" | awk '{print $1}')" = "$expected" ]; }; then
    echo "   $file: already here${expected:+, checked}"; return 0
  fi
  rm -f "$CACHE/$file"
  echo "   Downloading $file..."
  fetch "$file" || { echo "   $file could not be downloaded from any mirror"; return 1; }
  if [ -n "$expected" ] && [ "$(md5sum "$CACHE/$file" | awk '{print $1}')" != "$expected" ]; then
    rm -f "$CACHE/$file"; echo "   $file does not match the dataset's md5 sum"; return 1
  fi
  echo "   $file: downloaded${expected:+, checked}"
}
# The speech must match the dataset's own checksum; the list of failed restorations is a small text file.
[ -n "$(md5_of test_clean.tar.gz)" ] || { echo "   test_clean.tar.gz is not in the dataset's md5sum.txt"; exit 1; }
get test_clean.tar.gz
get libritts_r_failed_speech_restoration_examples.tar.gz || echo "   (continuing without the list of failed restorations)"
# The speakers' list (speakers.tsv, SPEAKERS.txt: who is a woman and who a man) is in the documentation archive.
# 22 November: its copy did not match the dataset's md5sum.txt (the list may be older than the archive), so each
# mirror's copy is fetched; one matching the md5 sum is used, otherwise a copy two independent mirrors agree on.
get_doc() {
  local expected base sum
  expected=$(md5_of doc.tar.gz)
  rm -rf "$CACHE/doc-mirrors"; mkdir -p "$CACHE/doc-mirrors"
  for base in $MIRRORS; do
    host=$(echo "$base" | cut -d/ -f3)
    curl -fsL --retry 3 --retry-delay 5 -o "$CACHE/doc-mirrors/$host" "$base/doc.tar.gz" || continue
    sum=$(md5sum "$CACHE/doc-mirrors/$host" | awk '{print $1}')
    echo "   doc.tar.gz from $host: $sum"
    if [ -n "$expected" ] && [ "$sum" = "$expected" ]; then
      cp "$CACHE/doc-mirrors/$host" "$CACHE/doc.tar.gz"; echo "   doc.tar.gz: checked against md5sum.txt"; return 0
    fi
  done
  agreed=$(md5sum "$CACHE/doc-mirrors"/* 2>/dev/null | awk '{print $1}' | sort | uniq -c | awk '$1 >= 2 {print $2}' | head -1)
  [ -n "$agreed" ] || return 1
  cp "$(md5sum "$CACHE/doc-mirrors"/* | awk -v h="$agreed" '$1 == h {print $2; exit}')" "$CACHE/doc.tar.gz"
  echo "   doc.tar.gz: the same on two mirrors ($agreed), used (md5sum.txt lists ${expected:-none})"
}
get_doc || { echo "   The dataset's documentation (its list of speakers) could not be confirmed from two mirrors"; exit 1; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/data" "$WORK/failed" "$WORK/out"
tar xzf "$CACHE/test_clean.tar.gz" -C "$WORK/data"
mkdir -p "$WORK/data/doc" && tar xzf "$CACHE/doc.tar.gz" -C "$WORK/data/doc"
echo "   speakers lists in the documentation: $(find "$WORK/data" -name speakers.tsv -o -name SPEAKERS.txt | wc -l)"
[ -f "$CACHE/libritts_r_failed_speech_restoration_examples.tar.gz" ] && tar xzf "$CACHE/libritts_r_failed_speech_restoration_examples.tar.gz" -C "$WORK/failed"
python3 scripts/voice_library_pick.py "$WORK/data" "$WORK/failed" "$WORK/out"
chmod 644 "$WORK/out"/*
docker volume inspect "$VOLUME" >/dev/null
docker run --rm -v "$VOLUME:/srv/voices" -v "$WORK/out:/in:ro" alpine:3.20 \
  sh -c 'rm -f /srv/voices/woman-*.wav /srv/voices/man-*.wav && cp /in/* /srv/voices/ && chmod 644 /srv/voices/*'
echo "   Voice library: $(ls "$WORK/out"/*.wav | wc -l) voices in $VOLUME"
