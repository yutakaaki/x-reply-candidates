#!/bin/bash
# ダブルクリック: 今すぐ1回抽出して、GitHub Pages に反映する（定時を待たずに確認したいとき）
cd "$(dirname "$0")/.."
/usr/bin/python3 src/run.py "$@"
echo ""
echo "閲覧ページ: https://yutakaaki.github.io/x-reply-candidates/ （反映まで1〜2分）"
