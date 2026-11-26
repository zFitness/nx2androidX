---
name: card-unpack
description: Use it to unpack a card - an XCI or an NSP cartridge dump - into one NSP per title (the base game, its update, its DLCs), written into a folder next to the card itself. Also use it when the player asks to split a card, to take the base game or the update out of it, or to get a single file to port or to test.
---

# Unpacking a card: one NSP per title

The player says "unpack this card", "split the cartridge", or wants a single base game or
update to port or to test. Follow this.

## Use the tools, do not write your own script

- `python3 $NX2A_REPO/tools/card.py "<card>" --keys $NX2A_HOME/../prod.keys`: what is on
  the card (which titles, whether the update is merged in, what the porter makes of it).
  Read-only.
- `python3 $NX2A_REPO/tools/card_split.py "<card>"`: cut it into one NSP per title.
  **No second argument**: the tool puts them into `<card name>-<base title ID>/` next to
  the card. prod.keys defaults to $NX2A_HOME/../prod.keys.

Do not write the unpacker yourself: the script that used to live in a temporary directory
is not in the tool tree, so it is gone on the next phone, and it dies with the next change
of the card format.

Reading the game files themselves (what is in romfs and exefs) is another job - that is
nx_extract. The App does not need it to pick a file.

## Where the output goes, and what it is called (the rules)

- The output folder is **next to the card**: `<the card's folder>/<card name without its
  suffix>-<base title ID>/`.
  - Example: the card is `/storage/emulated/0/Download/Fire Emblem.xci` and the base title
    ID is `010055D009F78000`, so the output is
    `/storage/emulated/0/Download/Fire Emblem-010055D009F78000/`.
  - You do not have to work the folder out: card_split.py uses it when no output folder is
    given. If you pass a second argument, pass that one.
  - The title ID in the folder name is the **base game's** one: card.py's output says what
    each title in the card is (base / update / DLC), so read it off there instead of
    guessing. A card without a base game is named after the first title in it.
  - Why here: the card is where the player put the game and where the file picker can reach
    it, so the split files can be reached too. The App's file picker does not see the App's
    private folders (files/..., files/tmp, files/tmpwork, $TMPDIR); those are good for
    scratch work (intermediate products) and are deleted afterwards.
  - The library merges by title ID: the split NSPs are the same game as the card, so they
    do not add a second card to the library.
  - When two cards sit in the same folder, the base title ID keeps them apart: never let
    two cards share one output folder.
- Flat inside that folder, no subfolders: no "base/update/DLC" subfolders - the player
  asked for one level, so keep one level.
- **The split never lands in the card's own folder.** The output is a folder of its own
  beside the card - not the card's folder, and not a subfolder of it. A card and the NSPs
  cut out of it are read together by the porter, and the update is then lost (see below).
- The tool names the files: `<title ID>_base.nsp`, `<title ID>_update.nsp`,
  `<title ID>_dlc.nsp` (a DLC's number is in its title ID), anything else `_other.nsp`.
- **The update NSP needs its version in its name**: `<title ID>_update[v<N>].nsp`. The
  porter reads a version from the `[v<N>]` tag and from nowhere else, and the tool does not
  know the version - it cuts the card, it does not read the update's build. Without the tag
  the update is only taken when it is the one update in the folder, and it is then taken on
  the assumption that it is the newest version the profile registers (a guess the build ID
  check afterwards reports on: it says which registered patches a module of the wrong build
  lost). `<N>` is the Switch version number (`[v131072]`, not `[v1.1.1]`), and
  it is in the profile's `build` rows (`build v131072 1.1.1`). Renaming the file the tool
  wrote is allowed - it is the tool's own product - but do not guess the number: if the
  profile does not say which version the update is, say so and leave the tag off.
- Do not touch the player's card: no move, no rename, no deleting the original. The split
  reads it and writes beside it.

## The card after the split: it is a trap for the port

The split leaves the card where it was, and a card that was rebuilt with the update inside
(1G+1U+1D) is read by the porter as **an untagged update** - it carries the update's title -
and it can even be taken as the base game of the folder.

The porter reads the folder the player selects for the build **and its first-level
subfolders** as one game. So:

- The card must not be in that folder, and not in one of its subfolders. It may sit beside
  it - but then the player has to select the split folder itself, not the folder above it.
- Card and split NSPs read together make two untagged updates: the porter leaves both out,
  says `leaving out update NSPs without a version tag`, and the build page shows **v0
  only**. The update is not ported - the port is of the old version, silently.
- After a successful split, tell the player that the card has to leave the folder the game
  is read from, and where it went. Moving the card is the player's call: ask before you
  move it, and never delete it on your own - it is their file, and a card is the only copy
  of some dumps.
- The folder the player selects should hold one base game, the tagged update and the DLCs.
  Then the build page shows every version the folder holds.

## Space

- The split NSPs together are about the size of the card (a 13 GB card needs 13 GB of
  room). Look before writing: `df -h "<the card's folder>" | tail -1`.
- The tool does the arithmetic itself: if there is not enough room it says so in one line
  and writes nothing.
- If the room is short, say so plainly. Do not delete the player's things to make space.

## When it is done

- Tell the player the name and the size of every NSP, and which folder they are in (the
  folder is next to the card, so one sentence is enough).
- Delete the intermediate products (the unpacked romfs, the listings, the temporary
  folders) unless the player wants them kept.
