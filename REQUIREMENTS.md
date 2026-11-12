# Earmark requirements

Status: **frozen on 2026-11-09.** Changes from here on are deliberate and recorded in this file.

## Goal

Turn what I save across social platforms into audio I can listen to on my commute, so saved items actually get reviewed.

## Constraints

- One user: me.
- Lowest practical cost. Claude runs on my subscription; X API spending is capped by an alert (T4).
- Runs on my always-on Mac.
- English only.

## Functional requirements

### Sources

| ID | Requirement | Phase |
|---|---|---|
| S1 | X bookmarks | 1 |
| S2 | Reddit saved items | 1 |
| S3 | Substack saved posts | 1 |
| S4 | Hacker News favorites | 1 |

YouTube is not a source. It is only used when a saved item links to a video (C3).

### Detection

- D1. Check all sources at least daily.
- D2. Identify items not seen before, using stored item IDs.
- D3. Never change anything on the source platform, including bookmark state.
- D4. The first run looks back one month. If that yields fewer than 10 items across all sources, it looks back two months instead. Only Substack records when something was saved; for X, Reddit and Hacker News the post's own date stands in.
- D5. Reddit and X items pass an LLM relevance check before audio is made, judged one item at a time on the full post and complete comment thread, with no artificial trimming. Uses Sonnet; script writing and review keep the default model. A skip that Sonnet marks as low confidence is treated as include, enforced in code. Skipped items are logged with a reason, can be overridden, and are decided only once. Chosen after comparing Opus, Sonnet, Haiku and the local Laya model on 25 borderline items; Laya could not tell items apart.

### Content

- C1. For a link, fetch the complete page content. Pages that only render with JavaScript are opened in headless Chrome; short links are expanded; X posts linked from a saved X post or its thread are fetched through the X API (added 2026-11-12).
- C2. For a post, include the whole thread.
- C2a. A saved Reddit item can be a whole post or a single comment. A saved comment becomes the focus of its episode, with its parent post as context.
- C2b. An X Article is read from its full text in the API, not from the short post that carries it. An author's thread is fetched while it is recent, so X is checked at least daily.
- C3. When a saved item links to a YouTube video or other spoken media, use its original audio track.
- C4. Paywalled content: use only what is publicly available, and say in the episode that it is a preview.
- C5. Articles are retold for the ear, covering every substantive idea. Tables and figures become spoken takeaways. No fact is added that the source does not support.
- C6. Discussions are synthesized in a clearly labelled section: first a short overview of the whole conversation, then a deeper pass by theme, with a few real comments quoted word for word. The whole thread is the input.
- C7. No special handling for very long videos for now.
- C8. Charts and diagrams that carry information are described by the writer agent itself, using Claude's built-in image understanding. Decorative images are skipped.

### Audio and delivery

- A1. Audio only.
- A2. Text is narrated by a local voice model: Breeze TTS 2, chosen over Kokoro after a listening test. Its licence covers personal, non-commercial use only. The model loads for each job and exits; shared models live in `~/Dev/labs/huggingface` (`HF_HOME`).
- A3. Delivered as a private podcast feed in AntennaPod on my phone, served from the Mac over plain HTTP on Tailscale only. Tailscale HTTPS stays off, so no machine name is published in certificate logs. The server must support resuming partial downloads.
- A4. One episode per item.
- A5. Newest first.
- A6. An item that cannot be read still gets a short episode saying so.
- A7. Loudness is leveled across paragraphs and voices within an episode.

### Tracking

- T1. A small local database records which items have already been processed, so audio is never produced twice for the same item.
- T2. Listening progress is left to the podcast app and is not reported back to Earmark.
- T3. Audio files are deleted after 30 days. The record of processed items is kept permanently.
- T4. Alert me if X API spending exceeds $5 in a month.

### Operation

- O1. Runs as a background service that starts automatically after login, checks sources on a schedule, and keeps the feed server running.
- O2. Sends a push notification through ntfy when a source's login stops working, a run fails, or the X spending alert triggers. Messages stay generic, with no secrets or content, because the public ntfy server is a third party.
- O3. No alert is sent while the Mac is down or waiting at the FileVault login screen. This is accepted.

### Script generation

- L1. Plain code lists saved items, prevents duplicates and publishes the feed.
- L2. A Claude Agent SDK agent (Python) gathers and writes each item's script, using only our own read-only tools. It has no shell and no write access. Its only file access is reading its own temporary folder, where sources too long for one tool result are saved (added 2026-11-10).
- L3. A separate reviewer with no tools checks each script against its sources and only reports findings. The writer agent fixes them, in one review-and-fix round per item; any remaining findings are logged.
- L4. Uses my Claude subscription for now. Whether unattended scheduled use is permitted is unclear, so an API key using plan credits remains the fallback.

## Known risks

| Risk | Mitigation |
|---|---|
| Reddit and Substack use unofficial endpoints and session cookies | Expiry triggers an ntfy alert (O2); manual link queue is the Reddit fallback |
| Reddit's public API reportedly closes by March 2027 | Revisit before then |
| X threads are only searchable for about 7 days | Daily checks (C2b) |
| Subscription terms for unattended use are unclear | API key fallback (L4) |
| Breeze licence is non-commercial | Personal use only; Kokoro is the unrestricted fallback |

## Experiments

| ID | Question | Status |
|---|---|---|
| E1 | Does Breeze stay consistent across a full episode? | Passed: full 10-minute episode with reference clips; one opening paragraph sounded louder |
| E2 | Can article text become a valid podcast feed? | Passed: feed played in AntennaPod |
| E3 | Can YouTube audio be fetched without login? | Passed on one short video |
| E4 | Can my Reddit saves be read? | Passed via session cookie: saved list and a full thread read without a browser. Official app route closed (redirects to Devvit) |
| E5 | Can Substack saved posts be retrieved? | Passed via session cookie and an unofficial endpoint; full text from public pages; paywalled posts untested |
| E6 | Real X API cost, and can whole threads be fetched? | Passed: bookmarks, long posts, full X Article text and recent author threads. About $0.06 across the test's requests |
| E7 | Can Hacker News favorites be read? | Passed: list, linked article and full comment thread, no login |
| E8 | Does the feed work in AntennaPod over the chosen route? | Passed: plain HTTP over Tailscale; download, playback, speed control and resume all worked on my phone |
| E9 | How well does extraction work on my real links? | Passed for articles: 6 of 6 Substack and 4 of 7 X-linked pages in full. Failures were a JavaScript app, a referral link and a paywalled preview |
