# TLR Save Editor

A save editor for **The Last Remnant Remastered**, built from scratch through
reverse-engineering of the `.sav` file format. Includes a cross-platform
tkinter GUI (`TLR_Save_Editor.py`, with a built-in Ukrainian/English language
toggle) and a command-line tool (`save_explorer.py`).

## Features

- **Gold & Battle Rank** — view and edit current gold, lifetime gold, and the
  real Battle Rank (with its EXP counter and load-screen display cache all
  kept in sync).
- **Playtime, Mr. Diggs, monster kills** — editable fields, all confirmed
  against real gameplay.
- **Union editor** — edit stats, leader, and full member roster (slots 1–5)
  for all **8** union slots (the game engine supports more than the 5 shown
  in the default UI), including activating previously-empty union slots.
- **Inventory editor** — grant, edit quantities, and edit stats for
  Equipment, Accessories, Consumables, Components, Captured Monsters, and
  Special Items, including in-place editing of already-equipped items.
- **Save info panel** — a consolidated view of gold, Battle Rank, playtime,
  Mr. Diggs attempts, monster kills, per-union stats, and inventory counts.
- **Checksum handling** — every save is automatically re-signed with the
  correct SHA1 checksum, so edited saves load without errors.
- **Search & diff tools** (CLI) — search for a value anywhere in a save, or
  diff two saves to find what changed between them.

## Why this exists

The Remastered `.sav` format isn't documented anywhere. Every field in this
tool — gold, Battle Rank, playtime, Mr. Diggs attempts, monster kills, the
union/roster structures, equipment tables — was found using a controlled-diff
method: make one precise, known change in-game, save before and after, diff
the two files byte-by-byte, and confirm the hypothesis against multiple
independent saves before trusting it. Every field listed above has been
verified in real gameplay, not just in theory.

## How the save format works

- The `.sav` file is a **plain zlib stream** (signature `78 DA`) — no
  container or footer. `zlib.decompress()` unpacks it in one call.
- All saves examined so far decompress to the same fixed size:
  **1,719,936 bytes**.
- Integrity check: `SHA1(dec[0x20:])` is written to `dec[0x0C:0x20]`. Both
  tools recompute this automatically on every save, so edited files load
  without a "corrupted data" error.

| offset | size | contents |
|---|---|---|
| `0x00` | 4 bytes | ASCII `"SAVE"` (magic signature) |
| `0x04` | int32 | format version (`= 1`) |
| `0x08` | int32 | decompressed size |
| `0x0C` | 20 bytes | SHA1 checksum of everything from `0x20` onward |
| `0x20` | 8 bytes | save timestamp fields |
| `0x28` | int16 | Battle Rank display cache (load screen only) |
| `0x30` | UTF-16 string | current location |

Selected confirmed fields:

| Field | Offset | Notes |
|---|---|---|
| Gold | `0x1D978` | int32 LE |
| Lifetime gold | `0x25A5A` | tracks in sync with Gold |
| Battle Rank | `0x259DD` | int16 LE |
| Battle Rank EXP | `0x259DF` | int16 LE, 0–499, rank increases every 500 |
| Playtime | `0x04F4C` | int32 LE, seconds |
| Mr. Diggs attempts | `0x4F5C` | int32 LE |
| Mr. Diggs max attempts | `0x4F60` | int32 LE |
| Monster kills | `0x1D2DA` | uint16 LE |
| Union records | `0x025C82`, stride `0x54`, 8 unions | HP/AP/stats + leader + 4 member slots per union |
| Inventory table | `~0x209E8` | 12-byte records: slot index, item ID, quantity |

Full technical notes and additional CLI commands (search, diff, dump,
pack/repack, checksum fix) are in [`save_explorer.py`](save_explorer.py)'s
`--help` output and inline comments in both scripts.

## Reference data files

`EquipItems.csv`, `AccItems.csv`, `Items.csv`, and `Chars.csv` translate raw
item/character IDs into readable names. These originate from a community
package for the **original PC release** of The Last Remnant (a memory
trainer called "RemnantTrainer" and its supporting files), with credit for
the underlying research going to several community contributors: lothrandier,
saeri, sage_inferno, TheHologramMan, VoxAngel, helodermatid, jesse_n,
hlvietlong, artennoir, SunS_MMX, suttyo, BR_Gamer, mikeyakame, and Samsong69.

Two caveats when using these against a **Remastered** save:

- The CSVs' own `Offset` column refers to the *original PC* game's memory
  layout and does not apply to Remastered's save-file offsets. Only the row
  order of `Items.csv` is used (it maps to Remastered's item table by row
  index) — every offset used by this tool was independently reverse-engineered.
- Equipment/accessory ID mappings were cross-checked against real equipped
  items in actual Remastered saves before being trusted.

## Installation & usage

Requires Python 3 with tkinter (bundled with the standard installer from
[python.org](https://www.python.org/downloads/) on macOS/Windows; on Linux
install your distro's `python3-tk` package).

```bash
python3 TLR_Save_Editor.py
```

To turn it into a double-clickable macOS app, use
[Platypus](https://sveinbjorn.org/platypus) pointed at
`TLR_Save_Editor.py` with interpreter `/usr/bin/env python3`.

### Command-line tool

```bash
python3 save_explorer.py info savegame.sav
python3 save_explorer.py diff save_before.sav save_after.sav
python3 save_explorer.py search savegame.sav 49280
python3 save_explorer.py setgold savegame.sav 999999 output.sav
python3 save_explorer.py setbr savegame.sav 99 output.sav
python3 save_explorer.py fixchecksum savegame.sav savegame_fixed.sav
```

## Disclaimer

Always back up your save before editing. Editing a save file always carries
some risk of a corrupted or unloadable file, even with a valid checksum, and
this project is not affiliated with Square Enix. Use at your own risk.

## License

MIT — see [LICENSE](LICENSE).
