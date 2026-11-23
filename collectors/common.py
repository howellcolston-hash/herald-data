"""Shared plumbing for every collector and builder.

Conventions (README.md, "How the code is laid out"):
  * Data lives under HERALD_DATA_DIR (default ./data). Views live under ./views.
  * Collectors are idempotent: re-running a period rewrites that period's file with the same content.
  * Every run appends one line to data/_runs/<collector>.jsonl.
  * HTTP goes through http_get() / http_download(): retries with backoff, a plain user agent, and a clear
    error after the last attempt.
  * Parquet is written with explicit column types and ZSTD, and no file is allowed over MAX_FILE_BYTES.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

USER_AGENT = "herald-data/0.1 (public procurement records; contact via repository)"
REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_BYTES = 95 * 1024 * 1024          # hard limit from the brief: no file over 95 MB
SPLIT_TARGET_BYTES = 70 * 1024 * 1024      # aim for parts of about this size when a file must be split


def data_dir() -> Path:
    d = Path(os.environ.get("HERALD_DATA_DIR", REPO_ROOT / "data")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def views_dir() -> Path:
    d = Path(os.environ.get("HERALD_VIEWS_DIR", REPO_ROOT / "views")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    """Downloads land here; never committed (.gitignore)."""
    d = Path(os.environ.get("HERALD_CACHE_DIR", REPO_ROOT / ".cache")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def today_utc() -> dt.date:
    return utc_now().date()


def parse_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def fiscal_year(d: dt.date | None) -> str:
    """Government of Canada fiscal year (April to March) as '2023-2024'; 'undated' when there is no date."""
    if d is None:
        return "undated"
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{start + 1}"


def fiscal_year_bounds(fy: str) -> tuple[dt.date, dt.date]:
    a = int(fy[:4])
    return dt.date(a, 4, 1), dt.date(a + 1, 3, 31)


# --------------------------------------------------------------------------- HTTP

class FetchError(RuntimeError):
    pass


def http_get(url: str, params: dict | None = None, *, timeout: float = 60, retries: int = 4,
             backoff: float = 3.0, headers: dict | None = None) -> bytes:
    """GET with retries. Returns the body (gunzipped if the server gzipped it)."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if headers:
        h.update(headers)
    last = None
    attempt = 0
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404, 410) and attempt >= 2:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise FetchError(f"GET failed after {attempt} attempts: {url} ({last})")


def http_get_json(url: str, params: dict | None = None, **kw):
    return json.loads(http_get(url, params, **kw).decode("utf-8"))


def http_head(url: str, *, timeout: float = 60) -> dict:
    """Last-Modified and Content-Length of a URL, or {} when the server won't say."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"last_modified": resp.headers.get("Last-Modified"),
                    "size": int(resp.headers.get("Content-Length") or 0) or None}
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return {}


def http_download(url: str, dest: Path, *, timeout: float = 600, retries: int = 4, backoff: float = 5.0) -> Path:
    """Stream a URL to a file (written beside it first, then moved into place). Retries the whole download."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    attempt = 0
    for attempt in range(1, retries + 1):
        tmp = dest.with_name(dest.name + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out, length=1 << 20)
                expected = resp.headers.get("Content-Length")
            if expected and tmp.stat().st_size != int(expected):
                raise FetchError(f"short download: {tmp.stat().st_size} of {expected} bytes")
            os.replace(tmp, dest)
            return dest
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404, 410) and attempt >= 2:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, FetchError) as e:
            last = e
        finally:
            if tmp.exists():
                tmp.unlink()
        if attempt < retries:
            time.sleep(backoff * attempt)
    raise FetchError(f"download failed after {attempt} attempts: {url} ({last})")


# --------------------------------------------------------------------------- run log

def _runs_path(collector: str) -> Path:
    p = data_dir() / "_runs" / f"{collector}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log_run(collector: str, status: str, *, started: dt.datetime, rows: int | None = None,
            periods: list[str] | None = None, notes: str = "", params: dict | None = None,
            counts: dict | None = None) -> dict:
    rec = {
        "collector": collector,
        "status": status,               # ok | partial | failed | skipped
        "started": started.isoformat(),
        "finished": utc_now().isoformat(),
        "rows": rows,
        "periods": periods or [],
        "notes": notes,
        "params": params or {},
        "counts": counts or {},
        "runner": f"github:{os.environ['GITHUB_RUN_ID']}" if os.environ.get("GITHUB_RUN_ID") else "local",
    }
    with open(_runs_path(collector), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def last_runs(collector: str) -> list[dict]:
    p = _runs_path(collector)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


class Terminated(BaseException):
    """Raised inside a run when the process receives SIGTERM (e.g. a CI step timeout)."""


@contextmanager
def run(collector: str, params: dict | None = None):
    """Log one run. Yields a dict the collector fills: rows, periods, notes, status, counts.

    Any exception, including SIGTERM from a CI timeout, is logged as a failed run before it propagates,
    so the workflow fails visibly and the run log still says why."""
    import signal
    import threading

    started = utc_now()
    ctx = {"rows": 0, "periods": [], "notes": [], "status": "ok", "counts": {}}
    previous = None
    if threading.current_thread() is threading.main_thread():
        def _on_term(signum, frame):  # noqa: ARG001
            raise Terminated("received SIGTERM")
        previous = signal.signal(signal.SIGTERM, _on_term)
    try:
        yield ctx
    except GeneratorExit:
        raise
    except BaseException as e:  # noqa: BLE001 - log and re-raise
        ctx["notes"].append(f"{type(e).__name__}: {e}")
        log_run(collector, "failed", started=started, rows=ctx["rows"], periods=ctx["periods"],
                notes=" | ".join(str(n) for n in ctx["notes"]), params=params, counts=ctx["counts"])
        traceback.print_exc()
        raise
    else:
        log_run(collector, ctx["status"], started=started, rows=ctx["rows"], periods=ctx["periods"],
                notes=" | ".join(str(n) for n in ctx["notes"]), params=params, counts=ctx["counts"])
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


# --------------------------------------------------------------------------- files

@contextmanager
def atomic_target(path: str | Path):
    """Yield a temporary path next to `path`; move it into place only if the block succeeds."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        yield tmp
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_json(path: str | Path) -> dict:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: str | Path, value) -> None:
    """Sorted, indented JSON, written atomically."""
    with atomic_target(path) as tmp:
        tmp.write_text(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)
