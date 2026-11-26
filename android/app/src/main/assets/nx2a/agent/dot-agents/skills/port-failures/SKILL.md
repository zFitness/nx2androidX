---
name: port-failures
description: The failures of a Switch game ported to Android, distilled from 387 upstream pull requests - the build that stops at a stage, the shader split that finds too few shaders, the crash, the black screen, the garbled picture, the freeze. Read it when a port does not build, when the game misbehaves on the device, or before searching the upstream for a fix that may already exist there. It says what the symptom usually is, what evidence tells the causes apart, and whether this fork already has the fix.
---

# The failures of a port: what broke, and where the fix goes

387 upstream pull requests (`shirai91/nx2android`), read and sorted into a diagnosis. Every
case carries the evidence that named it and the layer that owns the fix.

**This knowledge base is written by hand and it is static.** It does not crawl, it does not
refresh itself, and the assistant does not update it. What it gives the assistant is the
offline half of the upstream search: `tools/upstream_pr.py` asks GitHub whether a fix exists
there, and the phone's network often cannot reach GitHub at all. Search here first, search
GitHub after, and say which one you used.

When a case turns up that is not in here, write it into that game's case file - not into the
knowledge base. The knowledge base is maintained by a person, on a computer; the procedure
is in `openspec/specs/port-failures/tasks.md` in the repository.

**One thing the case file has to carry, so the knowledge can be written down later:** the
case's own index row. When the case is closed, write a `## Case index row` section into the
case file with one line of tab-separated fields, the same columns the index has: the case's
reference, the symptom, the layer, the game and its title ID, the paths the fix touched and
a one-line summary of the cause and the fix. The person at the computer pastes that line
into the index (`corpus-fork.json`), and the next game with the same symptom finds it.

## When to read what

| The question | The file |
|---|---|
| The port does not build, or stops at a stage | `references/build-failures.md` |
| The shaders are missing, the count is too low, the split and the profile disagree | `references/shader-split.md` |
| The game crashes, shows a black screen, draws garbage, or freezes | `references/runtime-symptoms.md` |
| What the symptom looks like on a phone, what the first move is, the dead ends | `references/device-findings.md` |
| How to bring up a new game, how to read a crash report, where a fix belongs | `references/porting-method.md` |
| Which upstream case is this? | `references/case-index.tsv`, through the search (`--corpus pr`) |
| Has anybody already hit this? | `references/issues/`, through the search (`--corpus issue`) - the closed issues of both repositories, the fork's ones written in chinese |
| What the documents say about this symptom, word for word | the documents, through the search (`--corpus doc`) |

The runtime document opens with a triage table: the symptom, the likely causes in order,
what tells them apart, and the first thing to do. Start there.

**The two runtime documents answer different questions.** `runtime-symptoms.md` is the
upstream's cases: what was fixed, and where the fix belongs. `device-findings.md` is what a
symptom looks like on a phone, the first move, the dead ends that were ruled out, and this
line's own findings. When a symptom has no cause yet, the second file may already know the
shape.

**`porting-method.md` is the method, not the cases.** How to measure a title before
touching the host, how to read the log and a crash report, the probe toolbox
(`DM_PROBE`, `DM_PROBE_WATCH`, `DM_PROBE_POLL`), how to make an intermittent failure
happen every time, and the levels a fix can be bound to. Reach for it when you need to
decide what to do, not when you need to know what a symptom means.

## Never read a document whole

The documents are a database, not a text to read: five files, 116 KB of prose, and every
answer is one section of one of them. Reading a whole document costs tens of thousands of
tokens, and they are paid again on every tool call that follows - a diagnosis turns dozens
of calls, so the bill is multiplied.

**Query first, then read one section.** The search finds the section and says where it is.
Read that section, and no more.

```bash
# the documents, by section: the answer, where it is, and a snippet of it
python3 $NX2A_REPO/tools/memory_search.py search --corpus doc "shared font glyph"
# one section as it is written, when the snippet is not enough
sed -n '196,240p' $NX2A_HOME/agent/.agents/skills/port-failures/references/device-findings.md
```

The search says where the section is (the file and its line range), so the second step is a
`sed` over that range - not a read of the whole document. When nothing matches, the search
says how the documents spell the word and points at the upstream cases, which hold the pull
request titles and summaries. The corpora answer different questions: the documents hold the
distilled knowledge, the index holds what upstream wrote.

**The player writes in chinese, the corpus is in english.** Rewrite the question into english
technical words before you search it - "启动后画面全黑" becomes "the screen is black after
launch". The search knows a few chinese words on its own (黑屏, 崩溃, 卡死, 闪退, 掉帧, 字体,
乱码), but that is a floor, not a way.

## The search

On the phone the skill sits in the assistant's own folder, so the search is:

```bash
python3 $NX2A_REPO/tools/memory_search.py search "black screen"
python3 $NX2A_REPO/tools/memory_search.py search --corpus case "black screen"          # this phone's own cases
python3 $NX2A_REPO/tools/memory_search.py search --corpus doc "shared font glyph"       # the documents
python3 $NX2A_REPO/tools/memory_search.py search --symptom crash --layer host           # the upstream's cases
python3 $NX2A_REPO/tools/memory_search.py search --game "0100A9D01C446000" --fork no
```

One search covers everything: the upstream's pull requests, the knowledge documents, the
closed issues of both repositories and this phone's own cases. `--corpus` picks one of them
(`pr`, `doc`, `issue`, `case`); without it every corpus is searched at once.

**A filter on its own lists what it matches** - no question needed:

```bash
python3 $NX2A_REPO/tools/memory_search.py search --corpus pr --symptom perf   # every performance PR
python3 $NX2A_REPO/tools/memory_search.py search --corpus pr --layer vk        # every PR in the vk layer
```

Use that when you want to see a whole corner of the corpus - "everything upstream did
about performance" - rather than one answer to one question. With a question, the filters
narrow the answers instead.

Every answer is bounded: a search lists at most five hits, or twelve cases when a corpus
was named, and says how many matched in all. `-k N` asks for more.

`--symptom` is one of `crash`, `black`, `garble`, `freeze`, `missing`, `build`, `memory`,
`shader`, `perf`, `audio`, `movie`, `feature`. `--layer` is one of `profile`, `shader`, `nvn`,
`tex`, `vk`, `host`, `rewriter`, `porter`, `app`, `android`, `audio`, `movie`, `perf`, `tools`,
`docs`. `--fork no` gives the cases whose fix is **not** in this fork: those are the ones
worth a port.

The index has one row per upstream pull request, tab separated: the upstream it came from,
the number, the state, the area, the symptom, the layer, the kind (core, profile, app,
tooling), whether the fix is in this fork, the game, the title IDs, the switches the pull
request names, the paths it touched, the title, the summary line and the link.

The first column says which upstream the case came from. `--source shirai91` narrows the
search to this fork's upstream; leaving it out searches every upstream in the index.

**This fork's own cases are in the index too**, with the source `nx2androidX`: a fix that
was worked out on a phone and put on a branch under `case/`, or a case whose fix is still
only in the phone's case file. `--source nx2androidX` finds them, and `--fork no` lists
the ones whose fix is not in the checkout yet - those are worth bringing over. Their
reference is the case's own name (`case/<title ID>-<slug>`) or a commit's hash, not a
pull request number: the code is on a branch, not on a pull request.

## The discipline

The same five steps every time. They are what turns a symptom into a fix.

1. **Make it countable.** "It flickers sometimes" becomes "58 of 118 frames bad". Count the
   draws the log says were skipped. A screenshot misses a one-frame bug.
2. **Find the evidence.** The log line, the fault address, the pass dump, the shader count.
   The documents say which evidence names which cause.
3. **Name the layer.** The tables at the end of `runtime-symptoms.md` say which directory
   owns which family of symptoms. The layer decides where the fix goes.
4. **Core or profile.** A core change is a rule in shared code: on by default, or behind a
   general switch, and it must not change any other game's behaviour. A profile change is a
   row in `nxnative/dm/games/<title ID>/`. When a symptom is one game's own, the upstream
   pattern is: add a general switch, default off, then set it in the profile.
5. **Check this fork first.** The index's `fork` column says whether the fix is already
   here. A symptom that this fork already fixed means the fix is somewhere else, not that
   the fix is missing.

## The upstream, and this fork

The upstream is `shirai91/nx2android`; the engine is `seedds/nxnative`. This fork
(`zFitness/nx2androidX`) is the product line: the phone app, the release line, and its own
core, which tracks the upstream's.

So an upstream case says three different things:

- **The diagnosis** - how the symptom was found and what it was. That is always worth
  having: the next game will show the same symptom.
- **The fix** - only worth having if this fork does not have it. The `fork` column says.
- **The way round** - how the upstream did something. This fork's own rules come first:
  this is an Android app, the engine's shared core stays shared, and a game-specific fact
  belongs in the profile.

A switch marked **upstream only** is in the upstream and not in this fork yet. The ones
that matter for a player right now:

| The switch | What it fixes | Upstream |
|---|---|---|
| `DM_VK_CUBE_WIDEN=1` | the water, the lakes and the rivers come out flat black | `#530` |
| `DM_VK_RUNTIME_SHADERS=1` (`runtime_shaders on`) | a game whose shaders it assembles at run time: the opening stays black until the game is ported a second time | `#505` |
| `DM_VK_POOL_INNERMOST=1` | a character that is never drawn, every triangle collapsed to a point | `#365` |
| `DM_VK_LIN_COPY_BACK=1` | a black portrait on the enrollment paper; the copy writes only the Vulkan image | `#451` |
| `DM_VK_UBO_COMPONENT=1` | jagged white steps on the hair's edges | `#451` |
| `DM_NVN_AHEAD=1` | a game that waits for the GPU never overlaps the replay and the GPU | `#438` |
| `DM_VK_ZEROCOPY_CHUNK_MB=512` | the library geometry missing in an intro montage | `#451` |

## The tool

- `memory_search.py` (in the tool tree, `$NX2A_REPO/tools/`) - the search. It reads the
  reference documents that ship with the app and the case files on this phone, and it
  builds its own index the first time it runs. No network.

```bash
python3 $NX2A_REPO/tools/memory_search.py search --symptom black --fork no
```

`--symptom` is one of `crash`, `black`, `garble`, `freeze`, `missing`, `build`, `memory`,
`shader`, `perf`, `audio`, `movie`, `feature`. `--layer` is one of `profile`, `shader`, `nvn`,
`tex`, `vk`, `host`, `rewriter`, `porter`, `app`, `android`, `audio`, `movie`, `perf`, `tools`,
`docs`, `other`. `--fork no` gives the cases whose fix is **not** in this fork: those are the ones
worth a port.

**A path under `devtools/`, `docs/` or `nxnative/docs/` is a path of the checkout.** The
phone carries the tool tree, not the documentation, so those files are not there: read what
the reference says about them, and ask the player for the file when the whole document
matters.

The tools that build and check this knowledge base are **not on the phone**: they live in the
repository, under `openspec/specs/port-failures/` (fetch the upstream, classify it, check
the citations). They are the maintainer's, not the assistant's.

## Never

- **Never change the code on the strength of this knowledge alone.** It is a map, not a
  verdict: read the log, find the evidence, then fix the one thing the evidence names.
- **Never try to update this knowledge base.** It is hand-written material. A case that is
  not in here goes into that game's case file; the knowledge base is refreshed by a person,
  on a computer, following `openspec/specs/port-failures/tasks.md`.
- **Never treat a switch that is not in this fork's registry as if it were there.** The
  registry is `nxnative/dm/settings.tsv`; a name with no row is logged as
  `[RED] setting ... is not in nxnative/dm/settings.tsv`.
- **Never put a game's own fact into the shared core.** A per-game branch in the core is
  never the answer: the game gets a profile key.
- **Never read or print `prod.keys`, and never read the game's files.** The profile, the
  logs and the dump's own directory are enough.
