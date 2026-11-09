"""E8: build a one-episode private podcast feed for testing delivery to AntennaPod.

Usage (from experiments/): uv run python make_test_feed.py BASE_URL
BASE_URL is where data/feed/ is served, e.g. https://my-mac.tailnet-name.ts.net
"""
import shutil
import sys
import time
from email.utils import formatdate
from pathlib import Path
from xml.sax.saxutils import escape

import soundfile as sf

DATA = Path(__file__).resolve().parent / "data"
FEED = DATA / "feed"
SOURCE = DATA / "episode_50429024_breeze_full.mp3"
TITLE = "Muse Ember: Meta's smallest model, and what Hacker News made of it"


def main() -> None:
    base = sys.argv[1].rstrip("/")
    FEED.mkdir(exist_ok=True)
    name = "muse-ember-test.mp3"
    target = FEED / name
    shutil.copyfile(SOURCE, target)
    seconds = round(sf.info(str(target)).duration)
    enclosure = escape(f"{base}/{name}", {'"': "&quot;"})
    (FEED / "feed.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>Earmark (test)</title>
  <link>{escape(base)}</link>
  <description>Saved links, read for the commute.</description>
  <language>en</language>
  <itunes:block>Yes</itunes:block>
  <item>
    <title>{escape(TITLE)}</title>
    <guid isPermaLink="false">bookcast-test-50429024</guid>
    <description>Test episode from Hacker News story 50429024.</description>
    <pubDate>{formatdate(time.time())}</pubDate>
    <enclosure url="{enclosure}" length="{target.stat().st_size}" type="audio/mpeg"/>
    <itunes:duration>{seconds}</itunes:duration>
  </item>
</channel>
</rss>
""", encoding="utf-8")
    print(f"feed: {base}/feed.xml\nepisode: {seconds // 60}m{seconds % 60:02d}s, {target.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
