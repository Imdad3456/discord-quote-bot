import io
import json
import os
import random
from datetime import datetime, time, timezone

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from quote_parser import MENTION_RE, parse_quotes

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
QUOTES_CHANNEL_ID = int(os.getenv("QUOTES_CHANNEL_ID", "0"))
QUOTES_FILE = os.getenv("QUOTES_FILE", "quotes.json")
NAMES_FILE = os.getenv("NAMES_FILE", "names.json")
NICKNAMES_FILE = os.getenv("NICKNAMES_FILE", "nicknames.json")
MOD_USER_ID = int(os.getenv("MOD_USER_ID")) if os.getenv("MOD_USER_ID") else None
QUOTE_OF_DAY_HOUR_UTC = int(os.getenv("QUOTE_OF_DAY_HOUR_UTC", "13"))

QUOTE_REACTION_EMOJI = "\U0001FAC3"  # 🫃 pregnant man

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


def load_quotes():
    if os.path.exists(QUOTES_FILE):
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def write_quotes(quotes):
    with open(QUOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(quotes, f, indent=2, ensure_ascii=False)


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


async def backfill_channel(channel):
    quotes = load_quotes()
    existing_ids = {q["id"] for q in quotes}
    added = 0

    async for message in channel.history(limit=None, oldest_first=True):
        if message.author.bot:
            continue
        if message.id in existing_ids:
            continue
        if not message.content and not message.attachments:
            continue
        quotes.append(build_entry(message))
        existing_ids.add(message.id)
        added += 1

    if added:
        quotes.sort(key=lambda q: q["timestamp"])
        write_quotes(quotes)

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


def format_quote_line(q, quote_text, attribution_name, attribution_id, names, guild):
    dt = datetime.fromisoformat(q["timestamp"]).strftime("%B %d, %Y")
    quote_text = resolve_mentions_in_text(quote_text, names, guild)
    who = resolve_attribution(attribution_name, attribution_id, names, guild)
    return f'"{quote_text}" — {who} ({dt})'


def build_quote_book_text(quotes, guild=None):
    names = load_names()
    lines = []
    i = 0
    for q, quote_text, attribution_name, attribution_id in iter_parsed_quotes(quotes):
        i += 1
        lines.append(f"{i}. " + format_quote_line(q, quote_text, attribution_name, attribution_id, names, guild))
        lines.append("")
    text = "\n".join(lines) if lines else "No formatted quotes found yet."
    return text, i


async def notify_unresolved(message, unresolved_ids):
    mentions = ", ".join(f"<@{uid}>" for uid in unresolved_ids)
    text = (
        f"⚠️ Unresolved quote attribution in {message.jump_url}: {mentions}\n"
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
    await message.reply(text, mention_author=False)


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
            quotes = load_quotes()
            if message.id not in {q["id"] for q in quotes}:
                quotes.append(build_entry(message))
                write_quotes(quotes)
                parsed = parse_quotes(message.content)
                if parsed:
                    await message.add_reaction(QUOTE_REACTION_EMOJI)
                    names = load_names()
                    unresolved = sorted(
                        {aid for _, _, aid in parsed if aid is not None and str(aid) not in names}
                    )
                    if unresolved:
                        await notify_unresolved(message, unresolved)

    await bot.process_commands(message)


@tasks.loop(time=time(hour=QUOTE_OF_DAY_HOUR_UTC, tzinfo=timezone.utc))
async def post_quote_of_the_day():
    channel = bot.get_channel(QUOTES_CHANNEL_ID)
    if channel is None:
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


@bot.command(name="quotebook")
@commands.has_permissions(manage_messages=True)
async def quotebook(ctx):
    quotes = load_quotes()
    text, count = build_quote_book_text(quotes, guild=ctx.guild)
    buffer = io.BytesIO(text.encode("utf-8"))
    await ctx.reply(
        content=f"Here's the compiled quote book ({count} quotes).",
        file=discord.File(buffer, filename="quote_book.txt"),
    )


@bot.command(name="randomquote")
async def random_quote(ctx):
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
async def top_quoted(ctx, top_n: int = 10):
    quotes = load_quotes()
    names = load_names()
    counts = {}
    for q, quote_text, attribution_name, attribution_id in iter_parsed_quotes(quotes):
        who = resolve_attribution(attribution_name, attribution_id, names, ctx.guild)
        counts[who] = counts.get(who, 0) + 1
    if not counts:
        await ctx.reply("No formatted quotes found yet.")
        return
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    lines = [f"{idx}. {name} — {count} quote(s)" for idx, (name, count) in enumerate(ranked, start=1)]
    await ctx.reply("**Most Quoted:**\n" + "\n".join(lines))


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
    else:
        raise error


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    if not QUOTES_CHANNEL_ID:
        raise SystemExit("QUOTES_CHANNEL_ID is not set. Copy .env.example to .env and fill it in.")
    bot.run(TOKEN)
