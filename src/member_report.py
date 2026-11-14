#!/usr/bin/env python3
"""リストの見直し用レポート: メンバーごとに「候補に入った回数」「投稿数」「表示数」「月の費用」を出す。
  python3 src/member_report.py   → 画面に表示し、data/member_report.md にも保存（Git管理外）

使うデータ（追加のAPI料金はかからない）
  - docs/runs/*.json        … 過去の回で候補に入った投稿（最大60回分）
  - data/members.json       … いまのリストのメンバー（run.py が週1回取り直す）
  - data/member_stats.json  … 11/14以降の回でメンバーごとに読んだ投稿の表示数
"""
import glob, json, os, statistics
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
COST_PER_POST = 0.005


def load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return default


def main():
    members = load(os.path.join(DATA, 'members.json'), {}).get('members', [])
    if not members:
        print('data/members.json がありません。先に run.py を1回実行してください。')
        return 1
    cfg = load(os.path.join(ROOT, 'config.json'), {})
    min_imp = cfg.get('min_impressions', 1000)

    # 過去の回で候補に入った回数（ページに載った投稿）
    runs = sorted(glob.glob(os.path.join(ROOT, 'docs', 'runs', '*.json')))
    ok_runs = 0
    cand = {}
    for f in runs:
        r = load(f, {})
        if r.get('error'):
            continue
        ok_runs += 1
        for p in r.get('posts', []):
            c = cand.setdefault(p['username'].lower(), {'ids': set(), 'best': 0})
            c['ids'].add(p['id'])  # 2回の回にまたがって載った投稿は1件と数える
            c['best'] = max(c['best'], p.get('impressions', 0))
    first_run = os.path.basename(runs[0])[:8] if runs else '—'

    # 11/14以降: メンバーごとの投稿数と表示数
    st_runs = load(os.path.join(DATA, 'member_stats.json'), {}).get('runs', [])
    hours_seen = sum(r['window_hours'] for r in st_runs)
    stats = {}
    for r in st_runs:
        for name, s in r['members'].items():
            a = stats.setdefault(name.lower(), {'imps': [], 'reps': [], 'kinds': ''})
            a['imps'] += s['imps']
            a['reps'] += s['reps']
            a['kinds'] += s.get('kinds', '')

    # 1日に読む時間幅（いまの定時の回の合計。6:00だけなら12時間）
    slots = cfg.get('slots', {})
    read_hours = sum(slots.get(t, {}).get('window_hours', cfg.get('window_hours', 12)) for t in cfg.get('schedule', ['06:00']))
    rows = []
    for m in members:
        key = m['username'].lower()
        c = cand.get(key, {'ids': set(), 'best': 0})
        s = stats.get(key, {'imps': [], 'reps': [], 'kinds': ''})
        per_hour = len(s['imps']) / hours_seen if hours_seen else None
        per_day = per_hour * 24 if per_hour is not None else None
        rows.append({
            'user': m['username'], 'followers': m.get('followers'),
            'cand': len(c['ids']), 'best': c['best'],
            'per_day': per_day,
            'median': statistics.median(s['imps']) if s['imps'] else None,
            'hit': sum(1 for i, rp in zip(s['imps'], s['reps']) if i >= min_imp and rp <= cfg.get('max_replies', 10)),
            'posts': len(s['imps']),
            'video': s['kinds'].count('v') / len(s['kinds']) if s['kinds'] else None,
            'cost_month': per_hour * read_hours * 30 * COST_PER_POST if per_hour is not None else None,
        })
    # 候補に入った回数が少ない順 → 同じなら費用が高い順
    rows.sort(key=lambda r: (r['cand'], -(r['cost_month'] or 0)))

    f = lambda v, fmt: '—' if v is None else format(v, fmt)
    lines = [
        f'# リスト見直しレポート（{datetime.now():%Y-%m-%d %H:%M}）',
        '',
        f'- メンバー {len(members)}人 ／ 候補に載った投稿数は過去 {ok_runs}回分（{first_run}〜）',
        f'- 投稿数・表示数は11/14以降の {len(st_runs)}回分（合計{hours_seen:.0f}時間）。1週間ほどたまると傾向が見えます',
        f'- 月の費用＝いまの定時の回（1日{read_hours}時間分を読む）で、その人の投稿を読む料金',
        f'- 「条件内」＝表示数{min_imp:,}以上・返信10件以下だった投稿の数',
        '',
        '| アカウント | フォロワー | 候補に載った投稿数 | 候補での最高表示数 | 1日の投稿数 | 表示数の中央値 | 条件内/読んだ数 | 動画の割合 | 月の費用 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for r in rows:
        lines.append(f"| @{r['user']} | {f(r['followers'], ',')} | {r['cand']} | {f(r['best'] or None, ',')} | "
                     f"{f(r['per_day'], '.1f')} | {f(r['median'], ',.0f')} | {r['hit']}/{r['posts']} | {'—' if r['video'] is None else format(r['video'], '.0%')} | "
                     f"{'—' if r['cost_month'] is None else '$' + format(r['cost_month'], '.2f')} |")
    total = sum(r['cost_month'] or 0 for r in rows)
    lines += ['', f'月の費用の合計（メンバー一覧の取り直し 週1回≒$0.5 を除く）: 約${total:.1f}']
    kinds = ''.join(s['kinds'] for s in stats.values())
    if kinds:
        v, p_, t_ = (kinds.count(k) / len(kinds) for k in 'vpt')
        lines.append(f'読んだ投稿の内訳（{len(kinds)}件）: 動画・GIF {v:.0%} ／ 画像だけ {p_:.0%} ／ テキストだけ {t_:.0%}'
                     f' → 動画だけを読む方式にすると約{1 - v:.0%}安くなる見込み')
    out = '\n'.join(lines)
    print(out)
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, 'member_report.md'), 'w', encoding='utf-8') as fp:
        fp.write(out + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
