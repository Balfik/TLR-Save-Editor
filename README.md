# TLR Save Editor — The Last Remnant / The Last Remnant Remastered Save File Editor

**Current version: 0.22.0**

A save editor for **The Last Remnant** and **The Last Remnant Remastered**,
built from scratch through reverse-engineering of the `.sav` file format.
Includes a cross-platform tkinter GUI (`TLR_Save_Editor.py`, with a built-in
Ukrainian/English language toggle) and a command-line tool
(`save_explorer.py`).

## Compatibility

Confirmed working with saves from:

- **The Last Remnant Remastered** (PC)
- **The Last Remnant Remastered** (Android)
- **The Last Remnant** original release (2008, PC)

All three share the same underlying `.sav` structure and every field this
tool edits, so a save from any of them can be opened, edited, and saved back
without issues in the testing done so far. That said, testing has been done
on a limited number of saves/devices — if you hit a save that behaves
differently, please open an issue.

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
  Special Items, including in-place editing of stats on items you already
  own/have equipped (e.g. raising a weapon's attack stat directly, not just
  at grant time).
- **Save info panel** — a consolidated view of gold, Battle Rank, playtime,
  Mr. Diggs attempts, monster kills, per-union stats, and inventory counts.
- **Checksum handling** — every save is automatically re-signed with the
  correct SHA1 checksum, so edited saves load without errors.
- **Search & diff tools** (CLI) — search for a value anywhere in a save, or
  diff two saves to find what changed between them.

### Beyond the game's own UI limits

The save format itself supports more than what the game's menus expose, and
this tool lets you use that extra room directly:

- **8 unions, not 5.** The default in-game screens only show 5 union slots,
  but the underlying save structure has room for 8. This tool can activate
  and populate the extra 3 (confirmed to work in real battles: they show up,
  fight, and recalculate stats normally after a battle).
- **More than 5 characters per union**, and **more than the "18 units"
  reference cap** shown in the battle stats screen — both turned out to be
  static UI labels, not hard engine limits, and were confirmed working with
  larger rosters in real battles.
- **Duplicate character assignments** (the same character in multiple union
  slots, or multiple unions at once) — confirmed safe in real gameplay.
- **In-place equipment stat editing** — change the stats of a weapon or
  accessory you already have equipped, not only at the moment you grant it.

None of this is exposed through the normal game UI — it's only reachable by
editing the save file directly, which is what this tool automates.

## Why this exists

No save editor for The Last Remnant Remastered existed before this project —
this started purely out of curiosity, to see what could actually be changed
in the save file, and what that opens up in the game itself. Some of the
questions that motivated it:

- What happens if you put **five Rush** in a single union — can you even
  clear the game that way?
- Can you fight the **final boss with 45 units on the field at once**,
  instead of the game's usual party size?
- Are the "18 units" / "5 unions" numbers shown in the battle stats screen
  actual hard limits, or just labels? (Turns out: just labels — see
  [Beyond the game's own UI limits](#beyond-the-games-own-ui-limits).)

None of this is documented anywhere, so every field in this tool — gold,
Battle Rank, playtime, Mr. Diggs attempts, monster kills, the union/roster
structures, equipment tables — was found using a controlled-diff method:
make one precise, known change in-game, save before and after, diff the two
files byte-by-byte, and confirm the hypothesis against multiple independent
saves before trusting it. Every field listed above has been verified in real
gameplay, not just in theory.

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

Two caveats when using these files:

- The CSVs' own `Offset` column refers to the *original 2008 PC release*'s
  **in-memory** layout (for cheat-engine-style memory editing while the game
  is running) and does not apply to any `.sav` **file** offset used by this
  tool. Only the row order of `Items.csv` is used (it maps to the item table
  by row index) — every file offset used by this tool was independently
  reverse-engineered from real save files.
- Equipment/accessory ID mappings were cross-checked against real equipped
  items in actual saves before being trusted.

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

This is an unofficial, fan-made tool, not affiliated with, endorsed by, or
supported by Square Enix or any other rights holder of The Last Remnant.
"The Last Remnant" and "The Last Remnant Remastered" are trademarks of their
respective owners.

The software is provided **"as is," without warranty of any kind**, express
or implied — see the [LICENSE](LICENSE) for the full text. Editing a save
file always carries some risk of producing a corrupted or unloadable save,
even when the checksum is valid, and the author(s) and contributors accept
**no responsibility or liability** for lost progress, corrupted saves, banned
accounts, or any other consequence of using this tool. **Always back up your
original save file before editing**, and use this tool entirely at your own
risk.

## License

MIT — see [LICENSE](LICENSE).
