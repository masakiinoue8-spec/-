#!/usr/bin/env python3
"""チャンネルの全投稿履歴（公開データ）を YouTube Data API v3 で取得し、
douga-jisseki.csv と同じカラム構成のCSVに書き出す。

使い方:
    YOUTUBE_API_KEY=xxxx python3 fetch_channel_data.py [--handle kuruma-sall] [-o output.csv]

取得できるのは公開データのみ: タイトル / 公開日 / 再生回数 / 高評価数 / コメント数 / 長さ。
インプレッション・CTR・視聴維持率・登録者増は YouTube Studio のエクスポートでしか取れない。
"""
import argparse
import csv
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

API_BASE = "https://www.googleapis.com/youtube/v3"

# タイトルから車種を推定するためのキーワード（前方一致ではなく部分一致、上から順に判定）
CAR_KEYWORDS = [
    "ジムニーノマド", "ジムニーシエラ", "ジムニー",
    "ランクル300", "ランクル250", "ランクル70", "ランドクルーザー", "ランクル",
    "ヴェルファイア", "アルファード", "ハイエース", "ヴォクシー", "ノア",
    "ライズ", "ハリアー", "RAV4", "ラヴ4", "プラド", "クラウン", "プリウス",
    "アクア", "ヤリス", "カローラ", "シエンタ", "ルーミー",
    "キャラバン", "セレナ", "エクストレイル", "デリカ", "N-BOX", "Nボックス",
    "タント", "スペーシア", "ステップワゴン", "ヴェゼル", "フリード", "フィット",
    "CX-5", "CX-8", "CX-60", "レヴォーグ", "フォレスター", "スイフト",
]

# タイトルからタイプを推定するためのキーワード
TYPE_RULES = [
    ("見積もり公開", ["見積", "値引き額"]),
    ("相場情報", ["相場", "買取", "リセール", "査定額", "下取り価格"]),
    ("売却ノウハウ", ["売却", "売る", "高く売", "下取り", "一括査定", "オークション"]),
    ("購入ノウハウ", ["購入", "値引き", "買う", "納車", "見積書の見方"]),
]


def api_get(endpoint: str, params: dict) -> dict:
    params = {**params, "key": os.environ["YOUTUBE_API_KEY"]}
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as res:
        return json.load(res)


def resolve_channel(handle: str) -> dict:
    data = api_get("channels", {
        "part": "snippet,statistics,contentDetails",
        "forHandle": handle,
    })
    items = data.get("items") or []
    if not items:
        sys.exit(f"チャンネルが見つかりません: @{handle}")
    return items[0]


def list_all_video_ids(uploads_playlist_id: str) -> list:
    ids, page_token = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": uploads_playlist_id, "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        data = api_get("playlistItems", params)
        ids += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids


def fetch_video_details(video_ids: list) -> list:
    videos = []
    for i in range(0, len(video_ids), 50):
        data = api_get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids[i:i + 50]),
        })
        videos += data.get("items", [])
    return videos


def parse_duration_seconds(iso: str) -> int:
    # PT#H#M#S 形式の簡易パース
    h = m = s = 0
    num = ""
    for ch in iso.replace("PT", ""):
        if ch.isdigit():
            num += ch
        else:
            if ch == "H":
                h = int(num or 0)
            elif ch == "M":
                m = int(num or 0)
            elif ch == "S":
                s = int(num or 0)
            num = ""
    return h * 3600 + m * 60 + s


def guess_car(title: str) -> str:
    for kw in CAR_KEYWORDS:
        if kw.lower() in title.lower():
            return kw
    return ""


def guess_type(title: str, is_short: bool) -> str:
    for label, kws in TYPE_RULES:
        if any(kw in title for kw in kws):
            return label
    return "その他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", default="kuruma-sall")
    ap.add_argument("-o", "--output", default="douga-jisseki-fetched.csv")
    args = ap.parse_args()

    if not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit("環境変数 YOUTUBE_API_KEY を設定してください")

    ch = resolve_channel(args.handle)
    stats = ch.get("statistics", {})
    print(f"チャンネル: {ch['snippet']['title']}")
    print(f"登録者数: {stats.get('subscriberCount', '非公開')} / 総再生: {stats.get('viewCount', '?')} / 動画数: {stats.get('videoCount', '?')}")

    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = list_all_video_ids(uploads)
    print(f"動画ID取得: {len(ids)}件")
    videos = fetch_video_details(ids)

    today = datetime.date.today().isoformat()
    rows = []
    for v in videos:
        sn, st = v["snippet"], v.get("statistics", {})
        dur = parse_duration_seconds(v["contentDetails"]["duration"])
        is_short = dur <= 62  # ショート判定の目安。60秒超3分以下のショートは手動で直す
        title = sn["title"]
        rows.append({
            "公開日": sn["publishedAt"][:10],
            "タイトル": title,
            "形式": "ショート" if is_short else "ロング",
            "タイプ": guess_type(title, is_short),
            "車種": guess_car(title),
            "再生回数": st.get("viewCount", ""),
            "数字の取得日": today,
            "インプレッション": "", "CTR": "", "平均視聴維持率": "", "平均視聴時間": "",
            "登録者増": "", "LINE登録数": "",
            "備考": f"高評価{st.get('likeCount', '?')}/コメント{st.get('commentCount', '?')}/長さ{dur}秒/videoId={v['id']}",
        })

    rows.sort(key=lambda r: r["公開日"], reverse=True)
    fields = ["公開日", "タイトル", "形式", "タイプ", "車種", "再生回数", "数字の取得日",
              "インプレッション", "CTR", "平均視聴維持率", "平均視聴時間", "登録者増", "LINE登録数", "備考"]
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"書き出し完了: {args.output}（{len(rows)}行）")


if __name__ == "__main__":
    main()
