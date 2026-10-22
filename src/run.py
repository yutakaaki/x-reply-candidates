#!/usr/bin/env python3
"""Xリストの直近12時間のポストから、返信候補（表示数上位）を抽出してページ用JSONを出力する。

launchd から毎日 6:00 / 18:00 に実行される。
  python3 src/run.py            # 抽出 → docs/ 更新 → GitHub へ push → 次回起床予約
  python3 src/run.py --no-push  # 抽出と docs/ 更新だけ（手元確認用）
"""
import html, json, os, socket, subprocess, sys, time, traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xauth

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS     = os.path.join(ROOT, 'docs')
RUNS_DIR = os.path.join(DOCS, 'runs')
JST      = ZoneInfo('Asia/Tokyo')


def log(msg):
    print(f'[{datetime.now(JST):%m/%d %H:%M:%S}] {msg}', flush=True)


def load_config():
    with open(os.path.join(ROOT, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def parse_time(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


def wait_for_network(host='api.x.com', timeout=180):
    """スリープから起きた直後は Wi-Fi がまだつながっていないことがあるので、名前が引けるまで待つ"""
    t0 = time.time()
    while True:
        try:
            socket.getaddrinfo(host, 443)
            return time.time() - t0
        except OSError:
            if time.time() - t0 > timeout:
                return None
            time.sleep(5)


def run_id_for(now, cfg):
    """定時（6:00/18:00）から90分以内の実行は定時の名前で保存する（起床遅れ対策）"""
    for hhmm in cfg['schedule']:
        h, m = map(int, hhmm.split(':'))
        for day in (-1, 0, 1):
            slot = (now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
            if abs((now - slot).total_seconds()) <= 90 * 60:
                return slot.strftime('%Y%m%d-%H%M'), slot
    return now.strftime('%Y%m%d-%H%M'), None


def fetch_list_posts(token, cfg, cutoff):
    """リストのタイムライン（新しい順）を、12時間前より古くなるまでページ送りで取得"""
    params = {'max_results': cfg['page_size'],
              'tweet.fields': 'created_at,public_metrics,referenced_tweets,author_id,note_tweet,attachments,entities',
              # 画像・動画（引用ポストの場合は引用元の画像・動画）も一緒にもらう
              'expansions': 'author_id,attachments.media_keys,referenced_tweets.id,'
                            'referenced_tweets.id.attachments.media_keys',
              'media.fields': 'type,url,preview_image_url,variants,duration_ms,width,height',
              'user.fields': 'username,name,profile_image_url'}
    posts, next_token, reached = [], None, False
    inc = {'users': {}, 'media': {}, 'tweets': {}}
    while len(posts) < cfg['max_posts_per_run']:
        p = dict(params)
        if next_token:
            p['pagination_token'] = next_token
        j = xauth.api_get(f'/lists/{cfg["list_id"]}/tweets', p, token)
        data = j.get('data') or []
        posts.extend(data)
        includes = j.get('includes') or {}
        for u in includes.get('users', []):
            inc['users'][u['id']] = u
        for m in includes.get('media', []):
            inc['media'][m['media_key']] = m
        for t in includes.get('tweets', []):
            inc['tweets'][t['id']] = t
        next_token = (j.get('meta') or {}).get('next_token')
        if not data or not next_token or parse_time(data[-1]['created_at']) < cutoff:
            reached = True  # 12時間分を取り切った（またはリストの投稿を全部見た）
            break
    return posts, inc, reached


def media_of(t, inc):
    """ポストの画像・動画を、ページで表示・再生しやすい形に整える"""
    out = []
    for key in (t.get('attachments') or {}).get('media_keys', []):
        m = inc['media'].get(key)
        if not m:
            continue
        item = {'type': m['type'], 'w': m.get('width'), 'h': m.get('height'),
                'thumb': m.get('url') or m.get('preview_image_url', '')}
        if m['type'] in ('video', 'animated_gif'):
            mp4s = [v for v in m.get('variants', []) if v.get('content_type') == 'video/mp4']
            # スマホで見る前提で、2Mbps以下で一番高画質なものを選ぶ（無ければ最低画質）
            mp4s.sort(key=lambda v: v.get('bit_rate', 0))
            fit = [v for v in mp4s if v.get('bit_rate', 0) <= 2_200_000]
            if mp4s:
                item['mp4'] = (fit[-1] if fit else mp4s[0])['url']
            if m.get('duration_ms'):
                item['duration'] = round(m['duration_ms'] / 1000)
        out.append(item)
    return out


def clean_text(t, text, hide_ids):
    """本文末尾の画像・動画・引用元への t.co リンクを消す（別枠で表示するため）"""
    for u in (t.get('entities') or {}).get('urls', []):
        exp = u.get('expanded_url', '')
        if u.get('media_key') or any(f'/status/{i}' in exp for i in hide_ids):
            text = text.replace(u['url'], '')
    return text.strip()


def velocity(p, now):
    """投稿から集計時点までの伸びの速さ＝1時間あたりの表示数（投稿直後の過大評価を避けるため最短1時間で割る）"""
    hours = (now - datetime.fromisoformat(p['created_at'])).total_seconds() / 3600
    return p['impressions'] / max(1.0, hours)


def pick_candidates(posts, inc, cfg, cutoff, me_id, now):
    users = inc['users']
    out = []
    for t in posts:
        if parse_time(t['created_at']) < cutoff:
            continue
        refs = {r['type'] for r in t.get('referenced_tweets') or []}
        if cfg['exclude_retweets'] and 'retweeted' in refs:
            continue
        if cfg['exclude_replies'] and 'replied_to' in refs:
            continue
        if me_id and t.get('author_id') == me_id:
            continue  # 自分のポストは対象外
        m = t.get('public_metrics') or {}
        imp, rep = m.get('impression_count', 0), m.get('reply_count', 0)
        if imp < cfg['min_impressions'] or rep > cfg['max_replies']:
            continue
        u = users.get(t.get('author_id'), {})
        username = u.get('username', 'i')
        quoted_ids = [r['id'] for r in t.get('referenced_tweets') or [] if r['type'] == 'quoted']
        media, media_from_quote = media_of(t, inc), False
        if not media and quoted_ids and quoted_ids[0] in inc['tweets']:
            media = media_of(inc['tweets'][quoted_ids[0]], inc)  # 引用ポストは引用元の動画・画像を見せる
            media_from_quote = bool(media)
        text = (t.get('note_tweet') or {}).get('text') or t.get('text', '')
        text = clean_text(t, text, quoted_ids)
        out.append({
            'id': t['id'],
            'url': f'https://x.com/{username}/status/{t["id"]}',
            'reply_url': f'https://x.com/intent/post?in_reply_to={t["id"]}',
            'username': username,
            'name': u.get('name', ''),
            'avatar': u.get('profile_image_url', ''),
            'text': html.unescape(text),
            'created_at': parse_time(t['created_at']).astimezone(JST).isoformat(),
            'is_quote': 'quoted' in refs,
            'media': media,
            'media_from_quote': media_from_quote,
            'impressions': imp,
            'replies': rep,
            'likes': m.get('like_count', 0),
            'retweets': m.get('retweet_count', 0),
            'quotes': m.get('quote_count', 0),
            'bookmarks': m.get('bookmark_count', 0),
        })
    out.sort(key=lambda p: p['impressions'], reverse=True)
    matched = len(out)
    for i, p in enumerate(out, 1):
        p['rank'] = i  # 表示数の順位（条件に合った全件の中で）
        p['velocity'] = round(velocity(p, now))
    for i, p in enumerate(sorted(out, key=lambda p: p['velocity'], reverse=True), 1):
        p['vrank'] = i  # 伸びの速さの順位
    n = cfg['top_n']
    # 表示数の上位n件に、伸びが速い上位n件も加える（新しくて表示数がまだ少ない投稿を拾うため）
    out = [p for p in out if p['rank'] <= n or p['vrank'] <= n]
    return out, matched


def hourly_counts(posts, cutoff, now):
    """読めた範囲の中で丸ごと見えた1時間ごと（JST）に、投稿数を種類別に数える。
    o=通常・引用、rt=リツイート、rp=返信。範囲の端で欠ける時間は数えない（開始10分の欠けまでは許容）"""
    hour = timedelta(hours=1)
    # 投稿は新しい順に切れ目なく読んでいるので、読めた一番古い投稿の時刻までは全件そろっている
    start = parse_time(posts[-1]['created_at']).astimezone(JST) if posts else cutoff.astimezone(JST)
    first = start.replace(minute=0, second=0, microsecond=0)
    if start - first > timedelta(minutes=10):
        first += hour
    end = now.replace(minute=0, second=0, microsecond=0)
    hours, h = {}, first
    while h + hour <= end:
        hours[h.strftime('%Y-%m-%dT%H')] = {'o': 0, 'rt': 0, 'rp': 0}
        h += hour
    for t in posts:
        k = parse_time(t['created_at']).astimezone(JST).strftime('%Y-%m-%dT%H')
        if k not in hours:
            continue
        refs = {r['type'] for r in t.get('referenced_tweets') or []}
        hours[k]['rt' if 'retweeted' in refs else 'rp' if 'replied_to' in refs else 'o'] += 1
    return hours


def update_hourly(hours, now, keep_days=60):
    """docs/hourly.json に時間帯ごとの投稿数をためる（同じ時間を複数回見たら多い方を採用）"""
    path = os.path.join(DOCS, 'hourly.json')
    try:
        data = json.load(open(path, encoding='utf-8'))
    except Exception:
        data = {'hours': {}}
    for k, v in hours.items():
        old = data['hours'].get(k)
        if not old or sum(v.values()) >= sum(old.values()):
            data['hours'][k] = v
    oldest = (now - timedelta(days=keep_days)).strftime('%Y-%m-%dT%H')
    data['hours'] = {k: v for k, v in sorted(data['hours'].items()) if k >= oldest}
    data['updated'] = now.isoformat()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def write_run(run, cfg):
    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(os.path.join(RUNS_DIR, f'{run["id"]}.json'), 'w', encoding='utf-8') as f:
        json.dump(run, f, ensure_ascii=False, indent=1)

    idx_path = os.path.join(DOCS, 'runs.json')
    try:
        index = json.load(open(idx_path, encoding='utf-8'))
    except Exception:
        index = []
    index = [r for r in index if r['id'] != run['id']]
    index.insert(0, {'id': run['id'], 'run_at': run['run_at'],
                     'count': len(run.get('posts', [])), 'error': run.get('error')})
    index.sort(key=lambda r: r['run_at'], reverse=True)
    keep, drop = index[:cfg['keep_runs']], index[cfg['keep_runs']:]
    for r in drop:  # 古い回は削除（既定60回＝30日分を保持）
        try:
            os.remove(os.path.join(RUNS_DIR, f'{r["id"]}.json'))
        except FileNotFoundError:
            pass
    with open(idx_path, 'w', encoding='utf-8') as f:
        json.dump(keep, f, ensure_ascii=False, indent=1)


def git_push(run_id):
    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    git('add', 'docs')
    if git('diff', '--cached', '--quiet').returncode == 0:
        log('変更なし（push不要）')
        return
    r = git('commit', '-m', f'返信候補 {run_id}')
    if r.returncode != 0:
        raise RuntimeError(f'git commit 失敗: {r.stderr.strip()}')
    r = git('push', 'origin', 'HEAD')
    if r.returncode != 0:
        raise RuntimeError(f'git push 失敗: {r.stderr.strip()}')
    log('GitHub へ push 完了')


def schedule_next_wake(now, cfg):
    """スリープ中でも次の定時に起きるよう予約（sudoers で pmset をパスワード無し許可済みの前提）"""
    slots = []
    for day in (0, 1):
        for hhmm in cfg['schedule']:
            h, m = map(int, hhmm.split(':'))
            t = (now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
            if t > now + timedelta(minutes=5):
                slots.append(t)
    nxt = min(slots)
    r = subprocess.run(['sudo', '-n', 'pmset', 'schedule', 'wake', nxt.strftime('%m/%d/%Y %H:%M:%S')],
                       capture_output=True, text=True)
    log(f'次回の自動起床を予約: {nxt:%m/%d %H:%M}' if r.returncode == 0
        else f'⚠️ 自動起床の予約に失敗（Macが起動中なら実行されます）: {r.stderr.strip()}')


def notify(msg):
    subprocess.run(['osascript', '-e', f'display notification "{msg}" with title "X返信候補"'],
                   capture_output=True)


def main():
    cfg = load_config()
    no_push = '--no-push' in sys.argv
    now = datetime.now(JST).replace(microsecond=0)
    run_id, slot = run_id_for(now, cfg)
    forced = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--slot=')), None)
    if forced:  # 失敗した定時の回をやり直す: --slot=21:00（範囲の始まりは定時基準、終わりは今）
        h, m = map(int, forced.split(':'))
        slot = now.replace(hour=h, minute=m, second=0)
        if slot > now:
            slot -= timedelta(days=1)
        run_id = slot.strftime('%Y%m%d-%H%M')
    if slot:  # 定時の回は、回ごとの範囲・件数を使う（6:00=12時間・50件、21:00=15時間・30件）
        cfg = dict(cfg, **cfg.get('slots', {}).get(slot.strftime('%H:%M'), {}))
    cutoff = ((slot if forced else now) - timedelta(hours=cfg['window_hours'])).astimezone(timezone.utc)
    run = {'id': run_id, 'run_at': now.isoformat(),
           'window_start': cutoff.astimezone(JST).isoformat(),
           'conditions': {k: cfg[k] for k in ('window_hours', 'min_impressions', 'max_replies', 'top_n',
                                              'exclude_retweets', 'exclude_replies')}}
    log(f'開始 {run_id}（{run["window_start"][5:16]} 以降のポスト）')
    waited = wait_for_network()
    if waited is None:
        log('⚠️ 3分待ってもネットにつながりません（このまま試します）')
    elif waited >= 1:
        log(f'ネット接続を {waited:.0f}秒 待ちました')
    try:
        token = xauth.access_token()
        me_id = xauth.load_secrets().get('me_id')
        posts, inc, reached = fetch_list_posts(token, cfg, cutoff)
        run["posts"], matched = pick_candidates(posts, inc, cfg, cutoff, me_id, now)
        in_window = sum(1 for t in posts if parse_time(t['created_at']) >= cutoff)
        run['stats'] = {'fetched': len(posts), 'in_window': in_window, 'matched': matched,
                        'reached_window': reached,
                        'est_cost_usd': round(len(posts) * cfg['cost_per_post_usd'], 3)}
        log(f'取得 {len(posts)}件（{cfg["window_hours"]}h内 {in_window}件）→ 条件一致 {matched}件 → 候補 {len(run["posts"])}件'
            f'／推定 ${run["stats"]["est_cost_usd"]}')
        if not reached:
            log(f'⚠️ 上限 {cfg["max_posts_per_run"]}件に達したため12時間分を取り切れていません')
        hours = hourly_counts(posts, cutoff, now)
        update_hourly(hours, now)
        log(f'時間帯別の投稿数を記録: {len(hours)}時間分')
        status_msg = f'{len(run["posts"])}件の返信候補を更新しました'
    except xauth.ApiError as e:
        hint = {401: '認証切れ → login.command で再ログイン',
                402: 'APIクレジット不足 → console.x.com でチャージ',
                403: 'リストへのアクセス権なし（持ち主でログインしているか確認）',
                429: 'レート制限 → しばらく待って再実行'}.get(e.status, '')
        run['error'] = f'X API エラー {e.status}{"：" + hint if hint else ""}'
        log(f'❌ {run["error"]}\n{e.body}')
        status_msg = run['error']
    except xauth.AuthError as e:
        run['error'] = str(e).splitlines()[0] + '（login.command で再ログイン）'
        log(f'❌ {e}')
        status_msg = run['error']
    except Exception as e:
        run['error'] = f'予期しないエラー: {e}'
        log(traceback.format_exc())
        status_msg = run['error']

    write_run(run, cfg)
    log(f'docs/runs/{run_id}.json を出力')
    if not no_push:
        try:
            git_push(run_id)
        except Exception as e:
            log(f'❌ {e}')
            status_msg += '（※GitHubへの反映に失敗）'
        schedule_next_wake(now, cfg)
        notify(status_msg)
    return 0 if 'error' not in run else 1


if __name__ == '__main__':
    sys.exit(main())
