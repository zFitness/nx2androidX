# The closed issues of the two repositories

One json per repository, one issue per line. The upstream (`shirai91-nx2android`) is the
desktop tool, this fork (`zFitness/nx2androidX`) is the phone app; both trackers carry what a
port broke and how it was put right. The issues of this fork are the ones only it has, and
the player writes them in chinese.

What is scrubbed away before a line is written: who wrote it (the author login is never
stored), the mail addresses, the phone numbers, the links to people's profiles, the log dumps
longer than a screen and the issue template's own text. What is kept: the issue number, the
title, the body, the closing replies, the language and the url.

The search reads them as one more corpus (`memory_search.py search --corpus issue`), and every hit
carries the issue number, so the answer can point at the tracker.

**These are a snapshot.** To refresh them, use the model repository (`zFitness/nx2-memory`,
private): its `train/fetch_issues.py` fetches, scrubs and classifies the issues, and
`train/train_memory_embed.py` mines the training pairs from them.

```bash
cd ../nx2-memory
.venv/bin/python train/fetch_issues.py --fetch --dedupe --report
cp .memembed/corpus/issues/*.jsonl \
   ../nx2android/android/app/src/main/assets/nx2a/agent/dot-agents/skills/port-failures/references/issues/
```

The script also writes `twins.md` (the cross-repo pairs, the same problem in two languages)
and `desktop.md` (the upstream issues about the desktop shell - they are not about the phone
and they are not in the index).
