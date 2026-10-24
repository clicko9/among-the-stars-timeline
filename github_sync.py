"""Among The Stars — scheduled Discord REST -> Supabase sync (no always-on PC).

Run on GitHub Actions with repository secrets. This is a scheduled *poller*, not a
long-running Discord Gateway client. It refreshes all post-baseline history on
each run to detect messages edited/deleted while nobody was online.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from lore_parser import (announce_fields, background_for, canonical_agency,
                         is_noncanon, parse_lore_date, visual_style_for)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('among-the-stars-github-sync')
API_ROOT = 'https://discord.com/api/v10'
PAGE_SIZE = 100
MAX_PAGES = 100  # 10,000 posts per run. Never delete on an incomplete scan.


def text_from_message(msg: dict[str, Any]) -> str:
    parts = [msg.get('content') or '']
    for embed in msg.get('embeds') or []:
        if embed.get('title'):
            parts.append(embed['title'])
        if embed.get('description'):
            parts.append(embed['description'])
    return '\n'.join(x for x in parts if x).strip()


def attachment_metadata(msg: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        'id': str(a['id']), 'name': a.get('filename') or '',
        'content_type': a.get('content_type'), 'size': a.get('size', 0)
    } for a in msg.get('attachments') or []]


def record_from_discord(msg: dict[str, Any], channel_id: str, agency_map: dict[str, str]) -> dict[str, Any]:
    author = msg['author']
    display_name = ((msg.get('member') or {}).get('nick') or author.get('global_name')
                    or author.get('username') or 'Unknown')
    content = text_from_message(msg)
    lore_date, label, confidence, source = parse_lore_date(content)
    title, summary = announce_fields(content, display_name)
    attachments = attachment_metadata(msg)
    agency = canonical_agency(agency_map.get(str(author['id']), display_name))
    noncanon = is_noncanon(content)
    return {
        'discord_message_id': str(msg['id']),
        'discord_channel_id': channel_id,
        'discord_url': f"https://discord.com/channels/{msg.get('guild_id') or '@me'}/{channel_id}/{msg['id']}",
        'discord_created_at': msg['timestamp'],
        'discord_edited_at': msg.get('edited_timestamp'),
        'author_name': display_name,
        'author_id': str(author['id']),
        'agency': agency,
        'lore_date': lore_date,
        'display_date': label,
        'date_confidence': confidence,
        'date_source': source,
        'title': title,
        'summary': summary[:6000],
        'quote': content[:4000],
        'message': content,
        'attachments': attachments,
        'visual_style': visual_style_for(lore_date),
        'background_scene': background_for(content, lore_date),
        'canon_status': 'not in canon' if noncanon else 'archive',
        'published': not noncanon,
        'editorial_locked': False,
        'needs_review': confidence == 'unverified' or not content,
        'discord_deleted': False,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def fetch_discord_messages(token: str, channel_id: str, before: str | None) -> list[dict[str, Any]]:
    query = {'limit': str(PAGE_SIZE)}
    if before:
        query['before'] = before
    url = f'{API_ROOT}/channels/{channel_id}/messages?{urllib.parse.urlencode(query)}'
    for retry in range(6):
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bot {token}', 'User-Agent': 'AmongTheStarsArchiveSync/1.0'
        })
        try:
            with urllib.request.urlopen(req, timeout=35) as response:
                value = json.load(response)
            if not isinstance(value, list):
                raise RuntimeError('Unexpected Discord API response')
            return value
        except urllib.error.HTTPError as error:
            if error.code == 429 and retry < 5:
                try:
                    delay = float(json.loads(error.read()).get('retry_after', 2))
                except (ValueError, TypeError):
                    delay = 2
                time.sleep(min(delay + .5, 60))
                continue
            if 500 <= error.code <= 599 and retry < 5:
                time.sleep(min(2 ** retry, 20))
                continue
            raise RuntimeError(f'Discord API returned HTTP {error.code}; verify bot channel permissions.') from error
    raise RuntimeError('Discord API retries exhausted')


def get_recent_archive(token: str, channel_id: str, baseline_id: int) -> dict[str, dict[str, Any]]:
    """Walk newest->oldest until reaching the original archived cutoff."""
    seen = {}
    before = None
    complete = False
    for page in range(MAX_PAGES):
        batch = fetch_discord_messages(token, channel_id, before)
        if not batch:
            complete = True
            break
        # Explicit sort: never rely on REST ordering for pagination logic.
        batch.sort(key=lambda m: int(m['id']), reverse=True)
        for msg in batch:
            if int(msg['id']) <= baseline_id:
                complete = True
                break
            seen[str(msg['id'])] = msg
        if complete or len(batch) < PAGE_SIZE:
            complete = True
            break
        last = str(batch[-1]['id'])
        if before is not None and int(last) >= int(before):
            raise RuntimeError('Discord history cursor did not move; refusing incomplete sync')
        before = last
    if not complete:
        # Refuse to infer deleted records from a truncated scan.
        raise RuntimeError(f'History exceeds {MAX_PAGES * PAGE_SIZE} posts; sync aborted without edits')
    return seen


def get_existing_rows(db: Any, channel_id: str, baseline_id: int) -> dict[str, dict[str, Any]]:
    existing = {}
    offset = 0
    cols = ('discord_message_id,discord_edited_at,message,attachments,discord_deleted,'
            'author_id,author_name,agency,editorial_locked,published')
    while True:
        res = (db.table('timeline_entries').select(cols)
               .eq('discord_channel_id', channel_id)
               .range(offset, offset + 999).execute())
        batch = res.data or []
        for item in batch:
            key = item['discord_message_id']
            if key.isdigit() and int(key) > baseline_id:
                existing[key] = item
        if len(batch) < 1000:
            return existing
        offset += len(batch)


def materially_changed(existing: dict[str, Any], record: dict[str, Any]) -> bool:
    return (existing.get('discord_deleted') or
            existing.get('message') != record['message'] or
            (existing.get('attachments') or []) != record['attachments'] or
            existing.get('discord_edited_at') != record['discord_edited_at'] or
            existing.get('author_id') != record['author_id'] or
            existing.get('author_name') != record['author_name'])


def sync_archive(db: Any, archive: dict[str, dict[str, Any]], channel_id: str,
                 baseline_id: int, agency_map: dict[str, str], self_id: str = '') -> tuple[int, int, int]:
    existing = get_existing_rows(db, channel_id, baseline_id)
    changed = 0
    unchanged = 0
    ignored_ids = set()
    for key, message in sorted(archive.items(), key=lambda pair: int(pair[0])):
        if message.get('author', {}).get('bot') or message.get('author', {}).get('id') == self_id:
            ignored_ids.add(key)
            continue
        new = record_from_discord(message, channel_id, agency_map)
        old = existing.get(key)
        if old and not materially_changed(old, new):
            unchanged += 1
            continue
        if old and old.get('editorial_locked'):
            # Match persistent bot: editorial work in curated records must survive updates.
            patch = {k: new[k] for k in ('discord_edited_at', 'message', 'attachments', 'updated_at')}
            patch['discord_deleted'] = False
            db.table('timeline_entries').update(patch).eq('discord_message_id', key).execute()
        else:
            db.table('timeline_entries').upsert(new, on_conflict='discord_message_id').execute()
        changed += 1
        log.info('Synced Discord message %s', key)

    # Only after a *complete, successful* Discord scan, mark deleted posts unpublished.
    missing = [key for key, old in existing.items()
               if key not in archive and not old.get('discord_deleted') and key not in ignored_ids]
    for key in missing:
        db.table('timeline_entries').update({
            'published': False, 'discord_deleted': True,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('discord_message_id', key).execute()
        log.info('Unpublished deleted Discord message %s', key)
    return changed, unchanged, len(missing)


def main() -> None:
    required = ('DISCORD_BOT_TOKEN', 'KSP_LORE_CHANNEL_ID', 'BASELINE_MESSAGE_ID',
                'SUPABASE_URL', 'SUPABASE_SECRET_KEY')
    absent = [key for key in required if not os.environ.get(key)]
    if absent:
        raise RuntimeError('Missing GitHub Actions secrets/config: ' + ', '.join(absent))
    token = os.environ['DISCORD_BOT_TOKEN']
    channel_id = os.environ['KSP_LORE_CHANNEL_ID']
    baseline_id = int(os.environ['BASELINE_MESSAGE_ID'])
    try:
        agency_map = json.loads(os.getenv('AGENCY_MAP_JSON') or '{}')
    except json.JSONDecodeError as exc:
        raise RuntimeError('AGENCY_MAP_JSON is not valid JSON') from exc
    from supabase import create_client
    db = create_client(os.environ['SUPABASE_URL'].rstrip('/'), os.environ['SUPABASE_SECRET_KEY'])
    messages = get_recent_archive(token, channel_id, baseline_id)
    changed, unchanged, deleted = sync_archive(db, messages, channel_id, baseline_id, agency_map)
    log.info('Scan complete: %d messages, %d synced, %d unchanged, %d deleted',
             len(messages), changed, unchanged, deleted)


if __name__ == '__main__':
    main()
