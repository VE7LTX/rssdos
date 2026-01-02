#!/usr/bin/env python3
"""
RSSDOS — World Feed (Three-Pane Retro GUI, Tkinter) + TTS (Windows built-in)

Layout:
- Top horizontal "HEADLINES" ribbon (newest items, clickable)
- Bottom split panes:
  - Left: scan list (fixed columns)
  - Right: detail view (clean + wrapped + clickable URL)

TTS:
- Zero-pip-deps on Windows: uses PowerShell + System.Speech.Synthesis (built-in)
- Keys:
    S  speak selected (title + summary)
    H  speak newest headline
    X  stop speaking (kills PowerShell process)

Auto-speak:
- Speaks ONLY when the newest headline changes (latch by item_id)
- Auto refresh loop (default 3 min)

Other keys:
  1–9  toggle categories
  A    toggle all categories
  R    refresh live (bypass cache)
  C    clear cache + refresh
  F    feed status window
  G    toggle grouping by category
  Enter / Double-click  open selected article

Author: Matt / VE7LTX
"""

from __future__ import annotations

import base64
import json
import pathlib
import queue
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import webbrowser
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape as html_unescape
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import font as tkfont


# =============================================================================
# CONFIG
# =============================================================================

APP_TITLE = "RSSDOS — World Feed"
CACHE_FILE = pathlib.Path("rssdos_cache.json")
SEEN_FILE = pathlib.Path("rssdos_seen.json")

CACHE_TTL_SECONDS = 15 * 60
HTTP_TIMEOUT_SECONDS = 15

MAX_ITEMS_TOTAL = 700
MAX_ITEMS_PER_FEED = 140

TITLE_CHARS_LIST = 120
SUMMARY_CHARS_DETAIL = 1400
HEADLINE_TITLE_CHARS = 70
HEADLINE_COUNT = 10

# ---- Auto refresh + auto speak (newest headline latch) ----
AUTO_REFRESH_SECONDS = 180                 # periodic live refresh
AUTO_SPEAK_NEWEST_HEADLINE_ON_CHANGE = True
AUTO_SPEAK_ON_START = False                # False = don't speak at first load
AUTO_SPEAK_INCLUDE_SUMMARY = False         # keep short; True reads summary too

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36 RSSDOS/desktop"
)

THEME = {
    "bg": "#050607",
    "panel": "#07090b",
    "fg": "#d6d6d6",
    "dim": "#8a8a8a",
    "border": "#223333",
    "select_bg": "#d6d6d6",
    "select_fg": "#050607",
    "cyan": "#5dfff6",
    "magenta": "#ff5df0",
    "red": "#ff4b4b",
    "green": "#5dff7a",
}

CAT_COLOR = {
    "NEWS": "#5dfff6",
    "WORLD": "#ff5df0",
    "TECH": "#57a7ff",
    "SCIENCE": "#ffe35d",
    "RESEARCH": "#5dff7a",
    "FINANCE": "#ffb86b",
    "ECONOMY": "#c792ea",
    "TRADE": "#ff4b4b",
    "WEATHER": "#7aa2f7",
    "OTHER": "#8a8a8a",
}

# 1–9 mapping
CATEGORY_KEYS = [
    "ECONOMY",   # 1
    "FINANCE",   # 2
    "TRADE",     # 3
    "TECH",      # 4
    "SCIENCE",   # 5
    "RESEARCH",  # 6
    "WEATHER",   # 7
    "WORLD",     # 8
    "NEWS",      # 9
]

# Headlines ribbon uses these categories (edit to taste)
HEADLINE_CATS = set(CATEGORY_KEYS)  # or set(["NEWS","WORLD"])

# Source codes for scan list
SRC_CODE = {
    "CBC Top Stories": "CBC",
    "CBC Canada": "CBC",
    "Al Jazeera": "AJZ",
    "The Guardian World": "GDN",
    "The Guardian Business": "GDN",
    "BBC World": "BBC",
    "BBC Sci/Env": "BBC",
    "Ars Technica": "ARS",
    "The Register": "REG",
    "Hacker News": "HN",
    "ScienceDaily": "SCI",
    "NASA Breaking": "NASA",
    "arXiv cs.AI": "ARX",
    "arXiv cs.LG": "ARX",
    "Bank of Canada News": "BoC",
    "BoC Press Releases": "BoC",
    "BoC Market Notices": "BoC",
    "WTO Latest News": "WTO",
    "Env Canada (BC Warnings)": "ECCC",
}

# Feeds
FEEDS: List[Dict[str, Any]] = [
    # News / World
    {"cat": "NEWS", "name": "CBC Top Stories", "urls": ["https://www.cbc.ca/webfeed/rss/rss-topstories"]},
    {"cat": "NEWS", "name": "CBC Canada", "urls": ["https://www.cbc.ca/webfeed/rss/rss-canada"]},
    {"cat": "WORLD", "name": "Al Jazeera", "urls": ["https://www.aljazeera.com/xml/rss/all.xml"]},
    {"cat": "WORLD", "name": "The Guardian World", "urls": ["https://www.theguardian.com/world/rss"]},
    {"cat": "WORLD", "name": "BBC World", "urls": ["http://feeds.bbci.co.uk/news/world/rss.xml"]},

    # Finance / Economy / Trade
    {"cat": "FINANCE", "name": "The Guardian Business", "urls": ["https://www.theguardian.com/business/rss"]},
    {"cat": "ECONOMY", "name": "Bank of Canada News", "urls": ["https://www.bankofcanada.ca/utility/news/feed/"]},
    {"cat": "ECONOMY", "name": "BoC Press Releases", "urls": ["https://www.bankofcanada.ca/content_type/press-releases/feed/"]},
    {"cat": "FINANCE", "name": "BoC Market Notices", "urls": ["https://www.bankofcanada.ca/content_type/notices/feed/"]},
    {"cat": "TRADE", "name": "WTO Latest News", "urls": ["https://www.wto.org/library/rss/latest_news_e.xml"]},

    # Science / Research / Tech
    {"cat": "SCIENCE", "name": "ScienceDaily", "urls": ["https://www.sciencedaily.com/rss/all.xml"]},
    {"cat": "SCIENCE", "name": "BBC Sci/Env", "urls": ["http://feeds.bbci.co.uk/news/science_and_environment/rss.xml"]},
    {"cat": "SCIENCE", "name": "NASA Breaking", "urls": ["https://www.nasa.gov/rss/dyn/breaking_news.rss"]},
    {"cat": "RESEARCH", "name": "arXiv cs.AI", "urls": ["http://export.arxiv.org/rss/cs.AI"]},
    {"cat": "RESEARCH", "name": "arXiv cs.LG", "urls": ["http://export.arxiv.org/rss/cs.LG"]},
    {"cat": "TECH", "name": "Ars Technica", "urls": ["https://feeds.arstechnica.com/arstechnica/index"]},
    {"cat": "TECH", "name": "The Register", "urls": ["https://www.theregister.com/headlines.atom"]},
    {"cat": "TECH", "name": "Hacker News", "urls": ["https://hnrss.org/frontpage"]},

    # Weather
    {"cat": "WEATHER", "name": "Env Canada (BC Warnings)", "urls": ["https://weather.gc.ca/rss/battleboard/bcrm1_e.xml"]},
]


# =============================================================================
# MODELS
# =============================================================================

@dataclass
class Item:
    id: str
    epoch: float
    ts: str
    cat: str
    src: str
    src_code: str
    title: str
    summary: str
    url: str
    domain: str
    is_new: bool


@dataclass
class FeedStatus:
    name: str
    cat: str
    status: str        # OK / FAIL
    used_url: str
    error: str
    count: int


# =============================================================================
# UTIL
# =============================================================================

def _strip_html(text: str) -> str:
    out = []
    in_tag = False
    for ch in text or "":
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag:
            out.append(ch)
    return "".join(out).replace("\u00a0", " ").strip()


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 1)].rstrip() + "…"


def _domain_from_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    try:
        rest = url.split("://", 1)[1] if "://" in url else url
        host = rest.split("/", 1)[0]
        return host.lower().replace("www.", "")
    except Exception:
        return ""


def _parse_date_any(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0

    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        pass

    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _fmt_hhmm(epoch: float) -> str:
    if not epoch:
        return "--:--"
    try:
        return time.strftime("%H:%M", time.localtime(epoch))
    except Exception:
        return "--:--"


def http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as r:
        return r.read()


def parse_feed_best_effort(raw: bytes) -> List[Dict[str, str]]:
    """
    Return list of {title, url, summary, date_str} from RSS or Atom.
    """
    root = ET.fromstring(raw)

    # RSS
    channel = root.find("channel")
    if channel is not None:
        out: List[Dict[str, str]] = []
        for it in channel.findall("item")[:MAX_ITEMS_PER_FEED]:
            title = it.findtext("title") or ""
            link = it.findtext("link") or ""
            desc = it.findtext("description") or it.findtext("summary") or ""
            pub = it.findtext("pubDate") or ""
            out.append({"title": title, "url": link, "summary": desc, "date": pub})
        return out

    # Atom
    entries = [e for e in root.iter() if e.tag.lower().endswith("entry")]
    out2: List[Dict[str, str]] = []
    for e in entries[:MAX_ITEMS_PER_FEED]:
        title_el = next((c for c in e if c.tag.lower().endswith("title")), None)
        title = title_el.text if title_el is not None and title_el.text else ""

        updated_el = next((c for c in e if c.tag.lower().endswith("updated")), None)
        published_el = next((c for c in e if c.tag.lower().endswith("published")), None)
        date_str = (updated_el.text if updated_el is not None and updated_el.text else "") or (
            published_el.text if published_el is not None and published_el.text else ""
        )

        summary_el = next((c for c in e if c.tag.lower().endswith("summary")), None)
        content_el = next((c for c in e if c.tag.lower().endswith("content")), None)
        summary = (summary_el.text if summary_el is not None and summary_el.text else "") or (
            content_el.text if content_el is not None and content_el.text else ""
        )

        link = ""
        for c in e:
            if c.tag.lower().endswith("link"):
                href = c.attrib.get("href", "").strip()
                rel = c.attrib.get("rel", "").strip().lower()
                if href and (not rel or rel == "alternate"):
                    link = href
                    break

        out2.append({"title": title, "url": link, "summary": summary, "date": date_str})
    return out2


def load_seen() -> set[str]:
    try:
        if SEEN_FILE.exists():
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(str(x) for x in data)
    except Exception:
        pass
    return set()


def save_seen(seen: set[str]) -> None:
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2), encoding="utf-8")
    except Exception:
        pass


def load_cache() -> Optional[Dict[str, Any]]:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        age = time.time() - float(data.get("cache_ts", 0))
        if age <= CACHE_TTL_SECONDS:
            return data
    except Exception:
        return None
    return None


def save_cache(items: List[Item], statuses: List[FeedStatus]) -> None:
    payload = {
        "cache_ts": time.time(),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": [it.__dict__ for it in items],
        "statuses": [st.__dict__ for st in statuses],
    }
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_cache() -> None:
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
    except Exception:
        pass


# =============================================================================
# FETCH
# =============================================================================

def fetch_all(force_refresh: bool) -> Tuple[List[Item], List[FeedStatus], str]:
    if not force_refresh:
        cached = load_cache()
        if cached:
            items = [Item(**d) for d in cached.get("items", [])]
            statuses = [FeedStatus(**d) for d in cached.get("statuses", [])]
            return items, statuses, "cache"

    seen = load_seen()
    items: List[Item] = []
    statuses: List[FeedStatus] = []

    for f in FEEDS:
        cat = f["cat"]
        name = f["name"]
        urls: List[str] = f.get("urls", [])
        used_url = ""
        last_err = ""
        count = 0

        for u in urls:
            try:
                raw = http_get(u)
                parsed = parse_feed_best_effort(raw)

                for p in parsed:
                    title_raw = html_unescape(_strip_html(p.get("title", "")))
                    summary_raw = html_unescape(_strip_html(p.get("summary", "")))
                    url = (p.get("url", "") or "").strip()

                    fallback_id = f"{name}|{title_raw[:200]}|{p.get('date','')[:50]}"
                    item_id = url if url else fallback_id

                    epoch = _parse_date_any(p.get("date", ""))
                    domain = _domain_from_url(url)
                    is_new = item_id not in seen

                    items.append(Item(
                        id=item_id,
                        epoch=epoch,
                        ts=_fmt_hhmm(epoch),
                        cat=cat,
                        src=name,
                        src_code=SRC_CODE.get(name, name[:6].upper()),
                        title=_truncate(title_raw, 260) or "(no title)",
                        summary=_truncate(summary_raw, SUMMARY_CHARS_DETAIL),
                        url=url,
                        domain=domain,
                        is_new=is_new,
                    ))
                    count += 1

                used_url = u
                last_err = ""
                break

            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                continue

        if count > 0 and not last_err:
            statuses.append(FeedStatus(name=name, cat=cat, status="OK", used_url=used_url, error="", count=count))
        else:
            statuses.append(FeedStatus(
                name=name, cat=cat, status="FAIL",
                used_url=urls[0] if urls else "", error=last_err, count=0
            ))

    items.sort(key=lambda x: float(x.epoch or 0.0), reverse=True)
    items = items[:MAX_ITEMS_TOTAL]

    for it in items:
        if it.id:
            seen.add(it.id)
    save_seen(seen)

    save_cache(items, statuses)
    return items, statuses, "live"


# =============================================================================
# TTS (Windows built-in, no pip deps)
# =============================================================================

class WindowsTTSWorker:
    """
    Non-blocking TTS worker:
    - UI thread only enqueues text
    - Worker thread runs PowerShell and waits there (UI stays responsive)
    - stop() kills current speech immediately
    """
    def __init__(self):
        self._q: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._alive = True
        self._thread.start()

    def shutdown(self) -> None:
        self._alive = False
        self.stop()
        try:
            self._q.put_nowait(("__quit__", None))
        except Exception:
            pass

    def stop(self) -> None:
        self._q.put(("stop", None))

    def speak_async(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._q.put(("speak", text))

    # ---------------- internals ----------------

    def _kill_proc(self) -> None:
        with self._lock:
            p = self._proc
            self._proc = None

        if not p or p.poll() is not None:
            return

        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

    def _run(self) -> None:
        while self._alive:
            cmd, payload = self._q.get()
            if cmd == "__quit__":
                break

            if cmd == "stop":
                self._kill_proc()
                # drain queued speech so stop actually stops the pipeline
                while True:
                    try:
                        c2, _ = self._q.get_nowait()
                        if c2 == "__quit__":
                            return
                    except queue.Empty:
                        break
                continue

            if cmd != "speak":
                continue

            text = (payload or "").strip()
            if not text:
                continue

            if len(text) > 2500:
                text = text[:2490] + "…"

            b = text.encode("utf-16le", errors="ignore")
            b64 = base64.b64encode(b).decode("ascii")

            ps = (
                "$b=[Convert]::FromBase64String('{b64}');"
                "$t=[Text.Encoding]::Unicode.GetString($b);"
                "Add-Type -AssemblyName System.Speech;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.Rate=0;"
                "$s.Volume=100;"
                "$s.Speak($t);"
            ).format(b64=b64)

            self._kill_proc()

            try:
                p = subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                with self._lock:
                    self._proc = p
                p.wait()
            except Exception:
                self._kill_proc()
                continue


# =============================================================================
# GUI
# =============================================================================

class RSSDOSApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1400x800")
        self.configure(bg=THEME["bg"])

        self.f_mono = tkfont.Font(family="Consolas", size=11)
        self.f_bold = tkfont.Font(family="Consolas", size=11, weight="bold")
        self.f_big = tkfont.Font(family="Consolas", size=12, weight="bold")

        self.items: List[Item] = []
        self.statuses: List[FeedStatus] = []
        self.source_mode: str = "cache"

        self.active_cats = set(CATEGORY_KEYS)
        self.group_by_cat = False
        self.filter_text = ""

        self.display_rows: List[Dict[str, Any]] = []
        self._headline_items: List[Item] = []

        self._q: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._loading = False

        self.tts = WindowsTTSWorker()

        # --- Auto-speak latch (speak only when newest headline changes) ---
        self._first_load_done = False
        self._last_newest_headline_id: Optional[str] = None

        self._build_ui()
        self._bind_keys()

        # periodic refresh loop
        self.after(AUTO_REFRESH_SECONDS * 1000, self._auto_refresh_tick)

        # initial load
        self._load(force_refresh=False)

        # ensure we kill TTS worker on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self.tts.shutdown()
        except Exception:
            pass
        self.destroy()

    # ---------------- Auto refresh ----------------

    def _auto_refresh_tick(self):
        try:
            if not self._loading:
                self._load(force_refresh=True)
        finally:
            self.after(AUTO_REFRESH_SECONDS * 1000, self._auto_refresh_tick)

    # ---------------- UI build ----------------

    def _build_ui(self):
        self.header = tk.Label(
            self,
            text="RSSDOS — Headlines + Two-Pane (1-9 cats, A all, R refresh, C cache, F feeds, G group, S speak, X stop, H headline)",
            bg=THEME["panel"],
            fg=THEME["fg"],
            font=self.f_mono,
            anchor="w",
            padx=12,
            pady=8
        )
        self.header.pack(fill="x")

        self.headline_panel = tk.Frame(self, bg=THEME["panel"])
        self.headline_panel.pack(fill="x")

        tk.Label(
            self.headline_panel,
            text="HEADLINES:",
            bg=THEME["panel"],
            fg=THEME["dim"],
            font=self.f_mono,
            padx=12,
            pady=6
        ).pack(side="left")

        self.head_canvas = tk.Canvas(
            self.headline_panel,
            bg=THEME["panel"],
            highlightthickness=0,
            height=44
        )
        self.head_canvas.pack(side="left", fill="x", expand=True)

        self.head_scroll = tk.Scrollbar(self.headline_panel, orient="horizontal", command=self.head_canvas.xview)
        self.head_scroll.pack(side="bottom", fill="x")

        self.head_canvas.configure(xscrollcommand=self.head_scroll.set)

        self.head_inner = tk.Frame(self.head_canvas, bg=THEME["panel"])
        self.head_window = self.head_canvas.create_window((0, 0), window=self.head_inner, anchor="w")

        self.head_inner.bind("<Configure>", lambda e: self.head_canvas.configure(scrollregion=self.head_canvas.bbox("all")))
        self.head_canvas.bind("<Configure>", self._on_head_canvas_resize)

        self.topbar = tk.Label(
            self,
            text="",
            bg=THEME["panel"],
            fg=THEME["dim"],
            font=self.f_mono,
            anchor="w",
            padx=12,
            pady=6
        )
        self.topbar.pack(fill="x")

        pw = tk.PanedWindow(self, orient="horizontal", bg=THEME["bg"], sashrelief="flat", sashwidth=6)
        pw.pack(fill="both", expand=True)

        left = tk.Frame(pw, bg=THEME["bg"])
        pw.add(left, width=620)

        search_row = tk.Frame(left, bg=THEME["bg"])
        search_row.pack(fill="x", padx=10, pady=(10, 6))

        tk.Label(search_row, text="FILTER:", bg=THEME["bg"], fg=THEME["dim"], font=self.f_mono).pack(side="left")
        self.search_var = tk.StringVar(value="")
        self.search = tk.Entry(
            search_row, textvariable=self.search_var,
            bg=THEME["panel"], fg=THEME["fg"], insertbackground=THEME["fg"],
            relief="flat", font=self.f_mono
        )
        self.search.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.search_var.trace_add("write", lambda *_: self._on_search_change())

        tk.Label(
            left,
            text="TIME  CAT  SRC   TITLE",
            bg=THEME["bg"],
            fg=THEME["dim"],
            font=self.f_mono,
            anchor="w"
        ).pack(fill="x", padx=10)

        list_frame = tk.Frame(left, bg=THEME["bg"])
        list_frame.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        self.lb = tk.Listbox(
            list_frame,
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=self.f_mono,
            selectbackground=THEME["select_bg"],
            selectforeground=THEME["select_fg"],
            activestyle="none",
            highlightthickness=0,
            relief="flat"
        )
        self.lb.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(list_frame, command=self.lb.yview)
        sb.pack(side="right", fill="y")
        self.lb.configure(yscrollcommand=sb.set)

        self.lb.bind("<<ListboxSelect>>", lambda e: self._on_select())
        self.lb.bind("<Double-Button-1>", lambda e: self._open_selected())

        right = tk.Frame(pw, bg=THEME["bg"])
        pw.add(right)

        self.detail = tk.Text(
            right,
            bg=THEME["bg"],
            fg=THEME["fg"],
            insertbackground=THEME["fg"],
            font=self.f_mono,
            wrap="word",
            relief="flat",
            highlightthickness=0,
            padx=12,
            pady=12
        )
        self.detail.pack(fill="both", expand=True)

        self.detail.tag_configure("h1", font=self.f_big, foreground=THEME["fg"])
        self.detail.tag_configure("dim", foreground=THEME["dim"])
        self.detail.tag_configure("src", foreground=THEME["cyan"])
        self.detail.tag_configure("cat", foreground=THEME["magenta"])
        self.detail.tag_configure("url", foreground=THEME["cyan"], underline=True)
        self.detail.tag_configure("new", foreground=THEME["green"])
        self.detail.tag_configure("warn", foreground=THEME["red"])

        self.detail.tag_bind("url", "<Button-1>", self._on_detail_url_click)
        self.detail.configure(state="disabled")

        self.footer = tk.Label(
            self,
            text="> LOADING…",
            bg=THEME["panel"],
            fg=THEME["dim"],
            font=self.f_mono,
            anchor="w",
            padx=12,
            pady=8
        )
        self.footer.pack(fill="x")

    def _bind_keys(self):
        self.bind("<KeyPress-r>", lambda e: self._load(force_refresh=True))
        self.bind("<KeyPress-R>", lambda e: self._load(force_refresh=True))

        self.bind("<KeyPress-c>", lambda e: self._clear_cache_and_reload())
        self.bind("<KeyPress-C>", lambda e: self._clear_cache_and_reload())

        self.bind("<KeyPress-a>", lambda e: self._toggle_all())
        self.bind("<KeyPress-A>", lambda e: self._toggle_all())

        self.bind("<KeyPress-f>", lambda e: self._show_feed_status())
        self.bind("<KeyPress-F>", lambda e: self._show_feed_status())

        self.bind("<KeyPress-g>", lambda e: self._toggle_group())
        self.bind("<KeyPress-G>", lambda e: self._toggle_group())

        # TTS
        self.bind("<KeyPress-s>", lambda e: self._tts_speak_selected())
        self.bind("<KeyPress-S>", lambda e: self._tts_speak_selected())
        self.bind("<KeyPress-x>", lambda e: self._tts_stop())
        self.bind("<KeyPress-X>", lambda e: self._tts_stop())
        self.bind("<KeyPress-h>", lambda e: self._tts_speak_headline())
        self.bind("<KeyPress-H>", lambda e: self._tts_speak_headline())

        for i, cat in enumerate(CATEGORY_KEYS, start=1):
            self.bind(f"<KeyPress-{i}>", lambda e, c=cat: self._toggle_cat(c))

        self.bind("<Return>", lambda e: self._open_selected())

    # ---------------- Headlines ribbon ----------------

    def _on_head_canvas_resize(self, event):
        self.head_canvas.itemconfigure(self.head_window, height=event.height)

    def _render_headlines(self):
        for child in list(self.head_inner.winfo_children()):
            child.destroy()

        candidates = [
            it for it in self.items
            if it.cat in HEADLINE_CATS and self._passes_filters(it)
        ]
        candidates.sort(key=lambda x: float(x.epoch or 0.0), reverse=True)
        self._headline_items = candidates[:HEADLINE_COUNT]

        if not self._headline_items:
            tk.Label(
                self.head_inner, text="(none)", bg=THEME["panel"], fg=THEME["dim"], font=self.f_mono, padx=8, pady=6
            ).pack(side="left")
            return

        for i, it in enumerate(self._headline_items):
            cat3 = it.cat[:3]
            new = " NEW" if it.is_new else ""
            text = f"{it.ts} [{cat3}] {it.src_code}: {_truncate(it.title, HEADLINE_TITLE_CHARS)}{new}"

            fg = CAT_COLOR.get(it.cat, THEME["fg"])
            chip = tk.Label(
                self.head_inner,
                text=text,
                bg=THEME["bg"],
                fg=fg,
                font=self.f_mono,
                padx=10,
                pady=6,
                bd=1,
                relief="solid",
                highlightthickness=0
            )
            chip.pack(side="left", padx=6, pady=6)

            chip.bind("<Button-1>", lambda e, item_id=it.id: self._select_item_by_id(item_id))
            chip.bind("<Double-Button-1>", lambda e, item_id=it.id: self._open_item_by_id(item_id))

    def _select_item_by_id(self, item_id: str):
        for idx, row in enumerate(self.display_rows):
            if row.get("type") == "item" and row["item"].id == item_id:
                self.lb.selection_clear(0, tk.END)
                self.lb.selection_set(idx)
                self.lb.activate(idx)
                self.lb.see(idx)
                self._render_detail_from_row_index(idx)
                return

    def _open_item_by_id(self, item_id: str):
        for row in self.display_rows:
            if row.get("type") == "item" and row["item"].id == item_id:
                if row["item"].url:
                    webbrowser.open(row["item"].url)
                return

    # ---------------- State changes ----------------

    def _toggle_cat(self, cat: str):
        if cat in self.active_cats:
            self.active_cats.remove(cat)
        else:
            self.active_cats.add(cat)
        self._rebuild_display()

    def _toggle_all(self):
        if self.active_cats:
            self.active_cats.clear()
        else:
            self.active_cats = set(CATEGORY_KEYS)
        self._rebuild_display()

    def _toggle_group(self):
        self.group_by_cat = not self.group_by_cat
        self._rebuild_display()

    def _on_search_change(self):
        self.filter_text = (self.search_var.get() or "").strip().lower()
        self._rebuild_display()

    def _clear_cache_and_reload(self):
        clear_cache()
        self._load(force_refresh=True)

    # ---------------- Loading (threaded) ----------------

    def _load(self, force_refresh: bool):
        if self._loading:
            return
        self._loading = True
        self.footer.config(text="> LOADING…")
        self._set_detail_loading()
        self.lb.delete(0, tk.END)

        t = threading.Thread(target=self._worker_fetch, args=(force_refresh,), daemon=True)
        t.start()
        self.after(60, self._poll_queue)

    def _worker_fetch(self, force_refresh: bool):
        try:
            items, statuses, source = fetch_all(force_refresh=force_refresh)
            self._q.put(("ok", (items, statuses, source)))
        except Exception as e:
            self._q.put(("err", e))

    def _poll_queue(self):
        try:
            kind, payload = self._q.get_nowait()
        except queue.Empty:
            self.after(60, self._poll_queue)
            return

        self._loading = False

        if kind == "err":
            self.footer.config(text=f"> ERROR · {payload}")
            self._set_detail_error(str(payload))
            return

        items, statuses, source = payload
        self.items = items
        self.statuses = statuses
        self.source_mode = source

        self._rebuild_display()

        # --- Auto-speak newest headline ONLY when it changes ---
        self._auto_speak_newest_headline_if_changed()

    # ---------------- Display build ----------------

    def _passes_filters(self, it: Item) -> bool:
        if self.active_cats and it.cat not in self.active_cats:
            return False
        if not self.filter_text:
            return True
        blob = f"{it.title} {it.summary} {it.src} {it.domain}".lower()
        return self.filter_text in blob

    def _rebuild_display(self):
        filtered = [it for it in self.items if self._passes_filters(it)]

        counts: Dict[str, int] = {c: 0 for c in CATEGORY_KEYS}
        for it in filtered:
            if it.cat in counts:
                counts[it.cat] += 1

        active = [c for c in CATEGORY_KEYS if c in self.active_cats] if self.active_cats else []
        active_str = ",".join(active) if active else "(none)"
        counts_str = " | ".join([f"{c[:3]} {counts.get(c,0)}" for c in CATEGORY_KEYS])
        group_str = "GROUP:CAT" if self.group_by_cat else "GROUP:TIME"
        filt_str = f"FILTER:'{self.filter_text}'" if self.filter_text else "FILTER:(none)"
        self.topbar.config(text=f"{group_str} · {filt_str} · ACTIVE:{active_str} · {counts_str}")

        ok = sum(1 for s in self.statuses if s.status == "OK")
        fail = sum(1 for s in self.statuses if s.status == "FAIL")
        self.footer.config(
            text=f"> OK · {len(filtered)}/{len(self.items)} items · {self.source_mode} · ok {ok}/{len(self.statuses)} · fail {fail} · (S speak, X stop)"
        )

        rows: List[Dict[str, Any]] = []
        if self.group_by_cat:
            by_cat: Dict[str, List[Item]] = {}
            for it in filtered:
                by_cat.setdefault(it.cat, []).append(it)
            for cat in CATEGORY_KEYS:
                grp = by_cat.get(cat, [])
                if not grp:
                    continue
                grp.sort(key=lambda x: float(x.epoch or 0.0), reverse=True)
                rows.append({"type": "header", "cat": cat, "count": len(grp)})
                for it in grp:
                    rows.append({"type": "item", "item": it})
        else:
            for it in filtered:
                rows.append({"type": "item", "item": it})

        self.display_rows = rows
        self._render_list()
        self._render_headlines()
        self._select_first_item()

    def _render_list(self):
        self.lb.delete(0, tk.END)

        for i, row in enumerate(self.display_rows):
            if row["type"] == "header":
                cat = row["cat"]
                cnt = row["count"]
                label = f"=== {cat} ({cnt}) " + "=" * 60
                self.lb.insert(tk.END, label[:240])
                try:
                    self.lb.itemconfig(i, fg=THEME["magenta"])
                except Exception:
                    pass
                continue

            it: Item = row["item"]
            cat3 = it.cat[:3]
            src = it.src_code[:6].ljust(6)
            new = "*" if it.is_new else " "
            line = f"{it.ts:>5}{new} [{cat3}] {src} {_truncate(it.title, TITLE_CHARS_LIST)}"
            self.lb.insert(tk.END, line)

            color = CAT_COLOR.get(it.cat, THEME["fg"])
            try:
                self.lb.itemconfig(i, fg=color)
            except Exception:
                pass

    def _select_first_item(self):
        for idx, row in enumerate(self.display_rows):
            if row["type"] == "item":
                self.lb.selection_clear(0, tk.END)
                self.lb.selection_set(idx)
                self.lb.activate(idx)
                self.lb.see(idx)
                self._render_detail_from_row_index(idx)
                return
        self._set_detail_empty()

    # ---------------- Selection + detail ----------------

    def _on_select(self):
        sel = self.lb.curselection()
        if not sel:
            return
        self._render_detail_from_row_index(int(sel[0]))

    def _render_detail_from_row_index(self, idx: int):
        if idx < 0 or idx >= len(self.display_rows):
            return

        row = self.display_rows[idx]
        if row["type"] == "header":
            for j in range(idx + 1, len(self.display_rows)):
                if self.display_rows[j]["type"] == "item":
                    self.lb.selection_clear(0, tk.END)
                    self.lb.selection_set(j)
                    self.lb.activate(j)
                    self.lb.see(j)
                    self._render_detail_from_row_index(j)
                    return
            self._set_detail_empty()
            return

        it: Item = row["item"]

        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)

        self.detail.insert(tk.END, it.title + "\n", ("h1",))

        new_tag = "new" if it.is_new else "dim"
        self.detail.insert(tk.END, "NEW  " if it.is_new else "", (new_tag,))
        self.detail.insert(tk.END, f"[{it.cat}] ", ("cat",))
        self.detail.insert(tk.END, f"{it.src}  ", ("src",))
        self.detail.insert(tk.END, f"{it.ts}  ", ("dim",))
        self.detail.insert(tk.END, f"{it.domain}\n\n" if it.domain else "\n\n", ("dim",))

        if it.summary:
            self.detail.insert(tk.END, it.summary.strip() + "\n\n", ())
        else:
            self.detail.insert(tk.END, "(no summary)\n\n", ("dim",))

        if it.url:
            self.detail.insert(tk.END, "OPEN: ", ("dim",))
            self.detail.insert(tk.END, it.url, ("url",))
            self.detail.insert(tk.END, "\n", ())
        else:
            self.detail.insert(tk.END, "(no url)\n", ("warn",))

        self.detail._active_url = it.url   # type: ignore[attr-defined]
        self.detail._active_item = it      # type: ignore[attr-defined]
        self.detail.configure(state="disabled")

    def _open_selected(self):
        sel = self.lb.curselection()
        if not sel:
            return
        idx = int(sel[0])
        row = self.display_rows[idx] if 0 <= idx < len(self.display_rows) else None
        if not row or row["type"] != "item":
            return
        it: Item = row["item"]
        if it.url:
            webbrowser.open(it.url)

    def _on_detail_url_click(self, event):
        url = getattr(self.detail, "_active_url", "")
        if url:
            webbrowser.open(url)

    # ---------------- Auto-speak newest headline latch ----------------

    def _auto_speak_newest_headline_if_changed(self):
        if not AUTO_SPEAK_NEWEST_HEADLINE_ON_CHANGE:
            self._first_load_done = True
            return

        if not self._headline_items:
            self._first_load_done = True
            return

        newest = self._headline_items[0]
        newest_id = newest.id or ""

        # first-load behavior
        if not self._first_load_done:
            self._first_load_done = True
            self._last_newest_headline_id = newest_id
            if AUTO_SPEAK_ON_START:
                self.tts.speak_async(self._compose_speak_text(newest, include_summary=AUTO_SPEAK_INCLUDE_SUMMARY))
                self.footer.config(text=self.footer.cget("text") + " · AUTO-TTS start")
            return

        # latch behavior
        if newest_id and newest_id != (self._last_newest_headline_id or ""):
            self._last_newest_headline_id = newest_id
            self.tts.speak_async(self._compose_speak_text(newest, include_summary=AUTO_SPEAK_INCLUDE_SUMMARY))
            self.footer.config(text=self.footer.cget("text") + " · AUTO-TTS new headline")

    # ---------------- TTS ----------------

    def _tts_stop(self):
        self.tts.stop()
        self.footer.config(text=self.footer.cget("text") + " · TTS stopped")

    def _tts_speak_selected(self):
        it: Optional[Item] = getattr(self.detail, "_active_item", None)
        if not it:
            return
        text = self._compose_speak_text(it, include_summary=True)
        self.tts.speak_async(text)
        self.footer.config(text=self.footer.cget("text") + " · TTS queued (selected)")

    def _tts_speak_headline(self):
        if not self._headline_items:
            return
        it = self._headline_items[0]
        text = self._compose_speak_text(it, include_summary=AUTO_SPEAK_INCLUDE_SUMMARY)
        self.tts.speak_async(text)
        self.footer.config(text=self.footer.cget("text") + " · TTS queued (headline)")

    def _compose_speak_text(self, it: Item, include_summary: bool) -> str:
        parts = [f"{it.cat}. {it.src_code}. {it.title}."]
        if include_summary and it.summary:
            parts.append(it.summary)
        return " ".join(parts)

    # ---------------- Detail helpers ----------------

    def _set_detail_loading(self):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)
        self.detail.insert(tk.END, "LOADING…\n", ("dim",))
        self.detail.configure(state="disabled")

    def _set_detail_empty(self):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)
        self.detail.insert(tk.END, "(no items)\n", ("dim",))
        self.detail.configure(state="disabled")

    def _set_detail_error(self, msg: str):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", tk.END)
        self.detail.insert(tk.END, "ERROR\n\n", ("warn",))
        self.detail.insert(tk.END, msg + "\n", ("dim",))
        self.detail.configure(state="disabled")

    # ---------------- Feed status window ----------------

    def _show_feed_status(self):
        w = tk.Toplevel(self)
        w.title("Feed Status")
        w.geometry("1100x520")
        w.configure(bg=THEME["bg"])

        t = tk.Text(
            w,
            bg=THEME["bg"],
            fg=THEME["fg"],
            font=self.f_mono,
            wrap="none",
            relief="flat",
            highlightthickness=0,
            padx=12,
            pady=12
        )
        t.pack(fill="both", expand=True)

        t.tag_configure("ok", foreground=THEME["green"])
        t.tag_configure("fail", foreground=THEME["red"])
        t.tag_configure("dim", foreground=THEME["dim"])
        t.tag_configure("cat", foreground=THEME["magenta"])
        t.tag_configure("src", foreground=THEME["cyan"])

        ok = 0
        fail = 0
        for st in self.statuses:
            if st.status == "OK":
                ok += 1
            else:
                fail += 1

            t.insert(tk.END, f"{st.status:<4} ", ("ok" if st.status == "OK" else "fail",))
            t.insert(tk.END, f"[{st.cat}] ", ("cat",))
            t.insert(tk.END, f"{st.name} ", ("src",))
            t.insert(tk.END, f"({st.count})\n", ("dim",))
            t.insert(tk.END, f"     {st.used_url}\n", ("dim",))
            if st.error:
                t.insert(tk.END, f"     {st.error}\n", ("fail",))
            t.insert(tk.END, "\n", ())

        t.insert(tk.END, f"Summary: OK {ok}/{len(self.statuses)} · FAIL {fail}/{len(self.statuses)}\n", ("dim",))
        t.configure(state="disabled")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    RSSDOSApp().mainloop()
