import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

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
html = r.text

soup = BeautifulSoup(html, "html.parser")

    title = soup.find("title")
    page_title = title.get_text(strip=True) if title else "Zeros Group Free Giveaway"

    text = soup.get_text("\n", strip=True)

    giveaway_id = make_id(text[:2000])

    return [{
        "id": giveaway_id,
        "title": page_title,
        "url": PAGE_URL,
        "description": text[:400] if text else "New free giveaway page update detected.",
    }]


def send_discord(item):
    embed = {
        "title": item["title"],
        "url": item["url"],
        "description": item["description"],
        "color": 0x00ff99,
        "footer": {
            "text": "Subho's Zeros Group Notifier"
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    payload = {
        "content": "🎁 **New Zeros Group free giveaway/update detected!**",
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
