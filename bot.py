import io
import json
import os
from datetime import datetime, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

from quote_parser import parse_quote

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
QUOTES_CHANNEL_ID = int(os.getenv("QUOTES_CHANNEL_ID", "0"))
QUOTES_FILE = os.getenv("QUOTES_FILE", "quotes.json")
NAMES_FILE = os.getenv("NAMES_FILE", "names.json")
NICKNAMES_FILE = os.getenv("NICKNAMES_FILE", "nicknames.json")

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


def build_quote_book_text(quotes, guild=None):
    names = load_names()
    lines = []
    i = 0
    for q in sorted(quotes, key=lambda x: x["timestamp"]):
        parsed = parse_quote(q.get("content", ""))
        if parsed is None:
            continue
        quote_text, attribution_name, attribution_id = parsed
        if attribution_id is not None:
            who = names.get(str(attribution_id))
            if who is None and guild is not None:
                member = guild.get_member(attribution_id)
                who = member.display_name if member else None
            if who is None:
                who = f"<@{attribution_id}>"
        else:
            who = attribution_name

        i += 1
        dt = datetime.fromisoformat(q["timestamp"]).strftime("%B %d, %Y")
        lines.append(f'{i}. "{quote_text}" — {who} ({dt})')
        lines.append("")
    return "\n".join(lines) if lines else "No formatted quotes found yet."


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
                if parse_quote(message.content) is not None:
                    await message.add_reaction("\U0001F4DD")  # 📝

    await bot.process_commands(message)


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
    text = build_quote_book_text(quotes, guild=ctx.guild)
    buffer = io.BytesIO(text.encode("utf-8"))
    await ctx.reply(
        content=f"Here's the compiled quote book ({len(quotes)} quotes).",
        file=discord.File(buffer, filename="quote_book.txt"),
    )


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
