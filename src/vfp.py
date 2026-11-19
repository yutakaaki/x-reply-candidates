"""動画の「指紋」を作って比べる（同じ動画が別アカウントで上げ直されたかを見分けるため）。

1秒ごとのコマを 32x32 の白黒に縮め、明るさの模様を64ビットの数（pHash）にする。
画質・サイズが変わっても、同じ場面ならほぼ同じ数になる。
2本の動画で「ほぼ同じコマ」が多ければ同じ動画とみなす（前後を切った・字幕を載せた程度なら一致する）。
動画そのものは保存しない（指紋だけを data/ に残す）。
"""
import os, tempfile, urllib.request

import numpy as np

MAX_SECONDS = 180      # 長い動画も最初の3分だけ見る
FRAME_DIST  = 10       # コマ同士の違いがこのビット数以下なら「同じ場面」
MIN_SHARE   = 0.5      # 短い方の動画のコマの半分以上が一致したら同じ動画
MIN_FRAMES  = 3        # ただし一致したコマが3つ未満なら判定しない（短すぎる動画の誤判定よけ）


def _dct_matrix(n=32):
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n))
    m[0] *= 1 / np.sqrt(2)
    return m * np.sqrt(2 / n)


_D = _dct_matrix()


def phash(gray32):
    """32x32 の白黒画像 → 64ビットの数。真っ黒・真っ白など模様の無いコマは None（何とでも一致してしまうため）"""
    if gray32.std() < 6:
        return None
    with np.errstate(all='ignore'):  # macOS の numpy は行列計算で誤った警告を出すことがある（値は正しい）
        c = _D @ gray32 @ _D.T
    if not np.isfinite(c).all():
        return None
    low = c[:8, :8].flatten()[1:]          # 一番左上（全体の明るさ）は除く
    bits = low > np.median(low)
    return int(''.join('1' if b else '0' for b in bits), 2)


def fingerprint_file(path):
    """動画ファイル → 1秒ごとのコマの pHash の一覧"""
    import av  # PyAV（pip install --user av）。無ければ指紋づくりだけ失敗し、抽出は続ける
    out, next_t = [], 0.0
    with av.open(path) as c:
        stream = c.streams.video[0]
        stream.thread_type = 'AUTO'
        for frame in c.decode(stream):
            t = float(frame.time or 0)
            if t > MAX_SECONDS:
                break
            if t + 1e-6 < next_t:
                continue
            next_t = t + 1.0
            img = frame.to_image().convert('L').resize((32, 32))
            h = phash(np.asarray(img, dtype=np.float64))
            if h is not None:
                out.append(h)
    return out


def fingerprint_url(url, timeout=60):
    """動画のURL（video.twimg.com の mp4）をダウンロードして指紋を作る。X APIの料金はかからない"""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})  # Referer は付けない（付けると403）
    fd, tmp = tempfile.mkstemp(suffix='.mp4')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, os.fdopen(fd, 'wb') as f:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                f.write(b)
        return fingerprint_file(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


_POP = np.array([bin(i).count('1') for i in range(256)], dtype=np.uint8)


def _dist(a, b):
    """コマの指紋どうしの違い（ビット数）を総当たりで計算: len(a) x len(b) の表"""
    x = np.ascontiguousarray(a[:, None] ^ b[None, :])
    return _POP[x.view(np.uint8)].reshape(len(a), len(b), 8).sum(-1, dtype=np.uint8)


class Bank:
    """照合相手の動画（返信済みの動画など）をまとめて持ち、1本の動画と一度に比べる"""

    def __init__(self, items):
        """items: [(名前, 指紋のリスト)]。指紋の無いものは除く"""
        items = [(k, fp) for k, fp in items if fp]
        self.keys = [k for k, _ in items]
        self.lens = np.array([len(fp) for _, fp in items], dtype=np.int64)
        self.frames = np.array([h for _, fp in items for h in fp], dtype=np.uint64)
        self.owner = np.repeat(np.arange(len(items)), self.lens) if items else np.array([], dtype=np.int64)

    def match(self, fp, chunk=20000):
        """fp と一致する動画を [(名前, 一致の割合)] で返す（割合の高い順）"""
        if not fp or not self.keys:
            return []
        a = np.array(fp, dtype=np.uint64)
        n, k = len(a), len(self.keys)
        best_a = np.full((n, k), 255, dtype=np.uint8)              # a の各コマと、各動画の一番近いコマとの違い
        hit_b = np.zeros(k, dtype=np.int64)                         # 各動画のコマのうち a に一致したものの数
        for s in range(0, len(self.frames), chunk):
            d = _dist(a, self.frames[s:s + chunk])
            own = self.owner[s:s + chunk]
            for o in np.unique(own):
                cols = own == o
                best_a[:, o] = np.minimum(best_a[:, o], d[:, cols].min(1))
                hit_b[o] += int((d[:, cols].min(0) <= FRAME_DIST).sum())
        hit_a = (best_a <= FRAME_DIST).sum(0)
        out = []
        for o in range(k):
            # 短い方の動画を基準に「何割のコマが相手にもあるか」
            hit, base = (hit_a[o], n) if n <= self.lens[o] else (hit_b[o], self.lens[o])
            share = hit / base
            if hit >= MIN_FRAMES and share >= MIN_SHARE:
                out.append((self.keys[o], round(float(share), 2)))
        return sorted(out, key=lambda x: -x[1])


def match_score(a, b):
    """2本の動画の一致の割合（短い方に対する割合。一致と言えなければ 0）"""
    m = Bank([('b', b)]).match(a)
    return m[0][1] if m else 0.0


def smallest_mp4(media):
    """X の media オブジェクトから、一番軽い mp4 のURL（指紋づくりは低画質で十分）"""
    mp4s = [v for v in media.get('variants', []) if v.get('content_type') == 'video/mp4']
    return min(mp4s, key=lambda v: v.get('bit_rate', 0))['url'] if mp4s else None
