# Asana Forum Tracker

Sends a Telegram alert for every new question on the [Asana Community forum](https://forum.asana.com)
in the categories you watch. Questions matching your keywords are flagged 🔥 and, if you add an
Anthropic API key, come with a Claude-drafted reply you can review and post.

## What each alert has

- Title, category, tags and the first ~280 characters of the question
- 🔥 priority flag with the matched keywords: any keyword in the title, or 2+ different ones in the body
- Reply count ("No replies yet, be first!")
- Optional ✍️ draft reply from Claude

A daily summary is sent at the first run after 00:00 UTC, so silence means something is wrong.
A failed workflow run also sends a ❌ alert.

## How "new" is decided

The forum's `/latest` feed is ordered by activity, so old topics reappear whenever someone replies.
The tracker only alerts on topics **created** in the last 48 hours (and after it first started) that
it hasn't alerted on before. The 48h window catches posts released late from the moderation queue.
If a Telegram send fails, the topic isn't marked seen and is retried on the next run.

## Configuration

| Setting | Where | Default |
|---|---|---|
| `BOT_TOKEN`, `CHAT_ID` | repo secrets (required) | none |
| `ANTHROPIC_API_KEY` | repo secret (optional) | drafts off |
| `WATCH_CATEGORIES` | repo variable, comma-separated ids | `6,161,7,24,9` (Ask the Community, Getting Started, Asana In Practice, API & Developers, App Integrations) |
| `KEYWORDS` | repo variable, comma-separated | api, automation, rules, integration, zapier, webhook, odoo, shopify… (see `tracker.py`) |
| `ONLY_PRIORITY` | repo variable | `0`; set `1` to alert only on keyword matches |
| `DRAFT_MODE` | repo variable | `priority`; also `all` or `off` |
| `CLAUDE_MODEL` | env | `claude-opus-5-5` |

Other category ids: 20 Product Ideas, 61 Critical Bugs, 18 Product Announcements.

## Running

**GitHub Actions** (default): `.github/workflows/tracker.yml` runs every 5 minutes. State is
committed to the `state` branch so `main` history stays clean. GitHub's scheduler is best-effort,
so runs can be late.

**Always-on:**

```bash
docker build -t asana-tracker .
docker run -d --restart=always -e BOT_TOKEN=... -e CHAT_ID=... -v tracker-data:/data asana-tracker
```

## Tests

```bash
BOT_TOKEN=test CHAT_ID=0 python -m unittest discover -s tests -v
```
