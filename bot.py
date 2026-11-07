import asyncio
import io
import json
import os
import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from quote_card import render_quote_card
from quote_parser import MENTION_RE, parse_quotes, parse_quotes_loose
from dashboard import Dashboard

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
QUOTES_CHANNEL_ID = int(os.getenv("QUOTES_CHANNEL_ID", "0"))
QUOTES_FILE = os.getenv("QUOTES_FILE", "quotes.json")
NAMES_FILE = os.getenv("NAMES_FILE", "names.json")
NICKNAMES_FILE = os.getenv("NICKNAMES_FILE", "nicknames.json")
MOD_USER_ID = int(os.getenv("MOD_USER_ID")) if os.getenv("MOD_USER_ID") else None
QUOTE_OF_DAY_HOUR_UTC = int(os.getenv("QUOTE_OF_DAY_HOUR_UTC", "13"))
ANNOUNCEMENTS_CHANNEL_ID = int(os.getenv("ANNOUNCEMENTS_CHANNEL_ID", "0")) or QUOTES_CHANNEL_ID
# Quote dates and years follow local time so a New Year's Eve quote stays in its year.
QUOTES_TIMEZONE = ZoneInfo(os.getenv("QUOTES_TIMEZONE") or "America/New_York")
DELETE_RECORDED_QUOTES = os.getenv("DELETE_RECORDED_QUOTES", "true").lower() != "false"
# Catch-up only deletes recent quotes, so pointing the bot at a channel with
# history can't sweep away years of old messages.
BACKFILL_DELETE_MAX_AGE = timedelta(days=7)
QUOTE_SAVED_NOTICE_SECONDS = 5
# While sealed, the bot keeps collecting quotes but never shows them to anyone.
# The only way out is the owner's (MOD_USER_ID) book, which opens on this date.
QUOTES_SEALED = os.getenv("QUOTES_SEALED", "true").lower() != "false"
QUOTE_BOOK_OPENS = tuple(int(part) for part in (os.getenv("QUOTE_BOOK_OPENS") or "12-31").split("-"))
SEALED_MESSAGE = "Quotes are sealed until the year-end book."

QUOTE_REACTION_EMOJI = "\U0001FAC3"  # 🫃 pregnant man

intents = discord.Intents.default()
intents.message_content = True

class QuoteBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("music")
        self.dashboard = Dashboard(self)
        await self.dashboard.start()

    async def close(self):
        import wavelink
        if hasattr(self, "dashboard"):
            await self.dashboard.close()
        await wavelink.Pool.close()
        await super().close()


bot = QuoteBot(command_prefix="!", intents=intents)
quotes_lock = asyncio.Lock()


def load_quotes():
    if os.path.exists(QUOTES_FILE):
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def write_quotes(quotes):
    # This file is the only copy of a deleted quote, so a crash mid-write must
    # never leave it truncated.
    temporary = f"{QUOTES_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(quotes, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, QUOTES_FILE)


def load_names():
    if os.path.exists(NAMES_FILE):
        with open(NAMES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def write_names(names):
    with open(NAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(names, f, indent=2, ensure_ascii=False)


def build_entry(message):
    return {
        "id": message.id,
        "author": str(message.author),
        "author_id": message.author.id,
        "content": message.content,
        "attachments": [a.url for a in message.attachments],
        "timestamp": message.created_at.astimezone(timezone.utc).isoformat(),
        "jump_url": message.jump_url,
    }


async def record_messages(messages):
    """Save any messages not yet recorded and return how many were added. Must
    finish before a message is deleted, because that makes this the only copy."""
    async with quotes_lock:
        quotes = load_quotes()
        existing_ids = {q["id"] for q in quotes}
        new_entries = [build_entry(m) for m in messages if m.id not in existing_ids]
        if new_entries:
            quotes.extend(new_entries)
            quotes.sort(key=lambda q: q["timestamp"])
            write_quotes(quotes)
    return len(new_entries)


def should_delete(message):
    return (
        DELETE_RECORDED_QUOTES
        and not message.content.startswith(bot.command_prefix)
        and bool(parse_quotes(message.content))
    )


async def save_attachments(message):
    # These only exist on Discord, so keep a copy before the message goes.
    folder = os.path.join(os.path.dirname(QUOTES_FILE), "attachments")
    os.makedirs(folder, exist_ok=True)
    for attachment in message.attachments:
        await attachment.save(os.path.join(folder, f"{attachment.id}-{attachment.filename}"))


async def delete_recorded_quote(message):
    try:
        await save_attachments(message)
        await message.delete()
    except discord.NotFound:
        pass
    except (discord.HTTPException, OSError) as error:
        print(f"Could not delete recorded quote {message.id}: {error}")
        return False
    return True


async def acknowledge_quote(message):
    if should_delete(message) and await delete_recorded_quote(message):
        await message.channel.send(
            f"{QUOTE_REACTION_EMOJI} Quote saved.", delete_after=QUOTE_SAVED_NOTICE_SECONDS
        )
    else:
        await message.add_reaction(QUOTE_REACTION_EMOJI)


async def backfill_channel(channel):
    existing_ids = {q["id"] for q in load_quotes()}
    oldest_deletable = discord.utils.utcnow() - BACKFILL_DELETE_MAX_AGE
    new_messages = []
    to_delete = []

    async for message in channel.history(limit=None, oldest_first=True):
        if message.author.bot:
            continue
        if not message.content and not message.attachments:
            continue
        if message.id not in existing_ids:
            new_messages.append(message)
        # Already-recorded messages count too, so a failed delete is retried.
        if message.created_at >= oldest_deletable and should_delete(message):
            to_delete.append(message)

    added = await record_messages(new_messages)
    deleted = 0
    for message in to_delete:
        if await delete_recorded_quote(message):
            deleted += 1
    if deleted:
        print(f"Backfill deleted {deleted} recorded quote(s).")

    return added


def resolve_user_id(user_id, names, guild):
    who = names.get(str(user_id))
    if who is None and guild is not None:
        member = guild.get_member(user_id)
        who = member.display_name if member else None
    return who if who is not None else f"<@{user_id}>"


def resolve_mentions_in_text(text, names, guild):
    return MENTION_RE.sub(lambda m: resolve_user_id(int(m.group(1)), names, guild), text)


def resolve_attribution(attribution_name, attribution_id, names, guild):
    if attribution_id is None:
        return attribution_name
    who = resolve_user_id(attribution_id, names, guild)
    if attribution_name:
        leftover = resolve_mentions_in_text(attribution_name, names, guild)
        who = f"{who} {leftover}"
    return who


def iter_parsed_quotes(quotes):
    """Yield (message, quote_text, attribution_name, attribution_id) for every
    formatted quote across all messages, oldest first."""
    for q in sorted(quotes, key=lambda x: x["timestamp"]):
        for quote_text, attribution_name, attribution_id in parse_quotes(q.get("content", "")):
            yield q, quote_text, attribution_name, attribution_id


def quote_datetime(q):
    return datetime.fromisoformat(q["timestamp"]).astimezone(QUOTES_TIMEZONE)


def book_is_open(year):
    today = datetime.now(QUOTES_TIMEZONE)
    return year < today.year or (year == today.year and (today.month, today.day) >= QUOTE_BOOK_OPENS)


def format_quote_line(q, quote_text, attribution_name, attribution_id, names, guild):
    dt = quote_datetime(q).strftime("%B %d, %Y")
    quote_text = resolve_mentions_in_text(quote_text, names, guild)
    who = resolve_attribution(attribution_name, attribution_id, names, guild)
    return f'"{quote_text}" — {who} ({dt})'


def build_quote_book_text(quotes, guild=None, year=None):
    """Quotes grouped under a heading per year, numbered from 1 within each year.
    Pass year to get just that year. Returns (text, total_quotes)."""
    names = load_names()
    lines = []
    total = 0
    number = 0
    current_year = None
    for q, quote_text, attribution_name, attribution_id in iter_parsed_quotes(quotes):
        quote_year = quote_datetime(q).year
        if year is not None and quote_year != year:
            continue
        if quote_year != current_year:
            current_year = quote_year
            number = 0
            lines.extend([f"===== {current_year} =====", ""])
        number += 1
        total += 1
        lines.append(f"{number}. " + format_quote_line(q, quote_text, attribution_name, attribution_id, names, guild))
        lines.append("")
    text = "\n".join(lines) if lines else "No formatted quotes found yet."
    return text, total


async def notify_unresolved(message, unresolved_ids):
    mentions = ", ".join(f"<@{uid}>" for uid in unresolved_ids)
    posted = message.created_at.astimezone(QUOTES_TIMEZONE).strftime("%B %d, %Y")
    text = (
        f"⚠️ Unresolved quote attribution on a quote from {posted}: {mentions}\n"
        f"Use `!setname @user Real Name` to map them."
    )
    if MOD_USER_ID:
        user = bot.get_user(MOD_USER_ID)
        if user is None:
            try:
                user = await bot.fetch_user(MOD_USER_ID)
            except discord.NotFound:
                user = None
        if user is not None:
            try:
                await user.send(text)
                return
            except discord.Forbidden:
                pass
    # Never fall back to the channel: it would show who was quoted.
    print(text)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}.")
    print(f"Bot is a member of {len(bot.guilds)} server(s):")
    for guild in bot.guilds:
        print(f"  - {guild.name} (ID: {guild.id})")
        for ch in guild.text_channels:
            print(f"      #{ch.name} (ID: {ch.id})")

    channel = bot.get_channel(QUOTES_CHANNEL_ID)
    if channel is None:
        print(f"Could not find channel with ID {QUOTES_CHANNEL_ID}. Check QUOTES_CHANNEL_ID.")
        return
    added = await backfill_channel(channel)
    print(f"Backfill complete: {added} past message(s) added. Watching #{channel.name} for new quotes.")

    if not post_quote_of_the_day.is_running():
        post_quote_of_the_day.start()


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id == QUOTES_CHANNEL_ID and not message.content.startswith(bot.command_prefix):
        if message.content or message.attachments:
            if await record_messages([message]):
                parsed = parse_quotes(message.content)
                if parsed:
                    await acknowledge_quote(message)
                    names = load_names()
                    unresolved = sorted(
                        {aid for _, _, aid in parsed if aid is not None and str(aid) not in names}
                    )
                    if unresolved:
                        await notify_unresolved(message, unresolved)

    await bot.process_commands(message)


@tasks.loop(time=time(hour=QUOTE_OF_DAY_HOUR_UTC, tzinfo=timezone.utc))
async def post_quote_of_the_day():
    channel = bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
    if channel is None or QUOTES_SEALED:
        return
    quotes = load_quotes()
    parsed = list(iter_parsed_quotes(quotes))
    if not parsed:
        return
    q, quote_text, attribution_name, attribution_id = random.choice(parsed)
    names = load_names()
    line = format_quote_line(q, quote_text, attribution_name, attribution_id, names, channel.guild)
    await channel.send(f"**Quote of the Day**\n{line}")


@bot.command(name="sync")
@commands.has_permissions(manage_messages=True)
async def sync_quotes(ctx):
    channel = bot.get_channel(QUOTES_CHANNEL_ID)
    if channel is None:
        await ctx.reply("Quotes channel not found. Check QUOTES_CHANNEL_ID.")
        return
    added = await backfill_channel(channel)
    await ctx.reply(f"Sync complete: added {added} new quote(s) from channel history.")


@bot.command(name="dashboard", help="DM the private music dashboard link to a server manager.")
@commands.has_permissions(manage_guild=True)
async def dashboard_link(ctx):
    dashboard_token = os.getenv("DASHBOARD_TOKEN", "")
    public_url = os.getenv("DASHBOARD_PUBLIC_URL", "").rstrip("/")
    if not public_url:
        railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
        public_url = f"https://{railway_domain}" if railway_domain else ""
    if not dashboard_token or not public_url:
        await ctx.reply("The music dashboard URL is not configured yet.", mention_author=False)
        return
    url = f"{public_url}/{dashboard_token}"
    try:
        await ctx.author.send(
            f"**Quote Bot Music Dashboard**\n<{url}>\n\nKeep this link private—it grants music control.",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.Forbidden:
        await ctx.reply("I couldn't DM you. Enable direct messages for this server and try again.", mention_author=False)
        return
    await ctx.reply("I sent the private dashboard link to your DMs.", mention_author=False)


@bot.command(name="quotebook")
async def quotebook(ctx, year: int = None):
    if ctx.author.id != MOD_USER_ID:
        await ctx.reply("The quote book is private.", mention_author=False)
        return
    quotes = load_quotes()
    if year is None:
        quotes = [q for q in quotes if book_is_open(quote_datetime(q).year)]
    elif not book_is_open(year):
        month, day = QUOTE_BOOK_OPENS
        opens = datetime(year, month, day).strftime("%B %d, %Y")
        await ctx.reply(f"The {year} book opens on {opens}.", mention_author=False)
        return
    text, count = build_quote_book_text(quotes, guild=ctx.guild, year=year)
    buffer = io.BytesIO(text.encode("utf-8"))
    book = f"{year} quote book" if year else "compiled quote book"
    filename = f"quote_book_{year}.txt" if year else "quote_book.txt"
    try:
        await ctx.author.send(
            content=f"Here's the {book} ({count} quotes).",
            file=discord.File(buffer, filename=filename),
        )
    except discord.Forbidden:
        await ctx.reply("I couldn't DM you. Enable direct messages and try again.", mention_author=False)
        return
    if ctx.guild is not None:
        await ctx.reply("I sent the book to your DMs.", mention_author=False)


@bot.command(name="randomquote")
async def random_quote(ctx):
    if QUOTES_SEALED:
        await ctx.reply(SEALED_MESSAGE, mention_author=False)
        return
    quotes = load_quotes()
    parsed = list(iter_parsed_quotes(quotes))
    if not parsed:
        await ctx.reply("No formatted quotes found yet.")
        return
    q, quote_text, attribution_name, attribution_id = random.choice(parsed)
    names = load_names()
    line = format_quote_line(q, quote_text, attribution_name, attribution_id, names, ctx.guild)
    await ctx.send(line)


@bot.command(name="topquoted")
async def top_quoted(ctx, top_n: int = 10, year: int = None):
    if QUOTES_SEALED:
        await ctx.reply(SEALED_MESSAGE, mention_author=False)
        return
    quotes = load_quotes()
    names = load_names()
    counts = {}
    for q, quote_text, attribution_name, attribution_id in iter_parsed_quotes(quotes):
        if year is not None and quote_datetime(q).year != year:
            continue
        who = resolve_attribution(attribution_name, attribution_id, names, ctx.guild)
        counts[who] = counts.get(who, 0) + 1
    if not counts:
        await ctx.reply("No formatted quotes found yet.")
        return
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    lines = [f"{idx}. {name} — {count} quote(s)" for idx, (name, count) in enumerate(ranked, start=1)]
    title = f"Most Quoted in {year}" if year else "Most Quoted"
    await ctx.reply(f"**{title}:**\n" + "\n".join(lines))


@bot.command(name="quotecard")
async def quote_card_command(ctx, *, override_text: str = None):
    if not ctx.message.reference:
        await ctx.reply("Reply to a message with `!quotecard` to turn it into a quote card.")
        return
    try:
        target = ctx.message.reference.resolved or await ctx.channel.fetch_message(
            ctx.message.reference.message_id
        )
    except discord.NotFound:
        await ctx.reply("Couldn't find that message.")
        return

    names = load_names()
    parsed = parse_quotes(target.content) if override_text is None else []
    if not parsed and override_text is None:
        parsed = parse_quotes_loose(target.content)

    if parsed:
        # Message follows the "quote" - Name/@mention format, so credit the person
        # actually being quoted, not whoever happened to type the message.
        quote_text, attribution_name, attribution_id = parsed[0]
        quote_text = resolve_mentions_in_text(quote_text, names, ctx.guild)
        who = resolve_attribution(attribution_name, attribution_id, names, ctx.guild)
        avatar_source = target.author
        if attribution_id is not None and ctx.guild is not None:
            member = ctx.guild.get_member(attribution_id)
            if member is None:
                try:
                    member = await ctx.guild.fetch_member(attribution_id)
                except discord.NotFound:
                    member = None
            if member is not None:
                avatar_source = member
    else:
        text = (override_text or target.content or "").strip()
        if not text:
            await ctx.reply("That message doesn't have any text to turn into a quote.")
            return
        quote_text = resolve_mentions_in_text(text, names, ctx.guild)
        who = names.get(str(target.author.id)) or target.author.display_name
        avatar_source = target.author

    avatar_bytes = await avatar_source.display_avatar.replace(size=256, format="png").read()
    buffer = await asyncio.to_thread(render_quote_card, quote_text, who, avatar_bytes)
    await ctx.reply(file=discord.File(buffer, filename="quote_card.png"))


@bot.command(name="setname")
@commands.has_permissions(manage_messages=True)
async def setname(ctx, member: discord.Member, *, real_name: str):
    names = load_names()
    names[str(member.id)] = real_name
    write_names(names)
    await ctx.reply(f"Mapped {member.mention} → {real_name}")


@bot.command(name="importnames")
@commands.has_permissions(manage_messages=True)
async def import_names(ctx):
    if not ctx.message.attachments:
        await ctx.reply("Attach a names.json file with this command (author_id -> name mapping).")
        return

    raw = await ctx.message.attachments[0].read()
    try:
        incoming = json.loads(raw)
    except json.JSONDecodeError:
        await ctx.reply("That attachment isn't valid JSON.")
        return
    if not isinstance(incoming, dict):
        await ctx.reply("Expected a JSON object of author_id -> name.")
        return

    names = load_names()
    names.update(incoming)
    write_names(names)
    await ctx.reply(f"Imported {len(incoming)} mapping(s). names.json now has {len(names)} total.")


@bot.command(name="names")
@commands.has_permissions(manage_messages=True)
async def list_names(ctx):
    names = load_names()
    if not names:
        await ctx.reply("No name mappings yet. Use `!setname @user Real Name` to add one.")
        return
    lines = [f"<@{uid}> → {name}" for uid, name in names.items()]
    await ctx.reply("Current name mappings:\n" + "\n".join(lines))


@bot.command(name="nicknames")
@commands.has_permissions(manage_messages=True)
async def export_nicknames(ctx):
    quotes = load_quotes()
    author_ids = sorted({q["author_id"] for q in quotes})
    result = {}
    not_found = []

    for author_id in author_ids:
        member = ctx.guild.get_member(author_id)
        if member is None:
            try:
                member = await ctx.guild.fetch_member(author_id)
            except discord.NotFound:
                not_found.append(author_id)
                continue
        result[str(author_id)] = {
            "username": member.name,
            "nick": member.nick,
            "display_name": member.display_name,
        }

    with open(NICKNAMES_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    await ctx.reply(
        f"Wrote {NICKNAMES_FILE}: {len(result)} member(s) resolved, "
        f"{len(not_found)} no longer in the server."
    )


@sync_quotes.error
@dashboard_link.error
@quotebook.error
@setname.error
@import_names.error
@list_names.error
@export_nicknames.error
async def command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("You need the Manage Messages permission to run this command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply("Couldn't find that member. Try mentioning them with @.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Usage: `!setname @user Real Name`")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Usage: `!quotebook 2026`")
    else:
        raise error


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    if not QUOTES_CHANNEL_ID:
        raise SystemExit("QUOTES_CHANNEL_ID is not set. Copy .env.example to .env and fill it in.")
    bot.run(TOKEN)
