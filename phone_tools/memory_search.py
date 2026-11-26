#!/usr/bin/env python3
"""The local search: one index over everything this phone knows, no network.

    python3 memory_search.py build  --index DIR --model DIR --public DIR --player DIR
    python3 memory_search.py search --index DIR --model DIR "the ground is flat grey"
    python3 memory_search.py search --index DIR --model DIR --corpus case "黑屏"
    python3 memory_search.py stats --index DIR

One index holds four corpora, each document carrying the number it came from:

    corpus  what it is                        the ref is
    pr      the upstream's pull requests       shirai91#574
    doc     the knowledge documents            runtime-symptoms.md · The shared fonts
    issue   the closed issues of both repos    zFitness/nx2androidX#88
    case    this phone's own case files        0100E8B028B54000

The ranking is the shape the experiments settled on 

    query
      |- lexical : BM25 over the documents, with the query expanded by a table
      |            of the words the corpus uses for the same thing
      |- semantic: an idf-weighted query vector against every chunk's vector,
      |            a document scores as its best chunk
      `- fuse    : the two rankings combined by RRF, lexical weighted 4:1

The model is optional. Without it the search is lexical only, which is what the
corpus wants anyway - see the honest boundaries in
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from array import array
from operator import mul
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory_embed import Model, tokenize  # noqa: E402

# ------------------------------------------------------------------ knobs ---

CHUNK_CHARS = 180          # a document is cut into chunks of about this size
BM25_K1 = 1.2
BM25_B = 0.75
RRF_K = 60                 # the constant everybody uses for RRF
# The lexical side is weighted four times the vector side: the lexical half
# carries this corpus - the teacher's own embeddings rank the held-out cases
# exactly as well as ours do (35/64 against BM25's 47/64) - so the vector side
# is a tie-breaker, not a co-equal partner.
RRF_WEIGHTS = (4.0, 1.0)

TOP_K = 5                  # hits listed
SUMMARY_CHARS = 220        # characters of a case summary
SNIPPET_LINES = 4          # lines of a document section
SNIPPET_CHARS = 400        # characters of a document section snippet
CASE_TOP = 12              # the case corpus is bigger; the answer stays capped

# ------------------------------------------------------- query expansion ---

# Words that carry no meaning in a query. They are not counted by the lexical
# side: a query full of them gave the wrong answer a higher score than the
# right one ("how do i read the backtrace" landed on a section with "how" in
# its heading).
#
# kb_search.py's list, plus the fillers that are fillers everywhere. "where" is
# NOT in it: the knowledge documents have a heading called "Where the fix
# belongs" and that word is the answer. "how" IS in it: dropping it was worth
# two questions on the documents' question bank and cost nothing anywhere else.
STOP = set(('the a an and or of in is are to at on for with as by be it its '
            'this that when then from not no you your we but if can will do '
            'does did has have had was were been they them their i me my our us '
            'what which who how there here too very').split())

# The word a query uses and the words the corpus uses for the same thing.
# Hand-written and small: it is the one thing a keyword index cannot do by
# itself, and it grows with the corpus rather than with the traffic.
ALIASES = {
    'audio': ('sound',), 'sound': ('audio',),
    'frozen': ('freeze', 'hang', 'stuck'), 'freeze': ('frozen', 'hang'),
    'hang': ('frozen', 'stuck'), 'stuck': ('stuck', 'stall'), 'stall': ('stuck',),
    'garbled': ('garbage', 'noise'), 'garbage': ('garbled',),
    'input': ('pad', 'touch', 'controller', 'joycon'), 'pad': ('input', 'touch'),
    'controller': ('pad', 'joycon', 'input'), 'touch': ('input', 'pad'),
    'vulkan': ('vk',), 'vk': ('vulkan',),
    'movie': ('video',), 'video': ('movie',),
    'font': ('glyph', 'typeface'), 'glyph': ('font',),
    'boot': ('start', 'launch'), 'launch': ('boot', 'start'),
    'killed': ('kill',), 'kill': ('killed',),
    'fps': ('frame', 'rate'), 'frame': ('fps',),
    'framerate': ('frame', 'rate'), 'framerates': ('frame', 'rate'),
    'lowfps': ('fps', 'frame', 'rate'), 'lowframerate': ('fps', 'frame', 'rate'),
    'stutter': ('jank',), 'jank': ('stutter',),
    'crash': ('crashes', 'crashed', 'sigsegv', 'sigill'),
    'driver': ('turnip',), 'turnip': ('driver',),
    'dlc': ('aoc', 'addon'), 'aoc': ('dlc', 'addon'),
    'shader': ('shaders', 'spirv'), 'compile': ('build',),
    'memory': ('lmk',), 'lmk': ('memory',),
    'install': ('apk',), 'apk': ('install',),
    'black': ('screen',),
    'question': ('marks', 'glyph', 'font'), 'marks': ('question',),
    'icons': ('icon', 'button'), 'draws': ('draw', 'drawn'), 'drawn': ('draws',),
}

# The words a player uses and the words every corpus uses. The table above is
# for the knowledge documents only (it was measured against them); these are
# the ones the corpus of pull requests and issues needs too: the player says
# "the controls do not respond", the upstream says "the controller".
ALIASES_ALL = {
    'lag': ('stutter', 'jank'), 'laggy': ('stutter', 'jank'),
    'lags': ('stutter', 'jank'), 'lagging': ('stutter', 'jank'),
    'gamepad': ('pad', 'controller', 'joycon', 'input'),
    'gyro': ('gyroscope', 'sensor'), 'gyroscope': ('gyro', 'sensor'),
    'control': ('controller', 'pad', 'input', 'button'),
    'controls': ('controller', 'pad', 'input', 'button'),
    'capped': ('pin', 'fps'), 'cap': ('pin', 'fps'),
    'rumble': ('vibration', 'controller'), 'vibration': ('rumble',),
    'vsync': ('sync',),
    'start': ('boot', 'launch'), 'started': ('boot', 'launch'),
    # the same word in another form: the tables above are keyed by the root,
    # so a query that spells the other form ("freezes" for "freeze") reached
    # nothing at all. A stemmer would do this generically, but it decides the
    # ranking on its own and cost the measured numbers three questions - the
    # hint's weight keeps the original word in charge.
    'freezes': ('freeze',), 'freezing': ('freeze',),
    'hangs': ('hang',), 'hanging': ('hang',), 'hung': ('hang',),
    'stutters': ('stutter',), 'stuttering': ('stutter',),
    'crashes': ('crash',), 'crashing': ('crash',),
    'fails': ('fail',), 'failed': ('fail',), 'failing': ('fail',),
    'failure': ('fail',),
    'boots': ('boot',), 'booting': ('boot',),
    'glitches': ('glitch',), 'corrupted': ('corrupt',),
    'errors': ('error',), 'shows': ('show',), 'showing': ('show',), 'shown': ('show',),
    'works': ('work',), 'working': ('work',),
    'runs': ('run',), 'running': ('run',),
    'stops': ('stop',), 'stopped': ('stop',),
    'misses': ('miss',), 'missing': ('miss',),
}

# The same table for the language the player writes in. The Chinese terms are
# matched in the raw text (the tokenizer splits them into single characters),
# and they only carry the query over to the words the corpus is written in.
# The real fix for a chinese question is the assistant rewriting it - this is
# the cheap floor under that.
CJK_ALIASES = {
    '黑屏': ('black', 'screen'), '全黑': ('black', 'screen'), '黑': ('black',),
    '崩溃': ('crash',), '闪退': ('crash',),
    '卡死': ('freeze', 'hang', 'stuck'), '卡住': ('freeze', 'hang'),
    '掉帧': ('fps', 'frame', 'stutter'), '卡顿': ('stutter', 'jank'),
    '字体': ('font', 'glyph'), '乱码': ('garbled', 'garbage'),
    '着色器': ('shader',), '构建': ('build',), '编译': ('compile', 'build'),
    '手柄': ('pad', 'controller', 'joycon'), '按键': ('input', 'button'),
    '内存': ('memory',), '显存': ('vulkan', 'gpu'), '驱动': ('driver', 'turnip'),
    '存档': ('save',), '进度': ('save',), '游戏': ('game',),
    '安装': ('install',), '安装包': ('apk',),
    '声音': ('audio', 'sound'), '没声音': ('audio', 'sound'),
    '无声': ('audio', 'sound'), '音频': ('audio', 'sound'),
    '卡': ('stutter', 'jank'), '花屏': ('garbled', 'garbage', 'screen'),
    '锁帧': ('fps', 'frame', 'pin'), '帧数': ('fps', 'frame', 'rate'),
    '贴图': ('texture',), '启动': ('boot', 'launch'),
    '震动': ('rumble', 'vibration'), '分辨率': ('resolution',),
    '触摸': ('touch', 'input'), '陀螺仪': ('gyroscope', 'gyro'),
}


ALIAS_WEIGHT = 0.35         # the expansion is a hint, not the question
TITLE_BONUS = 1.5           # a word in the heading counts more


def expand_query(query: str) -> tuple[list[str], list[str], list[str]]:
    """The query's words, in three groups.

    (own, bridge, english)

    * own    - the words the query uses. They carry the full weight.
    * bridge - the chinese words the corpus is written in. They apply to every
      corpus: the corpus is in english and the player asks in chinese.
    * english- the words the knowledge documents use for the same thing ("the
      question marks" are "the glyphs"). That table was written against those
      documents, so it applies to them only - on the case corpus it traded one
      real issue title for one synthetic one, which is not worth it.
    """
    tokens = tokenize(query.lower())
    seen = set(tokens)
    own = list(tokens)
    bridge: list[str] = []
    english: list[str] = []
    for word in set(tokens):
        for alt in ALIASES.get(word, ()):
            if alt not in seen:
                seen.add(alt)
                english.append(alt)
        for alt in ALIASES_ALL.get(word, ()):
            if alt not in seen:
                seen.add(alt)
                bridge.append(alt)
    text = query.lower()
    for word, alts in CJK_ALIASES.items():
        if word in text:
            for alt in alts:
                if alt not in seen:
                    seen.add(alt)
                    bridge.append(alt)
    return own, bridge, english


def query_terms(query: str, use_english: bool = False) -> list[tuple[str, float]]:
    """The query's terms with their weights, for the scorer."""
    own, bridge, english = expand_query(query)
    terms = [(t, 1.0) for t in own]
    terms += [(t, ALIAS_WEIGHT) for t in bridge]
    if use_english:
        terms += [(t, ALIAS_WEIGHT) for t in english]
    return terms


# ----------------------------------------------------------------- chunks ---


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """A document, cut into pieces small enough that one of them can match.

    The cuts are made on line boundaries: a chunk is a few whole lines, and a
    single very long line becomes a chunk of its own (capped at 400 chars).
    The evaluation script imports this function, so the shape that was
    measured is the shape that ships.
    """
    out: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("#") or len(line) > 400:
            if current:
                out.append("\n".join(current))
                current = []
            out.append(line[:400])
            continue
        current.append(line)
        if sum(len(x) for x in current) > limit:
            out.append("\n".join(current))
            current = []
    if current:
        out.append("\n".join(current))
    out = [c for c in out if len(c) > 20]
    return out or [text[:400]]


# --------------------------------------------------------------- documents ---


class Document:
    """One thing to find: a case section, a pull request, an issue, a doc."""

    __slots__ = ("id", "ref", "src", "corpus", "title", "text", "meta",
                 "chunks", "tf", "length", "title_tf", "df_all")

    def __init__(self, id_: int, ref: str, src: str, corpus: str, title: str,
                 text: str, meta: dict | None = None):
        self.id = id_
        self.ref = ref
        self.src = src
        self.corpus = corpus
        self.title = title
        self.text = text
        self.meta = meta or {}
        self.chunks: list[str] = []
        self.tf: dict[str, int] = {}
        self.length = 0
        self.title_tf: dict[str, int] = {}
        self.df_all = 0

    def prepare(self) -> None:
        """The token counts and the chunks - what the scoring needs.

        Two token lists: the model's own (every token, the vocabulary's rules)
        and the lexical one (the content words only - the stop words are what
        made a query full of filler decide the ranking).
        """
        counts: dict[str, int] = {}
        for token in tokenize(self.text.lower()):
            counts[token] = counts.get(token, 0) + 1
        self.tf = counts
        content = {t: c for t, c in counts.items() if t not in STOP}
        self.length = max(1, sum(content.values()))
        self.chunks = chunk_text(self.text)
        # the title's own words: the documents are organised by their headings,
        # and a heading that holds the query's word is what the reader wants
        self.title_tf = {t: 1 for t in tokenize(self.title.lower()) if t not in STOP}

    def matches(self, filters: dict) -> bool:
        """The field filters: a value the document holds (a field may hold several)."""
        for field, wanted in filters.items():
            if not wanted:
                continue
            if field == "corpus":
                if self.corpus != wanted:
                    return False
                continue
            held = str(self.meta.get(field, ""))
            if wanted.lower() not in [p.strip().lower()
                                      for p in held.split(",")]:
                return False
        return True


def read_case_index(path: Path) -> list[dict]:
    """The upstream pull requests: one document per row."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    out = []
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        title = (row.get("title") or "").strip()
        summary = (row.get("summary") or "").strip()
        if not title or not summary:
            continue
        source = (row.get("source") or "").strip() or "shirai91"
        ref = (row.get("ref") or "").strip()
        meta = {k: (row.get(k) or "").strip() for k in
                ("state", "area", "symptom", "layer", "kind", "fork", "source", "game")}
        meta["url"] = (row.get("url") or "").strip()
        # the searchable text: the title and the summary, plus the taxonomy the
        # search can filter on - the symptom ("crash", "black", "freeze") is a
        # word the player uses and the row carries
        parts = [title, summary]
        for field in ("symptom", "layer", "area", "game"):
            if meta.get(field):
                parts.append(meta[field])
        out.append({
            "ref": f"{source}#{ref}" if ref else source,
            "src": meta["url"] or str(path),
            "corpus": "pr",
            "title": title,
            "text": "\n".join(parts).strip(),
            "meta": meta,
        })
    return out


def read_issues(path: Path) -> list[dict]:
    """The closed issues of the two repositories: one document per issue."""
    out = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = (row.get("title") or "").strip()
        if not title:
            continue
        body = (row.get("body") or "").strip()
        resolution = (row.get("resolution") or "").strip()
        repo = (row.get("repo") or "").split("/")[-1]
        number = row.get("number", "?")
        out.append({
            "ref": f"{repo}#{number}",
            "src": (row.get("url") or "").strip() or str(path),
            "corpus": "issue",
            "title": title,
            "text": f"{title}\n{body}\n{resolution}".strip(),
            "meta": {"repo": repo, "state": row.get("state", ""),
                     "lang": row.get("lang", ""), "url": (row.get("url") or "").strip()},
        })
    return out


# The problem entry of a case file: "### 2026-11-23 the crash (status: fixed)". The stage of the
# port's life may follow it in brackets ("### ... (status: fixed) [stage 2]") - it is still an
# entry, and it still carries its fields.
ENTRY = re.compile(r'^###\s+(?P<title>.+?)\s*\((?P<status>status:[^)]*)\)\s*(?:\[[^\]]*\])?\s*$')
# The fields of an entry.
FIELDS = {
    "symptom": ("Symptom:",),
    "cause": ("Cause:",),
    "fix": ("Proposed fix:", "Fix:"),
    "evidence": ("Evidence:",),
}


def read_sections(path: Path, ref: str | None = None, corpus: str = "doc") -> list[dict]:
    """A markdown file, one document per heading section.

    A heading and the body under it are one document, and the heading stays
    part of the text: in the player's own notes the heading IS the symptom.
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    out: list[dict] = []
    title = ""
    start = 0
    body: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("#"):
            if body and title:
                out.append(_section(path, ref, corpus, title, body, start, i))
            body, title, start = [], line.strip(), i + 1
            continue
        body.append(line)
    if body and title:
        out.append(_section(path, ref, corpus, title, body, start, len(lines)))
    return [s for s in out if len(s["title"]) + len(s["text"]) > 40]


def _section(path: Path, ref: str | None, corpus: str, title: str,
             body: list[str], start: int, end: int) -> dict:
    """One section: its text, its place in the file, and the fields of an entry."""
    text = "\n".join(body).strip()
    meta = {"doc": path.name, "section": title, "lines": f"{start + 1}-{end}"}
    # a problem entry carries its fields; they are what the answer should show
    entry = ENTRY.match(title)
    if entry:
        meta["status"] = entry.group("status").replace("status:", "").strip()
        meta["title"] = entry.group("title").strip()
        holding = None
        for raw in body:
            line = raw.strip()
            for field, prefixes in FIELDS.items():
                if any(line.startswith(p) for p in prefixes):
                    meta[field] = line.split(":", 1)[1].strip() if ":" in line else ""
                    holding = field
                    break
            else:
                if holding and line and not meta.get(holding):
                    meta[holding] = line
                elif holding and line:
                    meta[holding] = meta[holding] + " " + line
    return {
        "ref": ref or path.stem,
        "src": f"{path}:{meta['lines']}",
        "corpus": corpus,
        "title": title,
        "text": f"{title}\n{text}".strip(),
        "meta": meta,
    }


def read_case_file(path: Path) -> list[dict]:
    """A player's case file: one document per section, the entries structured.

    The ref is the title id: the assistant needs to know which game the case
    is about, and the directory is what carries it.
    """
    out = []
    game = ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("# ") and not game:
            head = line[2:].strip()
            match = re.match(r"^(?P<name>.+?)\s*\((?P<id>[0-9A-Fa-f]{16})\)\s*case file", head)
            game = match.group("name").strip() if match else head
            break
    for section in read_sections(path, ref=path.parent.name, corpus="case"):
        section["meta"]["game"] = game
        section["meta"]["title_id"] = path.parent.name
        out.append(section)
    return out


# ------------------------------------------------------------- the layout ---

# Where things live on the phone. The assistant should not have to spell these
# out: the search is one command.
NX2A_HOME = os.environ.get("NX2A_HOME", "")


def default_index() -> Path:
    return Path(NX2A_HOME or ".") / "memory-index"


def default_public() -> Path | None:
    """The knowledge documents and the case index, where the skill puts them."""
    candidates = []
    if NX2A_HOME:
        candidates.append(Path(NX2A_HOME) / "agent/.agents/skills/port-failures/references")
        candidates.append(Path(NX2A_HOME) / "agent/dot-agents/skills/port-failures/references")
    here = Path(__file__).resolve().parent
    candidates.append(here.parent.parent / "android/app/src/main/assets/nx2a/agent/"
                      "dot-agents/skills/port-failures/references")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def default_issues() -> list[Path]:
    """The closed issues of the two repositories, if they were shipped."""
    candidates = []
    if NX2A_HOME:
        candidates.append(Path(NX2A_HOME) / "agent/.agents/skills/port-failures/references/issues")
        candidates.append(Path(NX2A_HOME) / "agent/dot-agents/skills/port-failures/references/issues")
    here = Path(__file__).resolve().parent
    candidates.append(here.parent.parent / "android/app/src/main/assets/nx2a/agent/"
                      "dot-agents/skills/port-failures/references/issues")
    for candidate in candidates:
        if candidate.is_dir():
            return sorted(candidate.glob("*.jsonl"))
    return []


def default_model() -> Path | None:
    """The embedding model, if it was shipped. Without it the search is lexical."""
    candidates = []
    if NX2A_HOME:
        candidates.append(Path(NX2A_HOME) / "memory-embed")
    here = Path(__file__).resolve().parent
    candidates.append(here / "memory-embed")
    for candidate in candidates:
        if (candidate / "meta.json").is_file():
            return candidate
    return None


# ------------------------------------------------------------------ index ---


class Index:
    """The built index: the documents, their tokens, their chunk vectors."""

    def __init__(self, model: Model | None):
        self.model = model
        self.docs: list[Document] = []
        self.df: dict[str, int] = {}
        self.df_all: dict[str, int] = {}
        self.avg_length = 1.0
        self.vectors = array("b")
        self.chunk_doc: list[int] = []
        self.fingerprint: dict[str, float] = {}

    # ---- building ----

    def add(self, spec: dict) -> None:
        text = spec.get("text", "").strip()
        if len(text) < 40:
            return
        doc = Document(len(self.docs), spec.get("ref", ""), spec.get("src", ""),
                       spec.get("corpus", "doc"), spec.get("title", ""), text,
                       spec.get("meta"))
        doc.prepare()
        if not doc.tf:
            return
        self.docs.append(doc)

    def encode_chunks(self) -> None:
        """Every chunk of every document gets its vector."""
        if self.model is None:
            return
        scale = self.model.scale
        dims = self.model.dims
        vectors = array("b")
        for doc in self.docs:
            for chunk in doc.chunks:
                vector = self.model.encode(chunk)
                for value in vector:
                    quantized = int(round(value * scale))
                    vectors.append(max(-127, min(127, quantized)))
                self.chunk_doc.append(doc.id)
        self.vectors = vectors

    def finish(self) -> None:
        """The document frequency and the average length.

        Two of them: the content words carry the lexical idf, and every token
        carries the vector's idf (a stop word is rare in the content words and
        would otherwise look important).
        """
        df: dict[str, int] = {}
        df_all: dict[str, int] = {}
        for doc in self.docs:
            for token in doc.tf:
                df[token] = df.get(token, 0) + 1
            for token in tokenize(doc.text.lower()):
                df_all[token] = df_all.get(token, 0) + 1
        self.df = df
        self.df_all = df_all
        total = sum(doc.length for doc in self.docs)
        self.avg_length = max(1.0, total / max(1, len(self.docs)))

    # ---- storing ----

    def save(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        header = {
            "docs": [{"id": d.id, "ref": d.ref, "src": d.src, "corpus": d.corpus,
                      "title": d.title, "text": d.text, "meta": d.meta,
                      "chunks": d.chunks, "tf": d.tf, "length": d.length}
                     for d in self.docs],
            "df": self.df,
            "df_all": self.df_all,
            "avg_length": self.avg_length,
            "chunk_doc": self.chunk_doc,
            "dims": self.model.dims if self.model else 0,
            "scale": self.model.scale if self.model else 127.0,
            "fingerprint": self.fingerprint,
            "sources": sorted(self.fingerprint),
            "model": bool(self.model),
        }
        # written to a temporary file and renamed: a search that finds the
        # index stale rebuilds it, and two of those at once must not leave a
        # half-written index behind
        write_atomic(out_dir / "index.json",
                     json.dumps(header, ensure_ascii=False).encode("utf-8"))
        write_atomic(out_dir / "vectors.bin", self.vectors.tobytes())

    @classmethod
    def load(cls, out_dir: Path, model: Model | None) -> "Index":
        index = cls(model)
        header = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
        for row in header["docs"]:
            doc = Document(row["id"], row["ref"], row["src"], row["corpus"],
                           row["title"], row["text"], row.get("meta"))
            doc.chunks = row["chunks"]
            doc.tf = row["tf"]
            doc.length = row["length"]
            index.docs.append(doc)
        index.df = header["df"]
        index.df_all = header.get("df_all", header["df"])
        index.avg_length = header["avg_length"]
        index.chunk_doc = header["chunk_doc"]
        index.fingerprint = header.get("fingerprint", {})
        index.vectors = array("b")
        index.vectors.frombytes((out_dir / "vectors.bin").read_bytes())
        return index

    # ---- searching ----

    def lexical_scores(self, query: str) -> list[float]:
        """BM25 over the documents (k1 1.2, b 0.75), with the query expanded.

        The english bridge is for the knowledge documents; the chinese bridge
        is for every corpus.
        """
        own, bridge, english = expand_query(query)
        own = [t for t in own if t not in STOP]
        scores = [0.0] * len(self.docs)
        n = len(self.docs)
        idfs: dict[str, float] = {}

        def idf_of(term: str) -> float:
            if term not in idfs:
                df = self.df.get(term, 0)
                idfs[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))
            return idfs[term]

        for doc in self.docs:
            terms = [(t, 1.0) for t in own]
            terms += [(t, ALIAS_WEIGHT) for t in bridge]
            if doc.corpus == "doc":
                terms += [(t, ALIAS_WEIGHT) for t in english]
            score = 0.0
            length = doc.length
            for term, weight in terms:
                frequency = doc.tf.get(term)
                if not frequency:
                    continue
                denominator = (frequency + BM25_K1 *
                               (1 - BM25_B + BM25_B * length / self.avg_length))
                score += weight * idf_of(term) * (frequency * (BM25_K1 + 1)) / denominator
                # a word in the heading counts more: the documents are organised
                # by their headings, and the long sections are the ones whose
                # heading says what they are about
                if term in doc.title_tf:
                    score += TITLE_BONUS * weight * idf_of(term)
            scores[doc.id] = score
        return scores

    def query_vector(self, query: str) -> list[float]:
        """The query as a vector, weighted by idf - the common words step aside."""
        if self.model is None:
            return []
        n = len(self.docs)
        acc = [0.0] * self.model.dims
        used = 0
        own, bridge, _ = expand_query(query)
        for token, weight in [(t, 1.0) for t in own] + [(t, ALIAS_WEIGHT) for t in bridge]:
            if token not in self.model.index:
                continue
            idf = math.log((n + 1) / (self.df_all.get(token, 0) + 1)) + 0.1
            if idf <= 0:
                continue
            row = self.model.row(token)
            if row is None:
                continue
            for d in range(self.model.dims):
                acc[d] += weight * idf * row[d]
            used += 1
        if not used:
            return acc
        norm = math.sqrt(sum(v * v for v in acc))
        return [v / norm for v in acc] if norm else acc

    def vector_scores(self, query: str) -> list[float]:
        """A document scores as its best chunk."""
        if self.model is None or not self.chunk_doc:
            return [0.0] * len(self.docs)
        qv = self.query_vector(query)
        if not any(qv):
            return [0.0] * len(self.docs)
        dims = self.model.dims
        scale = self.model.scale
        best = [0.0] * len(self.docs)
        raw = self.vectors
        for chunk_id, doc_id in enumerate(self.chunk_doc):
            base = chunk_id * dims
            row = raw[base:base + dims]
            # the row is int8: the real vector is row / scale
            score = sum(map(mul, row, qv)) / scale
            if score > best[doc_id]:
                best[doc_id] = score
        return best

    @staticmethod
    def ranks(scores: list[float]) -> list[int]:
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        ranks = [0] * len(scores)
        for position, index in enumerate(order):
            ranks[index] = position
        return ranks

    def search(self, query: str, top_k: int = TOP_K,
               filters: dict | None = None) -> tuple[list[dict], int]:
        """The two halves, fused by RRF with the lexical side weighted four times.

        The lexical half cuts the candidates: a document that holds no word of
        the query is not a candidate, however well its vectors happen to line up
        (the vectors are close to everything - they only say which of the
        candidates is closest).

        Returns the hits and how many documents matched in all.
        """
        candidates = [d for d in self.docs if d.matches(filters or {})]
        if not candidates:
            return [], 0
        lexical = self.lexical_scores(query)
        vector = self.vector_scores(query)
        candidates = [d for d in candidates if lexical[d.id] > 0]
        if not candidates:
            return [], 0
        rl = self.ranks(lexical)
        rv = self.ranks(vector)
        w_lex, w_vec = RRF_WEIGHTS
        scored = []
        for doc in candidates:
            fused = (w_lex / (RRF_K + rl[doc.id] + 1)
                     + w_vec / (RRF_K + rv[doc.id] + 1))
            scored.append((doc, fused))
        scored.sort(key=lambda pair: -pair[1])
        total = len(scored)
        hits = []
        for position, (doc, fused) in enumerate(scored[:top_k]):
            hits.append({
                "rank": position + 1,
                "ref": doc.ref,
                "src": doc.src,
                "corpus": doc.corpus,
                "title": doc.title,
                "meta": doc.meta,
                "score": round(fused, 6),
                "bm25": round(lexical[doc.id], 4),
                "vector": round(vector[doc.id], 4),
                "text": doc.text,
            })
        return hits, total

    def browse(self, filters: dict | None, top_k: int) -> tuple[list[dict], int]:
        """The documents a filter matches, without a question.

        "Every upstream PR about performance" is a question the filter
        answers on its own. The assistant asked for it exactly this way
        (search --symptom perf) and got nothing back - a filter without a
        question is a browse, not a failed search.
        """
        matched = [d for d in self.docs if d.matches(filters or {})]
        hits = []
        for doc in matched[:top_k]:
            hits.append({
                "rank": len(hits) + 1,
                "ref": doc.ref,
                "src": doc.src,
                "corpus": doc.corpus,
                "title": doc.title,
                "meta": doc.meta,
                "score": 0.0,
                "bm25": 0.0,
                "vector": 0.0,
                "text": doc.text,
            })
        return hits, len(matched)


# ------------------------------------------------------------------ output ---


def snippet_of(text: str, terms: list[str]) -> str:
    """The part of a document that answers the query.

    The first line that holds a word of the query, and what follows it. A table
    row can be a thousand characters long, so the snippet is cut at a cell
    boundary - a half row is readable, a half word is not.
    """
    wanted = set(terms)
    lines = text.splitlines()
    body = lines[1:] if lines else []      # the heading is the title, not the answer
    start = 0
    for i, line in enumerate(body):
        if wanted & set(tokenize(line.lower())):
            start = i
            break
    out = []
    used = 0
    for line in body[start:start + SNIPPET_LINES]:
        room = SNIPPET_CHARS - used
        if room <= 20:
            break
        if len(line) > room:
            cut = line[:room]
            bar = cut.rfind("|")
            line = (cut[:bar] + "| …" if bar > 20 else cut + " …")
        used += len(line) + 1
        out.append(line)
    return "\n".join(out)


def format_hit(hit: dict, terms: list[str]) -> list[str]:
    """One hit, in the shape a reader wants: where it is, what it is, why."""
    lines = [f"{hit['rank']}. {hit['ref']}  [{hit['corpus']}] {hit['title'][:110]}"]
    meta = hit.get("meta") or {}
    # a problem entry answers with its cause and its fix, not with its prose
    if meta.get("cause") or meta.get("fix"):
        if meta.get("symptom"):
            lines.append(f"   symptom: {meta['symptom'][:SUMMARY_CHARS]}")
        if meta.get("cause"):
            lines.append(f"   cause: {meta['cause'][:SUMMARY_CHARS]}")
        if meta.get("fix"):
            lines.append(f"   fix: {meta['fix'][:SUMMARY_CHARS]}")
        if meta.get("status"):
            lines.append(f"   status: {meta['status']}")
    else:
        body = hit["text"]
        if hit["corpus"] == "doc":
            piece = snippet_of(body, terms)
        else:
            # the title is already in the heading of the hit
            piece = "\n".join(body.splitlines()[1:])[:SUMMARY_CHARS]
        for line in piece.splitlines():
            lines.append(f"   {line}")
    where = hit["src"]
    if hit["corpus"] == "doc" and meta.get("lines"):
        where = f"{meta.get('doc', '')} lines {meta['lines']}"
    if where and where != hit["ref"]:
        lines.append(f"   at: {where}")
    return lines


def section_text(index: "Index", title: str) -> str:
    """One section as it is written, for the case where the snippet is not enough."""
    want = title.strip().lower()
    lines = []
    for doc in index.docs:
        if doc.corpus != "doc":
            continue
        if want not in doc.title.lower():
            continue
        heading = doc.title.lstrip("# ").strip()
        lines.append(f"{doc.meta.get('doc', '')} ## {heading} "
                     f"(lines {doc.meta.get('lines', '')})")
        lines.append("")
        lines.append(doc.text.split("\n", 1)[-1])
        lines.append("")
    if not lines:
        return f"(no section titled \"{title}\")"
    return "\n".join(lines)


def format_browse_hit(hit: dict) -> list[str]:
    """One document of a browse: what it is, and what it is about."""
    meta = hit.get("meta") or {}
    lines = [f"{hit['rank']}. {hit['ref']}  [{hit['corpus']}] {hit['title'][:110]}"]
    if meta.get("cause") or meta.get("fix"):
        # a case entry answers with its cause and its fix
        for field in ("symptom", "cause", "fix"):
            if meta.get(field):
                lines.append(f"   {field}: {meta[field][:SUMMARY_CHARS]}")
        if meta.get("status"):
            lines.append(f"   status: {meta['status']}")
    else:
        # the summary is the first line of the body; the taxonomy after it is
        # noise when the reader asked for the list, not for a ranking
        body = hit["text"].splitlines()
        if len(body) > 1:
            lines.append(f"   {body[1][:SUMMARY_CHARS]}")
        tags = [f"{k}={meta[k]}" for k in ("state", "symptom", "layer")
                if meta.get(k)]
        if tags:
            lines.append("   " + "  ".join(tags))
    if hit["src"] and hit["src"] != hit["ref"]:
        lines.append(f"   at: {hit['src']}")
    return lines


def format_browse(hits: list[dict], filters: dict, total: int) -> str:
    """The documents a filter matched, one per line, with where they live."""
    wanted = ", ".join(f"{k}={v}" for k, v in filters.items() if v)
    lines = [f"the documents that match {wanted}:", ""]
    for hit in hits:
        lines += format_browse_hit(hit)
        lines.append("")
    if total > len(hits):
        lines.append(f"({total} matched, {len(hits)} shown; -k asks for more)")
    return "\n".join(lines) + "\n"


def format_hits(query: str, hits: list[dict], corpus: str = "", total: int = 0) -> str:
    """The whole answer, capped: the corpus grows, the answer does not."""
    own, bridge, _ = expand_query(query)
    terms = list(own) + list(bridge)
    lines = []
    if hits:
        lines.append(f"searched the {corpus or 'local knowledge'} for: {query}")
        lines.append("")
    for hit in hits:
        lines += format_hit(hit, terms)
        lines.append("")
    if total > len(hits):
        lines.append(f"({total} matched, {len(hits)} shown; "
                     f"--corpus picks one corpus, -k asks for more)")
    if not hits:
        lines.append("(nothing found)")
        lines.append("")
        lines.append("the corpus may call it something else:")
        for hint in alias_hints(query):
            lines.append(f"  - {hint}")
        lines.append("  - the player asks in chinese and the corpus is in english: "
                     "rewrite the question in english technical words and ask again")
        lines.append("  - to see a whole corner of the corpus instead of one answer: "
                     "a filter alone lists what it matches (--corpus pr --symptom perf)")
    return "\n".join(lines).rstrip() + "\n"


def alias_hints(query: str, count: int = 4) -> list[str]:
    """When nothing matched: the words the corpus uses for the words the query used."""
    hints = []
    for token in tokenize(query.lower()):
        for table in (ALIASES, ALIASES_ALL):
            for alias in table.get(token, ()):
                hints.append(f'"{token}" is written "{alias}"')
    for word, alts in CJK_ALIASES.items():
        if word in query:
            hints.append(f'"{word}" is written "{alts[0]}"')
    return hints[:count]


# ------------------------------------------------------------------- build ---


def write_atomic(path: Path, data: bytes) -> None:
    """Write a file so that a reader sees either the old one or the new one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def fingerprint_of(paths: list[Path]) -> dict[str, float]:
    """When the sources last changed - the index is rebuilt when they do."""
    out = {}
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        out[str(path)] = stat.st_mtime
    return out


def source_files(public_dir: Path | None, issues: list[Path],
                 player_dir: Path | None) -> list[Path]:
    """Every file the index is built from."""
    out: list[Path] = []
    if public_dir and public_dir.is_dir():
        case_index = public_dir / "case-index.tsv"
        if case_index.is_file():
            out.append(case_index)
        out += sorted(public_dir.glob("*.md"))
    out += [p for p in issues if p.is_file()]
    if player_dir and player_dir.is_dir():
        out += sorted(player_dir.rglob("spec.md"))
        out += sorted(player_dir.rglob("local-cases.md"))
        out += sorted(player_dir.rglob("MEMORY.md"))
    return out


def collect_documents(public_dir: Path | None, issues: list[Path],
                      player_dir: Path | None) -> list[dict]:
    """Everything that can be found."""
    out: list[dict] = []
    if public_dir and public_dir.is_dir():
        case_index = public_dir / "case-index.tsv"
        if case_index.is_file():
            out += read_case_index(case_index)
        for path in sorted(public_dir.glob("*.md")):
            out += read_sections(path)
    for path in issues:
        out += read_issues(path)
    if player_dir and player_dir.is_dir():
        for path in sorted(player_dir.rglob("spec.md")):
            out += read_case_file(path)
        for path in sorted(player_dir.rglob("local-cases.md")):
            out += read_sections(path, ref="local-cases", corpus="case")
        for path in sorted(player_dir.rglob("MEMORY.md")):
            out += read_sections(path, ref="MEMORY", corpus="case")
    return out


def build(index_dir: Path, model_dir: Path | None, public_dir: Path | None,
          issues: list[Path], player_dir: Path | None) -> Index:
    model = Model(model_dir) if model_dir and (model_dir / "meta.json").is_file() else None
    index = Index(model)
    for spec in collect_documents(public_dir, issues, player_dir):
        index.add(spec)
    index.encode_chunks()
    index.finish()
    index.fingerprint = fingerprint_of(source_files(public_dir, issues, player_dir))
    index.save(index_dir)
    print(f"index: {len(index.docs)} documents, {len(index.chunk_doc)} chunks, "
          f"{len(index.df)} tokens"
          f"{'' if model else ' (no model: lexical only)'} -> {index_dir}")
    return index


def needs_rebuild(index_dir: Path, sources: list[Path]) -> bool:
    """The index is stale when a source file changed since it was built.

    The sources are the ones the index was built from, unless the caller named
    new ones - a search that says nothing about where the corpus is must not
    throw the index away.
    """
    try:
        header = json.loads((index_dir / "index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    old = header.get("fingerprint", {})
    if not sources:
        sources = [Path(p) for p in header.get("sources", [])]
    return old != fingerprint_of(sources)


# -------------------------------------------------------------------- cli ---

FILTERS = ("corpus", "symptom", "layer", "area", "kind", "fork", "source", "game")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="search",
                    help="build | search | stats (the default: search)")
    ap.add_argument("--index", default="", help="the index directory")
    ap.add_argument("--model", default="", help="the model directory (optional)")
    ap.add_argument("--public", default="", help="the public knowledge directory")
    ap.add_argument("--issues", default="", help="comma separated issue jsonl files")
    ap.add_argument("--player", default="", help="this phone's own directory")
    for name in FILTERS:
        ap.add_argument(f"--{name}", default="", help=f"only the documents with this {name}")
    ap.add_argument("-k", "--top-k", type=int, default=TOP_K)
    ap.add_argument("--json", action="store_true", help="print the hits as json")
    ap.add_argument("--section", default="", help="print the section with this title")
    ap.add_argument("query", nargs="*", help="the question")
    args = ap.parse_args()

    # The verb is optional: "memory_search.py 'black screen'" is a search.
    # (The old script took the question straight, and the assistant writes the
    # command it was told to write - a missing verb made every search fail
    # with a usage error on the first real session.)
    command = args.command
    if command not in ("build", "search", "stats"):
        args.query = [command] + list(args.query)
        command = "search"

    index_dir = Path(args.index) if args.index else default_index()
    model_dir = Path(args.model) if args.model else default_model()
    public_dir = Path(args.public) if args.public else default_public()
    issues = [Path(p) for p in args.issues.split(",") if p] or default_issues()
    player_dir = Path(args.player) if args.player else (Path(NX2A_HOME) if NX2A_HOME else None)
    filters = {name: getattr(args, name) for name in FILTERS}

    if command == "build":
        build(index_dir, model_dir, public_dir, issues, player_dir)
        return

    # A missing index is built once - there is nothing to search otherwise.
    # A stale one is rebuilt too: the sources it was built from changed (the app
    # updated its knowledge pack, a case was closed), and searching a stale
    # index quietly answers from the old documents. The notice goes to stdout,
    # not stderr: the caller pipes the output, and a warning on stderr is a
    # warning nobody reads.
    if not (index_dir / "index.json").is_file():
        print("index: there is none yet, building it (once)")
        build(index_dir, model_dir, public_dir, issues, player_dir)
    elif needs_rebuild(index_dir, source_files(public_dir, issues, player_dir)):
        print("index: the sources changed, rebuilding it")
        build(index_dir, model_dir, public_dir, issues, player_dir)

    model = None
    if model_dir and (model_dir / "meta.json").is_file():
        model = Model(model_dir)
    index = Index.load(index_dir, model)
    if command == "stats":
        print(f"documents: {len(index.docs)}  chunks: {len(index.chunk_doc)}  "
              f"tokens: {len(index.df)}  avg length: {index.avg_length:.1f}  "
              f"model: {'yes' if model else 'no (lexical only)'}")
        counts: dict[str, int] = {}
        for doc in index.docs:
            counts[doc.corpus] = counts.get(doc.corpus, 0) + 1
        print("corpora: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        return

    if args.section:
        print(section_text(index, args.section))
        return

    query = " ".join(args.query)
    top = CASE_TOP if filters.get("corpus") in ("pr", "issue") else args.top_k
    if not query:
        # A filter on its own is a question too: "every upstream PR about
        # performance" is answered by listing them. The notice goes to
        # stdout: the caller pipes the output, and a message on stderr is a
        # message nobody reads.
        if any(filters.values()):
            hits, total = index.browse(filters, top)
            if hits:
                if args.json:
                    print(json.dumps({"query": "", "count": total, "shown": len(hits),
                                      "hits": hits}, ensure_ascii=False, indent=2))
                else:
                    print(format_browse(hits, filters, total), end="")
                return
        print("nothing to search for: give a question, or a filter that matches "
              "something (--corpus pr --symptom perf lists the upstream's "
              "performance fixes)")
        return
    start = time.time()
    hits, total = index.search(query, top, filters)
    elapsed = (time.time() - start) * 1000
    if args.json:
        print(json.dumps({"query": query, "count": total, "shown": len(hits),
                          "hits": hits}, ensure_ascii=False, indent=2))
        return
    print(format_hits(query, hits, filters.get("corpus", ""), total), end="")
    print(f"({len(hits)} hits, {elapsed:.0f} ms)")


if __name__ == "__main__":
    main()
