#!/usr/bin/env python3
"""Is the model that was fetched any good? A smoke check, not an evaluation.

    python3 devtools/check_memory_model.py
    python3 devtools/check_memory_model.py --model .memembed/memory-embed

The full evaluation lives in the model repository (zFitness/nx2-memory):
five question sets, and a gate that says the tool and the evaluation agree.
That needs the training corpus and the question banks, so it does not belong
in the app's repository.

What belongs here is the check the app's build needs: **is this file a
working model?** It loads the artifact with the phone's own encoder
(phone_tools/memory_embed.py - the code that runs on the phone) and asks two
questions whose answers are known:

* two english sentences that mean the same thing must be close (the model
  learned the meaning);
* a chinese sentence and its english twin must NOT be close (the bridge
  between the languages is broken - that is why the assistant rewrites the
  player's question before searching; ).

A model that fails these is not this model: it is a truncated download, a
different artifact, or a file that was swapped.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "phone_tools"))

from memory_embed import Model, cosine  # noqa: E402

DEFAULT_MODEL = REPO / ".memembed" / "memory-embed"

# (text a, text b, the lowest cosine that still means "the model works")
CHECKS = (
    ("the ground is flat grey", "the land is one flat grey tone", 0.60),
    ("the shader split finds no shaders", "the shaders are not in the bundle", 0.45),
    ("地面一片平灰", "the ground is flat grey", 0.20),   # must stay below
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=str(DEFAULT_MODEL),
                    help="the model directory")
    args = ap.parse_args()
    model_dir = Path(args.model)

    meta_path = model_dir / "meta.json"
    if not meta_path.is_file():
        raise SystemExit(f"no model in {model_dir}\n"
                         "  fetch it: python3 devtools/fetch_memory_model.py")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    print(f"model: {model_dir}")
    print(f"  version {meta.get('version')!r}, rows {meta.get('rows')}, "
          f"dims {meta.get('dims')}, quantized {meta.get('quantized')}")
    print(f"  teacher {meta.get('teacher')}, source {meta.get('source_commit', '')[:12]}, "
          f"{meta.get('pairs', '?')} pairs")

    model = Model(model_dir)
    failures = 0
    for a, b, limit in CHECKS:
        value = cosine(model.encode(a), model.encode(b))
        # the chinese pair must stay far: the table says "below the limit"
        below = limit if a == "地面一片平灰" else None
        if below is not None:
            ok = value < below
            print(f"  {'ok ' if ok else 'BAD'} cos({a!r}, {b!r}) = {value:+.3f} "
                  f"(must stay below {below})")
        else:
            ok = value >= limit
            print(f"  {'ok ' if ok else 'BAD'} cos({a!r}, {b!r}) = {value:+.3f} "
                  f"(must be at least {limit})")
        failures += 0 if ok else 1

    if failures:
        print(f"\n{failures} check(s) failed - this is not the model we published")
        raise SystemExit(1)
    print("\nthe model is the one we published")


if __name__ == "__main__":
    main()
