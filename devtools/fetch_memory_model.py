#!/usr/bin/env python3
"""Fetch the local search's model from its release.

    python3 devtools/fetch_memory_model.py                    # the latest release
    python3 devtools/fetch_memory_model.py --version v2026.11.25
    python3 devtools/fetch_memory_model.py --dest .memembed/memory-embed

The model is built in the private repository (zFitness/nx2-memory) and
**published to a public one** (zFitness/public-dist): the build artifacts live
in their own public repository, so this download needs **no token** - a player,
a CI job or a fresh clone can fetch it.

This script is the app's side of that: it downloads the release asset and puts
the three files where the APK build expects them.

**The search works without the model.** It runs on the lexical side alone
(BM25 over the documents), which is what most of its strength comes from
 A build without the
model is a build without semantic ranking, not a broken build.

The file's sha256 is checked against the digest GitHub reports for the asset,
so a truncated download cannot pass silently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "zfitness/public-dist"
DEFAULT_DEST = REPO / ".memembed" / "memory-embed"
API = "https://api.github.com"


def token() -> str:
    """A token with read access, if there is one.

    The repository that carries the release is public, so a token is not
    needed. One is used when the environment has it: it lifts the API's rate
    limit, and it is what makes a private mirror work.
    """
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "MEMORY_MODEL_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                             timeout=60)
    except (OSError, subprocess.SubprocessError):
        out = None
    if out and out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    return ""


def auth_headers(tok: str, accept: str = "application/vnd.github+json") -> dict:
    """The request headers, with the token only when there is one."""
    headers = {
        "Accept": accept,
        "User-Agent": "nx2androidX-fetch-memory-model",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


def api(path: str, tok: str) -> dict:
    request = urllib.request.Request(f"{API}{path}", headers=auth_headers(tok))
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403) and not tok:
            raise SystemExit(
                f"GitHub said {error.code} for {path}.\n"
                "  the release repository is public - a token is not needed - but if\n"
                "  this is a private mirror, set GH_TOKEN (a token with read access).")
        raise SystemExit(f"GitHub said {error.code}: {error.reason} ({path})")
    except urllib.error.URLError as error:
        raise SystemExit(f"cannot reach GitHub: {error.reason}")


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """The token must not travel to the signed URL the release redirects to.

    The redirect lands on a different host, and that host authenticates by the
    signature in the URL - a second authentication (the token) makes it
    refuse the request.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != \
                urllib.parse.urlparse(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


def find_asset(repo: str, version: str, tok: str) -> tuple[str, str, str]:
    """The asset and its digest: (name, api url, sha256).

    The API's own asset URL, not the browser's download link: for a private
    repository the browser link answers 404 to a token that is not a session.
    """
    if version:
        release = api(f"/repos/{repo}/releases/tags/{version}", tok)
    else:
        release = api(f"/repos/{repo}/releases/latest", tok)
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("memory-embed-") and name.endswith(".zip"):
            digest = asset.get("digest", "") or ""
            sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
            return name, asset.get("url") or asset["browser_download_url"], sha
    raise SystemExit(f"no memory-embed asset in the release of {repo}")


def download(url: str, tok: str, target: Path) -> str:
    request = urllib.request.Request(
        url, headers=auth_headers(tok, "application/octet-stream"))
    digest = hashlib.sha256()
    opener = urllib.request.build_opener(_NoAuthOnRedirect())
    with opener.open(request, timeout=600) as response, \
            target.open("wb") as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def unpack(archive: Path, dest: Path) -> list[str]:
    """The three files, and nothing else."""
    wanted = {"embed.bin", "vocab.txt", "meta.json"}
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.iterdir():
        if stale.is_file():
            stale.unlink()
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if Path(n).name in wanted]
        if len(names) != len(wanted):
            raise SystemExit(f"the archive does not hold the three files: {zf.namelist()}")
        for name in names:
            with zf.open(name) as src, (dest / Path(name).name).open("wb") as out:
                shutil.copyfileobj(src, out)
    return sorted(Path(n).name for n in names)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.environ.get("MEMORY_REPO", DEFAULT_REPO),
                    help="the repository that carries the release")
    ap.add_argument("--version", default="",
                    help="the release to fetch (default: the latest)")
    ap.add_argument("--dest", default=str(DEFAULT_DEST),
                    help="where the three files go")
    args = ap.parse_args()

    tok = token()
    name, url, expected = find_asset(args.repo, args.version, tok)
    print(f"fetching {name} from {args.repo}")
    with tempfile.TemporaryDirectory(prefix="nx2a_model_") as tmp:
        archive = Path(tmp) / name
        actual = download(url, tok, archive)
        if expected and actual != expected:
            raise SystemExit(f"the download is not what the release says:\n"
                             f"  expected {expected}\n  got      {actual}")
        if not expected:
            print(f"  sha256 {actual}")
        files = unpack(archive, Path(args.dest))
    meta = json.loads((Path(args.dest) / "meta.json").read_text(encoding="utf-8"))
    size = sum((Path(args.dest) / f).stat().st_size for f in files)
    print(f"unpacked {', '.join(files)} -> {args.dest} ({size / 1e6:.1f} MB)")
    print(f"  version {meta.get('version')!r}, source {meta.get('source_commit', '')[:12]}, "
          f"{meta.get('pairs', '?')} pairs")


if __name__ == "__main__":
    main()
