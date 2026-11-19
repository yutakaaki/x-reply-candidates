"""同じ動画の見分け: 返信済みの動画の記録と、候補への印付け。

- data/replied.json   … 自分が返信した動画ポストの記録（動画の指紋つき）。導入した時点以降の返信だけ
- data/fp_cache.json  … 候補の動画の指紋（同じ動画を何度もダウンロードしないため。3週間で消す）
どちらも Git 管理外（data/）。
"""
import json, os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import vfp
import xauth

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, 'data')
REPLIED = os.path.join(DATA_DIR, 'replied.json')
FP_CACHE = os.path.join(DATA_DIR, 'fp_cache.json')

COST_OWNED_POST = 0.001   # 自分の投稿の読み取り
COST_POST = 0.005         # 他人の投稿の読み取り


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


class FpCache:
    def __init__(self, now, keep_days=21):
        self.now = now
        self.data = _load(FP_CACHE, {})
        oldest = (now - timedelta(days=keep_days)).isoformat()
        self.data = {k: v for k, v in self.data.items() if v.get('at', '') >= oldest}

    def get_many(self, items, log=print):
        """items: {media_key: mp4のURL} → {media_key: 指紋}。キャッシュに無いものだけダウンロードする"""
        todo = {k: u for k, u in items.items() if k not in self.data and u}

        def work(k):
            try:
                return k, vfp.fingerprint_url(todo[k])
            except Exception as e:
                log(f'  動画の指紋づくりに失敗（{k}）: {e}')
                return k, None

        with ThreadPoolExecutor(6) as ex:
            for k, fp in ex.map(work, todo):
                if fp is not None:
                    self.data[k] = {'fp': fp, 'at': self.now.isoformat()}
        return {k: (self.data.get(k) or {}).get('fp') for k in items}

    def save(self):
        _save(FP_CACHE, self.data)


def update_replied(token, me_id, now, cache, log=print):
    """前回以降の自分の返信を読み、返信先が動画ポストなら指紋つきで記録する。(新しい返信数, 費用)"""
    state = _load(REPLIED, {})
    if not state.get('since_time'):  # 初回: ここから先の返信だけを記録する（さかのぼらない）
        state = {'since_time': now.isoformat(), 'since_id': None, 'videos': []}
        _save(REPLIED, state)
        log('返信済みの記録を開始しました（これからの返信が対象）')
        return 0, 0.0
    params = {'max_results': 100, 'exclude': 'retweets',
              'tweet.fields': 'created_at,referenced_tweets,author_id,attachments',
              'expansions': 'referenced_tweets.id,referenced_tweets.id.author_id,'
                            'referenced_tweets.id.attachments.media_keys',
              'media.fields': 'type,variants,duration_ms',
              'user.fields': 'username'}
    if state.get('since_id'):
        params['since_id'] = state['since_id']
    else:
        params['start_time'] = datetime.fromisoformat(state['since_time']).astimezone(
            timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    mine, tweets, media, users, newest, next_token = [], {}, {}, {}, None, None
    while True:
        p = dict(params)
        if next_token:
            p['pagination_token'] = next_token
        j = xauth.api_get(f'/users/{me_id}/tweets', p, token)
        mine += j.get('data') or []
        inc = j.get('includes') or {}
        tweets.update({t['id']: t for t in inc.get('tweets', [])})
        media.update({m['media_key']: m for m in inc.get('media', [])})
        users.update({u['id']: u['username'] for u in inc.get('users', [])})
        meta = j.get('meta') or {}
        newest = newest or meta.get('newest_id')
        next_token = meta.get('next_token')
        if not next_token:
            break
    cost = len(mine) * COST_OWNED_POST + len(tweets) * COST_POST
    known = {v['post_id'] for v in state['videos']}
    new = {}
    for t in mine:
        target = next((r['id'] for r in t.get('referenced_tweets') or [] if r['type'] == 'replied_to'), None)
        tt = tweets.get(target)
        if not tt or target in known or tt.get('author_id') == me_id:
            continue
        for key in (tt.get('attachments') or {}).get('media_keys', []):
            m = media.get(key) or {}
            if m.get('type') not in ('video', 'animated_gif'):
                continue
            uname = users.get(tt.get('author_id'), 'i')
            new[key] = {'post_id': target, 'username': uname,
                        'post_url': f'https://x.com/{uname}/status/{target}',
                        'reply_id': t['id'], 'replied_at': t['created_at'], 'media_key': key,
                        'duration': round((m.get('duration_ms') or 0) / 1000),
                        '_mp4': vfp.smallest_mp4(m)}
            known.add(target)
            break  # 1つの投稿につき最初の動画だけ
    fps = cache.get_many({k: v['_mp4'] for k, v in new.items()}, log)
    for k, v in new.items():
        v.pop('_mp4')
        v['fp'] = fps.get(k) or []
        state['videos'].append(v)
    state['videos'] = state['videos'][-3000:]
    if newest:
        state['since_id'] = newest
    _save(REPLIED, state)
    log(f'自分の投稿 {len(mine)}件を確認 → 返信済みの動画を {len(new)}件 記録（計 {len(state["videos"])}件）')
    return len(new), cost


def label(posts, cache, log=print):
    """候補に印を付ける。
    p['replied']  … 以前返信した動画と同じ（返信先の投稿・一致の割合）
    p['same_as']  … この回の候補の中に同じ動画がほかにもある（その投稿の一覧）"""
    vids = {p['id']: p.pop('_vid') for p in posts if p.get('_vid')}
    fps = cache.get_many({v['media_key']: v['mp4'] for v in vids.values()}, log)
    cand_fp = {pid: fps.get(v['media_key']) for pid, v in vids.items()}

    replied = _load(REPLIED, {}).get('videos', [])
    by_key = {r['media_key']: r for r in replied}
    bank = vfp.Bank([(i, r.get('fp')) for i, r in enumerate(replied)])
    n_rep = n_dup = 0
    for p in posts:
        v = vids.get(p['id'])
        if not v:
            continue
        hit = None
        if v['media_key'] in by_key:   # 同じ動画ファイル（同じ投稿・共有された動画）
            hit = (by_key[v['media_key']], 1.0)
        else:
            m = bank.match(cand_fp.get(p['id']))
            if m:
                hit = (replied[m[0][0]], m[0][1])
        if hit:
            r, share = hit
            p['replied'] = {'post_url': r['post_url'], 'username': r['username'],
                            'replied_at': r['replied_at'], 'same_post': r['post_id'] == p['id'],
                            'share': share}
            n_rep += 1

    # 同じ回の候補どうし
    ids = [pid for pid in cand_fp if cand_fp[pid]]
    bank = vfp.Bank([(pid, cand_fp[pid]) for pid in ids])
    by_id = {p['id']: p for p in posts}
    for pid in ids:
        others = [k for k, _ in bank.match(cand_fp[pid]) if k != pid]
        if others:
            by_id[pid]['same_as'] = [{'id': k, 'username': by_id[k]['username'], 'url': by_id[k]['url']}
                                     for k in others]
            n_dup += 1
    log(f'同じ動画の照合: 返信済みと同じ {n_rep}件／候補内で重複 {n_dup}件（動画 {len(ids)}/{len(vids)}本を照合）')
    return {'replied_match': n_rep, 'dup_in_run': n_dup, 'fingerprinted': len(ids)}
