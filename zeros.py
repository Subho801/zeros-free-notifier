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


def fetch_giveaways():
    r = requests.get(PAGE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    giveaways = []

    cards = soup.find_all(["div", "article", "section"])

    for card in cards:
        card_text = clean_text(card.get_text(" ", strip=True))

        if "Remaining inventory" not in card_text:
            continue

        inventory_match = re.search(r"Remaining inventory\s*(\d+)\s*/\s*(\d+)", card_text, re.IGNORECASE)

        if inventory_match:
            remaining = inventory_match.group(1)
            total = inventory_match.group(2)
            keys_text = f"{remaining} / {total}"
        else:
            remaining = "Unknown"
            total = "Unknown"
            keys_text = "Unknown"

        img_tag = card.find("img")
        image_url = None
        if img_tag and img_tag.get("src"):
            image_url = urljoin(PAGE_URL, img_tag.get("src"))

        link_tag = card.find("a", href=True)
        giveaway_url = PAGE_URL
        if link_tag:
            giveaway_url = urljoin(PAGE_URL, link_tag["href"])

        possible_title = None

        for tag in card.find_all(["h1", "h2", "h3", "h4", "strong", "b", "a"]):
            t = clean_text(tag.get_text(" ", strip=True))
            if len(t) > 10 and "Remaining inventory" not in t and "tasks" not in t.lower():
                possible_title = t
                break

        if not possible_title:
            title_match = re.search(r"(\[[^\]]+\].{10,120})", card_text)
            possible_title = title_match.group(1) if title_match else "Random Steam Key Giveaway"

        status = "Available"
        if remaining != "Unknown" and int(remaining) <= 0:
            status = "Completed"

        giveaway_id = make_id(possible_title + giveaway_url)

        giveaways.append({
            "id": giveaway_id,
            "title": "Random Steam Key Giveaway",
            "original_title": possible_title,
            "url": giveaway_url,
            "source": "Subho's ZerosGroup Giveaway",
            "status": status,
            "keys": keys_text,
            "image": image_url,
        })

    if not giveaways:
        raise RuntimeError("No giveaway cards found. Website layout may have changed.")

    return giveaways


def send_discord(item):
    now_ts = int(datetime.now(timezone.utc).timestamp())

    embed = {
        "title": f"🎁 {item['title']}",
        "url": item["url"],
        "description": f"**{item['original_title']}**\nSource: {item['source']}",
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
        print(f"Posted: {item['original_title']}")

    state["posted"] = list(posted)[-200:]
    save_state(state)


if __name__ == "__main__":
    main()
