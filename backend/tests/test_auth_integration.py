"""Включает реальные ORM/session тесты в pytest, изолируя Django в subprocess."""

import os
import subprocess
import sys
from pathlib import Path


def test_django_authentication_regressions():
    env = os.environ.copy()
    for key in ("DATABASE_URL", "DJANGO_SUPERUSER_PASSWORD", "SK_PARTICIPANT_PASSWORD"):
        env.pop(key, None)
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "manage.py"),
            "test",
            "core.tests.test_authentication",
            "--settings=admin_panel.test_settings",
            "--noinput",
            "--verbosity=1",
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
