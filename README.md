# Earmark

Earmark turns what I save on X, Reddit, Substack and Hacker News into a private podcast. Once a day it checks each source for new saves, skips the ones that only make sense on a screen, and makes one episode per item. Each episode retells the article, summarizes the discussion and quotes the best comments word for word. The feed is served from my Mac to AntennaPod on my phone over Tailscale.

Requirements and design decisions are frozen in [REQUIREMENTS.md](REQUIREMENTS.md).

## How it works

```
sources ──> relevance check ──> writer agent ⇄ reviewer ──> Breeze voice ──> feed ──> AntennaPod
(X, Reddit,  (Sonnet, Reddit     (Claude with read-only      (local, MLX)     (RSS over
 Substack,    and X only)         tools; one fix round)                         Tailscale)
 HN)
```

1. **Find new saves.** Each source lists my saved items. Items already in the local database are ignored, so nothing is made twice. Earmark never changes anything on the platforms.
2. **Relevance check.** Reddit and X saves are judged one at a time by Sonnet on the full post and thread. A skip that Sonnet is unsure about counts as include. Skips are logged and can be overridden.
3. **Write.** A Claude Agent SDK agent reads the item, its thread and the linked page (and can look at charts), then writes a script. A separate reviewer with no tools checks the script against the sources and reports problems, and the writer fixes them in one round.
4. **Voice.** Breeze TTS 2 narrates locally on the Mac's GPU, with a second voice for quoted comments. When a save links to a YouTube video or podcast episode, its original audio plays inside the episode.
5. **Publish.** The episode joins the RSS feed. Audio is deleted after 30 days.

Problems such as an expired login, a failed run or high X spending send a push alert through ntfy.

## Setup

Requires an Apple Silicon Mac with enough memory for Breeze (about 40 GB at peak; built on 48 GB), [uv](https://docs.astral.sh/uv/), a Claude subscription, and Tailscale on both the Mac and the phone.

### 1. Install

```bash
git clone git@github.com:thomas-matthew/earmark.git
cd earmark
uv sync
```

Python and all packages stay inside this folder, in `.venv/`. Models are shared across projects in the folder named by `HF_HOME`. Set it in your shell profile (for example `~/.zshenv`) so other apps use it too:

```bash
export HF_HOME="$HOME/Dev/labs/huggingface"
```

Breeze TTS 2 (about 7.4 GB) downloads there on the first run. Its licence allows personal, non-commercial use only.

### 2. Create `.env`

```bash
cp .env.example .env
chmod 600 .env
```

`.env` holds logins and is git-ignored. Fill in each value as described below. `.env.example` lists every setting with comments.

| Setting | Where it comes from |
|---|---|
| `SUBSTACK_SID` | Sign in at substack.com in a browser. Open developer tools, go to Application, then Cookies, then `https://substack.com`, and copy the value of `substack.sid`. |
| `REDDIT_SESSION` | Sign in at reddit.com. In the same cookie view for `https://www.reddit.com`, copy the value of `reddit_session`. |
| `REDDIT_USERNAME` | Your Reddit username, without `u/`. |
| `X_CLIENT_ID`, `X_CLIENT_SECRET` | See [X API](#3-x-api) below. |
| `HN_USERNAME` | Your Hacker News username. Favorites are public, so no login is needed. |
| `EARMARK_HOST` | The Mac's Tailscale address, from `tailscale ip -4`. The server listens only there. |
| `EARMARK_PORT` | `8765` unless that port is taken. |
| `EARMARK_BASE_URL` | The address the phone uses, such as `http://your-mac.your-tailnet.ts.net:8765` (MagicDNS name) or `http://100.x.y.z:8765`. |
| `NTFY_TOPIC` | A long random name; see [Alerts](#5-alerts). |

The Reddit and Substack cookies last for months, but they end when you sign out of that browser session. When one stops working, Earmark sends an alert; copy a fresh cookie into `.env`.

### 3. X API

X bookmarks need the official API, which is pay-per-use.

1. At [developer.x.com](https://developer.x.com), create a project and an app, and buy a small amount of credit.
2. In the app's **User authentication settings**, turn on OAuth 2.0 with:
   - App type: **Web App, Automated App or Bot** (a confidential client)
   - Permissions: **Read**
   - Callback URI: `http://127.0.0.1:8723/callback`
   - Website URL: any URL you own
3. Copy the OAuth 2.0 **Client ID** and **Client Secret** into `.env`.
4. Approve read access once. This opens X in the browser:

   ```bash
   uv run earmark x-auth
   ```

   The token is saved to `data/x_token.json` (mode 600) and refreshes itself.

Costs: the first run reads every existing bookmark once (a one-time cost of about $2 for 200 bookmarks). Daily checks then cost a few cents. Earmark estimates monthly spend from its read count and alerts above `X_MONTHLY_ALERT` (default $5). X's developer console shows the exact figure.

### 4. Claude (Agent SDK)

The relevance check, writer and reviewer run through the [Claude Agent SDK](https://docs.claude.com/en/docs/agent-sdk/overview), which `uv sync` installs together with its own copy of the Claude Code CLI. They use a Claude subscription (Pro or Max) rather than an API key.

Log in once with the bundled CLI:

```bash
"$(uv run earmark claude-path)"
```

In the session that opens, type `/login`, choose your Claude account and finish in the browser, then exit with `/exit`. The login is stored in the macOS keychain, where the background service can also read it. If Claude Code is already installed and logged in on this Mac, the bundled CLI usually uses that login.

Every Claude session runs with no shell, no write access and no project settings. The writer's tools are Earmark's own read-only ones: read the saved item, fetch a public web page, and view an image. An item or page too long for one tool result (such as a Hacker News thread with hundreds of comments) is saved as a file in the writer's temporary folder, and the writer reads it in parts with the built-in Read and Grep tools. Permission rules limit those two tools to that folder; anything else on the Mac is refused.

It is unclear whether subscription terms cover unattended daily use. If that becomes a problem, switch to an API key by setting `EARMARK_USE_API_KEY=1` and `ANTHROPIC_API_KEY` in `.env`.

### 5. Alerts

1. Install the **ntfy** app on the phone.
2. Subscribe to the topic named in `NTFY_TOPIC` on the default server (`ntfy.sh`).
3. Send a test alert:

   ```bash
   uv run earmark notify-test
   ```

The public ntfy server is a third party, so alerts never include secrets or saved content. Anyone who guesses the topic name could read them, which is why it should be long and random.

### 6. Check everything

```bash
uv run earmark doctor
uv run earmark doctor --x   # also checks the X login, which costs one paid read
```

### 7. Phone

1. Install Tailscale on the phone and sign in to the same tailnet. Keep it connected while AntennaPod refreshes or downloads; it uses little battery when idle.
2. In AntennaPod, choose **Add podcast**, then **Add podcast by URL**, and enter `EARMARK_BASE_URL/feed.xml`.
3. Optionally turn on automatic downloads for the feed, so episodes are on the phone before the commute.

AntennaPod keeps listening progress and playback speed; Earmark never needs to know what you've heard.

### 8. Run it as a service

```bash
uv run earmark install            # daily run at 05:00
uv run earmark install --at 06:30 # or another time
```

This installs two LaunchAgents in `~/Library/LaunchAgents`:

- `dev.earmark.serve`: the feed server. It starts at login and restarts if it stops.
- `dev.earmark.run`: the daily run. If the Mac is asleep at the scheduled time, it runs on wake.

In System Settings, then General, then Login Items, they show as **Earmark Feed Server** and **Earmark Daily Run**. Each agent starts a small launcher script with that name in `data/service/`, which then starts Earmark's Python; macOS names background items after the program they start.

Logs go to `data/logs/`. Remove the service with `uv run earmark uninstall`.

Mac settings that keep it reliable:

- **Prevent sleep:** System Settings, then Energy, then turn on **Prevent automatic sleeping when the display is off**.
- **Restart after power cuts:** System Settings, then Energy, then turn on **Start up automatically after a power failure**.
- **FileVault:** with FileVault on, the Mac waits at the login screen after a restart and Earmark doesn't run until you log in. No alert can be sent while it waits.

## Using it

```bash
uv run earmark run                   # what the service does daily
uv run earmark run --limit 2         # make at most two episodes
uv run earmark run --source x,hn     # only check some sources
uv run earmark run --no-sync --item hn:50429024   # remake one specific item
uv run earmark status                # counts, X spending, recent skips, retries
uv run earmark include reddit:t3_abc # override a skip
uv run earmark serve                 # run the feed server in the foreground
```

The **first run** looks back one month, or two months if one month has fewer than 10 saves. Older saves are recorded so they are never processed. Only Substack records when something was saved, so for X, Reddit and Hacker News the post's own date is used. After that, every new save is processed, however old the post.

**Item ids** look like `x:<post id>`, `reddit:t3_<id>` (post) or `reddit:t1_<id>` (comment), `substack:<id>` and `hn:<id>`.

**Failures:** an item that fails is retried on the next runs. After three failures, a short episode says it couldn't be prepared, with the link in the episode notes. If several items fail in a row, the run stops early and sends an alert.

## Project layout

```
src/earmark/
  cli.py              command line
  config.py           settings and secrets from .env
  pipeline.py         one daily run, start to finish
  sources/            one module per platform (read-only)
    base.py           shared interface
    hn.py  reddit.py  substack.py
    x/                X: auth.py (OAuth), api.py (spend meter), __init__.py (bookmarks, threads)
  content/
    extract.py        page text and image lists, public addresses only
    media.py          original audio for linked videos and podcasts
  llm/
    claude.py         Agent SDK sessions, locked down
    prompts.py        relevance, writer and reviewer instructions
    relevance.py      Sonnet check for Reddit and X
    tools.py          the writer's read-only tools
    writer.py         writer agent with one review-and-fix round
    reviewer.py       reports issues; never edits
    script.py         the N:/Q: script format and quote checks
  audio/voice.py      Breeze narration, loudness leveling, MP3
  delivery/
    feed.py           RSS feed
    server.py         HTTP server with resumable downloads
    retention.py      deletes audio after 30 days
  storage/db.py       SQLite record of every item seen
  common/             HTTP helpers and ntfy alerts
  service/            LaunchAgents and `earmark doctor`
scripts/make_cover.py redraws the feed's cover art (delivery/assets/cover.png)
tests/                offline tests
experiments/          feasibility prototypes
```

Runtime data lives in `data/` (git-ignored): the database, feed and episodes, voice reference clips, the X token and logs.

## Development

```bash
uv run pytest
```

The tests run offline and need no logins.

`experiments/` holds the throwaway prototypes used to test feasibility before the requirements were frozen. They still use the project's working name, Bookcast, internally, and are not part of the app.
