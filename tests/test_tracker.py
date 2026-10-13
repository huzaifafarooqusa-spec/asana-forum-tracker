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


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Draft(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.orig_urlopen = tracker.urllib.request.urlopen
        self.orig_sleep = tracker.time.sleep
        tracker.time.sleep = lambda s: None
        tracker.DRAFT_MODE = "priority"
        os.environ["LLM_API_KEY"] = "test-key"

    def tearDown(self):
        tracker.urllib.request.urlopen = self.orig_urlopen
        tracker.time.sleep = self.orig_sleep
        os.environ.pop("LLM_API_KEY", None)

    def respond(self, *results):
        results = list(results)

        def fake(req, timeout=None, context=None):
            self.calls.append(req)
            r = results.pop(0)
            if isinstance(r, Exception):
                raise r
            return FakeResponse(r)
        tracker.urllib.request.urlopen = fake

    def http_error(self, code):
        import io
        return tracker.urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"{}"))

    GEMINI_OK = {"candidates": [{
        "finishReason": "STOP",
        "content": {"parts": [{"text": "Think first", "thought": True},
                              {"text": "  Use a rule \u2014 it runs on triggers.  "}]},
        "groundingMetadata": {
            "webSearchQueries": ["asana rules triggers"],
            "groundingChunks": [{"web": {"uri": "https://redirect/1", "title": "asana.com"}}],
        },
    }]}

    def test_gemini_request_is_search_grounded(self):
        self.respond(self.GEMINI_OK)
        draft = tracker.draft_reply("Title", "Body", "Ask the Community")
        self.assertEqual(draft["text"], "Use a rule, it runs on triggers.")  # thought dropped, dash removed
        self.assertEqual(draft["sources"], [("asana.com", "https://redirect/1")])
        self.assertEqual(draft["queries"], ["asana rules triggers"])
        self.assertEqual(draft["model"], tracker.LLM_MODELS[0])
        req = self.calls[0]
        self.assertIn(f"/models/{tracker.LLM_MODELS[0]}:generateContent", req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), "test-key")
        body = json.loads(req.data)
        self.assertEqual(body["tools"], [{"google_search": {}}])
        self.assertIn("Never use em dashes", body["systemInstruction"]["parts"][0]["text"])
        self.assertIn("<category>Ask the Community</category>", body["contents"][0]["parts"][0]["text"])

    def test_openai_compatible_provider(self):
        orig = tracker.LLM_BASE_URL
        tracker.LLM_BASE_URL = "https://openrouter.ai/api/v1"
        try:
            self.respond({"choices": [{"message": {"content": "Try a rule."}, "finish_reason": "stop"}]})
            draft = tracker.draft_reply("Title", "Body")
        finally:
            tracker.LLM_BASE_URL = orig
        self.assertEqual(draft["text"], "Try a rule.")
        req = self.calls[0]
        self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(json.loads(req.data)["messages"][0]["role"], "system")

    def test_no_key_means_no_call(self):
        os.environ.pop("LLM_API_KEY")
        self.respond()
        self.assertIsNone(tracker.draft_reply("t", "b"))
        self.assertEqual(self.calls, [])

    def test_bad_key_does_not_retry(self):
        self.respond(self.http_error(400))
        self.assertIsNone(tracker.draft_reply("t", "b"))
        self.assertEqual(len(self.calls), 1)

    def test_busy_model_falls_through_to_next(self):
        self.respond(self.http_error(503), self.GEMINI_OK)
        self.assertEqual(tracker.draft_reply("t", "b")["model"], tracker.LLM_MODELS[1])
        self.assertIn(tracker.LLM_MODELS[1], self.calls[1].full_url)

    def test_unknown_model_and_timeout_fall_through(self):
        self.respond(self.http_error(404), TimeoutError("timed out"), self.GEMINI_OK)
        self.assertIsNotNone(tracker.draft_reply("t", "b"))
        self.assertEqual(len(self.calls), 3)

    def test_gives_up_after_grounded_and_ungrounded_passes(self):
        n = 2 * len(tracker.LLM_MODELS)  # 1 grounded round + 1 ungrounded
        self.respond(*[self.http_error(503) for _ in range(n)])
        self.assertIsNone(tracker.draft_reply("t", "b"))
        self.assertEqual(len(self.calls), n)

    def test_search_quota_exhausted_falls_back_to_ungrounded(self):
        n = len(tracker.LLM_MODELS)
        self.respond(*[self.http_error(429) for _ in range(n)], self.GEMINI_OK)
        draft = tracker.draft_reply("t", "b")
        self.assertFalse(draft["grounded"])
        self.assertNotIn("tools", json.loads(self.calls[-1].data))
        self.assertIn("tools", json.loads(self.calls[0].data))
        msg = tracker.format_draft_message({**draft, "sources": []}, "H")
        self.assertIn("Not search-verified", msg)

    def test_error_summary_extracts_quota_id(self):
        import io
        body = json.dumps({"error": {"code": 429, "message": "You exceeded your current quota. For more information x",
                                     "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
        e = tracker.urllib.error.HTTPError("u", 429, "err", {}, io.BytesIO(body.encode()))
        self.assertEqual(tracker._error_summary(e),
                         "You exceeded your current quota [quota: GenerateRequestsPerDayPerProjectPerModel-FreeTier]")

    def test_declined_and_empty(self):
        self.assertIsNone(tracker.parse_gemini({"candidates": [{"finishReason": "SAFETY"}]}))
        self.assertIsNone(tracker.parse_gemini({"promptFeedback": {"blockReason": "OTHER"}}))
        self.assertIsNone(tracker.parse_draft({"choices": [{"finish_reason": "content_filter", "message": {}}]}))
        self.assertIsNone(tracker.parse_draft({"choices": []}))


class Style(unittest.TestCase):
    def test_clean_draft(self):
        self.assertEqual(tracker.clean_draft("Rules \u2014 not forms \u2013 work."), "Rules, not forms, work.")
        self.assertEqual(tracker.clean_draft("Takes 3\u20135 minutes"), "Takes 3-5 minutes")
        self.assertEqual(tracker.clean_draft("Done \u2014."), "Done.")
        self.assertEqual(tracker.clean_draft("## Steps\n**Open** the project"), "Steps\nOpen the project")

    def test_format_message_resolves_and_dedupes_sources(self):
        orig = tracker.resolve_url
        tracker.resolve_url = lambda u: "https://help.asana.com/s/article/rules" if "1" in u or "2" in u else u
        try:
            msg = tracker.format_draft_message(
                {"text": "a < b", "model": "m",
                 "sources": [("asana.com", "https://r/1"), ("asana.com", "https://r/2")],
                 "queries": ["asana rules"]}, "HEAD")
        finally:
            tracker.resolve_url = orig
        self.assertIn("a &lt; b", msg)
        self.assertEqual(msg.count("help.asana.com/s/article/rules</a>"), 1)
        self.assertIn("https://www.google.com/search?q=asana+rules", msg)


class Categories(unittest.TestCase):
    def setUp(self):
        self.orig = tracker.fetch_json

    def tearDown(self):
        tracker.fetch_json = self.orig

    def test_subcategories_included_announcements_excluded(self):
        tracker.fetch_json = lambda url: {"category_list": {"categories": [{"id": 160, "name": "Asana Community",
            "subcategory_list": [
                {"id": 24, "name": "API & Developers", "subcategory_list": [
                    {"id": 97, "name": "Platform News"}, {"id": 150, "name": "App Components"}]},
                {"id": 20, "name": "Product Ideas", "subcategory_list": [{"id": 78, "name": "In Progress"}]},
            ]}]}}
        names = tracker.watched_categories()
        self.assertEqual(names[150], "API & Developers › App Components")
        self.assertNotIn(97, names)
        self.assertNotIn(78, names)
        self.assertNotIn(160, names)

    def test_static_fallback(self):
        def boom(url):
            raise OSError("offline")
        tracker.fetch_json = boom
        names = tracker.watched_categories()
        self.assertIn(218, names)
        self.assertIn(219, names)

    def test_subcategory_topic_selected(self):
        got = tracker.select_new_topics([topic(1, 5, category=218)], state(), NOW, {6, 218})
        self.assertEqual([t["id"] for t in got], [1])


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
