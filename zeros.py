import os
import json
import time
import hashlib
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

PAGE_URL = "http://zeros.group/free/"
STATE_FILE = "posted_zeros.json"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

FOOTER_ICON = "https://cdn-icons-png.flaticon.com/512/5968/5968705.png"


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


def get_page_html():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1400, "height": 1000},
            user_agent="Mozilla/5.0 GiveawayNotifier/1.0"
        )

        page.goto(PAGE_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        html = page.content()

        browser.close()
        return html


def find_card_container(img):
    parent = img.parent

    for _ in range(8):
        if not parent:
            break

        text = clean_text(parent.get_text(" ", strip=True))

        if re.search(r"\d+\s*/\s*\d+", text) and len(text) > 30:
            return parent

        parent = parent.parent

    return None


def extract_title(card_text):
    text = card_text

    text = re.sub(r"Completed", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Remaining inventory.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+\s*/\s*\d+.*", "", text)
    text = clean_text(text)

    if len(text) > 140:
        text = text[:140] + "..."

    if not text:
        return "Random Steam Key Giveaway"

    return text


def fetch_giveaways():
    html = get_page_html()
    soup = BeautifulSoup(html, "html.parser")

    giveaways = []
    seen_cards = set()

    for img in soup.find_all("img"):
        src = img.get("src")

        if not src:
            continue

        image_url = urljoin(PAGE_URL, src)

        width = img.get("width")
        height = img.get("height")

        try:
            width = int(width) if width else 0
            height = int(height) if height else 0
        except:
            width = 0
            height = 0

        # Skip tiny/wrong images
        if width and height and width < 250:
            continue

        bad_words = [
            "avatar",
            "logo",
            "icon",
            "emoji",
            "profile",
            "user"
        ]

        if any(word in image_url.lower() for word in bad_words):
            continue

        card = find_card_container(img)

        if not card:
            continue

        card_text = clean_text(card.get_text(" ", strip=True))

        inventory_match = re.search(r"(\d+)\s*/\s*(\d+)", card_text)

        if not inventory_match:
            continue

        remaining = inventory_match.group(1)
        total = inventory_match.group(2)
        keys_text = f"{remaining} / {total}"

        original_title = extract_title(card_text)

        link_tag = card.find("a", href=True)
        giveaway_url = PAGE_URL

        if link_tag:
            giveaway_url = urljoin(PAGE_URL, link_tag["href"])

        status = "Available"
        embed_color = 0x2ecc71

        try:
            if int(remaining) <= 0:
                status = "Expired"
                embed_color = 0xe74c3c
        except ValueError:
            pass

        base_id = make_id(image_url + giveaway_url)
        unique_id = f"{base_id}_{status}"
        
        if unique_id in seen_cards:
            continue

        seen_cards.add(unique_id)

        giveaways.append({
            "id": unique_id,
            "title": "Random Steam Key Giveaway",
            "original_title": original_title,
            "url": giveaway_url,
            "source": "Subho's ZerosGroup Giveaway",
            "status": status,
            "keys": keys_text,
            "image": image_url,
            "color": embed_color,
        })

    if not giveaways:
        raise RuntimeError("No giveaway cards found after rendering page with Playwright.")

    return giveaways


def send_discord(item):
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    status_icon = "✅" if item["status"] == "Available" else "❌"

    embed = {
        "title": f"🎁 {item['title']}",
        "url": item["url"],
        "description": "",
        "color": item["color"],
        "fields": [
            {
                "name": "Status",
                "value": f"{status_icon} {item['status']}",
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
            "icon_url": "https://files.catbox.moe/qttqpy.png"
        },
        "timestamp": now.isoformat()
    }

    if item.get("image"):
        embed["image"] = {"url": item["image"]}

    payload = {
        "embeds": [embed]
    }

    res = requests.post(WEBHOOK_URL, json=payload, timeout=30)

    if res.status_code == 429:
        retry_after = res.json().get("retry_after", 5)
        print(f"Rate limited. Sleeping {retry_after} seconds...")
        time.sleep(float(retry_after) + 1)

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

    for item in new_items[:3]:
        send_discord(item)
        posted.add(item["id"])
        print(f"Posted: {item['title']} - {item['keys']} - {item['status']}")
        time.sleep(3)

    state["posted"] = list(posted)[-300:]
    save_state(state)


if __name__ == "__main__":
    main()
