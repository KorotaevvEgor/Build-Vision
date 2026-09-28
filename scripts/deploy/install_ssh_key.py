"""Разовая установка локального публичного SSH-ключа на сервер по паролю.

Пароль читается из переменной окружения VPS_PASSWORD (не как аргумент
командной строки и не печатается) — используется один раз для первого
подключения, дальше доступ идёт по ключу.

Запуск:
  $env:VPS_PASSWORD = '...'
  python scripts/deploy/install_ssh_key.py <host> <user>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

PUBKEY_PATH = Path.home() / ".ssh" / "id_ed25519.pub"


def main() -> None:
    host, user = sys.argv[1], sys.argv[2]
    password = os.environ["VPS_PASSWORD"]
    pubkey = PUBKEY_PATH.read_text(encoding="utf-8").strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, password=password, timeout=15)

    command = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qxF '{pubkey}' ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo '{pubkey}' >> ~/.ssh/authorized_keys && "
        "chmod 600 ~/.ssh/authorized_keys && echo INSTALLED"
    )
    _stdin, stdout, stderr = client.exec_command(command)
    out = stdout.read().decode()
    err = stderr.read().decode()
    print("STDOUT:", out.strip())
    if err.strip():
        print("STDERR:", err.strip())
    client.close()


if __name__ == "__main__":
    main()
