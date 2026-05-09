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


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def get_best_image(card):
    images = []

    for img in card.find_all("img"):
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
            "emoji",
            "profile",
            "user"
        ]

        if any(word in full_url.lower() for word in bad_words):
            continue

        images.append(full_url)

    if images:
        return images[0]

    return None


def get_inventory(card_text):
    patterns = [
        r"(\d+)\s*/\s*(\d+)",
        r"(?:剩余库存|库存|剩余|Remaining inventory)\D{0,30}(\d+)\s*/\s*(\d+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, card_text, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)

    return "Unknown", "Unknown"


def fetch_giveaways():
    r = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    giveaways = []
    seen = set()

    cards = soup.find_all("div", class_=lambda x: x and "card" in str(x).lower())

    if not cards:
        cards = soup.find_all(["div", "article", "section"])

    for card in cards:
        card_text = clean_text(card.get_text(" ", strip=True))

        if len(card_text) < 30:
            continue

        image_url = get_best_image(card)

        if not image_url:
            continue

        remaining, total = get_inventory(card_text)

        if remaining == "Unknown" and total == "Unknown":
            continue

        keys_text = f"{remaining} / {total}"

        status = "Available"
        try:
            if int(remaining) <= 0:
                status = "Completed"
        except ValueError:
            status = "Available"

        link_tag = card.find("a", href=True)
        giveaway_url = PAGE_URL

        if link_tag:
            giveaway_url = urljoin(PAGE_URL, link_tag["href"])

        title = "Random Steam Key Giveaway"

        title_candidates = []

        for tag in card.find_all(["h1", "h2", "h3", "h4", "strong", "b", "a"]):
            t = clean_text(tag.get_text(" ", strip=True))

            if not t:
                continue

            bad_title_words = [
                "tasks",
                "task",
                "remaining",
                "inventory",
                "steam",
                "获取链接",
                "验证",
                "请输入",
                "库存",
                "截止"
            ]

            if any(word.lower() in t.lower() for word in bad_title_words):
                continue

            if 8 <= len(t) <= 120:
                title_candidates.append(t)

        if title_candidates:
            original_title = title_candidates[0]
        else:
            original_title = "ZerosGroup Giveaway"

        unique_key = make_id(original_title + keys_text + image_url + giveaway_url)

        if unique_key in seen:
            continue

        seen.add(unique_key)

        giveaways.append({
            "id": unique_key,
            "title": title,
            "original_title": original_title,
            "url": giveaway_url,
            "source": "Subho's ZerosGroup Giveaway",
            "status": status,
            "keys": keys_text,
            "image": image_url,
        })

    if giveaways:
        return giveaways

    return [{
        "id": make_id("fallback"),
        "title": "Random Steam Key Giveaway",
        "original_title": "ZerosGroup Giveaway",
        "url": PAGE_URL,
        "source": "Subho's ZerosGroup Giveaway",
        "status": "Available",
        "keys": "Unknown",
        "image": None,
    }]


def send_discord(item):
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    embed = {
        "title": f"🎁 {item['title']}",
        "url": item["url"],
        "description": f"Source: {item['source']}",
        "color": 0x2ecc71,
        "fields": [
            {
                "name": "Status",
                "value": f"✅ {item['status']}",
                "inline": True
            },
            {
                "name": "Keys",
                "value": f"🔑 {item['keys']}",
                "inline": True
            },
            {
                "name": "Posted",
                "value": f"<t:{now_ts}:R>",
                "inline": True
            }
        ],
        "footer": {
            "text": "Subho's ZerosGroup Giveaway Notifier",
            "icon_url": "https://cdn-icons-png.flaticon.com/512/5968/5968705.png"
        },
        "timestamp": now.isoformat()
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
        print(f"Posted: {item['title']} - {item['keys']}")

    state["posted"] = list(posted)[-200:]
    save_state(state)


if __name__ == "__main__":
    main()
