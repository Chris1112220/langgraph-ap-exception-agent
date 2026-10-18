"""app/db.py - one place that knows how to connect to Postgres."""
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()


@contextmanager
def get_conn():
    """Yield a connection whose rows come back as dicts ({'column': value})."""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        yield conn