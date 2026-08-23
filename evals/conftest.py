"""Pytest wiring: repo root on sys.path + eval-DB env swap BEFORE collection.

The env swap must happen before any test module imports data.db (which
freezes SUPABASE_* via shared.config at import time). Pure tests run fine
without an eval DB; DB-backed tests skip when .env.eval is absent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from dotenv import load_dotenv

from evals import seed

_DB_READY = seed.load_eval_env()   # at import time, i.e. before collection
# Provider keys (OPENAI_API_KEY for L2 sessions, ANTHROPIC_API_KEY for the
# judge) come from the repo .env; never overrides the eval-DB swap above.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@pytest.fixture(scope="session")
def eval_db():
    if not _DB_READY:
        pytest.skip("evals/.env.eval not configured")
    seed.require_eval_db()
    yield
