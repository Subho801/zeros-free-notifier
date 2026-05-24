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

FOOTER_ICON = "https://files.catbox.moe/qttqpy.png"


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


def deadline_to_discord(deadline_text):
    if not deadline_text or deadline_text == "Unknown":
        return "Unknown"

    match = re.search(
        r"(\d+)\s*(?:days|天)\s*([0-9]{1,2}):([0-9]{2}):([0-9]{2})",
        deadline_text,
        re.IGNORECASE
    )

    if not match:
        return deadline_text.replace("天", " days")

    days = int(match.group(1))
    hours = int(match.group(2))
    minutes = int(match.group(3))
    seconds = int(match.group(4))

    future_ts = int(time.time()) + days * 86400 + hours * 3600 + minutes * 60 + seconds
    return f"<t:{future_ts}:R>"


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

    for _ in range(10):
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

    if len(text) > 120:
        text = text[:120] + "..."

    if not text:
        return "Random Steam Key Giveaway"

    return text


def get_deadline(card_text):
    patterns = [
        r"(?:As of|Deadline|截止)\s*[:：]?\s*([0-9]+\s*days?\s*[0-9:]+)",
        r"(?:As of|Deadline|截止)\s*[:：]?\s*([0-9]+\s*天\s*[0-9:]+)",
        r"([0-9]+\s*days?\s*[0-9:]+)",
        r"([0-9]+\s*天\s*[0-9:]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, card_text, re.IGNORECASE)
        if match:
            return clean_text(match.group(1))

    return "Unknown"


def is_good_image(image_url):
    image_url_lower = image_url.lower()

    return (
        image_url_lower.startswith("http://zeros.group/free/random")
        or image_url_lower.startswith("https://zeros.group/free/random")
        or "shared.akamai.steamstatic.com/store_item_assets" in image_url_lower
        or "cdn.akamai.steamstatic.com/steam/apps" in image_url_lower
    )


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

        if not is_good_image(image_url):
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

        deadline = get_deadline(card_text)
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

        base_id = make_id(giveaway_url + total)
        unique_id = f"{base_id}_{status}"

        if unique_id in seen_cards:
            continue

        seen_cards.add(unique_id)

        giveaways.append({
            "id": unique_id,
            "title": "Random Steam Key Giveaway",
            "original_title": original_title,
            "url": giveaway_url,
            "status": status,
            "keys": keys_text,
            "deadline": deadline,
            "image": image_url,
            "color": embed_color,
        })

    if not giveaways:
        raise RuntimeError("No giveaway cards found after rendering page with Playwright.")

    return giveaways


def send_discord(item):
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
                "name": "Deadline",
                "value": f"⏳ {deadline_to_discord(item.get('deadline', 'Unknown'))}",
                "inline": True
            }
        ],
        "footer": {
            "text": "Subho's ZerosGroup Giveaway Notifier",
            "icon_url": FOOTER_ICON
        }
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
        print(f"Posted: {item['title']} - {item['keys']} - {item['status']} - {item['deadline']}")
        time.sleep(3)

    state["posted"] = list(posted)[-300:]
    save_state(state)


if __name__ == "__main__":
    main()
