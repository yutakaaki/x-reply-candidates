# X返信候補

@anime_attention の非公開Xリストに入っているアカウントの投稿から、返信候補を毎日2回自動で抽出するツール。

- **実行**: 毎日 6:00 JST（自宅Macのlaunchd。スリープ中も自動起床）。21:00の回は2026-11-14から休止中
- **対象**: 前日21時〜6時（9時間・上位50件）の投稿 ／ 表示数1,000以上 ／ 返信10件以下 ／ RT・返信ポスト・自分の投稿は除外
- **出力**: 表示数の上位件数＋伸びが速い投稿 → https://yutakaaki.github.io/x-reply-candidates/
  - 「返信する」でXの返信画面が開く。「済」で対応済みに印（端末ごとに保存）

## 初回セットアップ

1. console.x.com → アプリ → **User authentication settings** を設定
   - App permissions: **Read** ／ Type of App: **Web App, Automated App or Bot**
   - Callback URI: `http://127.0.0.1:5573/callback` ／ Website URL: `https://x.com/anime_attention`
   - 保存後に表示される **Client ID / Client Secret** を控える
2. `scripts/login.command` をダブルクリック → Client ID/Secret を入力 → ブラウザで **@anime_attention として許可**
3. `scripts/run-now.command` で1回試す → ページを確認
4. `scripts/install.command` で定時実行を登録

## ファイル

| パス | 役割 |
|---|---|
| `config.json` | 抽出条件（時間幅・表示数・返信数・件数・取得上限） |
| `src/run.py` | 抽出 → `docs/runs/*.json` 出力 → GitHubへpush → 次回起床予約 |
| `src/login.py` / `src/xauth.py` | OAuth 2.0（PKCE）ログインとトークン自動更新 |
| `src/member_report.py`（`scripts/member-report.command`） | リスト見直し用レポート（メンバーごとの候補数・投稿数・表示数・月の費用。API料金なし） |
| `data/` | メンバー一覧・メンバー別の記録・レポート（非公開リストの中身なので**Git管理外**） |
| `docs/index.html` | 閲覧ページ（GitHub Pages） |
| `logs/run.log` | 実行ログ（Git管理外） |

秘密情報（Client Secret・トークン）は **リポジトリ外の `~/.x-reply-candidates/secrets.json`** にのみ保存される。

## 費用の目安

X APIは読み取り1件 ≒ $0.005。メンバー1人ずつ、範囲内の**本人の投稿だけ**を読む（RT・返信はX側で除くので料金がかからない。旧方式より約4割安い）。
12時間分の本人の投稿数 × $0.005 が1回あたりの費用（ページに推定額を表示）。メンバー一覧の取り直し（1人≒$0.01）は週1回。
`config.json` の `fetch_mode` を `"list"` にすると旧方式（リストのタイムラインをまとめて読む）に戻る。
`config.json` の `max_posts_per_run`（既定600件 ≒ $3）が1回の上限。

## トラブル時

- ページに「⚠️ 401」「再ログイン」→ `login.command` を再実行
- 「⚠️ 402」→ console.x.com でクレジットをチャージ
- 停止: `scripts/uninstall.command`
