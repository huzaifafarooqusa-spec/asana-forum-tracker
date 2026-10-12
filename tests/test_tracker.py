import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tracker  # noqa: E402

NOW = datetime(2026, 10, 12, 21, 0, tzinfo=timezone.utc)


def topic(tid, minutes_ago, category=6, title="How do I do X?", **kw):
    created = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    t = {"id": tid, "slug": f"topic-{tid}", "title": title, "category_id": category, "created_at": created,
         "bumped_at": created, "posts_count": 1, "pinned": False, "archetype": "regular", "tags": []}
    t.update(kw)
    return t


def state(started_minutes_ago=600, seen=()):
    return {"started_at": (NOW - timedelta(minutes=started_minutes_ago)).isoformat(), "seen": list(seen),
            "daily": {"date": NOW.strftime("%Y-%m-%d"), "alerts": 0, "priority": 0}}


class SelectNewTopics(unittest.TestCase):
    def test_filters(self):
        topics = [
            topic(1, 10),                                # new -> keep
            topic(2, 10, pinned=True),                   # pinned
            topic(3, 10, category=20),                   # Product Ideas not watched
            topic(4, 10),                                # already seen
            topic(5, 60 * 24 * 365),                     # old topic bumped by a reply
            topic(6, 10, archetype="private_message"),
            topic(7, 5),                                 # new -> keep
        ]
        got = tracker.select_new_topics(topics, state(seen=["4"]), NOW)
        self.assertEqual([t["id"] for t in got], [1, 7])  # oldest first

    def test_nothing_from_before_first_run(self):
        got = tracker.select_new_topics([topic(1, 30)], state(started_minutes_ago=10), NOW)
        self.assertEqual(got, [])

    def test_late_approved_topic_within_lookback_is_caught(self):
        # Created 20h ago but only visible now (moderation queue)
        got = tracker.select_new_topics([topic(1, 60 * 20)], state(started_minutes_ago=60 * 72), NOW)
        self.assertEqual([t["id"] for t in got], [1])


class Keywords(unittest.TestCase):
    def test_word_boundaries(self):
        self.assertEqual(tracker.keyword_hits("What is the capital of France"), [])
        self.assertIn("api", tracker.keyword_hits("Using the API to create tasks"))
        self.assertIn("rules", tracker.keyword_hits("My rules stopped firing"))
        self.assertIn("custom field", tracker.keyword_hits("Custom Field formulas"))

    def test_priority_needs_title_hit_or_two_body_hits(self):
        self.assertEqual(tracker.priority_hits("Desktop app hangs", "an integration is installed"), [])
        self.assertEqual(tracker.priority_hits("Rules not firing", "help"), ["rules"])
        self.assertEqual(sorted(tracker.priority_hits("Help", "use the api with zapier")), ["api", "zapier"])


class Html(unittest.TestCase):
    def test_strips_markup_quotes_and_images(self):
        cooked = ('<p>Hello <b>there</b><br>line two</p><aside class="quote">quoted text</aside>'
                  '<div class="lightbox-wrapper"><a href="x">image.png 800x600</a></div><p>end</p>')
        self.assertEqual(tracker.html_to_text(cooked), "Hello there line two end")

    def test_alert_escapes_html(self):
        msg = tracker.build_alert(topic(1, 1, title="<script> & stuff"), "a < b", ["api"])
        self.assertIn("&lt;script&gt; &amp; stuff", msg)
        self.assertIn("a &lt; b", msg)
        self.assertIn("Priority", msg)


class CheckForumFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tracker.STATE_FILE = os.path.join(self.tmp.name, "state.json")
        self.sent = []
        self.send_ok = True
        self.topics = []
        tracker.send_telegram = lambda m, preview=False: (self.sent.append(m), self.send_ok)[1]
        tracker.fetch_latest_topics = lambda: self.topics
        tracker.fetch_json = lambda url: {"post_stream": {"posts": [{"cooked": "<p>Need help with rules and automation</p>"}]}}
        tracker.DRAFT_MODE = "off"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        with open(tracker.STATE_FILE) as f:
            return json.load(f)

    def test_first_run_then_alert_then_no_duplicate(self):
        tracker.check_forum()  # first run: just creates state
        self.assertEqual(self.sent, [])
        s = self.load()
        s["started_at"] = "2000-01-01T00:00:00+00:00"
        with open(tracker.STATE_FILE, "w") as f:
            json.dump(s, f)

        self.topics = [topic(42, 1)]
        self.topics[0]["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        tracker.check_forum()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Priority", self.sent[0])  # "rules" keyword in body
        self.assertIn("42", self.load()["seen"])

        tracker.check_forum()
        self.assertEqual(len(self.sent), 1)

    def test_failed_send_retries_next_run(self):
        tracker.check_forum()
        s = self.load()
        s["started_at"] = "2000-01-01T00:00:00+00:00"
        with open(tracker.STATE_FILE, "w") as f:
            json.dump(s, f)
        self.topics = [topic(7, 1)]
        self.topics[0]["created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        self.send_ok = False
        tracker.check_forum()
        self.assertNotIn("7", self.load()["seen"])
        self.send_ok = True
        tracker.check_forum()
        self.assertIn("7", self.load()["seen"])


if __name__ == "__main__":
    unittest.main()
