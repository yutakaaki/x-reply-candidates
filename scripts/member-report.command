#!/bin/bash
# ダブルクリック: リストの見直し用レポートを表示する（API料金はかからない）
cd "$(dirname "$0")/.."
/usr/bin/python3 src/member_report.py
echo ""
echo "（data/member_report.md にも保存しました。このウィンドウは閉じて構いません）"
