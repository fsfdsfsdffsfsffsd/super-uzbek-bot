import os

from telethon.sync import TelegramClient
from telethon.sessions import StringSession


API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")


if not API_ID or not API_HASH:
    raise SystemExit(
        "API_ID va API_HASH kerak.\n"
        "PowerShell:\n"
        '  $env:API_ID="123456"\n'
        '  $env:API_HASH="api_hash_bu_yerga"\n'
        "  py export_session.py"
    )


with TelegramClient(StringSession(), int(API_ID), API_HASH) as client:
    print("\nTELETHON_SESSION qiymati:")
    print(client.session.save())
    print("\nBuni server env/secret sifatida TELETHON_SESSION nomi bilan qo'ying.")
