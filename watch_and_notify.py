"""
GitHub Actions上で動かす、Mellojoy Japanの在庫監視スクリプト。
在庫復活を検知したら ntfy.sh 経由でスマホにプッシュ通知を送る。
通知をタップすると、Shopifyのカート・パーマリンク機能によって
その場でスマホのブラウザにカート投入された状態のページが開く。
(このスクリプト自身はカート投入や決済を一切行わない)
"""
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://www.mellojoyjapan.com"
POLL_INTERVAL_SEC = 1.5
JST = ZoneInfo("Asia/Tokyo")
HARD_STOP_HOUR_MIN = (12, 12)  # この時刻(JST)になったら諦めて終了

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"


def now_jst() -> datetime:
    return datetime.now(JST)


def past_hard_stop() -> bool:
    n = now_jst()
    return (n.hour, n.minute) >= HARD_STOP_HOUR_MIN


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
    print(f"[{now_jst()}] 監視開始。締切: JST {HARD_STOP_HOUR_MIN[0]:02d}:{HARD_STOP_HOUR_MIN[1]:02d}")

    if past_hard_stop():
        print(f"[{now_jst()}] すでに締切を過ぎているため終了します。")
        sys.exit(0)

    while not past_hard_stop():
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
