"""Checks that nothing from the person's own Chrome reaches the headless browser.

The last test drives the real Chrome and the network, so it runs only with EARMARK_BROWSER_TESTS=1."""
import os
import tempfile

import pytest

from earmark.content import browser
from earmark.content.browser import UnsafeBrowser

FLAGS = " ".join(browser.PRIVACY_FLAGS)


def _version_page(folder: str, flags: str = FLAGS) -> str:
    return (f"Google Chrome\t157.0\nCommand Line\t/Applications/Google Chrome.app/Contents/MacOS/Google Chrome {flags} "
            f"--user-data-dir={folder} about:blank\nProfile Path\t{folder}/Default\n")


def test_version_page_must_show_our_profile_and_every_privacy_flag(tmp_path):
    folder = str(tmp_path)
    browser.check_version_page(_version_page(folder), folder)
    with pytest.raises(UnsafeBrowser, match="profile"):
        real = os.path.expanduser("~/Library/Application Support/Google/Chrome")
        browser.check_version_page(_version_page(folder).replace(f"{folder}/Default", f"{real}/Default"), folder)
    with pytest.raises(UnsafeBrowser, match="missing.*--use-mock-keychain"):
        browser.check_version_page(_version_page(folder, FLAGS.replace("--use-mock-keychain", "")), folder)
    with pytest.raises(UnsafeBrowser, match="unwanted.*--no-sandbox"):
        browser.check_version_page(_version_page(folder, FLAGS + " --no-sandbox"), folder)
    with pytest.raises(UnsafeBrowser):
        browser.check_version_page("nothing useful", folder)


def test_profile_folder_must_be_private_and_temporary():
    with tempfile.TemporaryDirectory(prefix="earmark-browser-") as folder:
        browser.check_profile_folder(folder)
    with pytest.raises(UnsafeBrowser):
        browser.check_profile_folder(os.path.expanduser("~/Library/Application Support/Google/Chrome"))
    with pytest.raises(UnsafeBrowser):
        browser.check_profile_folder(os.path.expanduser("~/Documents"))


def test_any_chrome_policy_file_stops_the_launch(tmp_path):
    present, absent = tmp_path / "com.google.Chrome.plist", tmp_path / "missing.plist"
    browser.check_no_policy_files([absent])
    present.write_text("{}")
    with pytest.raises(UnsafeBrowser, match="policies"):
        browser.check_no_policy_files([absent, present])


@pytest.mark.skipif(os.environ.get("EARMARK_BROWSER_TESTS") != "1", reason="drives real Chrome; set EARMARK_BROWSER_TESTS=1")
def test_real_browser_starts_empty_and_leaves_nothing_behind():
    with browser.session() as (context, page, folder):
        assert context.cookies() == []
        assert not browser._inside(folder, browser.CHROME_DATA)
        page.goto("chrome://version")
        assert "--no-sandbox" not in page.inner_text("body")
        # Sites the person may be signed in to in their own Chrome must see a stranger.
        for site, login_cookie in (("https://x.com", "auth_token"), ("https://www.reddit.com", "reddit_session"),
                                   ("https://substack.com", "substack.sid")):
            page.goto(site, wait_until="domcontentloaded", timeout=30_000)
            assert login_cookie not in {c["name"] for c in context.cookies()}, site
    assert not os.path.exists(folder)
