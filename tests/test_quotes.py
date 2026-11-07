"""Quote privacy: nothing leaves Discord until it is safely on disk."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

import bot as quote_bot


QUOTE = '"the robot is fine" - Sam'


def fake_message(message_id=1, content=QUOTE, attachments=(), age=timedelta(0), channel_id=55):
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(bot=False, id=7),
        content=content,
        attachments=[SimpleNamespace(id=9, filename='a.png', url=url, save=AsyncMock())
                     for url in attachments],
        created_at=datetime.now(timezone.utc) - age,
        jump_url='https://discord.com/channels/1/2/3',
        channel=SimpleNamespace(id=channel_id, send=AsyncMock()),
        delete=AsyncMock(),
        add_reaction=AsyncMock(),
        reply=AsyncMock(),
    )


def fake_channel(*messages, during_history=None):
    async def history(**kwargs):
        for message in messages:
            yield message
        if during_history:
            await during_history()
    return SimpleNamespace(history=history)


class QuoteTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / 'quotes.json'
        for name, value in {
            'QUOTES_FILE': str(self.file),
            'NAMES_FILE': str(Path(directory.name) / 'names.json'),
            'QUOTES_CHANNEL_ID': 55,
            'DELETE_RECORDED_QUOTES': True,
            'QUOTES_SEALED': True,
            'MOD_USER_ID': 7,
        }.items():
            patcher = patch.object(quote_bot, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(quote_bot.bot, 'process_commands', AsyncMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def saved_ids(self):
        return [q['id'] for q in json.loads(self.file.read_text(encoding='utf-8'))]


class DeleteAfterRecordTests(QuoteTestCase):
    async def test_quote_is_on_disk_before_the_message_is_deleted(self):
        message = fake_message()
        ids_at_delete = []
        message.delete.side_effect = lambda: ids_at_delete.extend(self.saved_ids())
        await quote_bot.on_message(message)
        self.assertEqual(ids_at_delete, [1])
        self.assertEqual(message.channel.send.await_args.kwargs['delete_after'], 5)
        message.add_reaction.assert_not_awaited()

    async def test_failed_save_never_deletes(self):
        message = fake_message()
        with patch.object(quote_bot, 'write_quotes', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                await quote_bot.on_message(message)
        message.delete.assert_not_awaited()

    async def test_failed_write_keeps_the_existing_file(self):
        quote_bot.write_quotes([{'id': 1}])
        with patch.object(quote_bot.json, 'dump', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                quote_bot.write_quotes([{'id': 2}])
        self.assertEqual(self.saved_ids(), [1])

    async def test_chat_stays_but_is_still_recorded(self):
        message = fake_message(content='who has the drill')
        await quote_bot.on_message(message)
        message.delete.assert_not_awaited()
        self.assertEqual(self.saved_ids(), [1])

    async def test_attachment_is_copied_before_the_message_is_deleted(self):
        message = fake_message(attachments=['https://cdn.discordapp.com/a.png'])
        attachment = message.attachments[0]
        message.delete.side_effect = lambda: attachment.save.assert_awaited_once()
        await quote_bot.on_message(message)
        message.delete.assert_awaited_once()
        self.assertTrue(attachment.save.await_args.args[0].endswith('9-a.png'))

    async def test_failed_attachment_copy_keeps_the_message(self):
        message = fake_message(attachments=['https://cdn.discordapp.com/a.png'])
        message.attachments[0].save.side_effect = OSError('disk full')
        await quote_bot.on_message(message)
        message.delete.assert_not_awaited()
        message.add_reaction.assert_awaited_once()

    async def test_setting_turns_deletion_off(self):
        message = fake_message()
        with patch.object(quote_bot, 'DELETE_RECORDED_QUOTES', False):
            await quote_bot.on_message(message)
        message.delete.assert_not_awaited()
        message.add_reaction.assert_awaited_once()

    async def test_failed_delete_falls_back_to_the_reaction(self):
        message = fake_message()
        message.delete.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'Missing Permissions')
        await quote_bot.on_message(message)
        self.assertEqual(self.saved_ids(), [1])
        message.add_reaction.assert_awaited_once()
        message.channel.send.assert_not_awaited()

    async def test_already_deleted_message_counts_as_done(self):
        message = fake_message()
        message.delete.side_effect = discord.NotFound(
            SimpleNamespace(status=404, reason='Not Found'), 'Unknown Message')
        await quote_bot.on_message(message)
        message.channel.send.assert_awaited_once()

    async def test_unresolved_name_warning_survives_the_delete(self):
        message = fake_message(content='"the robot is fine" - <@123>')
        with patch.object(quote_bot, 'MOD_USER_ID', None):
            await quote_bot.on_message(message)
        sent = [call.args[0] for call in message.channel.send.await_args_list]
        self.assertFalse([text for text in sent if '<@123>' in text])
        message.reply.assert_not_awaited()

    async def test_other_channels_are_ignored(self):
        message = fake_message(channel_id=999)
        await quote_bot.on_message(message)
        message.delete.assert_not_awaited()
        self.assertFalse(self.file.exists())


class BackfillTests(QuoteTestCase):
    async def test_recent_quote_is_recorded_then_deleted(self):
        message = fake_message()
        ids_at_delete = []
        message.delete.side_effect = lambda: ids_at_delete.extend(self.saved_ids())
        self.assertEqual(await quote_bot.backfill_channel(fake_channel(message)), 1)
        self.assertEqual(ids_at_delete, [1])

    async def test_old_history_is_recorded_but_never_deleted(self):
        message = fake_message(age=timedelta(days=30))
        await quote_bot.backfill_channel(fake_channel(message))
        self.assertEqual(self.saved_ids(), [1])
        message.delete.assert_not_awaited()

    async def test_failed_delete_is_retried(self):
        message = fake_message()
        quote_bot.write_quotes([quote_bot.build_entry(message)])
        self.assertEqual(await quote_bot.backfill_channel(fake_channel(message)), 0)
        message.delete.assert_awaited_once()

    async def test_quote_saved_during_backfill_is_not_overwritten(self):
        live = fake_message(message_id=2)

        async def live_quote_arrives():
            await quote_bot.on_message(live)

        await quote_bot.backfill_channel(fake_channel(fake_message(), during_history=live_quote_arrives))
        self.assertEqual(sorted(self.saved_ids()), [1, 2])


def stored(message_id, timestamp, content=QUOTE):
    return {'id': message_id, 'timestamp': timestamp, 'content': content}


def fake_ctx(author_id=7):
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id, send=AsyncMock()),
        guild=None,
        reply=AsyncMock(),
        send=AsyncMock(),
    )


class SealedTests(QuoteTestCase):
    def setUp(self):
        super().setUp()
        quote_bot.write_quotes([
            stored(1, '2025-06-01T12:00:00+00:00'),
            stored(2, datetime.now(timezone.utc).isoformat()),
        ])
        self.this_year = datetime.now(quote_bot.QUOTES_TIMEZONE).year

    def sent_book(self, ctx):
        file = ctx.author.send.await_args.kwargs['file']
        return file.fp.read().decode('utf-8')

    async def test_random_and_top_show_nothing_while_sealed(self):
        for command, args in ((quote_bot.random_quote, ()), (quote_bot.top_quoted, (10,))):
            ctx = fake_ctx()
            await command.callback(ctx, *args)
            self.assertEqual(ctx.reply.await_args.args[0], quote_bot.SEALED_MESSAGE)
            ctx.send.assert_not_awaited()

    async def test_quote_of_the_day_stays_silent_while_sealed(self):
        channel = SimpleNamespace(send=AsyncMock(), guild=None)
        with patch.object(quote_bot.bot, 'get_channel', return_value=channel):
            await quote_bot.post_quote_of_the_day.coro()
        channel.send.assert_not_awaited()

    async def test_only_the_owner_gets_the_book(self):
        ctx = fake_ctx(author_id=8)
        await quote_bot.quotebook.callback(ctx, 2025)
        ctx.author.send.assert_not_awaited()
        self.assertEqual(ctx.reply.await_args.args[0], 'The quote book is private.')

    async def test_nobody_gets_the_book_without_an_owner(self):
        ctx = fake_ctx()
        with patch.object(quote_bot, 'MOD_USER_ID', None):
            await quote_bot.quotebook.callback(ctx, 2025)
        ctx.author.send.assert_not_awaited()

    async def test_owner_gets_past_years_by_dm(self):
        ctx = fake_ctx()
        await quote_bot.quotebook.callback(ctx, 2025)
        self.assertIn('===== 2025 =====', self.sent_book(ctx))

    async def test_this_years_book_waits_for_the_open_date(self):
        ctx = fake_ctx()
        with patch.object(quote_bot, 'book_is_open', return_value=False):
            await quote_bot.quotebook.callback(ctx, self.this_year)
        ctx.author.send.assert_not_awaited()
        self.assertIn('opens on', ctx.reply.await_args.args[0])

    async def test_this_years_book_opens_on_the_date(self):
        ctx = fake_ctx()
        with patch.object(quote_bot, 'QUOTE_BOOK_OPENS', (1, 1)):
            await quote_bot.quotebook.callback(ctx, self.this_year)
        self.assertIn(f'===== {self.this_year} =====', self.sent_book(ctx))

    async def test_plain_book_leaves_out_the_sealed_year(self):
        ctx = fake_ctx()
        with patch.object(quote_bot, 'QUOTE_BOOK_OPENS', (13, 1)):
            await quote_bot.quotebook.callback(ctx)
        book = self.sent_book(ctx)
        self.assertIn('===== 2025 =====', book)
        self.assertNotIn(f'===== {self.this_year} =====', book)


class YearTests(QuoteTestCase):
    async def test_new_years_eve_stays_in_its_local_year(self):
        evening = stored(1, '2026-01-01T02:00:00+00:00')
        text, count = quote_bot.build_quote_book_text([evening], year=2025)
        self.assertEqual(count, 1)
        self.assertIn('December 31, 2025', text)

    async def test_book_is_grouped_by_year_and_numbered_per_year(self):
        quotes = [
            stored(3, '2026-06-01T12:00:00+00:00'),
            stored(1, '2025-06-01T12:00:00+00:00'),
            stored(2, '2025-07-01T12:00:00+00:00'),
        ]
        text, count = quote_bot.build_quote_book_text(quotes)
        self.assertEqual(count, 3)
        lines = [line.split(' "')[0] for line in text.split('\n') if line]
        self.assertEqual(lines, ['===== 2025 =====', '1.', '2.', '===== 2026 =====', '1.'])

    async def test_year_filter_returns_only_that_year(self):
        quotes = [stored(1, '2025-06-01T12:00:00+00:00'), stored(2, '2026-06-01T12:00:00+00:00')]
        text, count = quote_bot.build_quote_book_text(quotes, year=2026)
        self.assertEqual(count, 1)
        self.assertNotIn('2025', text)

    async def test_empty_year_is_reported(self):
        text, count = quote_bot.build_quote_book_text([], year=2030)
        self.assertEqual((text, count), ('No formatted quotes found yet.', 0))
