# phone_tools — the tools that travel with the app

These are the tools the assistant (and the player) run on the phone. They are shipped inside the
app's payload, in `tool/tools/`, next to the app's own scripts — so they are always the same
version as the porter they work with.

On the phone they live at `$NX2A_REPO/tools/` (`NX2A_REPO` is the app's `files/tool`):

    python3 $NX2A_REPO/tools/fetch.py --help

## The rules every tool follows

- **Read, then print.** A tool reads a few files and prints a table a human reads. With `--json`
  it prints the same thing for a program.
- **One line about a failure, never a traceback.** The assistant reads what the tool says; a
  Python stack trace is noise to it.
- **Only the standard library** (plus Pillow for the frames, which the payload already carries).
  Everything else is in the porter, which the tools reach through the tree they are shipped with.
- **Paths come from the environment**: `$NX2A_HOME` (the player's nx2android folder), `$NX2A_REPO`
  (the tool tree), `$NX2A_WORK` (the build workspace). Never a hard-coded `/data/user/0/...`.

## The tools

| tool | what it does |
|---|---|
| `port_status.py` | every data pack on the phone in one table: the game, its title ID, its status, and whether it crashed |
| `mem_layout.py` | a game's memory layout: the alias window, the stack and the heap, in both notations |
| `log_triage.py` | a run's log: the crash's signature, the last errors, and which log holds the backtrace |
| `builds.py` | the build history: what was built, how it went, where the failing one went wrong |
| `card.py` | what is on a game card, and what the porter makes of it (a card rebuilt with the update inside) |
| `card_split.py` | cut a card into one NSP per title (the base game, its update, its DLCs), flat in a folder next to the card itself (`<card name>-<title ID>/`, unless the player names another folder) |
| `fetch.py` | fetch a URL: the certificate is checked, a dropped handshake is retried, the failure is in plain words |
| `shot.py` | catch a frame, turn it into a PNG, and say what is in it (is it black, is it moving) |
| `upstream_diff.py` | what the phone's porter and engine differ from the upstream's |
| `upstream_pr.py` | the upstream's PRs and issues on GitHub that mention the symptom (the fix may already exist) |
| `gamespec_pack.py` | a game's case file, packed into a zip the player can hand to the upstream (the document, the files that were changed, the manifest, and the diff against the originals when the case file has them) |
| `memory_embed.py` | the static embedding model as a lookup table: the model artifact (5.6 MB) turned into a vector for a text, in plain python, no numpy |
| `memory_search.py` | the search over what this phone knows: the upstream's pull requests, the knowledge documents, the closed issues and the player's own cases, in one index, with the pull request and issue numbers on every hit |

## Adding a tool

1. Write it in this folder. `nx2a_common.py` has the shared parts (the paths, the table, the
   error, the `--json` flag).
2. Add a test in `tests/` (the repository's own: `python3 -m unittest discover tests`).
3. Add it to the table above and to the assistant's working agreement
   (`android/app/src/main/assets/nx2a/AGENTS.md` - the seed text the app plants on the
   phone), so the assistant knows it exists.

When a task needs a whole procedure and not just a command, write it as a skill: a `SKILL.md` the
engine loads when the task matches (the engine reads the ones in `$HOME/.agents/skills/`; ours are
seeded from the App's assets - `android/app/src/main/assets/nx2a/agent/dot-agents/skills/`, and
the card-unpack playbook is the example).

The payload picks this folder up as it is (`packaging/android-apk/build_assets.py`): nothing else
has to be registered.
