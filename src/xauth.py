"""X API の OAuth 2.0（PKCE）トークン管理と GET ヘルパー。

秘密情報（Client ID/Secret・トークン）はリポジトリの外
~/.x-reply-candidates/secrets.json（権限600）にだけ保存する。
"""
import base64, json, os, time, urllib.error, urllib.parse, urllib.request

SECRETS_DIR  = os.path.expanduser('~/.x-reply-candidates')
SECRETS_FILE = os.path.join(SECRETS_DIR, 'secrets.json')
AUTH_URL     = 'https://x.com/i/oauth2/authorize'
TOKEN_URL    = 'https://api.x.com/2/oauth2/token'
API          = 'https://api.x.com/2'
SCOPES       = 'tweet.read users.read list.read offline.access'
REDIRECT_URI = 'http://127.0.0.1:5573/callback'


class AuthError(Exception):
    """ログインが必要／トークン更新に失敗した"""


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f'HTTP {status}: {body}')
        self.status, self.body = status, body


def load_secrets():
    try:
        with open(SECRETS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_secrets(s):
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True)
    tmp = SECRETS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SECRETS_FILE)  # 途中で落ちても壊れないよう置き換えで保存


def _token_request(s, form):
    form = dict(form, client_id=s['client_id'])
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    if s.get('client_secret'):  # Web App（confidential client）の場合
        cred = f"{s['client_id']}:{s['client_secret']}".encode()
        headers['Authorization'] = 'Basic ' + base64.b64encode(cred).decode()
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode(),
                                 headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        raise AuthError(f'トークン取得に失敗 ({e.code}): {e.read().decode(errors="replace")[:300]}')
    s['access_token'] = tok['access_token']
    if tok.get('refresh_token'):  # リフレッシュトークンは毎回入れ替わるので必ず保存
        s['refresh_token'] = tok['refresh_token']
    s['expires_at'] = time.time() + int(tok.get('expires_in', 7200)) - 120
    save_secrets(s)
    return s


def exchange_code(s, code, verifier):
    return _token_request(s, {'grant_type': 'authorization_code', 'code': code,
                              'redirect_uri': REDIRECT_URI, 'code_verifier': verifier})


def access_token():
    s = load_secrets()
    if not s.get('client_id') or not s.get('refresh_token'):
        raise AuthError('未ログインです。scripts/login.command を実行してください。')
    if s.get('access_token') and time.time() < s.get('expires_at', 0):
        return s['access_token']
    try:
        _token_request(s, {'grant_type': 'refresh_token', 'refresh_token': s['refresh_token']})
    except AuthError as e:
        raise AuthError(f'{e}\n→ scripts/login.command で再ログインしてください。')
    return s['access_token']


def api_get(path, params, token):
    url = f'{API}{path}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}',
                                               'User-Agent': 'x-reply-candidates'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors='replace')[:500])
