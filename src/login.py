#!/usr/bin/env python3
"""初回（または期限切れ時）に @anime_attention でXにログインし、非公開リストを読む許可をもらう。

使い方: scripts/login.command をダブルクリック（Client ID を変えたいときは --reset）
"""
import base64, getpass, hashlib, json, os, secrets, sys, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xauth import (AUTH_URL, REDIRECT_URI, SCOPES, ApiError, AuthError,
                   api_get, exchange_code, load_secrets, save_secrets)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))


def ask_client(s):
    print('━━ X Developer Console のアプリ情報を入力します ━━')
    print('  console.x.com → アプリ → 「Keys and tokens」の')
    print('  「OAuth 2.0 Client ID and Client Secret」をコピーしてください。\n')
    s['client_id'] = input('Client ID: ').strip()
    s['client_secret'] = getpass.getpass('Client Secret（入力は表示されません。無い場合は空でEnter）: ').strip()
    for k in ('access_token', 'refresh_token', 'expires_at'):
        s.pop(k, None)
    save_secrets(s)


def main():
    s = load_secrets()
    if '--reset' in sys.argv or not s.get('client_id'):
        ask_client(s)

    verifier  = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state     = secrets.token_urlsafe(16)
    url = AUTH_URL + '?' + urllib.parse.urlencode({
        'response_type': 'code', 'client_id': s['client_id'], 'redirect_uri': REDIRECT_URI,
        'scope': SCOPES, 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})

    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path != '/callback':
                self.send_response(404); self.end_headers(); return
            result.update({k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()})
            ok = 'code' in result
            msg = ('✅ ログイン完了。このタブを閉じてターミナルに戻ってください。' if ok
                   else f'❌ 許可されませんでした: {result.get("error", "")}')
            body = f'<meta charset="utf-8"><p style="font:18px sans-serif;padding:40px">{msg}</p>'.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(('127.0.0.1', 5573), Callback)
    print(f'\nブラウザが開きます。必ず @{CONFIG["account"]} でログインした状態で')
    print('「アプリにアクセスを許可」を押してください。')
    print(f'（開かない場合はこのURLを開く）\n{url}\n')
    webbrowser.open(url)
    while 'code' not in result and 'error' not in result:
        server.handle_request()
    server.server_close()

    if 'error' in result:
        sys.exit(f'❌ 許可されませんでした: {result["error"]}')
    if result.get('state') != state:
        sys.exit('❌ state が一致しません。もう一度やり直してください。')

    s = exchange_code(load_secrets(), result['code'], verifier)
    token = s['access_token']

    me = api_get('/users/me', {}, token)['data']
    s['me_id'], s['me_username'] = me['id'], me['username']
    save_secrets(s)
    print(f'✅ @{me["username"]} としてログインしました。')
    if me['username'].lower() != CONFIG['account'].lower():
        print(f'⚠️ 想定アカウント @{CONFIG["account"]} と違います。リストの持ち主でログインし直してください。')

    lst = api_get(f'/lists/{CONFIG["list_id"]}', {'list.fields': 'member_count,private'}, token)
    if 'data' in lst:
        d = lst['data']
        print(f'✅ リスト「{d.get("name")}」を読めました（メンバー {d.get("member_count", "?")} 人'
              f'{"・非公開" if d.get("private") else ""}）。')
    else:
        print(f'⚠️ リストを読めませんでした: {json.dumps(lst, ensure_ascii=False)[:300]}')
    print('\nこのウィンドウは閉じて構いません。')


if __name__ == '__main__':
    try:
        main()
    except (AuthError, ApiError) as e:
        sys.exit(f'❌ {e}')
