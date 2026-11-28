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


def porter_env(pack_dir: Path | str | None = None) -> dict:
    """The environment the porter's children run with. The launcher's line is a Linux host:
    the host builds as a Linux ELF (NX2A_HOST_OS), and the machine is its own device — the
    game's own decoder and compiler run here, the way the phone app's porter is its device
    (NX2A_ON_DEVICE, on_android()'s override).  NX2A_PACK_DIR is where the finished pack
    goes: the porter writes it there itself (an atomic rename that replaces an older pack
    of the same game), so the launcher never moves a pack around.  DM_TARGET=linux names the
    host's TLS variant of this line (build.py's define and the rewrite's module mode — the
    same env the dev loop builds the host with on the container).  LD_PRELOAD is dropped:
    the desktop session's exec hook (DroidDeck's libddnatv-hook) redirects ELF executions
    into its own cache and breaks the pipeline's prebuilt tools."""
    env = dict(os.environ)
    env['NX2A_HOST_OS'] = 'linux'
    env['NX2A_ON_DEVICE'] = '1'
    env['DM_TARGET'] = 'linux'
    env.pop('LD_PRELOAD', None)   # the desktop session's exec hook breaks the pipeline's tools
    # the confirmed layout: the porter's own config under the launcher's config dir, its
    # working resources under the data dir (work is a running resource, not a cache)
    from launcher.settings import CONFIG_DIR, DEFAULT_WORK
    env.setdefault('NX2A_HOME', str(CONFIG_DIR / 'porter'))
    env.setdefault('NX2A_WORK', str(DEFAULT_WORK))
    env['PYTHONIOENCODING'] = 'utf-8'
    if pack_dir:
        env['NX2A_PACK_DIR'] = str(pack_dir)
        # the build work dir goes on the exec-capable disk too: the pipeline runs its
        # prebuilt tools from here, and the game storage is mounted noexec (a run from
        # there gets copied into DroidDeck's exec cache without its companion files)
        env['NX2A_WORK'] = str(Path(pack_dir).with_name('work'))
    return env


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

    def __init__(self, root: Path, pack_dir: Path | str | None = None):
        self.root = Path(root)
        self.pack_dir = pack_dir
        self.events: queue.Queue = queue.Queue()
        self.process: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, args: list[str]) -> None:
        env = porter_env(self.pack_dir)
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


def run_text(root: Path, args: list[str], timeout: float | None = None,
             pack_dir: Path | str | None = None) -> tuple[int, str, str]:
    """One porter command whose output is plain text (the profile import says one line).

    Returns the exit code, what it printed and what it complained about.
    """
    env = porter_env(pack_dir)
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


def run_json(root: Path, args: list[str], timeout: float | None = None,
             pack_dir: Path | str | None = None) -> tuple[dict | None, int, str]:
    """One porter command that prints one JSON document (the game's card).

    Returns the document, the exit code and a message when there is no document to read.
    """
    env = porter_env(pack_dir)
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


def _idle(callback, *args) -> None:
    """Hand a result to the main loop: the interface may only be touched there."""
    from gi.repository import GLib
    GLib.idle_add(callback, *args)


def run_json_async(root: Path, args: list[str], callback, timeout: float = 60,
                   pack_dir: Path | str | None = None) -> None:
    """One JSON command on a thread of its own, so it cannot freeze the interface:
    (document, code, error) arrives on the idle loop."""
    def work():
        _idle(callback, *run_json(root, args, timeout=timeout, pack_dir=pack_dir))
    threading.Thread(target=work, daemon=True).start()


def run_text_async(root: Path, args: list[str], callback, timeout: float = 60,
                   pack_dir: Path | str | None = None) -> None:
    """The same for a plain-text command: (code, out, err) arrives on the idle loop."""
    def work():
        _idle(callback, *run_text(root, args, timeout=timeout, pack_dir=pack_dir))
    threading.Thread(target=work, daemon=True).start()
