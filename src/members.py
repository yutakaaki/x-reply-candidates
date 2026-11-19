#!/usr/bin/env python3
"""Xのリストでメンバーを入れ替えたとき、変わった人だけをツールの一覧（data/members.json）に反映する。

  python3 src/members.py +@追加する人 -@外す人 …   # 追加は1人≒$0.01、外すのは無料
  python3 src/members.py                           # 入力を聞かれる（scripts/members.command から）
  python3 src/members.py --all                     # 一覧を全部取り直す（50人で約$0.5）
  python3 src/members.py --check                   # Xのリストの人数と比べるだけ（≒$0.001）
  python3 src/members.py --list                    # ツールの一覧を見るだけ（無料）
"""
import json, os, sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xauth
import run

JST = ZoneInfo('Asia/Tokyo')


def save(cache):
    os.makedirs(run.DATA_DIR, exist_ok=True)
    with open(run.MEMBERS_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def check(token, cfg, me_id, n):
    count = run.list_member_count(token, cfg, me_id)
    run.save_member_count(count, datetime.now(JST).replace(microsecond=0))
    if count is None:
        print('⚠️ リストが見つかりませんでした（config.json の list_id を確認）')
    elif count == n:
        print(f'✅ Xのリストの人数（{count}人）とツールの一覧（{n}人）は一致しています')
    else:
        print(f'⚠️ Xのリストは {count}人、ツールの一覧は {n}人です。追加・削除の伝え漏れがないか確認してください')


def show():
    """ツールの一覧を表示する（APIは使わない）"""
    cache = json.load(open(run.MEMBERS_PATH, encoding='utf-8'))
    ms = sorted(cache['members'], key=lambda m: m['username'].lower())
    print(f'ツールの一覧: {len(ms)}人（一覧を取った日 {cache["fetched_at"][:10]}'
          + (f'、最後に編集 {cache["edited_at"][:10]}' if cache.get('edited_at') else '') + '）')
    for i, m in enumerate(ms, 1):
        print(f'{i:3} @{m["username"]}  {m.get("name", "")}')
    mc = run.load_member_count()
    if mc.get('count') is not None:
        print(f'（Xのリストは {mc["count"]}人: {mc["checked_at"][:10]} 確認）')
    print()


def main():
    cfg = run.load_config()
    args = sys.argv[1:]
    if '--list' in args:
        show()
        return
    if not args and os.path.exists(run.MEMBERS_PATH):
        show()
    token = xauth.access_token()
    me_id = xauth.load_secrets().get('me_id')
    now = datetime.now(JST).replace(microsecond=0)

    if '--all' in args:
        members, _ = run.list_members(token, cfg, now, force=True)
        print(f'一覧を全部取り直しました: {len(members)}人（約${len(members) * cfg.get("cost_per_user_usd", 0.01):.2f}）')
        return
    try:
        cache = json.load(open(run.MEMBERS_PATH, encoding='utf-8'))
    except FileNotFoundError:
        print('一覧がまだありません。--all で全部取り直します')
        members, _ = run.list_members(token, cfg, now, force=True)
        print(f'{len(members)}人')
        return
    if '--check' in args:
        check(token, cfg, me_id, len(cache['members']))
        return

    if not args:
        print(f'いまのツールの一覧: {len(cache["members"])}人')
        print('変わった人を入力してください（例: +@追加する人 -@外す人）。空のままEnterで人数の確認だけ')
        args = input('> ').split()
    adds = [a.lstrip('+').lstrip('@') for a in args if a.startswith('+')]
    removes = {a.lstrip('-').lstrip('@').lower() for a in args if a.startswith('-')}
    unknown = [a for a in args if a[:1] not in '+-']
    if unknown:
        print(f'⚠️ 先頭に + か - が無いものは無視しました: {" ".join(unknown)}')

    members = cache['members']
    if removes:
        before = {m['username'].lower() for m in members}
        members = [m for m in members if m['username'].lower() not in removes]
        for r in removes:
            print(f'－ @{r} を外しました' if r in before else f'⚠️ @{r} は一覧にいません')
    if adds:
        have = {m['id'] for m in members}
        j = xauth.api_get('/users/by', {'usernames': ','.join(adds),
                                        'user.fields': 'username,name,profile_image_url,public_metrics'}, token)
        for u in j.get('data') or []:
            if u['id'] in have:
                print(f'・@{u["username"]} はすでに一覧にいます')
                continue
            members.append({'id': u['id'], 'username': u['username'], 'name': u.get('name', ''),
                            'followers': (u.get('public_metrics') or {}).get('followers_count')})
            print(f'＋ @{u["username"]}（{u.get("name", "")}）を追加しました')
        for e in j.get('errors') or []:
            print(f'⚠️ 見つかりませんでした: {e.get("value") or e.get("detail")}')
        print(f'（追加の確認に約${len(adds) * cfg.get("cost_per_user_usd", 0.01):.2f}）')
    if adds or removes:
        cache['members'] = members
        cache['edited_at'] = now.isoformat()
        save(cache)
    print(f'ツールの一覧: {len(members)}人')
    check(token, cfg, me_id, len(members))


if __name__ == '__main__':
    try:
        main()
    except (xauth.ApiError, xauth.AuthError) as e:
        print(f'❌ {e}')
        sys.exit(1)
