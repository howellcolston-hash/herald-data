"""Shared test setup: point the data, views and cache directories at a temporary folder."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TempDataCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="herald-test-"))
        self._env = {k: os.environ.get(k) for k in ("HERALD_DATA_DIR", "HERALD_VIEWS_DIR", "HERALD_CACHE_DIR")}
        os.environ["HERALD_DATA_DIR"] = str(self.tmp / "data")
        os.environ["HERALD_VIEWS_DIR"] = str(self.tmp / "views")
        os.environ["HERALD_CACHE_DIR"] = str(self.tmp / "cache")

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def data(self) -> Path:
        return self.tmp / "data"
