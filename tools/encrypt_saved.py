"""Encrypt what was saved before QUOTES_KEY existed, or open an encrypted file.

  data FOLDER        Encrypt quotes.json, names.json and attachments/ in place.
  files PATH...      Replace each plain file with PATH.enc.
  decrypt PATH OUT   Write the plain copy of a PATH.enc to OUT.

Nothing plain is removed until its encrypted copy has been read back and matched.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import vault


def encrypt_json(path):
    if not os.path.exists(path):
        return
    before = vault.read_json(path, None)
    candidate = f"{path}.new"
    vault.write_json(candidate, before)
    if vault.read_json(candidate, None) != before:
        os.remove(candidate)
        raise SystemExit(f"{path} didn't match after encrypting. Left it as it was.")
    os.replace(candidate, path)
    print(f"Encrypted {os.path.basename(path)}: {len(before)} entries")


def encrypt_file(path):
    with open(path, "rb") as f:
        content = f.read()
    target = f"{path}.enc"
    vault.write_bytes(target, content)
    if vault.read_bytes(target) != content:
        os.remove(target)
        raise SystemExit(f"{path} didn't match after encrypting. Left it as it was.")
    os.remove(path)


def encrypt_data(folder):
    encrypt_json(os.path.join(folder, "quotes.json"))
    encrypt_json(os.path.join(folder, "names.json"))
    attachments = os.path.join(folder, "attachments")
    if os.path.isdir(attachments):
        for name in os.listdir(attachments):
            if not name.endswith(".enc"):
                encrypt_file(os.path.join(attachments, name))


def decrypt_file(path, output):
    with open(output, "wb") as f:
        f.write(vault.read_bytes(path))


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "data":
        encrypt_data(args[1])
    elif len(args) > 1 and args[0] == "files":
        for path in args[1:]:
            encrypt_file(path)
        print(f"Encrypted {len(args) - 1} file(s)")
    elif len(args) == 3 and args[0] == "decrypt":
        decrypt_file(args[1], args[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
