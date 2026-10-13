# Asana Forum Tracker

Sends a Telegram alert for every new question on the [Asana Community forum](https://forum.asana.com)
in the categories you watch. Questions matching your keywords are flagged 🔥 and, if you add a free
Gemini API key, come with an AI-drafted reply you can review and post.

## What each alert has

- Title, category, tags and the first ~280 characters of the question
- 🔥 priority flag with the matched keywords: any keyword in the title, or 2+ different ones in the body
- Reply count ("No replies yet, be first!")
- Optional ✍️ AI draft reply (🔥 priority questions only, by default)

A daily summary is sent at the first run after 00:00 UTC, so silence means something is wrong.
A failed workflow run also sends a ❌ alert.

## Free AI drafts (Gemini)

1. Open [Google AI Studio](https://aistudio.google.com/apikey), sign in with a Google account
   and click **Create API key**. The free tier needs no card.
2. Add it as a repo secret named `LLM_API_KEY`: Settings → Secrets and variables → Actions →
   New repository secret. Or from a terminal, which prompts for the value so it never lands in
   your shell history:
   ```bash
   gh secret set LLM_API_KEY -R huzaifafarooqusa-spec/asana-forum-tracker
   ```
3. Test it: Actions → Asana Forum Monitor → **Run workflow** → tick *Send a test AI draft* →
   Run. A 🧪 draft for the latest forum question arrives on Telegram.

Free-tier models are sometimes briefly overloaded (HTTP 503); the tracker then falls through to
the next model in `LLM_MODEL`. Only priority questions get drafts (`DRAFT_MODE=priority`), so usage stays far inside the free
limits. If a draft fails (rate limit, outage), the alert still arrives without it. Google may use
free-tier prompts to improve its models; forum posts are public anyway.

To use another provider, set the `LLM_BASE_URL` and `LLM_MODEL` repo variables to any
OpenAI-compatible API, e.g. OpenRouter (`https://openrouter.ai/api/v1`) or Groq
(`https://api.groq.com/openai/v1`), and put that provider's key in `LLM_API_KEY`.

## How "new" is decided

The forum's `/latest` feed is ordered by activity, so old topics reappear whenever someone replies.
The tracker only alerts on topics **created** in the last 48 hours (and after it first started) that
it hasn't alerted on before. The 48h window catches posts released late from the moderation queue.
If a Telegram send fails, the topic isn't marked seen and is retried on the next run.

## Configuration

| Setting | Where | Default |
|---|---|---|
| `BOT_TOKEN`, `CHAT_ID` | repo secrets (required) | none |
| `LLM_API_KEY` | repo secret (optional) | drafts off |
| `LLM_BASE_URL` | repo variable | Gemini's OpenAI-compatible API |
| `LLM_MODEL` | repo variable, comma-separated fallback list | `gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash-lite` |
| `WATCH_CATEGORIES` | repo variable, comma-separated ids | `6,161,7,24,9` (Ask the Community, Getting Started, Asana In Practice, API & Developers, App Integrations) |
| `KEYWORDS` | repo variable, comma-separated | api, automation, rules, integration, zapier, webhook, odoo, shopify… (see `tracker.py`) |
| `ONLY_PRIORITY` | repo variable | `0`; set `1` to alert only on keyword matches |
| `DRAFT_MODE` | repo variable | `priority`; also `all` or `off` |

Other category ids: 20 Product Ideas, 61 Critical Bugs, 18 Product Announcements.

## Running

**GitHub Actions** (default): `.github/workflows/tracker.yml` runs every 5 minutes. State is
committed to the `state` branch so `main` history stays clean. GitHub's scheduler is best-effort,
so runs can be late.

**Reliable free 5-minute trigger (recommended):** GitHub's own cron is best-effort and can
skip runs for hours. Use [cron-job.org](https://cron-job.org) (free, no card) to start the
workflow instead:

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token.
   Repository access: only this repo. Permissions: **Actions → Read and write**, nothing else.
   Expiration: 1 year (set a reminder to renew).
2. cron-job.org → Create cronjob:
   - URL: `https://api.github.com/repos/huzaifafarooqusa-spec/asana-forum-tracker/actions/workflows/tracker.yml/dispatches`
   - Schedule: every 5 minutes
   - Advanced → Request method `POST`, body `{"ref":"main"}`, headers:
     `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
     `X-GitHub-Api-Version: 2022-11-28`
3. Save. Job history should show HTTP **204** and a new run appears under Actions.

Keep the repo **public**: Actions minutes are free there, while private repos get only 2,000
minutes a month. The workflow's own schedule stays on as a backup, and the concurrency group
stops overlapping runs from clashing.

**Always-on:**

```bash
docker build -t asana-tracker .
docker run -d --restart=always -e BOT_TOKEN=... -e CHAT_ID=... -v tracker-data:/data asana-tracker
```

## Tests

```bash
BOT_TOKEN=test CHAT_ID=0 python -m unittest discover -s tests -v
```
