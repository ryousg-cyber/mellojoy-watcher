"""
GitHub Actions上で動かす、Mellojoy Japanの在庫監視スクリプト。
在庫復活を検知したら ntfy.sh 経由でスマホにプッシュ通知を送る。
通知をタップすると、Shopifyのカート・パーマリンク機能によって
その場でスマホのブラウザにカート投入された状態のページが開く。
(このスクリプト自身はカート投入や決済を一切行わない)
"""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://www.mellojoyjapan.com"
POLL_INTERVAL_SEC = 1.5
SLEEP_CHECK_INTERVAL_SEC = 60  # 監視開始前の待機中、この間隔で時刻を確認する
JST = ZoneInfo("Asia/Tokyo")
WATCH_START_HOUR_MIN = (11, 59)  # この時刻(JST)から実際の監視(高頻度ポーリング)を始める
HARD_STOP_HOUR_MIN = (12, 20)  # この時刻(JST)になったら諦めて終了

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"


def now_jst() -> datetime:
    return datetime.now(JST)


def today_at(hour: int, minute: int) -> datetime:
    return now_jst().replace(hour=hour, minute=minute, second=0, microsecond=0)


def find_available_variant():
    resp = requests.get(f"{BASE_URL}/products.json?limit=250", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    for product in data.get("products", []):
        for variant in product.get("variants", []):
            if variant.get("available"):
                return {
                    "product_title": product["title"],
                    "variant_id": variant["id"],
                    "price": variant["price"],
                }
    return None


def notify(found: dict) -> None:
    cart_link = f"{BASE_URL}/cart/{found['variant_id']}:1"
    requests.post(
        NTFY_URL,
        data=f"{found['product_title']} (¥{found['price']})\nタップして即カート＆決済へ".encode("utf-8"),
        headers={
            "Title": "Mellojoy 在庫あり！".encode("utf-8"),
            "Priority": "urgent",
            "Tags": "rotating_light",
            "Click": cart_link,
        },
        timeout=10,
    )


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
