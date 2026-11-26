#!/usr/bin/env python3
"""The static embedding model on the phone: a lookup table, no numpy, no tokenizers.

The model is a token -> vector table (distilled from a sentence-transformer and
fine-tuned on this project's own cases). Encoding a text is: split it into the
tokens the table knows, look their rows up, weight them, average, normalize.

The artifact is three files next to each other:

    embed.bin    a json header line, then the int8 rows, then the float32
                 per-token weights
    vocab.txt    one token per line; the line number is the row number
    meta.json    what the model is (dims, teacher, when it was trained)

Everything here is plain python on purpose: the phone has no numpy, and this
runs on every query.

    python3 memory_embed.py --model DIR "some query"      # prints the vector
    python3 memory_embed.py --model DIR --check            # self-test
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from array import array
from pathlib import Path

# The same rules the model's vocabulary was built with: words (lower-cased),
# identifiers split on their camel humps, and CJK characters one by one.
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]{2,}|[0-9]+")
CJK = re.compile(r"[㐀-鿿豈-﫿]")


def tokenize(text: str) -> list[str]:
    """The tokens of a text, in order."""
    out: list[str] = []
    for word in WORD.findall(text):
        out.append(word.lower())
        parts = CAMEL.findall(word)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
    out.extend(CJK.findall(text))
    return out


class Model:
    """The static embedding table."""

    def __init__(self, model_dir: Path):
        self.dir = Path(model_dir)
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.tokens = (self.dir / "vocab.txt").read_text(encoding="utf-8").split("\n")
        if self.tokens and self.tokens[-1] == "":
            self.tokens.pop()
        self.index = {t: i for i, t in enumerate(self.tokens)}
        self._load_embed()

    def _load_embed(self) -> None:
        raw = (self.dir / "embed.bin").read_bytes()
        nl = raw.index(b"\n")
        header = json.loads(raw[:nl].decode("utf-8"))
        self.dims = int(header["dims"])
        self.rows = int(header["rows"])
        self.scale = float(header.get("scale", 127.0))
        start = nl + 1
        # signed bytes: the array module reads them as int8, bytes would read
        # them as 0..255 and every negative value would come out wrong
        self.vectors = array('b', raw[start:start + self.rows * self.dims])

    def encode(self, text: str) -> list[float]:
        """The vector of a text: the mean of its tokens' rows, then unit length."""
        acc = [0.0] * self.dims
        used = 0
        for token in tokenize(text):
            row = self.index.get(token)
            if row is None:
                continue
            base = row * self.dims
            for d in range(self.dims):
                acc[d] += self.vectors[base + d]
            used += 1
        if used == 0:
            return [0.0] * self.dims
        # the rows are int8: scale them back, average them, then normalize
        factor = 1.0 / (self.scale * used)
        acc = [v * factor for v in acc]
        norm = math.sqrt(sum(v * v for v in acc))
        if norm == 0.0:
            return acc
        return [v / norm for v in acc]

    def row(self, token: str) -> list[float] | None:
        row = self.index.get(token)
        if row is None:
            return None
        base = row * self.dims
        return [v / self.scale for v in self.vectors[base:base + self.dims]]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="the model's directory")
    ap.add_argument("text", nargs="*", help="the text to encode")
    ap.add_argument("--check", action="store_true", help="self-test")
    ap.add_argument("--json", action="store_true", help="print the vector as json")
    args = ap.parse_args()

    model = Model(Path(args.model))
    if args.check:
        print(f"tokens: {len(model.tokens)}  dims: {model.dims}  rows: {model.rows}")
        for probe in ("the ground is flat grey", "地面一片平灰", "cull_visibility"):
            vector = model.encode(probe)
            norm = math.sqrt(sum(v * v for v in vector))
            print(f"  {probe!r:28s} -> {len(vector)} dims, norm {norm:.3f}")
        return
    text = " ".join(args.text)
    vector = model.encode(text)
    if args.json:
        print(json.dumps({"text": text, "dims": len(vector),
                          "vector": [round(v, 6) for v in vector]}))
        return
    print(json.dumps([round(v, 6) for v in vector]))


if __name__ == "__main__":
    main()
