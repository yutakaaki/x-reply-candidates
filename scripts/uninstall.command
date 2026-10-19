#!/bin/bash
# ダブルクリック: 自動抽出を停止する（ログイン情報とページは残る）
PLIST="$HOME/Library/LaunchAgents/com.xreply.candidates.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✅ 自動抽出を停止しました。再開は install.command。"
