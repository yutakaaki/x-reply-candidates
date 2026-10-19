#!/bin/bash
# ダブルクリック: @anime_attention でXにログインし、非公開リストを読む許可を与える（初回・期限切れ時）
# Client ID を入れ直したいときは、ターミナルで  ./login.command --reset
cd "$(dirname "$0")/.."
/usr/bin/python3 src/login.py "$@"
