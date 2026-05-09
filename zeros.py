import os
import json
import hashlib
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urljoin

PAGE_URL = "http://zeros.group/free/"
STATE_FILE = "posted_zeros.json"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

HEADERS = {
    "User-Agent": "Mozilla/5.0 GiveawayNotifier/1.0"
}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"posted": []}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def make_id(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fetch_giveaways():
    r = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else "ZerosGroup Giveaway"

    text = soup.get_text("\n", strip=True)

    image_url = None
    images = []

    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue

        full_url = urljoin(PAGE_URL, src)

        bad_words = [
            "avatar",
            "logo",
            "icon",
            "steamcommunity",
            "default",
            "emoji"
        ]

        if any(word in full_url.lower() for word in bad_words):
            continue

        images.append(full_url)

    if images:
        image_url = images[-1]

    key_amount = "Unknown"

    patterns = [
        r"(\d{2,6})\s*(?:keys|key|份|个|枚|激活码)",
        r"(?:剩余|库存|数量|发放)\D{0,10}(\d+)",
        r"🔑\s*(\d+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            key_amount = match.group(1)
            break

    giveaway_id = make_id(page_title + text[:1000] + str(image_url))

    return [{
        "id": giveaway_id,
        "title": page_title,
        "url": PAGE_URL,
        "source": "Subho's ZerosGroup Giveaway",
        "status": "Available",
        "keys": key_amount,
        "image": image_url,
    }]


def send_discord(item):
    embed = {
        "title": f"🎁 {item['title']}",
        "url": item["url"],
        "description": f"来自： {item['source']}",
        "color": 0x2ecc71,
        "fields": [
            {
                "name": f"✅ {item['status']}  |  🔑 {item['keys']}",
                "value": "\u200b",
                "inline": False
            }
        ],
        "footer": {
            "text": "ZerosGroup Giveaway Notifier"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if item.get("image"):
        embed["image"] = {"url": item["image"]}

    payload = {
        "embeds": [embed]
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=30)
    res.raise_for_status()


def main():
    if not WEBHOOK_URL:
        raise RuntimeError("DISCORD_WEBHOOK_URL secret is missing")

    state = load_state()
    posted = set(state.get("posted", []))

    items = fetch_giveaways()
    new_items = [item for item in items if item["id"] not in posted]

    if not new_items:
        print("No new Zeros Group giveaway updates.")
        return

    for item in new_items:
        send_discord(item)
        posted.add(item["id"])
        print(f"Posted: {item['title']}")

    state["posted"] = list(posted)[-100:]
    save_state(state)


if __name__ == "__main__":
    main()
