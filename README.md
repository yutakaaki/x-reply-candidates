# X返信候補

@anime_attention の非公開Xリストに入っているアカウントの投稿から、返信候補を毎日2回自動で抽出するツール。

- **実行**: 毎日 6:00 JST（自宅Macのlaunchd。スリープ中も自動起床）。21:00の回は2026-11-14から休止中
- **対象**: 前日21時〜6時（9時間・上位50件）の投稿 ／ 表示数1,000以上 ／ 返信10件以下 ／ 本人が付けた動画がある投稿だけ（テキストだけ・画像だけ・引用元にだけ動画がある引用・他アカウントの動画を「共有」で貼った投稿は除外） ／ RT・返信ポスト・自分の投稿は除外
- **同じ動画の印**: 以前返信した動画と同じ内容なら「↩︎ 返信済みと同じ動画」、同じ回の候補に同じ動画があれば「⧉ 同じ動画 ほかN件」（動画の指紋で照合。上げ直し・字幕違い・前後カットも一致）
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
| `src/members.py`（`scripts/members.command`） | リストのメンバーを入れ替えたら、変わった人だけ伝える（`+@追加 -@外す`。追加1人≒$0.01、外すのは無料、`--all` で全部取り直し） |
| `src/vfp.py` / `src/dupes.py` | 動画の指紋（1秒ごとのコマのpHash）／返信済み動画の記録と候補への印付け |
| `src/member_report.py`（`scripts/member-report.command`） | リスト見直し用レポート（メンバーごとの候補数・投稿数・表示数・月の費用。API料金なし） |
| `data/` | メンバー一覧・メンバー別の記録・レポート（非公開リストの中身なので**Git管理外**） |
| `docs/index.html` | 閲覧ページ（GitHub Pages） |
| `logs/run.log` | 実行ログ（Git管理外） |

秘密情報（Client Secret・トークン）は **リポジトリ外の `~/.x-reply-candidates/secrets.json`** にのみ保存される。

## 費用の目安

X APIは読み取り1件 ≒ $0.005。メンバー1人ずつ、範囲内の**本人の投稿だけ**を読む（RT・返信はX側で除くので料金がかからない。旧方式より約4割安い）。
範囲内の本人の投稿数 × $0.005 が1回あたりの費用（ページに推定額を表示）。メンバー一覧は自動では取り直さない（毎回リストの人数だけ確認≒$0.001、合わなければ通知）。
返信済みの記録: 前回以降の自分の投稿（1件$0.001）＋返信先（1件$0.005）。1日20件返信で約$0.1。動画のダウンロードと指紋づくりは無料。
`config.json` の `fetch_mode` を `"list"` にすると旧方式（リストのタイムラインをまとめて読む）に戻る。
`config.json` の `max_posts_per_run`（既定600件 ≒ $3）が1回の上限。

## トラブル時

- ページに「⚠️ 401」「再ログイン」→ `login.command` を再実行
- 「⚠️ 402」→ console.x.com でクレジットをチャージ
- 停止: `scripts/uninstall.command`
