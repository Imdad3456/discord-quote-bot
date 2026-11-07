import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet, InvalidToken

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))

import encrypt_saved
import vault

SECRET = 'a very private quote'


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        self.file = self.folder / 'quotes.json'
        patcher = patch.dict(os.environ, {'QUOTES_KEY': Fernet.generate_key().decode()})
        patcher.start()
        self.addCleanup(patcher.stop)


class SavedFileTests(VaultTestCase):
    def test_saved_file_has_no_readable_text_and_opens_again(self):
        vault.write_json(self.file, [{'content': SECRET}])
        self.assertNotIn(SECRET, self.file.read_text(encoding='utf-8'))
        self.assertEqual(vault.read_json(self.file, []), [{'content': SECRET}])

    def test_saved_file_stays_valid_json_for_the_backup_job(self):
        vault.write_json(self.file, [])
        json.loads(self.file.read_bytes())

    def test_missing_file_gives_the_default(self):
        self.assertEqual(vault.read_json(self.file, []), [])

    def test_a_different_key_cannot_open_it(self):
        vault.write_json(self.file, [])
        with patch.dict(os.environ, {'QUOTES_KEY': Fernet.generate_key().decode()}):
            with self.assertRaises(InvalidToken):
                vault.read_json(self.file, [])

    def test_no_key_refuses_to_read_or_write(self):
        vault.write_json(self.file, [])
        with patch.dict(os.environ, {'QUOTES_KEY': ''}):
            with self.assertRaises(RuntimeError):
                vault.read_json(self.file, [])
            with self.assertRaises(RuntimeError):
                vault.write_json(self.file, [{'content': SECRET}])
        self.assertEqual(vault.read_json(self.file, []), [])

    def test_changed_file_is_rejected(self):
        vault.write_json(self.file, [])
        saved = json.loads(self.file.read_bytes())
        saved[vault.MARKER] = saved[vault.MARKER][:-4] + 'AAAA'
        self.file.write_text(json.dumps(saved), encoding='utf-8')
        with self.assertRaises(InvalidToken):
            vault.read_json(self.file, [])


class EncryptExistingTests(VaultTestCase):
    def test_plain_data_is_encrypted_in_place(self):
        self.file.write_text(json.dumps([{'content': SECRET}]), encoding='utf-8')
        names = self.folder / 'names.json'
        names.write_text(json.dumps({'1': 'Sam'}), encoding='utf-8')
        attachments = self.folder / 'attachments'
        attachments.mkdir()
        (attachments / '9-a.png').write_bytes(b'picture')

        encrypt_saved.encrypt_data(str(self.folder))
        encrypt_saved.encrypt_data(str(self.folder))

        self.assertNotIn(SECRET, self.file.read_text(encoding='utf-8'))
        self.assertEqual(vault.read_json(self.file, []), [{'content': SECRET}])
        self.assertEqual(vault.read_json(names, {}), {'1': 'Sam'})
        self.assertEqual([p.name for p in attachments.iterdir()], ['9-a.png.enc'])
        self.assertEqual(vault.read_bytes(attachments / '9-a.png.enc'), b'picture')

    def test_plain_file_goes_only_after_its_copy_matches(self):
        backup = self.folder / 'daily.tar.gz'
        backup.write_bytes(SECRET.encode())
        with patch.object(vault, 'read_bytes', return_value=b'wrong'):
            with self.assertRaises(SystemExit):
                encrypt_saved.encrypt_file(str(backup))
        self.assertTrue(backup.exists())
        self.assertFalse((self.folder / 'daily.tar.gz.enc').exists())

        encrypt_saved.encrypt_file(str(backup))
        self.assertFalse(backup.exists())
        output = self.folder / 'restored'
        encrypt_saved.decrypt_file(str(self.folder / 'daily.tar.gz.enc'), str(output))
        self.assertEqual(output.read_bytes(), SECRET.encode())


if __name__ == '__main__':
    unittest.main()
