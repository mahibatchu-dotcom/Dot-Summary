"""
One-time builder: downloads K. T. Telang's public-domain English translation of
the Anugita (Sacred Books of the East, vol. 8, 1882) from sacred-texts.com and
saves it as data/anugita.json, split into chapters and passages.
"""
import re
import json
import html
import time
from pathlib import Path

import requests

BASE = "https://sacred-texts.com/hin/sbe08/sbe08{:02d}.htm"
FIRST_PAGE, CHAPTERS = 28, 36          # Anugita chapters I-XXXVI are pages 28-63
OUT = Path(__file__).parent / "data" / "anugita.json"


def clean(fragment):
    fragment = re.sub(r"<a[^>]*href=\"#fn_\d+\"[^>]*>.*?</a>", "", fragment, flags=re.S | re.I)   # footnote refs
    fragment = re.sub(r"<font[^>]*color=\"?green\"?[^>]*>.*?</font>", "", fragment, flags=re.S | re.I)  # page numbers
    fragment = re.sub(r"<a name=\"page_\d+\">.*?</a>", "", fragment, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def passages_from(page_html):
    body = re.split(r"<h3[^>]*>\s*Footnotes\s*</h3>", page_html, flags=re.I)[0]
    paras = re.findall(r"<p[^>]*>(.*?)(?=<p[^>]*>|</p>|<hr|<h\d|$)", body, flags=re.S | re.I)
    out = []
    for p in paras:
        t = clean(p)
        if len(t) < 60:
            continue
        if re.match(r"^(Next|Previous|Index|Sacred Texts)\b", t):
            continue
        if "sacred-texts.com" in t or "public domain" in t.lower():
            continue
        out.append(t)
    return out


def main():
    chapters = []
    for i in range(CHAPTERS):
        url = BASE.format(FIRST_PAGE + i)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (personal study app)"}, timeout=60)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        ps = passages_from(r.text)
        print(f"Chapter {i + 1}: {len(ps)} passages from {url}")
        chapters.append({"n": i + 1, "adhyaya": 16 + i, "passages": ps})
        time.sleep(1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "title": "Anu Gita",
        "source": "Translated by Kashinath Trimbak Telang, Sacred Books of the East vol. 8 (1882). Public domain; text via sacred-texts.com.",
        "chapters": chapters,
    }, ensure_ascii=False), encoding="utf-8")
    print("Saved", OUT, sum(len(c["passages"]) for c in chapters), "passages")


if __name__ == "__main__":
    main()
