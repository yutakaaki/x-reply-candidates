#!/bin/bash
# ダブルクリック: 毎日 6:00 / 18:00 の自動抽出を登録する（先に login.command を済ませておく）
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
PLIST="$HOME/Library/LaunchAgents/com.xreply.candidates.plist"
mkdir -p "$PROJECT_DIR/logs" "$HOME/Library/LaunchAgents"

if ! grep -q refresh_token "$HOME/.x-reply-candidates/secrets.json" 2>/dev/null; then
  echo "⚠️ まだXにログインしていません。先に scripts/login.command を実行してください。"
  exit 1
fi

cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.xreply.candidates</string>
  <!-- 実行時刻＝自動起床時刻。caffeinate -i で実行中の再スリープを防ぐ -->
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>/usr/bin/python3</string><string>$PROJECT_DIR/src/run.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$PROJECT_DIR/logs/run.log</string>
  <key>StandardErrorPath</key><string>$PROJECT_DIR/logs/run.log</string>
</dict></plist>
PL

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# 次の定時にスリープから起きるよう予約（以降は毎回の実行後に自動で次を予約）
H=$(date +%H)
if [ "$H" -lt 6 ]; then NEXT="$(date '+%m/%d/%Y') 06:00:00"
elif [ "$H" -lt 18 ]; then NEXT="$(date '+%m/%d/%Y') 18:00:00"
else NEXT="$(date -v+1d '+%m/%d/%Y') 06:00:00"; fi
if sudo -n pmset schedule wake "$NEXT" 2>/dev/null; then
  echo "✓ 次回の自動起床を予約: $NEXT"
else
  echo "▶ 自動起床の予約に管理者パスワードが必要です。"
  sudo pmset schedule wake "$NEXT" && echo "✓ 次回の自動起床を予約: $NEXT"
fi

echo ""
echo "✅ 登録完了！ 毎日 6:00 / 18:00 に返信候補を更新します。"
echo "   閲覧: https://yutakaaki.github.io/x-reply-candidates/"
echo "   ・電源アダプタに接続したままにしてください（スリープ・フタ閉じOK）。"
echo "このウィンドウは閉じて構いません。"
