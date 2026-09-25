"""
Daily Dot article summariser.
Opens dot.news in a real (headless) browser, grabs the day's article,
summarises it with Gemini (free tier), saves it, and optionally emails it.
"""
import os
import re
import sys
import json
import time
import smtplib
import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from email.message import EmailMessage

import requests
from playwright.sync_api import sync_playwright

HOME_URL = "https://www.dot.news/posts"
ROOT = Path(__file__).parent
SUMMARY_DIR = ROOT / "summaries"
DEBUG_DIR = ROOT / "debug"
MIN_ARTICLE_CHARS = 1500          # below this, the page is probably a teaser, not the full story
TODAY = datetime.datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")


# ---------- 1. Get the article text ----------

def load_text(page, url):
    page.goto(url, wait_until="networkidle", timeout=90000)
    page.wait_for_timeout(3000)
    for _ in range(6):                      # scroll so lazy-loaded text appears
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(700)
    return page.inner_text("body")


def find_article_link(page):
    """If the homepage is only a teaser, find the most likely article link."""
    links = page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => ({href: e.href, text: (e.innerText || '').trim()}))",
    )
    for link in links:
        href = link["href"]
        if "dot.news" not in href:
            continue
        if re.search(r"[0-9a-f]{24}", href) or re.search(r"/(post|story|article|giftpost)/", href):
            return href
    return None


def get_article():
    DEBUG_DIR.mkdir(exist_ok=True)
    override = (os.environ.get("ARTICLE_URL") or "").strip()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1600})
        url = override or HOME_URL
        text = load_text(page, url)

        if not override:
            link = find_article_link(page)
            if link:
                url = link
                text = load_text(page, url)

        # Saved so problems can be diagnosed from the GitHub run page
        page.screenshot(path=str(DEBUG_DIR / "page.png"), full_page=True)
        (DEBUG_DIR / "page.txt").write_text(f"URL: {url}\n\n{text}", encoding="utf-8")
        browser.close()
    return url, text


# ---------- 2. Summarise with Gemini ----------

def summarise(text, url):
    key = os.environ["GEMINI_API_KEY"]
    instructions = (ROOT / "prompt.txt").read_text(encoding="utf-8")
    body = {
        "contents": [{
            "parts": [{"text": f"{instructions}\n\nSOURCE URL: {url}\n\nPAGE TEXT:\n{text[:60000]}"}]
        }]
    }
    models = [m for m in [os.environ.get("GEMINI_MODEL"), "gemini-3.5-flash", "gemini-3.5-flash-lite"] if m]

    for model in models:
        for attempt in range(3):
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            if r.status_code == 200:
                parts = r.json()["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts).strip()
            print(f"{model} attempt {attempt + 1}: HTTP {r.status_code} {r.text[:300]}")
            if r.status_code in (429, 500, 503):
                time.sleep(30 * (attempt + 1))
                continue
            break                           # other errors: try the next model
    sys.exit("Gemini failed with every model. See messages above.")


# ---------- 3. Save and deliver ----------

def save(title, summary, url):
    SUMMARY_DIR.mkdir(exist_ok=True)
    index_file = SUMMARY_DIR / "index.json"
    index = json.loads(index_file.read_text()) if index_file.exists() else {}

    if title in index:
        print(f"Already summarised on {index[title]}: {title}. Skipping.")
        return False

    entry = f"# {title}\n*{TODAY}* · [Original article]({url})\n\n{summary}\n"
    (SUMMARY_DIR / f"{TODAY}.md").write_text(entry, encoding="utf-8")

    # One running file, newest first, for easy revision
    all_file = SUMMARY_DIR / "ALL_SUMMARIES.md"
    old = all_file.read_text(encoding="utf-8") if all_file.exists() else ""
    all_file.write_text(entry + "\n---\n\n" + old, encoding="utf-8")

    index[title] = TODAY
    index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    return True


def email(title, summary, url):
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not (sender and password):
        print("Email not set up. Skipping email.")
        return
    msg = EmailMessage()
    msg["Subject"] = f"Dot summary {TODAY}: {title}"
    msg["From"] = sender
    msg["To"] = os.environ.get("EMAIL_TO") or sender
    msg.set_content(f"{title}\n{url}\n\n{summary}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, password.replace(" ", ""))
        s.send_message(msg)
    print("Email sent.")


def main():
    url, text = get_article()
    print(f"Read {len(text)} characters from {url}")
    result = summarise(text, url)

    if result.startswith("NO_ARTICLE"):
        sys.exit("Gemini could not find an article on the page. Check the 'debug' download on the run page.")

    first, _, rest = result.partition("\n")
    title = first.replace("TITLE:", "").strip() or "Untitled"
    summary = rest.strip()

    if save(title, summary, url):
        email(title, summary, url)
        print(f"Done: {title}")


if __name__ == "__main__":
    main()
