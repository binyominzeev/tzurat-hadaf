#!/usr/bin/env bash
# Egy parancs: letöltés -> illesztés -> mérés/tördelés -> PDF.   Használat: ./build.sh [config.yaml]
set -euo pipefail
cd "$(dirname "$0")"
CONFIG="${1:-config.live.yaml}"
mkdir -p out

echo "==> 1/2 Adatok letöltése és illesztése ($CONFIG)"
python3 pilot.py "$CONFIG"

echo "==> 2/2 Tördelés és PDF"
python3 layout.py "$CONFIG"

BAD=$(awk -F, 'NR>1 && $2=="inherited"' out/matches.csv | wc -l)
echo "Örökölt (nem illesztett) Abudraham-szegmens: $BAD  -> nézd át: out/matches.csv"
echo "Kész: out/page.pdf"
