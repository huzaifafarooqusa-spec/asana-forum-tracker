import os
import sys
import time
import json
import ssl
import urllib.request
import urllib.error

BOT_TOKEN = os.getenv("BOT_TOKEN", "8995329698:AAH8t_4777maZKsC50TTaHIdEFimh5V8cmM")
CHAT_ID = os.getenv("CHAT_ID", "714192775")
FORUM_URL = "https://forum.asana.com/c/forum-en/tips/6/l/latest.json"
CACHE_FILE = os.path.join(os.path.dirname(__file__), "seen_topics.txt")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AsanaTracker/1.0"}

ssl_ctx = ssl._create_unverified_context()

def load_seen_topics():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen_topics(seen_ids):
    with open(CACHE_FILE, "w") as f:
        for tid in sorted(seen_ids):
            f.write(f"{tid}\n")

def send_telegram_alert(title, url, excerpt=None):
    clean_title = title.replace("*", "").replace("_", "")
    message = (
        f"🚨 *Naya Question Aya Asana Forum Par!*\n\n"
        f"📌 *Title:* {clean_title}\n"
    )
    if excerpt:
        clean_excerpt = excerpt[:180].replace("*", "").replace("_", "").strip()
        message += f"\n📝 *Summary:* {clean_excerpt}...\n"

    message += f"\n🔗 [Question Open Karein]({url})"

    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "AsanaTracker/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            if resp.status == 200:
                print(f"✅ Notification sent to Telegram: {title}")
    except Exception as e:
        print(f"❌ Telegram send error: {e}")

def check_forum():
    seen_ids = load_seen_topics()
    is_initial_run = (len(seen_ids) == 0)

    try:
        req = urllib.request.Request(FORUM_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        topics = data.get("topic_list", {}).get("topics", [])
        current_batch_ids = set(seen_ids)
        new_topics_found = 0

        for topic in reversed(topics):
            # Skip pinned announcements
            if topic.get("pinned", False):
                continue

            topic_id = str(topic["id"])

            if is_initial_run:
                current_batch_ids.add(topic_id)
                continue

            if topic_id not in seen_ids:
                new_topics_found += 1
                current_batch_ids.add(topic_id)

                title = topic.get("title", "Untitled Question")
                slug = topic.get("slug", "topic")
                topic_url = f"https://forum.asana.com/t/{slug}/{topic_id}"
                excerpt = topic.get("excerpt", "")

                print(f"🔍 Naya topic mil gaya: {title}")
                send_telegram_alert(title, topic_url, excerpt)

        save_seen_topics(current_batch_ids)

        if is_initial_run:
            print(f"ℹ️ Pehli martaba {len(current_batch_ids)} topics cache ho gaye hain. Ab naya topic aate hi alert aayega!")
        else:
            print(f"ℹ️ Check complete. {new_topics_found} new topics notified.")

    except Exception as e:
        print(f"❌ Error checking Asana forum: {e}")

if __name__ == "__main__":
    if "--loop" in sys.argv:
        print("🚀 Asana Forum Tracker started in continuous loop (every 60s)...")
        while True:
            check_forum()
            time.sleep(60)
    else:
        check_forum()
