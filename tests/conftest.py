from pathlib import Path

import pytest

from earmark import config
from earmark.sources.base import Context
from earmark.storage import db as store


@pytest.fixture
def settings(tmp_path: Path) -> config.Settings:
    env = tmp_path / ".env"
    env.write_text(f"EARMARK_DATA={tmp_path / 'data'}\nEARMARK_BASE_URL=http://100.1.2.3:8765\n")
    return config.load(env)


@pytest.fixture
def ctx(settings) -> Context:
    return Context(settings, store.connect(settings.db_path))
