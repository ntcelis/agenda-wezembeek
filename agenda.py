#!/usr/bin/env python3
"""
Agenda de Wezembeek-Oppem — génère les calendriers .ics (FR/NL), une page web
publique et les messages WhatsApp hebdomadaires à partir de la liste officielle
des activités publiée sur www.wezembeek-oppem.be.

Usage :
    python agenda.py                 # lit le site et écrit dans ./docs
    python agenda.py --fixtures DIR  # lit des pages HTML locales (tests)
    python agenda.py --today 2026-10-15

Variables d'environnement (facultatives) :
    PAGES_URL   adresse publique du site GitHub Pages (ex. https://moi.github.io/agenda-wezembeek)
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Réglages
# --------------------------------------------------------------------------- #
BASE = "https://www.wezembeek-oppem.be"
LISTS = {"fr": "/fr/activites", "nl": "/activiteiten"}
MAX_PAGES = 15                 # garde-fou contre une boucle infinie
TZ = ZoneInfo("Europe/Brussels")
PUBLISH_WEEKDAY = 3            # 0 = lundi … 3 = jeudi
WINDOW_DAYS = 10               # jeudi → samedi de la semaine suivante
KEEP_PAST_DAYS = 120           # garder l'historique dans le calendrier
OUT = Path(__file__).parent / "docs"

# Textes modifiables librement ------------------------------------------------
TEXTS = {
    "fr": {
        "cal_name": "Agenda Wezembeek-Oppem",
        "cal_desc": "Activités publiées par la commune de Wezembeek-Oppem (mise à jour automatique).",
        "msg_title": "📅 *Agenda de Wezembeek-Oppem*",
        "msg_intro": "Bonjour à toutes et à tous ! Voici les activités prévues dans notre commune :",
        "msg_period": "du {start} au {end}",
        "msg_ongoing": "*En cours*",
        "msg_until": "jusqu'au {d}",
        "msg_empty": "Aucune activité n'est annoncée pour cette période.",
        "msg_footer": "🗓️ Tout l'agenda et l'abonnement à votre calendrier :\n{url}",
        "msg_source": "Source : site de la commune (wezembeek-oppem.be/fr/activites)",
        "page_title": "Agenda de Wezembeek-Oppem",
        "page_sub": "Toutes les activités annoncées par la commune, dans votre propre agenda.",
        "subscribe": "S'abonner",
        "sub_google": "Google Agenda",
        "sub_apple": "iPhone / Mac",
        "sub_outlook": "Outlook (travail / Microsoft 365)",
        "sub_outlook_live": "Outlook.com / Hotmail",
        "sub_copy": "Copier le lien",
        "sub_help": "L'abonnement se met à jour tout seul : les nouvelles activités apparaissent automatiquement.",
        "sub_help_outlook": "Outlook installé sur l'ordinateur : Ajouter un calendrier → S'abonner à partir du web, puis collez ce lien (il doit commencer par https://) :",
        "upcoming": "Prochaines activités",
        "updated": "Mis à jour le {d}",
        "other_lang": "Nederlands",
        "more": "Plus d'infos",
        "all_day": "toute la journée",
    },
    "nl": {
        "cal_name": "Agenda Wezembeek-Oppem",
        "cal_desc": "Activiteiten gepubliceerd door de gemeente Wezembeek-Oppem (automatisch bijgewerkt).",
        "msg_title": "📅 *Agenda van Wezembeek-Oppem*",
        "msg_intro": "Hallo allemaal! Dit zijn de geplande activiteiten in onze gemeente:",
        "msg_period": "van {start} tot {end}",
        "msg_ongoing": "*Lopend*",
        "msg_until": "tot {d}",
        "msg_empty": "Er zijn geen activiteiten aangekondigd voor deze periode.",
        "msg_footer": "🗓️ De volledige agenda en abonneren in je eigen kalender:\n{url}",
        "msg_source": "Bron: website van de gemeente (wezembeek-oppem.be/activiteiten)",
        "page_title": "Agenda van Wezembeek-Oppem",
        "page_sub": "Alle activiteiten die de gemeente aankondigt, in je eigen agenda.",
        "subscribe": "Abonneren",
        "sub_google": "Google Agenda",
        "sub_apple": "iPhone / Mac",
        "sub_outlook": "Outlook (werk / Microsoft 365)",
        "sub_outlook_live": "Outlook.com / Hotmail",
        "sub_copy": "Link kopiëren",
        "sub_help": "Het abonnement werkt zichzelf bij: nieuwe activiteiten verschijnen automatisch.",
        "sub_help_outlook": "Outlook op de computer: Agenda toevoegen → Abonneren vanaf het web, en plak deze link (hij moet beginnen met https://):",
        "upcoming": "Komende activiteiten",
        "updated": "Bijgewerkt op {d}",
        "other_lang": "Français",
        "more": "Meer info",
        "all_day": "hele dag",
    },
}

MONTHS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"],
    "nl": ["januari", "februari", "maart", "april", "mei", "juni", "juli",
           "augustus", "september", "oktober", "november", "december"],
}
DAYS = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "nl": ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"],
}
# accepte aussi les variantes sans accent
MONTH_LOOKUP = {m: i + 1 for lang in MONTHS for i, m in enumerate(MONTHS[lang])}
MONTH_LOOKUP.update({"fevrier": 2, "aout": 8, "decembre": 12})


# --------------------------------------------------------------------------- #
# Modèle
# --------------------------------------------------------------------------- #
@dataclass
class Event:
    lang: str
    title: str
    url: str
    start: str                 # ISO, heure locale de Bruxelles
    end: str | None = None
    all_day: bool = False
    location: str = ""
    category: str = ""
    subtitle: str = ""
    uid: str = ""

    # helpers ---------------------------------------------------------------
    @property
    def dt_start(self) -> datetime:
        return datetime.fromisoformat(self.start)

    @property
    def dt_end(self) -> datetime:
        if self.end:
            return datetime.fromisoformat(self.end)
        if self.all_day:
            return self.dt_start + timedelta(days=1)
        return self.dt_start + timedelta(hours=1)

    @property
    def multi_day(self) -> bool:
        last = self.dt_end - (timedelta(seconds=1) if self.all_day else timedelta(0))
        return last.date() > self.dt_start.date()


# --------------------------------------------------------------------------- #
# Lecture du site
# --------------------------------------------------------------------------- #
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (agenda-wezembeek-oppem; +https://github.com) Python-requests",
    "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8",
})


def fetch(url: str) -> str:
    last = None
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:  # réessaie
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Impossible de lire {url}: {last}")


def parse_day(text: str) -> date:
    # « jeudi 15 octobre 2026 » / « donderdag 15 oktober 2026 »
    m = re.search(r"(\d{1,2})\s+([^\s\d]+)\s+(\d{4})", text.lower())
    if not m:
        raise ValueError(f"Date illisible : {text!r}")
    month = MONTH_LOOKUP.get(m.group(2).strip("."))
    if not month:
        raise ValueError(f"Mois inconnu : {text!r}")
    return date(int(m.group(3)), month, int(m.group(1)))


def parse_hour(text: str | None):
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s*[h:.u]\s*(\d{2})", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def at(d: date, hm) -> datetime:
    return datetime(d.year, d.month, d.day, hm[0], hm[1])


def text_of(node) -> str:
    return " ".join(node.stripped_strings) if node else ""


def parse_list(page_html: str, lang: str) -> list[Event]:
    soup = BeautifulSoup(page_html, "lxml")
    events = []
    for li in soup.select("li.partial__item"):
        a = li.select_one("a[href]")
        title = text_of(li.select_one(".title"))
        date_div = li.select_one(".partial-date")
        if not (a and title and date_div):
            continue
        try:
            ev = _parse_item(li, a, title, date_div, lang)
        except ValueError as e:
            print(f"  ! ignoré ({lang}) {title!r}: {e}", file=sys.stderr)
            continue
        events.append(ev)
    return events


def _parse_item(li, a, title, date_div, lang) -> Event:
    from_day = parse_day(text_of(date_div.select_one(".txt-from-day")))
    to_day_node = date_div.select_one(".txt-to-day")
    hours_blocks = date_div.select(".txt-hours")

    start_hm = end_hm = None
    if to_day_node:  # évènement sur plusieurs jours : « lundi 5 … 08h30 à vendredi 30 … 16h00 »
        to_day = parse_day(text_of(to_day_node))
        if hours_blocks:
            start_hm = parse_hour(text_of(hours_blocks[0].select_one(".hour")))
        if len(hours_blocks) > 1:
            end_hm = parse_hour(text_of(hours_blocks[1].select_one(".hour")))
    else:
        to_day = from_day
        start_hm = parse_hour(text_of(date_div.select_one(".txt-from-hour .hour")))
        end_hm = parse_hour(text_of(date_div.select_one(".txt-to-hour .hour")))

    multi = to_day > from_day
    if multi or not start_hm:
        # Toute la journée (ou plusieurs jours) : évite un bloc horaire de 3 semaines
        start, end, all_day = datetime.combine(from_day, datetime.min.time()), \
            datetime.combine(to_day + timedelta(days=1), datetime.min.time()), True
    else:
        start = at(from_day, start_hm)
        end = at(to_day, end_hm) if end_hm else None
        if end and end <= start:            # se termine après minuit
            end += timedelta(days=1)
        all_day = False

    href = a["href"]
    url = href if href.startswith("http") else BASE + href
    hours_txt = ""
    if multi and start_hm:
        hours_txt = f"{start_hm[0]:02d}:{start_hm[1]:02d}"
    ev = Event(
        lang=lang,
        title=re.sub(r"\s+", " ", title),
        url=url,
        start=start.isoformat(),
        end=end.isoformat() if end else None,
        all_day=all_day,
        location=text_of(li.select_one(".event-location")),
        category=text_of(li.select_one(".event-type")),
        subtitle=text_of(li.select_one(".sub-title")),
    )
    # Identifiant stable : identifiant de l'activité (ou adresse) + date
    m = re.search(r"/detail/(\d+)/", url)
    key = (m.group(1) if m else url) + "|" + from_day.isoformat()
    ev.uid = hashlib.sha1(f"{lang}|{key}".encode()).hexdigest()[:20] + "@agenda-wezembeek-oppem"
    return ev


def scrape(lang: str, fixtures: Path | None = None) -> list[Event]:
    events: list[Event] = []
    if fixtures:
        for f in sorted(fixtures.glob(f"{lang}_*.html")):
            events += parse_list(f.read_text(encoding="utf-8"), lang)
    else:
        for page in range(MAX_PAGES):
            url = f"{BASE}{LISTS[lang]}?page={page}"
            found = parse_list(fetch(url), lang)
            print(f"  {lang} page {page}: {len(found)} activités")
            if not found:
                break
            events += found
            time.sleep(1)  # politesse envers le serveur
    # dédoublonnage
    uniq = {}
    for e in events:
        uniq.setdefault(e.uid, e)
    return sorted(uniq.values(), key=lambda e: (e.start, e.title))


def merge_with_history(lang: str, fresh: list[Event], today: date) -> list[Event]:
    """Garde les activités passées (qui disparaissent du site) pour l'historique du calendrier."""
    path = OUT / f"events-{lang}.json"
    merged = {e.uid: e for e in fresh}
    if path.exists():
        cutoff = datetime.combine(today - timedelta(days=KEEP_PAST_DAYS), datetime.min.time())
        now = datetime.combine(today, datetime.min.time())
        for raw in json.loads(path.read_text(encoding="utf-8")):
            e = Event(**raw)
            if e.uid not in merged and cutoff <= e.dt_end < now:
                merged[e.uid] = e
    return sorted(merged.values(), key=lambda e: (e.start, e.title))


# --------------------------------------------------------------------------- #
# Calendrier .ics
# --------------------------------------------------------------------------- #
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Brussels
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def fold(line: str) -> str:
    """Coupe les lignes à 75 octets (RFC 5545)."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > 74:
            out.append(cur.decode())
            cur = b" "
        cur += b
    out.append(cur.decode())
    return "\r\n".join(out)


def build_ics(events: list[Event], lang: str, stamp: datetime) -> str:
    t = TEXTS[lang]
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Agenda Wezembeek-Oppem//FR-NL//",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(t['cal_name'])}",
        f"X-WR-CALDESC:{ics_escape(t['cal_desc'])}",
        "X-WR-TIMEZONE:Europe/Brussels",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
        *VTIMEZONE.splitlines(),
    ]
    dtstamp = stamp.astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        desc = "\n".join(x for x in [e.subtitle, e.category, e.url] if x)
        lines += ["BEGIN:VEVENT", f"UID:{e.uid}", f"DTSTAMP:{dtstamp}"]
        if e.all_day:
            lines += [f"DTSTART;VALUE=DATE:{e.dt_start:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{e.dt_end:%Y%m%d}", "TRANSP:TRANSPARENT"]
        else:
            lines += [f"DTSTART;TZID=Europe/Brussels:{e.dt_start:%Y%m%dT%H%M%S}",
                      f"DTEND;TZID=Europe/Brussels:{e.dt_end:%Y%m%dT%H%M%S}"]
        lines += [f"SUMMARY:{ics_escape(e.title)}"]
        if e.location:
            lines.append(f"LOCATION:{ics_escape(e.location + ', Wezembeek-Oppem' if ',' not in e.location else e.location)}")
        lines += [f"DESCRIPTION:{ics_escape(desc)}", f"URL:{e.url}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# --------------------------------------------------------------------------- #
# Message WhatsApp
# --------------------------------------------------------------------------- #
def nice_day(d: date, lang: str, with_weekday=True) -> str:
    s = f"{d.day}{'er' if lang == 'fr' and d.day == 1 else ''} {MONTHS[lang][d.month - 1]}"
    return f"{DAYS[lang][d.weekday()]} {s}" if with_weekday else s


def hhmm(dt: datetime, lang: str) -> str:
    return f"{dt.hour}h{dt.minute:02d}" if lang == "fr" else f"{dt.hour}u{dt.minute:02d}" if dt.minute else f"{dt.hour}u"


def window_for(today: date) -> tuple[date, date]:
    """Jeudi de publication le plus récent (aujourd'hui si on est jeudi) + 10 jours."""
    start = today - timedelta(days=(today.weekday() - PUBLISH_WEEKDAY) % 7)
    return start, start + timedelta(days=WINDOW_DAYS - 1)


def build_message(events: list[Event], lang: str, today: date, pages_url: str) -> str:
    t = TEXTS[lang]
    w_start, w_end = window_for(today)
    win_s = datetime.combine(w_start, datetime.min.time())
    win_e = datetime.combine(w_end + timedelta(days=1), datetime.min.time())

    by_day: dict[date, list[Event]] = {}
    ongoing: list[Event] = []
    for e in events:
        if e.dt_end <= win_s or e.dt_start >= win_e:
            continue
        if e.multi_day:
            ongoing.append(e)
        else:
            by_day.setdefault(e.dt_start.date(), []).append(e)

    cap = lambda s: s[:1].upper() + s[1:]
    out = [t["msg_title"],
           "_" + t["msg_period"].format(start=nice_day(w_start, lang), end=nice_day(w_end, lang)) + "_",
           "", t["msg_intro"]]
    if not by_day and not ongoing:
        out += ["", t["msg_empty"]]
    for d in sorted(by_day):
        out += ["", f"*{cap(nice_day(d, lang))}*"]
        for e in by_day[d]:
            if e.all_day:
                when = t["all_day"]
            else:
                when = hhmm(e.dt_start, lang)
                if e.end:
                    when += "–" + hhmm(e.dt_end, lang)
            out.append(f"▪️ {when} · *{e.title}*")
            if e.location:
                out.append(f"   📍 {e.location}")
            out.append(f"   🔗 {e.url}")
    if ongoing:
        out += ["", t["msg_ongoing"]]
        for e in ongoing:
            last = (e.dt_end - timedelta(days=1)).date() if e.all_day else e.dt_end.date()
            out.append(f"▪️ *{e.title}* ({t['msg_until'].format(d=nice_day(last, lang, False))})")
            if e.location:
                out.append(f"   📍 {e.location}")
            out.append(f"   🔗 {e.url}")
    out += [""]
    if pages_url:
        out += [t["msg_footer"].format(url=pages_url.rstrip("/") + ("/" if lang == "fr" else "/nl.html"))]
    out += ["_" + t["msg_source"] + "_"]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Pages web
# --------------------------------------------------------------------------- #
CSS = """
:root{--bg:#f7f7f4;--card:#fff;--ink:#1d2b24;--muted:#5d6b63;--line:#e3e5df;--accent:#1f6f4a;--accent-ink:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#121614;--card:#1b211e;--ink:#e8ece9;--muted:#9aa7a0;--line:#2b332f;--accent:#4fb985;--accent-ink:#0d1a13}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}
header h1{font-size:1.7rem;margin:.2em 0}header p{color:var(--muted);margin:0 0 1em}
.lang{float:right;color:var(--accent);font-weight:600;text-decoration:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:16px 0}
.btns{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.btn{display:inline-block;border:0;cursor:pointer;background:var(--accent);color:var(--accent-ink);padding:10px 14px;border-radius:10px;font:inherit;font-weight:600;text-decoration:none}
.btn.alt{background:transparent;color:var(--accent);border:1.5px solid var(--accent)}
small,.muted{color:var(--muted)}
h2{font-size:1.15rem;margin:28px 0 8px}
.day{font-weight:700;margin:22px 0 6px}.day::first-letter{text-transform:uppercase}
.ev{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:8px 0;color:inherit;text-decoration:none}
.ev:hover{border-color:var(--accent)}.ev b{display:block}.ev .meta{color:var(--muted);font-size:.92rem}
textarea{width:100%;min-height:340px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);padding:12px;font:14px/1.45 ui-monospace,Menlo,Consolas,monospace}
code{word-break:break-all}
"""


def page(title: str, body: str, lang: str) -> str:
    return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main></body></html>")


def build_public_page(events, lang, today, pages_url, stamp) -> str:
    t = TEXTS[lang]
    base = pages_url.rstrip("/") if pages_url else ""
    ics = f"{base}/agenda-{lang}.ics" if base else f"agenda-{lang}.ics"
    webcal = re.sub(r"^https?://", "webcal://", ics)
    google = "https://calendar.google.com/calendar/render?cid=" + requests.utils.quote(webcal, safe="")
    q = "url=" + requests.utils.quote(ics, safe="") + "&name=" + requests.utils.quote(t["cal_name"], safe="")
    outlook_work = "https://outlook.office.com/calendar/0/addfromweb?" + q
    outlook_live = "https://outlook.live.com/calendar/0/addfromweb?" + q
    other = "nl.html" if lang == "fr" else "index.html"
    now = datetime.combine(today, datetime.min.time())
    up = [e for e in events if e.dt_end > now]
    parts = [f"<a class='lang' href='{other}'>{t['other_lang']}</a>",
             f"<header><h1>{t['page_title']}</h1><p>{t['page_sub']}</p></header>",
             f"<section class='card'><b>{t['subscribe']}</b><div class='btns'>"
             f"<a class='btn' href='{html.escape(google)}' target='_blank' rel='noopener'>{t['sub_google']}</a>"
             f"<a class='btn' href='{html.escape(webcal)}'>{t['sub_apple']}</a>"
             f"<a class='btn' href='{html.escape(outlook_work)}' target='_blank' rel='noopener'>{t['sub_outlook']}</a>"
             f"<a class='btn' href='{html.escape(outlook_live)}' target='_blank' rel='noopener'>{t['sub_outlook_live']}</a>"
             f"</div><small>{t['sub_help']}</small>"
             f"<p style='margin:12px 0 4px'><small>{t['sub_help_outlook']}</small></p>"
             f"<code>{html.escape(ics)}</code>"
             f"<div class='btns'><button class='btn alt' onclick=\"navigator.clipboard.writeText('{ics}');this.textContent='✓'\">{t['sub_copy']}</button></div>"
             f"</section>",
             f"<h2>{t['upcoming']}</h2>"]
    cur = None
    for e in up:
        d = max(e.dt_start.date(), today)
        if d != cur:
            parts.append(f"<div class='day'>{nice_day(d, lang)}</div>")
            cur = d
        if e.multi_day:
            last = (e.dt_end - timedelta(days=1)).date() if e.all_day else e.dt_end.date()
            when = t["msg_until"].format(d=nice_day(last, lang, False))
        elif e.all_day:
            when = t["all_day"]
        else:
            when = hhmm(e.dt_start, lang) + ("–" + hhmm(e.dt_end, lang) if e.end else "")
        meta = " · ".join(x for x in [when, e.location] if x)
        parts.append(f"<a class='ev' href='{html.escape(e.url)}' target='_blank' rel='noopener'>"
                     f"<b>{html.escape(e.title)}</b><span class='meta'>{html.escape(meta)}</span></a>")
    parts.append(f"<p class='muted' style='margin-top:32px'><small>{t['updated'].format(d=stamp.strftime('%d/%m/%Y %H:%M'))} · "
                 f"<a href='{BASE}{LISTS[lang]}'>wezembeek-oppem.be</a></small></p>")
    return page(t["page_title"], "".join(parts), lang)


def build_whatsapp_page(messages: dict[str, str], today: date, stamp) -> str:
    w_s, w_e = window_for(today)
    blocks = []
    for lang, label in (("fr", "Communauté FR"), ("nl", "Gemeenschap NL")):
        blocks.append(
            f"<section class='card'><b>{label}</b><div class='btns'>"
            f"<button class='btn' onclick=\"copy('{lang}',this)\">📋 Copier / Kopiëren</button>"
            f"<a class='btn alt' href='https://wa.me/?text={requests.utils.quote(messages[lang])}'>Ouvrir WhatsApp</a></div>"
            f"<textarea id='{lang}'>{html.escape(messages[lang])}</textarea></section>")
    body = (f"<header><h1>Messages WhatsApp</h1><p>Semaine du {nice_day(w_s,'fr')} au {nice_day(w_e,'fr')} "
            f"· généré le {stamp:%d/%m/%Y %H:%M}</p></header>" + "".join(blocks) +
            "<script>function copy(id,b){const t=document.getElementById(id);t.select();"
            "navigator.clipboard.writeText(t.value).then(()=>{b.textContent='✓ Copié';setTimeout(()=>b.textContent='📋 Copier / Kopiëren',2000)})}</script>")
    html_page = page("Messages WhatsApp", body, "fr")
    return html_page.replace("<head>", "<head><meta name='robots' content='noindex'>")


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path)
    ap.add_argument("--today", type=date.fromisoformat)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    global OUT
    if args.out:
        OUT = args.out
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ)
    today = args.today or stamp.date()
    pages_url = os.environ.get("PAGES_URL", "").strip()

    messages = {}
    for lang in ("fr", "nl"):
        fresh = scrape(lang, args.fixtures)
        if len(fresh) < 3:
            # garde-fou : si le site change ou est en panne, on n'écrase rien
            print(f"ERREUR : seulement {len(fresh)} activités trouvées en {lang}. "
                  "Le site a peut-être changé. Rien n'a été modifié.", file=sys.stderr)
            return 1
        events = merge_with_history(lang, fresh, today)
        (OUT / f"events-{lang}.json").write_text(
            json.dumps([asdict(e) for e in events], ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / f"agenda-{lang}.ics").write_text(build_ics(events, lang, stamp), encoding="utf-8", newline="")
        messages[lang] = build_message(events, lang, today, pages_url)
        (OUT / f"whatsapp-{lang}.txt").write_text(messages[lang], encoding="utf-8")
        (OUT / ("index.html" if lang == "fr" else "nl.html")).write_text(
            build_public_page(events, lang, today, pages_url, stamp), encoding="utf-8")
        print(f"{lang}: {len(fresh)} activités sur le site, {len(events)} dans le calendrier")
    (OUT / "whatsapp.html").write_text(build_whatsapp_page(messages, today, stamp), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
