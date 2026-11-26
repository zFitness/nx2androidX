"""Running the porter.

The porter is a child process: `python -m porter.phone_cli ...`, the same pipeline the
phone app runs.  Its stdout is one JSON event per line (a stage, a step, a progress
line, a message, the result); a line that is not JSON is a message of its own.

A port runs dotnet, the rewriter and a compiler as children of its own, so a cancel
has to reach the whole process group: the child is started in a session of its own and
the group is signalled.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DONE = 'done'


def porter_root(setting: str = '') -> Path | None:
    """Where the porter package is: the setting, the environment, or the checkout next to
    this launcher.  None when there is none, which the caller turns into a message."""
    for raw in (setting, os.environ.get('NX2A_PORTER_DIR', ''), str(REPO)):
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if (candidate / 'porter' / 'phone_cli.py').is_file():
            return candidate
    return None


def _event(line: str) -> dict:
    """One line of the stream: a JSON event, or a message."""
    text = line.strip()
    if not text:
        return {}
    try:
        event = json.loads(text)
    except ValueError:
        return {'ev': 'say', 'msg': text}
    return event if isinstance(event, dict) else {'ev': 'say', 'msg': text}


class Porter:
    """One porter command.  The events come out of `events`, a queue the interface
    drains; the command ends with a `done` event carrying the exit code."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.events: queue.Queue = queue.Queue()
        self.process: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, args: list[str]) -> None:
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'porter.phone_cli', *args],
            cwd=str(self.root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            start_new_session=True,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process and self.process.stdout
        try:
            for line in self.process.stdout:
                event = _event(line)
                if event:
                    self.events.put(event)
        finally:
            self.process.stdout.close()
        code = self.process.wait()
        self.events.put({'ev': DONE, 'code': code})

    def cancel(self) -> None:
        """Stop the command and everything it started."""
        if not self.running or not self.process:
            return
        try:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            self.process.terminate()


def run_text(root: Path, args: list[str], timeout: float | None = None) -> tuple[int, str, str]:
    """One porter command whose output is plain text (the profile import says one line).

    Returns the exit code, what it printed and what it complained about.
    """
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        done = subprocess.run(
            [sys.executable, '-m', 'porter.phone_cli', *args],
            cwd=str(root), env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, '', 'the porter did not answer in time'
    except OSError as error:
        return -1, '', f'could not start the porter: {error}'
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def run_json(root: Path, args: list[str], timeout: float | None = None) -> tuple[dict | None, int, str]:
    """One porter command that prints one JSON document (the game's card).

    Returns the document, the exit code and a message when there is no document to read.
    """
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        done = subprocess.run(
            [sys.executable, '-m', 'porter.phone_cli', *args],
            cwd=str(root), env=env, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, -1, 'the porter did not answer in time'
    except OSError as error:
        return None, -1, f'could not start the porter: {error}'
    out = done.stdout.strip()
    if not out:
        detail = done.stderr.strip().splitlines()
        reason = detail[-1] if detail else 'no answer'
        return None, done.returncode, reason
    try:
        document = json.loads(out)
    except ValueError:
        return None, done.returncode, 'the porter answered with something that is not JSON'
    return (document if isinstance(document, dict) else None), done.returncode, ''
