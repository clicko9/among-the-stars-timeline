"""Parse Among The Stars in-universe announcements without guessing historical facts.

This module intentionally has no Discord/Supabase dependency, so it can be tested offline.
"""
from __future__ import annotations

import re
from datetime import date, datetime

DATE_LINE = re.compile(r'^\s*(?:lore date|in-universe date|mission date|date)\s*:\s*(\d{4}-\d{2}-\d{2})\s*$', re.I | re.M)
DATE_WORDS = re.compile(r'^\s*(?:lore date|in-universe date|mission date|date)\s*:\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\s*$', re.I | re.M)
BARE_DATE_WORDS = re.compile(r'^\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\s*$', re.I | re.M)
DATE_YEAR = re.compile(r'^\s*(?:lore year|in-universe year|mission year|year)\s*:\s*(\d{4})\s*$', re.I | re.M)
DATE_OPENING_YEAR = re.compile(r'^\s*(1[89]\d{2}|20\d{2}|21\d{2})\s*[-–—:]\s+\S', re.M)
BARE_DATE_ISO = re.compile(r'^\s*((?:18|19|20|21)\d{2}-\d{2}-\d{2})\s*$', re.M)
WORLDS_OUTER = re.compile(r'\b(jool|laythe|tylo|vall|bop|pol|sarnus|tekto|hale|ovok|urlum|wal|tal|priax|neidon|plock|eeloo)\b', re.I)
WORLDS_INNER = re.compile(r'\b(moho|eve|gilly|duna|ike|dres)\b', re.I)
WORLD_MUN = re.compile(r'\b(mun|munar)\b', re.I)
WORLD_ROCKET = re.compile(r'\b(sounding rocket|k[aá]rm[aá]n|upper atmosphere)\b', re.I)
NONCANON = re.compile(r'(?im)^\s*(?:#noncanon|\[noncanon\])(?:\s|$)')
CANONICAL_KERBSCI = 'Kerbsci Aeromechanical Works'


def parse_lore_date(text: str):
    m = DATE_LINE.search(text) or BARE_DATE_ISO.search(text)
    if m:
        raw = m.group(1)
        try:
            d = date.fromisoformat(raw)
            return d.isoformat(), f'{d.day} {d:%B %Y}', 'confirmed', 'Explicit date in Discord post'
        except ValueError:
            pass
    m = DATE_WORDS.search(text) or BARE_DATE_WORDS.search(text)
    if m:
        try:
            d = datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%d %B %Y').date()
            return d.isoformat(), f'{d.day} {d:%B %Y}', 'confirmed', 'Explicit written date in Discord post'
        except ValueError:
            pass
    m = DATE_YEAR.search(text) or DATE_OPENING_YEAR.search(text)
    if m:
        return f'{m.group(1)}-01-01', m.group(1), 'year-only', 'Year explicitly stated; month and day not supplied'
    return None, 'Date awaiting in-universe confirmation', 'unverified', 'No in-universe date supplied'


def canonical_agency(name: str) -> str:
    candidate = str(name or '').strip()
    if candidate.casefold() in {
        'kerbin aeromechanics works', 'kerbin aeromechanical works',
        'kerbsci', 'kerbsci aeromechanical works',
    }:
        return CANONICAL_KERBSCI
    return candidate


def announce_fields(text: str, author: str):
    """Use only author-provided words for title/summary; never fabricate event prose."""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not DATE_LINE.fullmatch(line)
             and not DATE_WORDS.fullmatch(line) and not BARE_DATE_WORDS.fullmatch(line)
             and not BARE_DATE_ISO.fullmatch(line) and not DATE_YEAR.fullmatch(line)
             and not NONCANON.fullmatch(line)]
    if lines:
        first = re.sub(r'^(?:(?:1[89]|20|21)\d{2}(?:-\d{2}-\d{2})?)\s*[-–—:]\s*', '', lines[0]).strip() or lines[0]
        title = first[:150] + ('…' if len(first) > 150 else '')
        summary = '\n'.join(lines[1:]).strip() if len(lines) > 1 else first
    else:
        title = f'Archival attachment — {author}'
        summary = 'Image-only lore announcement. Historical details await verification against the source image.'
    return title, summary[:6000]


def background_for(text: str, lore_date: str | None):
    # Heading gets priority for mixed-body posts referencing several locations.
    heading = next((x.strip() for x in text.splitlines() if x.strip()
                    and not DATE_LINE.fullmatch(x.strip()) and not DATE_WORDS.fullmatch(x.strip())
                    and not DATE_YEAR.fullmatch(x.strip())), '')
    for value in (heading, text):
        if WORLDS_OUTER.search(value): return 'sarnus'
        if WORLDS_INNER.search(value): return 'duna'
        if WORLD_MUN.search(value): return 'mun'
    if WORLD_ROCKET.search(text) and (not lore_date or int(lore_date[:4]) < 1957):
        return 'rocketry'
    if lore_date and int(lore_date[:4]) < 1934: return 'aviation'
    return 'kerbin'


def visual_style_for(lore_date: str | None):
    if not lore_date: return 'modern'
    year = int(lore_date[:4])
    if year < 1934: return 'aviation'
    if year < 1957: return 'rocketry'
    if year < 1966: return 'spaceflight'
    if year < 1989: return 'moonage'
    if year < 1995: return 'technical'
    if year < 1998: return 'modern'
    return 'outer'


def is_noncanon(text: str):
    return bool(NONCANON.search(text))
