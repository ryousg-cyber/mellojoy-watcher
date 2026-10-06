"""
GitHub Actions上で動かす、Mellojoy Japanの在庫監視スクリプト。
在庫復活を検知したら ntfy.sh 経由でスマホにプッシュ通知を送る。
通知をタップすると、Shopifyのカート・パーマリンク機能によって
その場でスマホのブラウザにカート投入された状態のページが開く。
(このスクリプト自身はカート投入や決済を一切行わない)
"""
import os
import socket
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import urllib3.util.connection as urllib3_cn

# GitHub Actionsランナーで、IPv6経路が使えず"Network is unreachable"に
# なることがある(実際に2026-09-18に発生し、通知処理がクラッシュした)。
# DNS解決をIPv4のみに限定し、この種の失敗を避ける。
def _allowed_gai_family():
    return socket.AF_INET


urllib3_cn.allowed_gai_family = _allowed_gai_family

BASE_URL = "https://www.mellojoyjapan.com"
POLL_INTERVAL_SEC = 1.0
SLEEP_CHECK_INTERVAL_SEC = 60  # 監視開始前の待機中、この間隔で時刻を確認する
JST = ZoneInfo("Asia/Tokyo")
WATCH_START_HOUR_MIN = (11, 59)  # この時刻(JST)から実際の監視(高頻度ポーリング)を始める
HARD_STOP_HOUR_MIN = (12, 20)  # この時刻(JST)になったら諦めて終了
NOTIFY_MAX_RETRIES = 5
NOTIFY_RETRY_WAIT_SEC = 3

# 優先して狙う商品(Shopifyのhandle)。上から順に優先度が高い。
# 全部売り切れのままなら、他の商品が復活した時点でそれを採用する(フォールバック)。
# 2026-10-06時点でカタログが入れ替わったため、対象商品を再設定(旧:バター・うさぎ桜餅)。
TARGET_HANDLES = [
    "mellojoy-にぎにぎおにぎり-a032-開封後のキャンセルができません-ブラインドボックスのおもちゃ",  # 優先1: にぎにぎおにぎり【A032】
    "a025-開封後のキャンセルができません-ブラインドボックスのおもちゃ-アニマルシリーズ-副本",  # 優先2: メロジョイクリームまみれ大福シリーズ【A026】
]

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"


def now_jst() -> datetime:
    return datetime.now(JST)


def today_at(hour: int, minute: int) -> datetime:
    return now_jst().replace(hour=hour, minute=minute, second=0, microsecond=0)


def _first_available_variant(product: dict):
    for variant in product.get("variants", []):
        if variant.get("available"):
            return {
                "product_title": product["title"],
                "variant_id": variant["id"],
                "price": variant["price"],
            }
    return None


def find_available_variant():
    resp = requests.get(f"{BASE_URL}/products.json?limit=250", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    products_by_handle = {p["handle"]: p for p in data.get("products", [])}

    # 優先対象を順番にチェック
    for handle in TARGET_HANDLES:
        product = products_by_handle.get(handle)
        if not product:
            continue
        found = _first_available_variant(product)
        if found:
            return found

    # 優先対象がどちらも無ければ、他の商品にフォールバック
    for product in data.get("products", []):
        found = _first_available_variant(product)
        if found:
            return found
    return None


def notify(found: dict) -> None:
    cart_link = f"{BASE_URL}/cart/{found['variant_id']}:1"
    # 通知が最後まで送れなくても、ログにさえ残ればここから手動で開ける保険
    print(f"[{now_jst()}] カートリンク(手動フォールバック用): {cart_link}")

    payload = f"{found['product_title']} (¥{found['price']})\nタップして即カート＆決済へ".encode("utf-8")
    headers = {
        "Title": "Mellojoy 在庫あり！".encode("utf-8"),
        "Priority": "urgent",
        "Tags": "rotating_light",
        "Click": cart_link,
    }

    last_error = None
    for attempt in range(1, NOTIFY_MAX_RETRIES + 1):
        try:
            requests.post(NTFY_URL, data=payload, headers=headers, timeout=10)
            print(f"[{now_jst()}] ntfy通知を送信しました(試行{attempt}回目)。")
            return
        except requests.RequestException as e:
            last_error = e
            print(f"[{now_jst()}] ntfy送信失敗(試行{attempt}/{NOTIFY_MAX_RETRIES}回目): {e}")
            if attempt < NOTIFY_MAX_RETRIES:
                time.sleep(NOTIFY_RETRY_WAIT_SEC)

    raise RuntimeError(f"ntfy通知に{NOTIFY_MAX_RETRIES}回失敗しました。最後のエラー: {last_error}")


def main() -> None:
    watch_start = today_at(*WATCH_START_HOUR_MIN)
    hard_stop = today_at(*HARD_STOP_HOUR_MIN)
    print(f"[{now_jst()}] ジョブ起動。監視開始予定: {watch_start} / 締切: {hard_stop}")

    while now_jst() < watch_start:
        remaining = (watch_start - now_jst()).total_seconds()
        time.sleep(min(SLEEP_CHECK_INTERVAL_SEC, max(remaining, 0)))

    print(f"[{now_jst()}] 高頻度ポーリングを開始します。")

    while now_jst() < hard_stop:
        try:
            found = find_available_variant()
        except requests.RequestException as e:
            print(f"[{now_jst()}] 通信エラー(継続): {e}")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        if found:
            print(f"[{now_jst()}] 在庫発見: {found['product_title']} (¥{found['price']})")
            notify(found)
            print(f"[{now_jst()}] ntfy通知を送信しました。終了します。")
            return

        time.sleep(POLL_INTERVAL_SEC)

    print(f"[{now_jst()}] 締切に達しました。本日はここで終了します。")


if __name__ == "__main__":
    main()
