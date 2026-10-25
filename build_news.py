#!/usr/bin/env python3
"""NOVA daily news builder.

Runs inside GitHub Actions once a day. Reads public RSS/Atom feeds (headline +
short snippet only), optionally asks Claude for a Persian translation and a short
paraphrased summary, and writes news.json next to index.html.
Uses only the Python standard library.
"""
import json, os, re, sys, html, datetime, subprocess, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

FEEDS = [
    # (section, source name, url)
    # --- economy ---
    ("economy", "BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("economy", "The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ("economy", "The Guardian", "https://www.theguardian.com/uk/business/rss"),
    ("economy", "Bloomberg", "https://www.bloomberg.com/feeds/markets/news.rss"),
    ("economy", "Bloomberg", "https://www.bloomberg.com/feeds/economics/news.rss"),
    ("economy", "The Economist", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("economy", "The Economist", "https://www.economist.com/business/rss.xml"),
    ("economy", "The Wall Street Journal", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"),
    ("economy", "The Wall Street Journal", "https://feeds.content.dowjones.io/public/rss/WSJcomUSBusiness"),
    ("economy", "Deutsche Welle", "https://rss.dw.com/rdf/rss-en-bus"),
    # --- technology ---
    ("tech", "BBC News", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("tech", "The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
    ("tech", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("tech", "The Verge", "https://www.theverge.com/rss/index.xml"),
    ("tech", "Bloomberg", "https://www.bloomberg.com/feeds/technology/news.rss"),
    ("tech", "The Wall Street Journal", "https://feeds.content.dowjones.io/public/rss/RSSWSJD"),
    ("tech", "MIT Technology Review", "https://www.technologyreview.com/feed/"),
    # --- management & leadership ---
    ("management", "MIT Sloan Management Review", "https://sloanreview.mit.edu/feed/"),
    ("management", "Fast Company", "https://www.fastcompany.com/latest/rss"),
    ("management", "Fortune", "https://fortune.com/feed/"),
    ("management", "McKinsey", "https://www.mckinsey.com/insights/rss"),
    # --- trade & business ---
    ("trade", "Financial Times", "https://www.ft.com/?format=rss"),
    ("trade", "CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("trade", "Supply Chain Dive", "https://www.supplychaindive.com/feeds/news/"),
    ("trade", "Nikkei Asia", "https://asia.nikkei.com/rss/feed/nar"),
    ("trade", "World Trade Organization", "https://www.wto.org/library/rss/latest_news_e.xml"),
]
SECTIONS = ("economy", "tech", "management", "trade")

# General-news feeds (their RSS mixes politics, world news, etc.) are kept only
# for items that actually match the topic of the section they feed.
TOPIC_FILTER = {}
# Empty = no filtering: general feeds keep their top headlines as published.
# To keep only on-topic items from a feed, add its URL, e.g.
#   "https://fortune.com/feed/": "management",   (or "trade")
TOPIC_WORDS = {
    "trade": r"trade|tariffs?|exports?|exported|exporting|exporters?|imports?|imported|importers?|supply[- ]chains?|shipping|freight|cargo|containers?|ports?|customs|sanctions?|embargo|logistics|wto|commerce|manufactur\w*|outbound investment|foreign investment|investment curbs|curbs|subsid\w*|duties|quotas?|dumping",
    "management": r"manag\w*|leader\w*|ceos?|executives?|workforce|workplace|employees?|employers?|hiring|layoffs?|culture|strategy|productivity|remote work|bosses|boss|talent|teams?|careers?|burnout|mentor\w*|organi[sz]ation\w*",
}


def on_topic(topic, e):
    return re.search(r"\b(?:" + TOPIC_WORDS[topic] + r")\b", (e["title"] + " " + e["summary"]).lower()) is not None
PER_FEED = 3
PER_SECTION = 10
MAX_AGE_HOURS = 96
MAX_AGE_BY_SECTION = {}  # optional per-section windows, e.g. {"management": 240}; default is MAX_AGE_HOURS
OUT = "news.json"
MODEL = os.environ.get("NEWS_MODEL", "claude-haiku-5-5")
UA = "Mozilla/5.0 (compatible; NOVA-news-bot/1.0)"


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def short(s, n=260):
    s = strip_html(s)
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(el, names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def parse_feed(data):
    """Return a list of dicts: title, summary, link, published(datetime|None)."""
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        t = local(el.tag)
        if t not in ("item", "entry"):
            continue
        title = strip_html(child_text(el, ("title",)))
        summary = child_text(el, ("description", "summary", "content"))
        link = child_text(el, ("link",))
        if not link:
            for c in el:
                if local(c.tag) == "link" and c.attrib.get("href"):
                    if c.attrib.get("rel", "alternate") == "alternate":
                        link = c.attrib["href"]
                        break
        pub = parse_date(child_text(el, ("pubDate", "published", "updated", "date")))
        if title and link.startswith("http"):
            out.append({"title": title, "summary": short(summary), "link": link, "published": pub})
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


EPOCH = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def when(e):
    return e["published"] or EPOCH


def pick_section(cands, limit):
    """Round-robin by source so every source that has fresh items gets a place
    before any source gets a second one; the result is then sorted newest first."""
    by_src = {}
    for e in sorted(cands, key=when, reverse=True):
        by_src.setdefault(e["source"], []).append(e)
    order = sorted(by_src, key=lambda s: when(by_src[s][0]), reverse=True)
    picked, rnd = [], 0
    while len(picked) < limit and any(rnd < len(v) for v in by_src.values()):
        for src in order:
            if rnd < len(by_src[src]) and len(picked) < limit:
                picked.append(by_src[src][rnd])
        rnd += 1
    return sorted(picked, key=when, reverse=True)


def collect():
    now = datetime.datetime.now(datetime.timezone.utc)
    buckets = {k: [] for k in SECTIONS}
    report = []
    seen = set()
    for section, source, url in FEEDS:
        try:
            entries = parse_feed(fetch(url))
        except Exception as e:  # one broken feed must not stop the edition
            print(f"[warn] {source} ({section}) failed: {e}")
            report.append({"section": section, "source": source, "ok": False, "count": 0, "error": str(e)[:120]})
            continue
        dropped = 0
        if url in TOPIC_FILTER:
            kept = [e for e in entries if on_topic(TOPIC_FILTER[url], e)]
            dropped = len(entries) - len(kept)
            entries = kept
        fresh = []
        for e in entries:
            if e["published"] and (now - e["published"]).total_seconds() > MAX_AGE_BY_SECTION.get(section, MAX_AGE_HOURS) * 3600:
                continue
            if norm(e["title"]) in seen:
                continue
            fresh.append(e)
        fresh.sort(key=when, reverse=True)
        taken = 0
        for e in fresh:
            if taken >= PER_FEED:
                break
            seen.add(norm(e["title"]))
            e["source"] = source
            buckets[section].append(e)
            taken += 1
        print(f"[ok] {source} ({section}): {taken} items" + (f" (off-topic dropped: {dropped})" if dropped else ""))
        report.append({"section": section, "source": source, "ok": True, "count": taken, "dropped": dropped, "error": ""})
    items = []
    for section in SECTIONS:
        for e in pick_section(buckets[section], PER_SECTION):
            items.append({
                "id": f"{section[:2]}{len(items)+1}",
                "section": section,
                "source": e["source"],
                "link": e["link"],
                "published": e["published"].isoformat() if e["published"] else "",
                "title": {"en": e["title"], "fa": ""},
                "summary": {"en": e["summary"], "fa": ""},
            })
    return items, report


def extract_json(text):
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[a:b + 1])


def ask_claude(items, key):
    payload = [{"id": i["id"], "section": i["section"], "title": i["title"]["en"], "snippet": i["summary"]["en"]} for i in items]
    prompt = (
        "You are the editor of a daily economy and technology briefing.\n"
        "For each item below return: title_fa (natural, accurate Persian headline), "
        "summary_en (ONE or TWO sentences, written in your own words, neutral, no quotes from the snippet) and "
        "summary_fa (the same summary in fluent Persian). Keep company names, people and numbers exact. "
        "Do not invent facts that are not in the title or snippet.\n"
        "Also return brief_en and brief_fa: a 2-3 sentence overview of the day's main themes across all items.\n"
        "Reply with ONE JSON object only, no markdown fences, in this shape:\n"
        '{"brief_en":"","brief_fa":"","items":[{"id":"","title_fa":"","summary_en":"","summary_fa":""}]}\n\n'
        "ITEMS:\n" + json.dumps(payload, ensure_ascii=False)
    )
    body = json.dumps({"model": MODEL, "max_tokens": 6000, "temperature": 0.2,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as r:
        reply = json.loads(r.read())
    text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
    return extract_json(text)


def load_previous():
    """Previously published machine translations, keyed by article link (saves time and keeps text stable)."""
    try:
        with open(OUT, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    if d.get("translator") != "argos":
        return {}
    return {it["link"]: it for it in d.get("items", []) if isinstance(it, dict) and it.get("link")}


def ensure_argos():
    """Install the free translation library on first use (GitHub Actions runners have pip and network)."""
    try:
        import argostranslate.package  # noqa: F401
    except ImportError:
        print("[info] installing argostranslate (first run takes a few minutes)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "argostranslate"], check=True, timeout=1500)


def argos_translator():
    """Return a function en->fa using Argos Translate (free, open source, runs offline once the model is installed)."""
    import argostranslate.package as pkg
    import argostranslate.translate as tr

    def has_pair():
        langs = {l.code: l for l in tr.get_installed_languages()}
        return "en" in langs and "fa" in langs and langs["en"].get_translation(langs["fa"]) is not None

    if not has_pair():
        pkg.update_package_index()
        cand = next((p for p in pkg.get_available_packages() if p.from_code == "en" and p.to_code == "fa"), None)
        if cand is None:
            raise RuntimeError("no en->fa model in the Argos package index")
        pkg.install_from_path(cand.download())
        if not has_pair():
            raise RuntimeError("en->fa model did not install")
    return lambda text: tr.translate(text, "en", "fa")


def translate_local(items, prev):
    """Fill title.fa / summary.fa with Argos machine translation. Returns True if any title was translated."""
    todo = []
    for it in items:
        old = prev.get(it["link"])
        if old and (old.get("title") or {}).get("fa"):
            it["title"]["fa"] = old["title"]["fa"]
            it["summary"]["fa"] = (old.get("summary") or {}).get("fa", "")
        else:
            todo.append(it)
    if todo:
        ensure_argos()
        tx = argos_translator()
        for it in todo:
            for field, limit in (("title", 300), ("summary", 400)):
                src = (it[field]["en"] or "").strip()[:limit]
                if not src:
                    continue
                try:
                    out = (tx(src) or "").strip()
                except Exception as e:
                    print(f"[warn] could not translate one {field}: {e}")
                    continue
                if out and out != src:
                    it[field]["fa"] = out
    return any(it["title"]["fa"] for it in items)


def main():
    items, report = collect()
    if not items:
        print("[error] no items collected; keeping the previous news.json")
        sys.exit(1)
    brief = {"en": "", "fa": ""}
    translated = False
    translator = ""
    translator_error = ""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        try:
            res = ask_claude(items, key)
            by_id = {x.get("id"): x for x in res.get("items", []) if isinstance(x, dict)}
            for it in items:
                x = by_id.get(it["id"])
                if not x:
                    continue
                it["title"]["fa"] = (x.get("title_fa") or "").strip()
                if (x.get("summary_en") or "").strip():
                    it["summary"]["en"] = x["summary_en"].strip()
                it["summary"]["fa"] = (x.get("summary_fa") or "").strip()
            brief = {"en": (res.get("brief_en") or "").strip(), "fa": (res.get("brief_fa") or "").strip()}
            translated = any(it["title"]["fa"] for it in items)
            translator = "claude" if translated else ""
        except Exception as e:
            print(f"[warn] translation step failed, publishing English only: {e}")
    elif os.environ.get("LOCAL_TRANSLATE", "argos").strip().lower() == "argos":  # default; set to "off" to disable
        try:
            translated = translate_local(items, load_previous())
            translator = "argos" if translated else ""
            print(f"[info] local (Argos) translation: translated={translated}")
        except Exception as e:  # missing package, no model, no network... never block the English edition
            translator_error = (type(e).__name__ + ": " + str(e)).strip()[:160]
            print(f"[warn] local translation unavailable, publishing English only: {translator_error}")
    else:
        print("[info] no translator configured; publishing English only")
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {"generated_at": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"),
           "translated": translated, "translator": translator, "translator_error": translator_error, "brief": brief, "feeds": report, "items": items}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[done] wrote {OUT}: {len(items)} items, translated={translated}")


if __name__ == "__main__":
    main()
