#!/usr/bin/env python3
"""
TLR Save Editor - GUI save editor for The Last Remnant Remastered.
TLR Save Editor - редактор сейвів для The Last Remnant Remastered.

Works on any OS with Python 3 + tkinter (Windows / macOS / Linux).
On macOS tkinter is bundled with the standard installer from python.org.

Керовано перемикачем мови (UA / EN) в правому верхньому куті вікна.
Language is switched with the UA / EN toggle in the top-right corner.
"""
import os
import sys
import shutil
import struct
import zlib
import hashlib
import json
import time
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

AUTHOR_LINK_URL = "https://github.com/Balfik"

APP_VERSION = "0.30.0"

GOLD_OFFSET = 0x1D978
GOLD_LIFETIME_OFFSET = 0x25A5A
BR_DISPLAY_CACHE_OFFSET = 0x28   # load-screen display cache only
BR_OFFSET = 0x259DD              # REAL Battle Rank (int16 LE)
BR_EXP_OFFSET = 0x259DF          # BR EXP counter, 0-499 (int16 LE)
CHECKSUM_OFFSET = 0x0C
CHECKSUM_DATA_START = 0x20

# Playtime, in whole seconds, int32 LE. HYPOTHESIS, not confirmed against
# an in-game display (the user couldn't check at the time), but found by
# scanning 5 chronological test saves (savegame05..09) for an int32 field
# that (a) stays within a plausible playtime range, (b) increases
# monotonically across every save, and (c) increases by an amount of
# seconds consistent with the real time that passed between each test
# save. This was the strongest candidate out of ~110 fields that matched
# criteria (a)+(b) alone. Treat as provisional until confirmed in-game.
PLAYTIME_OFFSET = 0x04F4C


def read_playtime_seconds(dec):
    return struct.unpack("<i", dec[PLAYTIME_OFFSET:PLAYTIME_OFFSET + 4])[0]


def write_playtime_seconds(buf, seconds):
    buf[PLAYTIME_OFFSET:PLAYTIME_OFFSET + 4] = struct.pack("<i", seconds)


def format_hms(total_seconds):
    total_seconds = max(0, int(total_seconds))
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_hms(text):
    """Parses 'HH:MM:SS' (or 'H:MM:SS', or a bare integer of seconds)
    into total seconds. Raises ValueError on bad input."""
    text = text.strip()
    if ":" not in text:
        return int(text)
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"Expected HH:MM:SS, got {text!r}")
    h, m, s = (int(p) for p in parts)
    if m < 0 or m > 59 or s < 0 or s > 59 or h < 0:
        raise ValueError(f"Invalid HH:MM:SS: {text!r}")
    return h * 3600 + m * 60 + s


# Mr. Diggs dig attempts - found via controlled test: three saves with
# 12/11/10 attempts remaining (one dig used between each). A unique
# uint32 LE hit at 0x4F5C matched exactly (12, 11, 10) across all three;
# right after it, 0x4F60 held a constant uint32 LE = 12 in every save -
# almost certainly the max-attempts cap, separate from the current
# count. Both are right next to PLAYTIME_OFFSET (0x4F4C), suggesting
# this whole area is a small block of misc progress counters.
MR_DIGGS_ATTEMPTS_OFFSET = 0x4F5C
MR_DIGGS_MAX_ATTEMPTS_OFFSET = 0x4F60


def read_mr_diggs_attempts(dec):
    return struct.unpack("<i", dec[MR_DIGGS_ATTEMPTS_OFFSET:MR_DIGGS_ATTEMPTS_OFFSET + 4])[0]


def write_mr_diggs_attempts(buf, value):
    buf[MR_DIGGS_ATTEMPTS_OFFSET:MR_DIGGS_ATTEMPTS_OFFSET + 4] = struct.pack("<i", value)


def read_mr_diggs_max_attempts(dec):
    return struct.unpack(
        "<i", dec[MR_DIGGS_MAX_ATTEMPTS_OFFSET:MR_DIGGS_MAX_ATTEMPTS_OFFSET + 4])[0]


def write_mr_diggs_max_attempts(buf, value):
    buf[MR_DIGGS_MAX_ATTEMPTS_OFFSET:MR_DIGGS_MAX_ATTEMPTS_OFFSET + 4] = struct.pack("<i", value)


# Misc small counter - first candidate found for "monster kills" (from a
# 3-battle test: +5, +5, +4), but the user pointed out the real lifetime
# kill count should be in the ~700-2000+ range, not 18-34. Ruled out as
# the kill counter, but kept defined (unused in the GUI for now) in case
# it turns out useful later - it's a real, isolated field in a wide
# "misc counters" table (0x1D5C0-0x1D680) that reliably tracked combat
# activity across all 4 original test saves, just at too small a scale
# to be a lifetime total. Possibly a quest/guild-task kill-progress
# counter instead.
MISC_COMBAT_COUNTER_OFFSET = 0x1D5FA


def read_misc_combat_counter(dec):
    return struct.unpack(
        "<H", dec[MISC_COMBAT_COUNTER_OFFSET:MISC_COMBAT_COUNTER_OFFSET + 2])[0]


# Monster kill counter (likely correct) - found via a 4th controlled
# battle (+2 kills) added to the original 3 (+5, +5, +4). Out of the
# candidates whose delta matched +2 between saves 08 and 09, this one
# ALSO matched the full +5/+5/+4/+2 sequence across all 5 saves AND sits
# at a plausible magnitude (3652 baseline, ~41h playtime) instead of the
# too-small MISC_COMBAT_COUNTER_OFFSET found earlier. Uint16 LE.
MONSTER_KILLS_OFFSET = 0x1D2DA


def read_monster_kills(dec):
    return struct.unpack(
        "<H", dec[MONSTER_KILLS_OFFSET:MONSTER_KILLS_OFFSET + 2])[0]


def write_monster_kills(buf, value):
    buf[MONSTER_KILLS_OFFSET:MONSTER_KILLS_OFFSET + 2] = struct.pack("<H", value)


# --- Rush character (main) ---
# All 12 stat slots found in Rush's stat-block, base = 0x025C82 (where HP lives).
# Every slot is stored TWICE in a row (copy1 immediately followed by copy2),
# either as two int16 (size=2) or two uint8 (size=1). Confirmed against a
# community Cheat Engine table (CharPtr+0x18=HP, +0x1C=MaxAP, +0x3A=STR,
# +0x46=INT, +0x52=SPD, +0x5E=Unique) - order matches. The remaining slots
# are unnamed (possibly cached combat stats: ATK/DEF/MYS/M.DEF/EVA/M.EVA,
# per the README's note that those are normally computed, not stored raw).
RUSH_STRUCT_BASE = 0x025C82

# *** UPDATE: this is actually an 8-slot UNION array, not just Rush ***
# Confirmed via controlled test: split the party into 5 separate unions
# (5/2/3/4/4 members) and searched for the exact in-game HP/AP values of
# unions 2-5 in the save. Found each union's HP field at a fixed stride
# of 0x54 (84) bytes after the previous one - union index 0 (this base)
# is "Union 1", index 1 is "Union 2", etc. This also explains the
# earlier oddity where swapping the sole member of a 1-person union
# (Rush -> David) didn't change these bytes at all: that test only ever
# touched Union 1, and the game apparently doesn't recompute a union's
# aggregate stats just from a same-headcount member swap - only from
# real roster changes (add/remove) or entering formation/battle.
#
# *** SECOND UPDATE: 8 slots, not 5 ***
# A ~2013 community forum post (independent research into the original
# PC release's memory/save layout, shared for TLRPlanner/RemnantTrainer)
# listed this exact address (0x25C6C) as "Unions (Table 237) -
# 8*84=672 Bytes". Verified against a real Remastered save: union
# records at index 5, 6, 7 (beyond the 5 we'd tested) do exist as
# well-formed, currently-inactive records (HP=0, member list = the same
# 0xFFFF-sentinel empty pattern as any other unused union slot) - not
# overlapping unrelated data as an earlier, less careful look concluded.
# The same post also cross-validated several other tables we'd already
# found independently (Money @ 0x1D978 exact match, "Equipment"/our
# Accessories @ 0x1D97C exact match down to the 8-byte record size,
# Items table 4 bytes earlier than ours - likely a header field we
# don't need to touch, Monster kills table @ 0x1D2D8 with our confirmed
# working field landing 2 bytes into it). Its "Mr. Diggs" address
# (0x1D2B8) did NOT match our independently-confirmed 0x4F5C, so
# offsets from that post should still be verified before being trusted
# outright - Remastered evidently moved some tables and not others.
UNION_COUNT = 8
UNION_RECORD_STRIDE = 0x54

RUSH_STATS = [
    # key,    label key,          rel.offset, size(bytes per copy)
    ("hp",    "rush_hp_label",    0x00, 2),
    ("ap",    "rush_ap_label",    0x04, 2),
    ("f3",    "rush_f3_label",    0x08, 2),
    ("f4",    "rush_f4_label",    0x0c, 1),
    ("f5",    "rush_f5_label",    0x0e, 2),
    ("str",   "rush_str_label",   0x12, 1),
    ("int",   "rush_int_label",   0x14, 1),
    ("spd",   "rush_spd_label",   0x16, 1),
    ("uniq",  "rush_uniq_label",  0x18, 1),
    ("f10",   "rush_f10_label",   0x1a, 1),
    ("f11",   "rush_f11_label",   0x1c, 1),
    ("f12",   "rush_f12_label",   0x1e, 1),
]

# "Max stats" preset values. The 1-byte fields are written unsigned
# (write_rush_stat packs size==1 as "<B"), so 255 is their hard byte
# ceiling. The 2-byte fields are written signed ("<h"), so 32767 is the
# true byte ceiling, but that's liable to look broken/glitchy on-screen
# for a single-battle boost - HP=9999/AP=999/AP+per turn=99 are more
# conservative, comfortably-displayable round numbers instead of the
# raw overflow max. Since this whole section is already documented as a
# temporary, one-battle-only boost (not a permanent, verified-safe
# change), there's no strict "correct" answer here - these are
# reasonable, safe defaults, not a reverse-engineered hard limit.
RUSH_STAT_MAX = {
    "hp": 9999, "ap": 999, "f3": 99, "f4": 255, "f5": 999,
    "str": 255, "int": 255, "spd": 255, "uniq": 255,
    "f10": 255, "f11": 255, "f12": 255,
}

# Extra known duplicate addresses elsewhere in the file for HP and STR only
# (found via controlled-test diffing); kept in sync on save for consistency.
RUSH_HP_EXTRA_OFFSETS = [0x03D9E3, 0x03DA5D]
RUSH_STR_EXTRA_OFFSETS = [0x03D9FB, 0x03DA63, 0x03E58C]


def rush_stat_addrs(rel_offset, size, union_index=0):
    """Returns (addr_copy1, addr_copy2) for a stat slot in the given
    union's struct (union_index 0 = Union 1, ... 4 = Union 5)."""
    base = RUSH_STRUCT_BASE + union_index * UNION_RECORD_STRIDE
    addr1 = base + rel_offset
    addr2 = addr1 + size
    return addr1, addr2


def read_rush_stat(dec, rel_offset, size, union_index=0):
    addr1, _ = rush_stat_addrs(rel_offset, size, union_index)
    if size == 2:
        return struct.unpack("<h", dec[addr1:addr1 + 2])[0]
    return dec[addr1]


def write_rush_stat(buf, rel_offset, size, value, union_index=0):
    addr1, addr2 = rush_stat_addrs(rel_offset, size, union_index)
    if size == 2:
        packed = struct.pack("<h", value)
        buf[addr1:addr1 + 2] = packed
        buf[addr2:addr2 + 2] = packed
    else:
        buf[addr1:addr1 + 1] = struct.pack("<B", value)
        buf[addr2:addr2 + 1] = struct.pack("<B", value)


def read_union_stats(dec, union_index):
    return {
        key: read_rush_stat(dec, rel_off, size, union_index)
        for key, label_key, rel_off, size in RUSH_STATS
    }


def write_union_stats(buf, union_index, stats):
    """Writes all 12 stat slots for one union. If union_index is 0
    (Union 1), also syncs the extra known HP/STR duplicate addresses -
    those were only ever confirmed for Union 1 / Rush, so they're left
    untouched for unions 2-5 to avoid corrupting unrelated data."""
    for key, label_key, rel_off, size in RUSH_STATS:
        write_rush_stat(buf, rel_off, size, stats[key], union_index)
    if union_index == 0:
        new_hp = stats["hp"]
        for off in RUSH_HP_EXTRA_OFFSETS:
            buf[off:off + 2] = struct.pack("<h", new_hp)
        new_str = stats["str"]
        for off in RUSH_STR_EXTRA_OFFSETS:
            buf[off:off + 1] = struct.pack("<B", new_str)


# Union roster: slots 2-5, PLUS slot 1 (the leader), whose storage was
# found later (see UNION_LEADER_REL_OFFSET below). Slots 2-5 sit 8
# bytes before each union's stat struct, 4x uint16 LE character IDs,
# sentinel 0xFFFF for an empty slot. Confirmed safe by live controlled
# tests: writing a character ID directly into an empty slot (no other
# bytes touched) loaded fine in-game, showed the character immediately,
# and the union's aggregate stats (which were stale right after
# loading) recalculated correctly once the user entered a battle - so
# the game itself handles reconciling the dependent counters/stats, we
# don't need to write them ourselves. Duplicate characters (the same ID
# in multiple slots/unions at once) were also confirmed safe live.
# STILL EXPERIMENTAL: not tested - giving an unrecruited/story-locked
# character (bosses/uniques crashed the union-board screen specifically
# in testing, though they worked fine in battle).
UNION_MEMBER_SLOT_COUNT = 4  # slots 2, 3, 4, 5
UNION_MEMBER_EMPTY_ID = 0xFFFF
CHARS_CSV_FILENAME = "Chars.csv"

# Leader (slot 1) - found by decoding the 7-uint16 header that sits
# right before the slots-2-5 member list (14 bytes total, offsets
# +0..+12 relative to the header start = union base - 0x16). The LAST
# of those 7 fields (+12, i.e. 2 bytes before the member list, which is
# exactly where you'd expect a 5-element roster array - [leader, slot2,
# slot3, slot4, slot5] - to start) held a clean, plausible character ID
# for every one of the 5 known-active unions in a real save (e.g. Union
# 1 -> id 0 = Rush, matching the story's default leader) and the
# 0xFFFF empty sentinel for every known-inactive union. Not yet
# confirmed whether writing this actually makes an inactive union
# playable in-game (that's the current open question) - awaiting the
# user's test.
UNION_LEADER_REL_OFFSET = -10  # relative to RUSH_STRUCT_BASE + union_index*STRIDE


def union_leader_addr(union_index):
    return RUSH_STRUCT_BASE + union_index * UNION_RECORD_STRIDE + UNION_LEADER_REL_OFFSET


def read_union_leader(dec, union_index):
    addr = union_leader_addr(union_index)
    return struct.unpack("<H", dec[addr:addr + 2])[0]


def write_union_leader(buf, union_index, char_id):
    addr = union_leader_addr(union_index)
    buf[addr:addr + 2] = struct.pack("<H", char_id)


# Union "active" flags - CONFIRMED WORKING via a live controlled test.
# First found by diffing a save before/after a guest union (a story-
# triggered NPC ally, "Sheryl") appeared mid-game: the union's 7-field
# header (see the big comment above UNION_LEADER_REL_OFFSET) changed at
# exactly 3 places - field 0 (0 -> 257 = 0x0101: low byte 1 = "active",
# high byte 1 = a "guest" marker specifically), field 2 (0 -> 36, the
# same constant every already-active union also has at this position),
# and the leader field. Writing just the "active" (low byte=1, no guest
# bit) + "36" + leader trio into a previously-empty union slot (6, 7,
# or 8) was then confirmed LIVE by the user: the union showed up in the
# roster immediately (as "Dummy"/all-zero stats until the next battle,
# same lazy-recalculation behavior as every other union stat change),
# and after one battle displayed correctly with real stats and the
# leader's name - fully playable, could even recruit more members into
# it afterwards. The "18 units / 7 unions" in-game counters also didn't
# block anything, consistent with the earlier finding that those are
# just static labels, not enforced caps.
UNION_ACTIVE_REL_OFFSET = -0x16       # field 0 of the header (uint16)
UNION_ACTIVE_FLAG = 0x0001            # low byte only; leave high byte 0 (not a guest union)
UNION_POPULATED_REL_OFFSET = -0x12    # field 2 of the header (uint16)
UNION_POPULATED_VALUE = 36


def activate_union(buf, union_index, leader_id):
    """Writes the 3 fields needed to bring an empty union slot (6, 7, or
    8) to life as an ordinary playable union: the active flag, the '36'
    populated marker, and the leader."""
    base = RUSH_STRUCT_BASE + union_index * UNION_RECORD_STRIDE
    active_addr = base + UNION_ACTIVE_REL_OFFSET
    populated_addr = base + UNION_POPULATED_REL_OFFSET
    buf[active_addr:active_addr + 2] = struct.pack("<H", UNION_ACTIVE_FLAG)
    buf[populated_addr:populated_addr + 2] = struct.pack("<H", UNION_POPULATED_VALUE)
    write_union_leader(buf, union_index, leader_id)


def deactivate_union(buf, union_index):
    """Counterpart to activate_union(): clears the active flag and the
    '36' populated marker along with the leader, so clearing a union's
    leader back to empty doesn't leave it in a half-active state."""
    base = RUSH_STRUCT_BASE + union_index * UNION_RECORD_STRIDE
    active_addr = base + UNION_ACTIVE_REL_OFFSET
    populated_addr = base + UNION_POPULATED_REL_OFFSET
    buf[active_addr:active_addr + 2] = struct.pack("<H", 0)
    buf[populated_addr:populated_addr + 2] = struct.pack("<H", 0)
    write_union_leader(buf, union_index, UNION_MEMBER_EMPTY_ID)


def union_member_addr(union_index, slot_position):
    """slot_position is 0-3, corresponding to Union slots 2-5."""
    base = RUSH_STRUCT_BASE + union_index * UNION_RECORD_STRIDE
    return base - 8 + slot_position * 2


def read_union_members(dec, union_index):
    return [
        struct.unpack("<H", dec[a:a + 2])[0]
        for a in (union_member_addr(union_index, i) for i in range(UNION_MEMBER_SLOT_COUNT))
    ]


def write_union_member(buf, union_index, slot_position, char_id):
    addr = union_member_addr(union_index, slot_position)
    buf[addr:addr + 2] = struct.pack("<H", char_id)


def all_union_members(dec):
    """Returns {(union_index, slot_position): char_id} for every
    occupied (non-empty) slot across all 5 unions - used to detect
    duplicate assignments before writing a new one."""
    result = {}
    for u in range(UNION_COUNT):
        for s in range(UNION_MEMBER_SLOT_COUNT):
            addr = union_member_addr(u, s)
            char_id = struct.unpack("<H", dec[addr:addr + 2])[0]
            if char_id != UNION_MEMBER_EMPTY_ID:
                result[(u, s)] = char_id
    return result


def load_chars_catalog():
    """Loads character names from Chars.csv, in file row order (row
    order IS the character ID - confirmed by cross-checking ids found
    in real save files, e.g. id 261/224 matched Caedmon/Paris exactly).
    Returns [] if not found."""
    try:
        lines = _read_csv_lines(CHARS_CSV_FILENAME)
    except Exception:
        return []
    names = []
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 2:
            continue
        names.append(parts[1])
    return names


# ---------------------------------------------------------------------------
# Accessories table (carried, not equipped) - found while reverse-
# engineering the Accessories category. Sits right after Gold
# (0x1D978), 8-byte records: [item_id: uint32 LE][display_order:
# uint32 LE], up to 50 slots (matches the in-game "x/50" counter).
# Confirmed by controlled test: selling "Superior Necklace" cleared its
# record to EQUIP_EMPTY_ID/0xFFFF and every remaining item's order value
# shifted down by 1 to stay contiguous from 0 (the physical slot each
# item occupies does NOT change - only the display-order counter is
# compacted). IMPORTANT: this table's IDs come from the SAME namespace
# as Equipment's, but AccItems.csv has no stat columns (Att/Def/etc) -
# accessories apparently don't carry raw combat stats in the save file
# the way equipment does (their bonuses are % based, applied elsewhere).
ACCESSORY_TABLE_BASE = 0x1D97C
ACCESSORY_RECORD_SIZE = 8
# In-game the UI shows a "x/50" capacity, but 50 * 8 bytes would end at
# 0x1DB0C - 12 bytes PAST where the (corrected) Equipment table starts
# (0x1DB00), i.e. the last ~1.5 "slots" of a literal 50-slot array
# would alias with Equipment's first record. Since we can't yet prove
# whether the true on-disk reservation is exactly 50 records or
# something else, we deliberately cap this tool at 48 slots - the
# largest count that ends with zero overlap (0x1D97C + 48*8 = 0x1DAFC,
# 4 bytes of margin before Equipment). This sacrifices the theoretical
# last 2 accessory slots rather than risk corrupting Equipment data.
ACCESSORY_SLOT_COUNT = 48
ACCESSORY_ID_REL_OFFSET = 0
ACCESSORY_ORDER_REL_OFFSET = 4
ACCESSORY_EMPTY_ID = 0xFFFFFFFF
ACCESSORY_EMPTY_ORDER = 0xFFFF
ACCESSORY_CSV_FILENAME = "AccItems.csv"

# ---------------------------------------------------------------------------
# Items table (Consumables / Components / Captured Monsters / Special
# Items) - a dense, fixed array covering all 1705 possible items in the
# game, each with a permanently reserved 12-byte record (unlike
# Equipment/Accessories, which only list items you actually own - here
# EVERY item always has a slot, most just sitting at quantity 0).
#
# Confirmed by controlled test: consuming/selling exactly 1 of a known
# item decremented byte offset+0 of its record by exactly 1, for 3
# items across 3 different categories (Cureleaf/Herb, Landworm
# Talon/Monster Component, Captured Aeronite/Captured Monster). Record
# index = row order in the bundled Items.csv (same file used by the
# community TLRPlanner tool for names, but note ITS "Offset" column is
# wrong for this Remastered save format - only the row ORDER is usable,
# not the offsets it lists). Base + row_index*12 was verified against
# 6 independent data points (3 from the controlled test, 3 more from
# values the user read directly off their in-game inventory), matching
# exactly every time, quantities landing cleanly in 0-100 (the game's
# own per-item stack cap).
#
# NOT yet understood: bytes +1 through +11 of each record. Byte +1 in
# particular looks like it might be a "have you ever picked this up"
# flag (owned Herbs show 3 there, a never-obtained Herb showed 0) -
# until that's verified, this tool only allows editing the quantity of
# items that are ALREADY > 0 (i.e. already legitimately owned), not
# granting brand new items from a quantity of 0. See ITEMS_MIN_QTY_TO_EDIT.
ITEMS_TABLE_BASE = 0x209F0
ITEMS_RECORD_SIZE = 12
ITEMS_QTY_REL_OFFSET = 0
ITEMS_MAX_QTY = 100
ITEMS_MIN_QTY_TO_EDIT = 1  # only items already owned (qty >= 1) are editable for now
ITEMS_CSV_FILENAME = "Items.csv"

# Best-effort mapping from the CSV's "Type" column to this tool's 4
# Inventory sub-tabs, based on the subcategories the user described
# seeing in-game (Consumables: Herbs/Potions/Lotions/Explosives/
# Shards/Traps/Other; Components: Ore/Vegetation/Metals/Minerals/
# Monster Components/Other). The CSV's "Other" and "Morsel" types are
# a mixed bag (recipes, seeds, oils, ore-like items) that don't map
# cleanly to one bucket - they're grouped under Consumables here as a
# reasonable guess, and can be moved if that turns out to be wrong.
ITEMS_CATEGORY_TYPES = {
    "consumables": ["Herb", "Potion", "Lotion", "Explosive", "Shard", "Trap", "Other", "Morsel"],
    "components": ["Ore", "Vegetation", "Metal", "Mineral", "Monster Component"],
    "captured_monsters": ["Captured Monster"],
    "special_items": ["Special Item", "Map"],
}

# Special Items are always quantity 1 (own it or not - confirmed by
# checking every currently-owned Special Item's record: all showed
# qty_byte=1, never higher), so there's nothing meaningful to "change
# the quantity" of - that tab is view-only, no edit controls.
ITEMS_CATEGORY_EDITABLE = {
    "consumables": True,
    "components": True,
    "captured_monsters": True,
    "special_items": False,
}


def _find_items_csv_path():
    return find_data_csv_path(ITEMS_CSV_FILENAME)


def load_items_catalog():
    """Loads the item catalog from Items.csv as a list of dicts, in file
    row order (that row order IS the record index in the save - see the
    big comment above ITEMS_TABLE_BASE). Returns [] if not found."""
    try:
        lines = _read_csv_lines(ITEMS_CSV_FILENAME)
    except Exception:
        return []
    catalog = []
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 4:
            continue
        catalog.append({"name": parts[1], "type": parts[3]})
    return catalog


def item_record_addr(row_index):
    return ITEMS_TABLE_BASE + row_index * ITEMS_RECORD_SIZE


def read_item_qty(dec, row_index):
    return dec[item_record_addr(row_index)]


def write_item_qty(buf, row_index, qty):
    """Writes a 0-100 quantity into an item's record. Refuses to bring
    a currently-0 (never owned) item up from zero, since bytes +1..+11
    of a "never owned" record aren't understood yet and might need to
    be initialized too (same class of problem Equipment had with its
    stat bytes) - see the big comment above ITEMS_TABLE_BASE."""
    addr = item_record_addr(row_index)
    current = buf[addr]
    qty = max(0, min(ITEMS_MAX_QTY, int(qty)))
    if current < ITEMS_MIN_QTY_TO_EDIT and qty > 0:
        raise ValueError(
            f"Refusing to grant a new item (row {row_index}) from quantity 0 - "
            "not yet verified safe. Only editing already-owned items is supported."
        )
    buf[addr] = qty


# --- Granting brand-new items (quantity 0 -> something) ---------------------
# Confirmed by a controlled test: buying 1x each of 3 previously-never-owned
# items (Alpacan Cloth/Mineral, Angoran Cloth/Mineral, Platinum Ore/Ore) and
# diffing before/after showed exactly 3 fields change per record:
#   +0  (qty)          0 -> 1
#   +1  (type/owned tag) 0 -> 3   (a "this slot is a live, valid stack" tag -
#                                  scanning 508 already-owned records across
#                                  the whole save, this is 3 for basically all
#                                  Consumable/Component types, but 1 for
#                                  Captured Monster/Monster Component)
#   +2..+3 (discovery order, uint16 LE)  garbage -> next sequential value
#                                  (338, 339, 340 for the 3 items bought in
#                                  that order - contiguous with the save's
#                                  existing max order of 8513 among already-
#                                  discovered items)
# +4..+7 stayed 0 (already 0 before, matches every "never owned" record
# checked), and +8..+11 were UNCHANGED by the purchase (already correctly
# pre-populated even in never-owned records) - so those don't need touching.
ITEMS_ORDER_REL_OFFSET = 2
ITEMS_TYPE_TAG_REL_OFFSET = 1
ITEMS_DEFAULT_TYPE_TAG = 3
ITEMS_DEFAULT_TYPE_TAG_OVERRIDES = {
    "Captured Monster": 1,
    "Monster Component": 1,
}


def guess_item_type_tag(dec, catalog, item_type):
    """Best guess for the byte+1 'type tag' a newly granted item of
    `item_type` should get: the most common value already seen among
    this save's own already-owned items of that same type (falls back
    to a hardcoded default if none are owned yet)."""
    from collections import Counter
    counts = Counter()
    for row_index, item in enumerate(catalog):
        if item["type"] != item_type:
            continue
        addr = item_record_addr(row_index)
        if dec[addr] < ITEMS_MIN_QTY_TO_EDIT:
            continue
        counts[dec[addr + ITEMS_TYPE_TAG_REL_OFFSET]] += 1
    if counts:
        return counts.most_common(1)[0][0]
    return ITEMS_DEFAULT_TYPE_TAG_OVERRIDES.get(item_type, ITEMS_DEFAULT_TYPE_TAG)


def next_item_discovery_order(dec, catalog):
    """Next 'discovery order' value to assign to a newly granted item -
    one past the highest order value seen among records that are
    actually owned (qty > 0). Everything else (never-owned consumables,
    and even some never-owned unique Special Items that already carry a
    non-zero type tag) holds a leftover/sentinel value here (often the
    max uint16, 0xFFFF, meaning "no order assigned yet") that would
    throw off a naive max(), so only genuinely-owned records count."""
    best = -1
    for row_index in range(len(catalog)):
        addr = item_record_addr(row_index)
        if dec[addr] < ITEMS_MIN_QTY_TO_EDIT:
            continue
        order = struct.unpack("<H", dec[addr + ITEMS_ORDER_REL_OFFSET:addr + ITEMS_ORDER_REL_OFFSET + 2])[0]
        if order > best:
            best = order
    return best + 1


def grant_new_item(buf, catalog, row_index, qty):
    """Grants a brand-new item (currently at quantity 0), writing the
    quantity plus the two extra fields (+1 type tag, +2..+3 discovery
    order) that a legitimately-obtained item gets - see the big comment
    above. Raises ValueError if the item isn't actually at 0 (use
    write_item_qty for adjusting something you already own)."""
    addr = item_record_addr(row_index)
    if buf[addr] >= ITEMS_MIN_QTY_TO_EDIT:
        raise ValueError(
            f"Row {row_index} is already owned (qty={buf[addr]}) - use write_item_qty "
            "to change its quantity instead of grant_new_item."
        )
    qty = max(1, min(ITEMS_MAX_QTY, int(qty)))
    item_type = catalog[row_index]["type"]
    dec_snapshot = bytes(buf)
    type_tag = guess_item_type_tag(dec_snapshot, catalog, item_type)
    order = next_item_discovery_order(dec_snapshot, catalog)

    buf[addr] = qty
    buf[addr + ITEMS_TYPE_TAG_REL_OFFSET] = type_tag & 0xFF
    buf[addr + ITEMS_ORDER_REL_OFFSET:addr + ITEMS_ORDER_REL_OFFSET + 2] = struct.pack("<H", order)


# ---------------------------------------------------------------------------
# Equipment table (weapons / shields / armor carried, not equipped)
# ---------------------------------------------------------------------------
# Confirmed by a controlled test: selling "Combat Halberd" zeroed out its
# 120-byte record entirely. Table base and item-ID meaning cross-checked
# against EquipItems.csv (from the community TLRPlanner tool) - the ID at
# each record's +12 offset (uint32 LE) matches that CSV's "Value" column
# 1:1 (e.g. 8323782 = "Combat Halberd").
#
# *** CORRECTED base (was 0x1D998 for a while - IMPORTANT FIX) ***
# The original base was wrong by exactly 3 records (0x1D998 = 0x1DB00 -
# 3*0x78). It was found using only equipment-only test saves where the
# Accessories table (see above, ends at 0x1D97C + 50*8 = 0x1DB0C) was
# basically empty, so its trailing empty bytes silently looked like 3
# harmless "always empty" equipment slots. Once the save actually had
# accessories in it, those same bytes turned out to be real accessory
# data that the old base would have let this tool overwrite (e.g. via
# "Fill empty slots"), corrupting the Accessories table. Re-verified
# against all 11 known real equipped items (Commander's Rapier, etc.) -
# they all line up perfectly starting at 0x1DB00.
EQUIP_TABLE_BASE = 0x1DB00
EQUIP_RECORD_SIZE = 0x78     # 120 bytes per slot
EQUIP_SLOT_COUNT = 96        # was 99 at the old (wrong) base; end address
                              # of the table is unchanged, so 3 fewer slots
                              # fit ahead of that same end point
EQUIP_ID_REL_OFFSET = 12     # uint32 LE, item ID within each record
EQUIP_EMPTY_ID = 0xFFFFFFFF  # sentinel value for an empty slot

# Confirmed by cross-checking 12 already-equipped items against
# EquipItems.csv: starting at record offset 21, there are 6 stats
# (Att, M-Att, Def, M-Def, Eva, M-Eva - same order as the CSV columns),
# each stored as a 3-byte triple [value, 0x00, value] (the value
# duplicated, same "write it twice" pattern seen everywhere else in
# this save format). Writing only the item ID (as the earlier version
# of this tool did) leaves these all at 0x00, which is why items placed
# into previously-empty slots showed 0 Attack/Defense in-game and were
# not actually providing any combat benefit, even though they equipped
# without error.
EQUIP_STAT_REL_OFFSET = 21
EQUIP_STAT_COUNT = 6
EQUIP_STAT_STRIDE = 3
EQUIP_STAT_NAMES = ["att", "matt", "def", "mdef", "eva", "meva"]

EQUIP_CSV_FILENAME = "EquipItems.csv"


def _data_csv_candidate_dirs():
    """Directories to search for a data CSV (EquipItems.csv, AccItems.csv,
    ...), in priority order. Not just "next to the script": also checks
    the current working directory and the launched executable's
    directory, since double-clicking the script, running it via a
    shortcut, or a cloud-synced folder (iCloud Drive etc. can briefly
    report a file as "not there yet" while it's downloading) can all
    make __file__-relative lookup alone unreliable."""
    dirs = []
    try:
        dirs.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    try:
        dirs.append(os.getcwd())
    except Exception:
        pass
    try:
        import sys
        dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    # de-duplicate while keeping order
    seen = set()
    unique_dirs = []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            unique_dirs.append(d)
    return unique_dirs


# Kept as a private alias for backwards compatibility.
_equip_csv_candidate_dirs = _data_csv_candidate_dirs


def find_data_csv_path(filename):
    """Looks for `filename` next to this script, in the current working
    directory, or next to the launched executable (in that order).
    Returns None if it truly can't be found anywhere."""
    for d in _data_csv_candidate_dirs():
        candidate = os.path.join(d, filename)
        if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    return None


def find_equip_csv_path():
    return find_data_csv_path(EQUIP_CSV_FILENAME)


# Kept as a private alias for backwards compatibility with any external
# callers/tests that used the old name.
_find_equip_csv_path = find_equip_csv_path


def _read_csv_lines(filename):
    """Reads a data CSV and returns its lines (header included), or
    raises with a clear reason if it can't. Centralized so every loader
    for a given file sees the exact same content/error instead of
    independent (and possibly inconsistent, e.g. if the file changes
    mid-read on a syncing cloud folder) reads."""
    path = find_data_csv_path(filename)
    if not path:
        raise FileNotFoundError(
            f"{filename} not found in: " + ", ".join(_data_csv_candidate_dirs())
        )
    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        raise ValueError(f"{path} is empty (0 bytes) - possibly still syncing/downloading")
    text = raw.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError(f"{path} has no data rows (only {len(lines)} line(s))")
    return lines


def _read_equip_csv_lines():
    return _read_csv_lines(EQUIP_CSV_FILENAME)


CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".tlr_save_editor_config.json")


def load_app_config():
    """Small persisted settings file (currently just remembers the last
    folder picked for 'Find saves'), stored in the user's home directory
    so it works the same whether the app is run as a script or wrapped
    into a double-clickable .app."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_app_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def scan_for_sav_files(root_dirs, max_depth=6, max_results=300, max_seconds=8):
    """Recursively look for *.sav files under the given root directories.
    The exact save location for The Last Remnant Remastered varies by
    platform/install, so this isn't a guaranteed hit - it's a bounded
    scan (depth/result/time capped so it can't hang on a huge disk) meant
    to save the user from having to browse for the file by hand once
    they've pointed it at roughly the right folder."""
    start = time.time()
    found = []
    seen_dirs = set()
    for root_dir in root_dirs:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        base_depth = os.path.normpath(root_dir).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root_dir):
            if time.time() - start > max_seconds or len(found) >= max_results:
                return found
            depth = os.path.normpath(dirpath).count(os.sep) - base_depth
            if depth >= max_depth:
                dirnames[:] = []
                continue
            if dirpath in seen_dirs:
                continue
            seen_dirs.add(dirpath)
            for fn in filenames:
                if fn.lower().endswith(".sav"):
                    found.append(os.path.join(dirpath, fn))
                    if len(found) >= max_results:
                        return found
    return found


def filter_combo_values(all_values, typed):
    """Pure helper behind the searchable-combobox live filter: given the
    full list of names and whatever text is currently typed, return the
    subset whose name contains the typed text (case-insensitive substring
    match). Empty/whitespace-only input returns the full list unchanged."""
    typed = (typed or "").strip().lower()
    if not typed:
        return list(all_values)
    return [v for v in all_values if typed in v.lower()]


def load_equip_names():
    """Loads {item_id: name} from EquipItems.csv. Returns {} if the file
    isn't found or can't be parsed (equipment editing UI will just show
    raw IDs then, and the app warns the user on startup - see
    SaveEditorApp._load_equip_database)."""
    try:
        lines = _read_equip_csv_lines()
    except Exception:
        return {}
    names = {}
    for line in lines[1:]:  # skip header
        parts = line.split(";")
        if len(parts) < 2:
            continue
        try:
            item_id = int(parts[0])
        except ValueError:
            continue
        names[item_id] = parts[1]
    return names


def load_equip_stats():
    """Loads {item_id: [att, matt, def, mdef, eva, meva]} (ints) from
    EquipItems.csv. Returns {} if the file isn't found or can't be parsed."""
    try:
        lines = _read_equip_csv_lines()
    except Exception:
        return {}
    stats = {}
    for line in lines[1:]:  # skip header
        parts = line.split(";")
        if len(parts) < 2 + EQUIP_STAT_COUNT:
            continue
        try:
            item_id = int(parts[0])
            vals = [int(v) for v in parts[2:2 + EQUIP_STAT_COUNT]]
        except ValueError:
            continue
        stats[item_id] = vals
    return stats


def load_accessory_names():
    """Loads {item_id: name} from AccItems.csv (Value;English;German -
    no stat columns, unlike EquipItems.csv). Returns {} if not found."""
    try:
        lines = _read_csv_lines(ACCESSORY_CSV_FILENAME)
    except Exception:
        return {}
    names = {}
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 2:
            continue
        try:
            item_id = int(parts[0])
        except ValueError:
            continue
        names[item_id] = parts[1]
    return names


def accessory_slot_base(slot_index):
    return ACCESSORY_TABLE_BASE + slot_index * ACCESSORY_RECORD_SIZE


def read_accessories(dec):
    """Returns a list of (slot_index, item_id, order) for all
    ACCESSORY_SLOT_COUNT slots. `order` is the game's own display-order
    counter (0-based, contiguous among non-empty slots) - kept here so
    callers can compute the next free order value when adding an item."""
    slots = []
    for i in range(ACCESSORY_SLOT_COUNT):
        base = accessory_slot_base(i)
        item_id, order_raw = struct.unpack("<II", dec[base:base + 8])
        order = order_raw if order_raw != ACCESSORY_EMPTY_ORDER else None
        slots.append((i, item_id, order))
    return slots


def next_accessory_order(dec):
    """The next free display-order value = count of currently non-empty
    accessory slots (orders are compacted/contiguous from 0 by the
    game itself, confirmed by controlled test: selling an item shifted
    every later item's order down by 1)."""
    count = 0
    for _, item_id, _ in read_accessories(dec):
        if item_id != ACCESSORY_EMPTY_ID:
            count += 1
    return count


def write_accessory_slot(buf, slot_index, item_id, order):
    base = accessory_slot_base(slot_index)
    buf[base:base + 4] = struct.pack("<I", item_id)
    buf[base + 4:base + 8] = struct.pack("<I", order)


def clear_accessory_slot(buf, slot_index):
    write_accessory_slot(buf, slot_index, ACCESSORY_EMPTY_ID, ACCESSORY_EMPTY_ORDER)


def equip_slot_base(slot_index):
    return EQUIP_TABLE_BASE + slot_index * EQUIP_RECORD_SIZE


def equip_slot_addr(slot_index):
    return equip_slot_base(slot_index) + EQUIP_ID_REL_OFFSET


def read_equipment(dec):
    """Returns a list of (slot_index, item_id) for all EQUIP_SLOT_COUNT slots."""
    slots = []
    for i in range(EQUIP_SLOT_COUNT):
        addr = equip_slot_addr(i)
        item_id = struct.unpack("<I", dec[addr:addr + 4])[0]
        slots.append((i, item_id))
    return slots


def read_equip_slot_stats(dec, slot_index):
    """Reads the 6 Att/M-Att/Def/M-Def/Eva/M-Eva values currently stored
    for a slot (the first copy of each duplicated triple)."""
    rec_base = equip_slot_base(slot_index)
    stats = []
    for i in range(EQUIP_STAT_COUNT):
        s = rec_base + EQUIP_STAT_REL_OFFSET + i * EQUIP_STAT_STRIDE
        stats.append(dec[s])
    return stats


def write_equip_slot(buf, slot_index, item_id, stats=None):
    """Writes the item ID into a slot, and (if given) also writes the
    6 Att/M-Att/Def/M-Def/Eva/M-Eva stat triples so the item actually
    has working stats in-game instead of showing as 0/0/0/0.
    `stats` is a list of 6 ints in [att, matt, def, mdef, eva, meva] order."""
    addr = equip_slot_addr(slot_index)
    buf[addr:addr + 4] = struct.pack("<I", item_id)

    if stats is None:
        return
    rec_base = equip_slot_base(slot_index)
    for i, value in enumerate(stats[:EQUIP_STAT_COUNT]):
        value = max(0, min(255, int(value)))
        s = rec_base + EQUIP_STAT_REL_OFFSET + i * EQUIP_STAT_STRIDE
        buf[s] = value
        buf[s + 1] = 0
        buf[s + 2] = value


def clear_equip_slot(buf, slot_index):
    """Empties a slot: sets the ID to the empty sentinel and zeroes out
    the stat triples too, so no stale stats linger."""
    write_equip_slot(buf, slot_index, EQUIP_EMPTY_ID, stats=[0] * EQUIP_STAT_COUNT)


# ---------------------------------------------------------------------------
# Per-character equipped items ("what a character is actually wearing", as
# opposed to EQUIP_TABLE_BASE above which is the carried/unequipped pool).
# ---------------------------------------------------------------------------
# Found via a controlled test: equipped a specific weapon on Rush in-game
# (Shamshir -> Warrior's Broadsword) and diffed two saves. The changed item
# ID landed in a record using the exact same layout as the carried-equipment
# table above (ID at rel +12, 6 stat triples at rel +21 stride 3), but in a
# completely separate array.
#
# The array covers every character in Chars.csv order (same catalog used for
# the Union roster editor), 2 consecutive slots per character (slot 1 =
# weapon, slot 2 = shield/secondary - both were confirmed populated on
# several named characters, e.g. Rush: Shamshir + Superior Targe, David:
# Durendal + Elite's Buckler). This table is also where each character's
# personal/unique weapon lives (e.g. "Emma's Longsword") - items that don't
# show up anywhere in the general carried-equipment pool.
CHAR_EQUIP_TABLE_BASE = 0x25F00
CHAR_EQUIP_RECORD_SIZE = 0x78   # 120 bytes, same record layout as EQUIP_RECORD_SIZE
CHAR_EQUIP_SLOTS_PER_CHAR = 2


def char_equip_slot_base(char_id, slot):
    """slot is 0 (weapon) or 1 (shield/secondary)."""
    index = char_id * CHAR_EQUIP_SLOTS_PER_CHAR + slot
    return CHAR_EQUIP_TABLE_BASE + index * CHAR_EQUIP_RECORD_SIZE


def read_char_equip_item(dec, char_id, slot):
    addr = char_equip_slot_base(char_id, slot) + EQUIP_ID_REL_OFFSET
    return struct.unpack("<I", dec[addr:addr + 4])[0]


def read_char_equip_stats(dec, char_id, slot):
    rec_base = char_equip_slot_base(char_id, slot)
    stats = []
    for i in range(EQUIP_STAT_COUNT):
        s = rec_base + EQUIP_STAT_REL_OFFSET + i * EQUIP_STAT_STRIDE
        stats.append(dec[s])
    return stats


def write_char_equip_slot(buf, char_id, slot, item_id, stats=None):
    """Same write pattern as write_equip_slot(), applied to a character's
    worn-item record instead of the carried-inventory table."""
    rec_base = char_equip_slot_base(char_id, slot)
    addr = rec_base + EQUIP_ID_REL_OFFSET
    buf[addr:addr + 4] = struct.pack("<I", item_id)

    if stats is None:
        return
    for i, value in enumerate(stats[:EQUIP_STAT_COUNT]):
        value = max(0, min(255, int(value)))
        s = rec_base + EQUIP_STAT_REL_OFFSET + i * EQUIP_STAT_STRIDE
        buf[s] = value
        buf[s + 1] = 0
        buf[s + 2] = value


def clear_char_equip_slot(buf, char_id, slot):
    write_char_equip_slot(buf, char_id, slot, EQUIP_EMPTY_ID, stats=[0] * EQUIP_STAT_COUNT)


# ---------------------------------------------------------------------------
# Save file logic (same as the CLI version)
# ---------------------------------------------------------------------------

def decompress_save(path):
    with open(path, "rb") as f:
        data = f.read()
    return zlib.decompress(data)


def compress_save(dec_bytes, level=9):
    return zlib.compress(dec_bytes, level)


def recalc_checksum(dec_bytes):
    """SHA1(dec[0x20:]) is written into dec[0x0C:0x20] - formula found by
    reverse-engineering TLRPSave.exe (ChecksumFix), confirmed on real saves."""
    buf = bytearray(dec_bytes)
    new_hash = hashlib.sha1(bytes(buf[CHECKSUM_DATA_START:])).digest()
    buf[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 20] = new_hash
    return buf


def verify_checksum(dec_bytes):
    stored = bytes(dec_bytes[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 20])
    actual = hashlib.sha1(bytes(dec_bytes[CHECKSUM_DATA_START:])).digest()
    return stored == actual


def backup_if_exists(path):
    """If a file already exists at `path`, copy it to `path + '.bak'`
    before it gets overwritten. Returns the backup path, or None if
    there was nothing to back up."""
    if os.path.exists(path):
        backup_path = path + ".bak"
        shutil.copy2(path, backup_path)
        return backup_path
    return None


def read_header_info(dec):
    magic = dec[0:4]
    version = struct.unpack("<i", dec[4:8])[0]
    size_field = struct.unpack("<i", dec[8:12])[0]
    checksum_ok = verify_checksum(dec)
    loc = try_decode_location(dec)
    g1 = struct.unpack("<i", dec[GOLD_OFFSET:GOLD_OFFSET + 4])[0]
    g2 = struct.unpack("<i", dec[GOLD_LIFETIME_OFFSET:GOLD_LIFETIME_OFFSET + 4])[0]
    br = struct.unpack("<h", dec[BR_OFFSET:BR_OFFSET + 2])[0]
    playtime = read_playtime_seconds(dec)
    diggs_attempts = read_mr_diggs_attempts(dec)
    diggs_max_attempts = read_mr_diggs_max_attempts(dec)
    monster_kills = read_monster_kills(dec)
    rush_stats = {}
    for key, label_key, rel_off, size in RUSH_STATS:
        rush_stats[key] = read_rush_stat(dec, rel_off, size)
    union_stats = [read_union_stats(dec, i) for i in range(UNION_COUNT)]
    return {
        "magic": magic.decode("ascii", errors="replace"),
        "version": version,
        "size_field": size_field,
        "actual_size": len(dec),
        "checksum_ok": checksum_ok,
        "location": loc,
        "gold1": g1,
        "gold2": g2,
        "br": br,
        "playtime": playtime,
        "diggs_attempts": diggs_attempts,
        "diggs_max_attempts": diggs_max_attempts,
        "monster_kills": monster_kills,
        "rush_stats": rush_stats,
        "union_stats": union_stats,
    }


def try_decode_location(dec, start=0x30, max_len=200):
    chunk = dec[start:start + max_len]
    end = len(chunk)
    for i in range(0, len(chunk) - 1, 2):
        if chunk[i] == 0 and chunk[i + 1] == 0:
            end = i
            break
    try:
        return chunk[:end].decode("utf-16-le", errors="replace")
    except Exception:
        return "?"


def find_diff_regions(a, b):
    regions = []
    i, n = 0, min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            regions.append((i, j))
            i = j
        else:
            i += 1
    return regions


def merge_regions(regions, gap=8):
    merged = []
    for s, e in regions:
        if merged and s - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def search_value_in_buffer(dec, value):
    hits = []
    for size, fmt in [(1, "<b"), (2, "<h"), (4, "<i"), (8, "<q")]:
        try:
            packed = struct.pack(fmt, value)
        except struct.error:
            continue
        start = 0
        while True:
            idx = dec.find(packed, start)
            if idx == -1:
                break
            hits.append((idx, size))
            start = idx + 1
    return hits


# ---------------------------------------------------------------------------
# Translations / Переклади
# ---------------------------------------------------------------------------

STRINGS = {
    "uk": {
        "title": "TLR Save Editor — The Last Remnant Remastered",
        "open_button": "Відкрити .sav файл...",
        "find_saves_btn": "Знайти сейви...",
        "find_saves_pick_dir_title": "Обери папку, де шукати сейви гри",
        "find_saves_win_title": "Знайдені сейви",
        "find_saves_dir_label": "Папка пошуку: {dir}",
        "find_saves_none_found": "У цій папці .sav файлів не знайдено.",
        "find_saves_open_btn": "Відкрити",
        "find_saves_change_dir_btn": "Інша папка...",
        "cancel_btn": "Скасувати",
        "no_file": "Файл не вибрано",
        "info_frame": "Інформація про сейв",
        "char_frame": "Персонаж — Rush",
        "char_toggle_expand": "▶ Раш (розгорнути статы)",
        "char_toggle_collapse": "▼ Раш (згорнути)",
        "char_hint": "Тимчасова зміна для одного важкого бою — не перманентна. "
                     "Значення видно на Union Board і в персонажа до бою, але після "
                     "бою гра перераховує їх заново з власних даних і скидає на попередні.",
        "rush_hp_label": "HP:",
        "rush_ap_label": "AP:",
        "rush_f3_label": "AP +/хід:",
        "rush_f4_label": "Стат #4 (?):",
        "rush_f5_label": "Стат #5 (?):",
        "rush_str_label": "STR:",
        "rush_int_label": "INT (?):",
        "rush_spd_label": "SPD (?):",
        "rush_uniq_label": "ATK:",
        "rush_f10_label": "MYS:",
        "rush_f11_label": "DEF:",
        "rush_f12_label": "M.DEF:",
        "gold_frame": "Gold / Battle Rank",
        "gold_label": "Gold:",
        "gold_lifetime_label": "Lifetime Gold:",
        "br_label": "Battle Rank:",
        "save_button": "Зберегти як новий .sav файл",
        "preset_max_gold": "Max Gold",
        "preset_br_1": "BR 1",
        "preset_br_99": "BR 99",
        "preset_br_250": "BR 250",
        "search_frame": "Пошук числа у сейві (для дослідження нових полів)",
        "search_number_label": "Число:",
        "search_button": "Знайти",
        "diff_frame": "Порівняти з іншим сейвом",
        "diff_button": "Обрати другий сейв і показати різницю...",
        "readme_button": "README",
        "select_sav_title": "Обери .sav файл",
        "select_sav2_title": "Обери другий .sav файл для порівняння",
        "save_as_title": "Зберегти новий .sav файл",
        "filetype_sav": "The Last Remnant save",
        "filetype_all": "Усі файли",
        "err_title": "Помилка",
        "warn_title": "Немає файлу",
        "warn_open_first": "Спочатку відкрий .sav файл.",
        "warn_open_first2": "Спочатку відкрий перший .sav файл.",
        "err_decompress": "Не вдалось розпакувати файл:\n{e}",
        "err_int": "Gold і Battle Rank повинні бути цілими числами.",
        "err_int_search": "Введи ціле число.",
        "done_title": "Готово",
        "done_msg": "Збережено: {path}\n\nSHA1 чек-суму перераховано автоматично — "
                     "файл має коректно завантажитись у грі.",
        "backup_line": "\n\nІснуючий файл був збережений як бекап: {backup}",
        "search_none": "Значення {value} не знайдено.",
        "search_found": "Знайдено {n} співпадінь:",
        "search_offset_line": "  offset={off}   розмір={size} байт",
        "diff_title": "Різниця: {a}  ->  {b}",
        "diff_found": "Знайдено {n} блоків змін (об'єднано, gap<=8):\n\n",
        "diff_more_hidden": "... ще {n} блоків не показано.",
        "magic_line": "Magic: {magic}    Версія: {version}\n",
        "size_line": "Розмір розпакований: {size} байт (поле в заголовку: {size_field})\n",
        "checksum_ok_line": "SHA1 чек-сума: OK ✅\n",
        "checksum_bad_line": "SHA1 чек-сума: НЕ ЗБІГАЄТЬСЯ ⚠️\n",
        "location_line": "Локація: {loc}\n",
        "playtime_line": "Час у грі: {playtime} (гіпотеза, не підтверджено екраном гри)\n",
        "gold_line": "Золото: {gold1}  (всього накопичено за гру: {gold2})\n",
        "br_line": "Battle Rank: {br}\n",
        "diggs_line": "Mr. Diggs: {cur} / {max} спроб\n",
        "monster_kills_line": "Вбито мобів (гіпотеза, підтверджено на 4 контрольних боях +5/+5/+4/+2): {n}\n",
        "unions_line_header": "Юніони (HP / AP):\n",
        "union_line": "  Юніон {n}: HP {hp}, AP +{apf}/{ap}\n",
        "inventory_line_header": "Інвентар:\n",
        "inventory_line": "  {label}: {count}\n",
        "playtime_label": "Час у грі:",
        "tip_playtime": "Offset 0x04F4C (int32 LE), у секундах.\nЗНАЙДЕНО ЕВРИСТИЧНО: серед ~110 полів-кандидатів це\n"
                         "єдине, що монотонно зростало між 5 тестовими сейвами\n"
                         "на правдоподібну кількість секунд реального часу між\n"
                         "збереженнями. НЕ підтверджено звіркою з екраном гри -\n"
                         "редагуй з обережністю. Формат поля: ГГ:ХХ:СС.",
        "diggs_attempts_label": "Mr. Diggs (спроби):",
        "diggs_max_label": "Mr. Diggs (максимум):",
        "diggs_fill_btn": "Заповнити до максимуму",
        "tip_diggs_attempts": "Offset 0x4F5C (int32 LE) - поточні спроби Mr. Diggs.\n"
                               "Підтверджено контрольним тестом: 3 сейви з 12/11/10\n"
                               "спробами (по одному викопуванню між ними) співпали\n"
                               "рівно на цьому офсеті.",
        "tip_diggs_max": "Offset 0x4F60 (int32 LE) - ліміт спроб Mr. Diggs\n"
                          "(константа 12 у всіх трьох тестових сейвах, окреме\n"
                          "поле від лічильника поточних спроб). Підняття цього\n"
                          "значення вище 12 - ЕКСПЕРИМЕНТАЛЬНО, не перевірено\n"
                          "в грі.",
        "monster_kills_label": "Вбито мобів:",
        "tip_monster_kills": "Offset 0x1D2DA (uint16 LE).\nПідтверджено 4 контрольними боями: приріст точно\n"
                              "збігся з кількістю вбитих мобів (+5, +5, +4, +2) на\n"
                              "5 послідовних сейвах, стартове значення 3652 -\n"
                              "правдоподібно для ~41 години гри. Раніше помилково\n"
                              "вважали цим лічильником offset 0x1D5FA (замалі\n"
                              "числа 18-34) - той залишений у коді про запас, але\n"
                              "не показується в інтерфейсі.",
        "tip_gold": "Offset 0x1D978 (int32 LE).\nПідтверджено контрольним тестом: продаж\n"
                    "предмета за 6 gold дав рівно +6 у цьому полі.",
        "tip_gold_lifetime": "Offset 0x25A5A (int32 LE).\nЗавжди змінюється синхронно з Gold, але лежить\n"
                             "серед масиву дрібних службових чисел. Найімовірніше -\n"
                             "лічильник 'всього золота за гру' (lifetime), а не гаманець.\n"
                             "Редагуй з обережністю.",
        "tip_br": "Offset 0x259DD (int16 LE) - РЕАЛЬНИЙ Battle Rank.\n"
                  "Є ще косметичний кеш на offset 0x28 (тільки для екрану\n"
                  "завантаження) і лічильник BR EXP на offset 0x259DF (0-499,\n"
                  "скидається при рангапі). При збереженні інструмент оновлює\n"
                  "всі три поля автоматично.",
        "readme_win_title": "README — TLR Save Editor",
        "readme_content": None,  # filled below
        "version_label": "TLR Save Editor v{version}",
        "lang_button_uk": "UA",
        "lang_button_en": "EN",
        "equip_frame": "Екіпіровка (в інвентарі, не одягнена)",
        "equip_toggle_expand": "▶ Екіпіровка (розгорнути)",
        "equip_toggle_collapse": "▼ Екіпіровка (згорнути)",
        "equip_hint": "Список зброї/щитів/броні в інвентарі (не одягнених на персонажах). "
                      "Обери слот(и) у списку, вибери предмет зі списку і натисни "
                      "«Застосувати», щоб замінити його. «Заповнити порожні слоти» "
                      "проставить обраний предмет у всі порожні слоти одразу. "
                      "Характеристики (Att/M-Att/Def/M-Def/Eva/M-Eva) прописуються "
                      "автоматично з таблиці предметів. Якщо персонаж не може вдіти "
                      "предмет - це обмеження за класом персонажа (визначає сама гра, "
                      "не цей інструмент).",
        "equip_empty_slot": "— порожньо —",
        "equip_setitem_label": "Предмет:",
        "tip_equip_edit_existing": "Щоб змінити стати вже екіпірованого предмета: вибери\n"
                                    "один слот у списку зверху - поля \"Предмет\" і стати\n"
                                    "самі підвантажать те, що там ЗАРАЗ (не базові стати з\n"
                                    "довідника), онови потрібні числа і натисни кнопку\n"
                                    "застосування.",
        "equip_apply_btn": "Застосувати до обраних",
        "equip_fillempty_btn": "Заповнити порожні слоти",
        "equip_clear_btn": "Очистити обрані",
        "equip_col_slot": "#",
        "equip_col_name": "Предмет",
        "warn_select_slot": "Спочатку обери один або декілька слотів у списку.",
        "warn_pick_item": "Обери предмет зі списку.",
        "err_unknown_item": "Невідомий предмет: {name}",
        "equip_filled_msg": "Заповнено порожніх слотів: {n}",
        "equip_max_stats_btn": "Максимум (255)",
        "tab_gold": "Основне",
        "tab_union": "Union",
        "tab_inventory": "Inventory",
        "tab_charequip": "Екіпіровка персонажів",
        "tab_tools": "Інструменти",
        "subtab_equipment": "Equipment",
        "subtab_accessories": "Accessories",
        "subtab_consumables": "Consumables",
        "subtab_components": "Components",
        "subtab_monsters": "Captured Monsters",
        "subtab_special": "Special Items",
        "charequip_char_label": "Персонаж:",
        "charequip_slot_weapon": "Зброя:",
        "charequip_slot_shield": "Щит/друге:",
        "charequip_apply_btn": "Застосувати екіпіровку",
        "charequip_applied_msg": "Екіпіровку персонажа {name} оновлено.",
        "tip_charequip": "Що персонаж РЕАЛЬНО носить на собі (окремо від загального "
                          "інвентарю). Працює для БУДЬ-ЯКОГО персонажа, включно з тими, "
                          "кому в грі не можна вручну міняти зброю (вони одягають самі, "
                          "рандомно) — тут можна поставити конкретний предмет напряму, "
                          "включно з унікальною особистою зброєю персонажів (напр. "
                          "Emma's Longsword). Знайдено і підтверджено контрольованим тестом "
                          "(зміна зброї Раша в грі, звірка сейвів до/після).",
        "equip_db_status_ok": "Базу предметів завантажено: {n} шт.",
        "equip_db_status_missing": "⚠ Базу предметів (EquipItems.csv) не знайдено — назви й список предметів не працюватимуть.",
        "equip_reload_btn": "Перезавантажити базу",
        "equip_db_missing_msg": "Не вдалось знайти або прочитати {filename}.\n\n"
                                 "Шукав тут:\n{dirs}\n\n"
                                 "Переконайся, що файл лежить поруч зі скриптом. Якщо "
                                 "папка синхронізується через iCloud/OneDrive/Dropbox — "
                                 "дочекайся завершення завантаження файлу і натисни "
                                 "«Перезавантажити базу».",
        "items_col_qty": "К-сть",
        "items_qty_label": "Нова кількість:",
        "err_grant_new_item": "Не можна видати предмет, якого зараз 0 — ще не перевірено, "
                               "чи це безпечно (див. пояснення в чаті). Можна лише "
                               "змінювати кількість того, що вже є в інвентарі.",
        "items_grant_label": "Новий предмет:",
        "items_grant_btn": "Видати",
        "items_granted_msg": "Видано: {name} x{qty}",
        "err_already_owned": "Цей предмет вже є в інвентарі — зміни кількість через список зверху, "
                              "а не через видачу нового.",
        "rush_max_stats_btn": "Максимум статів (HP 9999 / AP 999 / решта 255)",
        "union_select_label": "Юніон:",
        "union_roster_label": "Склад юніону (слоти 2-5, ЕКСПЕРИМЕНТАЛЬНО):",
        "union_leader_label": "Лідер:",
        "union_slot_n": "Слот {n}:",
        "union_slot_empty": "-- порожньо --",
        "union_roster_apply_btn": "Застосувати склад",
        "union_roster_applied_msg": "Склад юніону оновлено. Стати юніону можуть виглядати "
                                     "застарілими, доки не зайдеш у бій чи формейшн-екран — "
                                     "гра сама перерахує їх.",
        "union_all_250_btn": "Весь юніон: 250",
        "union_all_max_btn": "Весь юніон: MAX (255)",
        "union_export_profile_btn": "Зберегти профіль...",
        "union_import_profile_btn": "Завантажити профіль...",
        "union_profile_saved_msg": "Профіль спорядження збережено: {path}",
        "union_profile_loaded_msg": "Профіль завантажено в поля. Натисни "
                                     "\"Застосувати склад\", щоб записати в сейв.",
        "union_profile_load_error": "Не вдалося завантажити профіль: {err}",
        "diff_label_br_exp": "Battle Rank EXP",
        "diff_label_br_cache": "Battle Rank (кеш екрану завантаження)",
        "diff_label_acc_slot": "Аксесуари (склад), слот {n}",
        "diff_label_equip_slot": "Інвентар: зброя/спорядження, слот {n}",
        "diff_label_item_slot": "Предмети, запис {n} ({name})",
        "diff_label_union": "Юніон {n} (стати/склад)",
        "diff_label_charequip": "Спорядження персонажа: {char}, слот {slot}",
        "err_chars_db_missing": "Не знайдено Chars.csv (потрібен для списку персонажів).",
        "err_unknown_char": "Невідомий персонаж: {name}",
        "err_duplicate_char_same_union": "Один і той самий персонаж вибраний у кількох слотах.",
        "err_duplicate_char_other_union": "{name} вже є у Юніоні {union} — спершу прибери "
                                           "звідти.",
        "tip_union_roster": "Лідер + слоти 2-5 юніону. ПІДТВЕРДЖЕНО В ГРІ: якщо\n"
                             "виставити лідера на порожній юніон (6, 7 або 8), він\n"
                             "автоматично активується (з'являється в списку, спершу\n"
                             "як \"Dummy\" з нульовими статами, а після одного бою\n"
                             "показує реальне ім'я й стати) — стає повноцінним\n"
                             "юніоном, куди потім можна набирати ще персонажів.\n"
                             "Очищення лідера (порожньо) деактивує юніон назад.\n"
                             "Дублі персонажів у кількох юніонах теж підтверджені\n"
                             "безпечними. Обережно з персонажами, яких ще не\n"
                             "завербовано по сюжету (боси/унікальні валили екран\n"
                             "складу юніону в тестах, хоч у бою працювали).",
    },
    "en": {
        "title": "TLR Save Editor — The Last Remnant Remastered",
        "open_button": "Open .sav file...",
        "find_saves_btn": "Find saves...",
        "find_saves_pick_dir_title": "Pick a folder to search for game saves",
        "find_saves_win_title": "Saves found",
        "find_saves_dir_label": "Search folder: {dir}",
        "find_saves_none_found": "No .sav files found in this folder.",
        "find_saves_open_btn": "Open",
        "find_saves_change_dir_btn": "Different folder...",
        "cancel_btn": "Cancel",
        "no_file": "No file selected",
        "info_frame": "Save Info",
        "char_frame": "Character — Rush",
        "char_toggle_expand": "▶ Rush (expand stats)",
        "char_toggle_collapse": "▼ Rush (collapse)",
        "char_hint": "Temporary boost for one tough battle - not permanent. "
                     "Values show on the Union Board and character screen before the "
                     "battle, but the game recalculates them from its own data "
                     "afterward and resets them.",
        "rush_hp_label": "HP:",
        "rush_ap_label": "AP:",
        "rush_f3_label": "AP +/turn:",
        "rush_f4_label": "Stat #4 (?):",
        "rush_f5_label": "Stat #5 (?):",
        "rush_str_label": "STR:",
        "rush_int_label": "INT (?):",
        "rush_spd_label": "SPD (?):",
        "rush_uniq_label": "ATK:",
        "rush_f10_label": "MYS:",
        "rush_f11_label": "DEF:",
        "rush_f12_label": "M.DEF:",
        "gold_frame": "Gold / Battle Rank",
        "gold_label": "Gold:",
        "gold_lifetime_label": "Lifetime Gold:",
        "br_label": "Battle Rank:",
        "save_button": "Save as new .sav file",
        "preset_max_gold": "Max Gold",
        "preset_br_1": "BR 1",
        "preset_br_99": "BR 99",
        "preset_br_250": "BR 250",
        "search_frame": "Search for a number in the save (for finding new fields)",
        "search_number_label": "Number:",
        "search_button": "Search",
        "diff_frame": "Compare with another save",
        "diff_button": "Choose a second save and show the difference...",
        "readme_button": "README",
        "select_sav_title": "Choose a .sav file",
        "select_sav2_title": "Choose a second .sav file to compare",
        "save_as_title": "Save new .sav file",
        "filetype_sav": "The Last Remnant save",
        "filetype_all": "All files",
        "err_title": "Error",
        "warn_title": "No file",
        "warn_open_first": "Open a .sav file first.",
        "warn_open_first2": "Open the first .sav file first.",
        "err_decompress": "Could not decompress the file:\n{e}",
        "err_int": "Gold and Battle Rank must be whole numbers.",
        "err_int_search": "Enter a whole number.",
        "done_title": "Done",
        "done_msg": "Saved: {path}\n\nThe SHA1 checksum was recalculated automatically — "
                     "the file should load correctly in-game.",
        "backup_line": "\n\nThe existing file was backed up as: {backup}",
        "search_none": "Value {value} not found.",
        "search_found": "Found {n} matches:",
        "search_offset_line": "  offset={off}   size={size} bytes",
        "diff_title": "Diff: {a}  ->  {b}",
        "diff_found": "Found {n} changed blocks (merged, gap<=8):\n\n",
        "diff_more_hidden": "... {n} more blocks not shown.",
        "magic_line": "Magic: {magic}    Version: {version}\n",
        "size_line": "Decompressed size: {size} bytes (header field: {size_field})\n",
        "checksum_ok_line": "SHA1 checksum: OK ✅\n",
        "checksum_bad_line": "SHA1 checksum: MISMATCH ⚠️\n",
        "location_line": "Location: {loc}\n",
        "playtime_line": "Playtime: {playtime} (hypothesis, not confirmed against an in-game display)\n",
        "gold_line": "Gold: {gold1}  (total earned this game: {gold2})\n",
        "br_line": "Battle Rank: {br}\n",
        "diggs_line": "Mr. Diggs: {cur} / {max} attempts\n",
        "monster_kills_line": "Monsters killed (hypothesis, confirmed across 4 controlled battles +5/+5/+4/+2): {n}\n",
        "unions_line_header": "Unions (HP / AP):\n",
        "union_line": "  Union {n}: HP {hp}, AP +{apf}/{ap}\n",
        "inventory_line_header": "Inventory:\n",
        "inventory_line": "  {label}: {count}\n",
        "playtime_label": "Playtime:",
        "tip_playtime": "Offset 0x04F4C (int32 LE), in seconds.\nHEURISTICALLY FOUND: out of ~110 candidate fields,\n"
                         "this was the only one that increased monotonically across\n"
                         "5 test saves by a plausible amount of real elapsed time\n"
                         "between saves. NOT confirmed against an in-game display -\n"
                         "edit with caution. Field format: HH:MM:SS.",
        "diggs_attempts_label": "Mr. Diggs (attempts):",
        "diggs_max_label": "Mr. Diggs (max):",
        "diggs_fill_btn": "Fill to max",
        "tip_diggs_attempts": "Offset 0x4F5C (int32 LE) - current Mr. Diggs attempts.\n"
                               "Confirmed by a controlled test: 3 saves with 12/11/10\n"
                               "attempts (one dig used between each) matched exactly\n"
                               "at this offset.",
        "tip_diggs_max": "Offset 0x4F60 (int32 LE) - Mr. Diggs attempt cap\n"
                          "(constant 12 across all 3 test saves, a separate field\n"
                          "from the current-attempts counter). Raising this above\n"
                          "12 is EXPERIMENTAL, not verified in-game.",
        "monster_kills_label": "Monsters killed:",
        "tip_monster_kills": "Offset 0x1D2DA (uint16 LE).\nConfirmed across 4 controlled battles: the increase\n"
                              "matched the exact number of monsters killed (+5, +5,\n"
                              "+4, +2) across 5 consecutive saves, starting at 3652 -\n"
                              "plausible for ~41 hours of playtime. Earlier we\n"
                              "mistakenly thought offset 0x1D5FA was this counter\n"
                              "(too-small numbers, 18-34) - that's kept in the code\n"
                              "for reference but not shown in the UI.",
        "tip_gold": "Offset 0x1D978 (int32 LE).\nConfirmed by a controlled test: selling an\n"
                    "item for 6 gold gave exactly +6 in this field.",
        "tip_gold_lifetime": "Offset 0x25A5A (int32 LE).\nAlways changes in sync with Gold, but sits\n"
                             "among an array of small internal counters. Most likely a\n"
                             "'lifetime gold earned' counter, not the wallet itself.\n"
                             "Edit with caution.",
        "tip_br": "Offset 0x259DD (int16 LE) - the REAL Battle Rank.\n"
                  "There's also a cosmetic cache at offset 0x28 (load-screen\n"
                  "display only) and a BR EXP counter at offset 0x259DF (0-499,\n"
                  "resets on rank-up). Saving updates all three fields\n"
                  "automatically.",
        "readme_win_title": "README — TLR Save Editor",
        "readme_content": None,  # filled below
        "version_label": "TLR Save Editor v{version}",
        "lang_button_uk": "UA",
        "lang_button_en": "EN",
        "equip_frame": "Equipment (carried, not equipped)",
        "equip_toggle_expand": "▶ Equipment (expand)",
        "equip_toggle_collapse": "▼ Equipment (collapse)",
        "equip_hint": "Weapons/shields/armor carried in the inventory (not worn by any "
                      "character). Select slot(s) in the list, pick an item from the "
                      "dropdown, and click 'Apply' to replace it. 'Fill empty slots' "
                      "sets the chosen item into every currently empty slot at once. "
                      "Stats (Att/M-Att/Def/M-Def/Eva/M-Eva) are filled in automatically "
                      "from the item table. If a character can't equip an item, that's "
                      "a class restriction enforced by the game itself, not this tool.",
        "equip_empty_slot": "— empty —",
        "equip_setitem_label": "Item:",
        "tip_equip_edit_existing": "To change an already-equipped item's stats: select a\n"
                                    "single slot in the list above - the \"Item\" field and\n"
                                    "the stat fields auto-fill with what's actually there\n"
                                    "right now (not the reference baseline), tweak the\n"
                                    "numbers you want, then click the apply button.",
        "equip_apply_btn": "Apply to selected",
        "equip_fillempty_btn": "Fill empty slots",
        "equip_clear_btn": "Clear selected",
        "equip_col_slot": "#",
        "equip_col_name": "Item",
        "warn_select_slot": "Select one or more slots in the list first.",
        "warn_pick_item": "Pick an item from the dropdown.",
        "err_unknown_item": "Unknown item: {name}",
        "equip_filled_msg": "Filled empty slots: {n}",
        "equip_max_stats_btn": "Max (255)",
        "tab_gold": "Main",
        "tab_union": "Union",
        "tab_inventory": "Inventory",
        "tab_charequip": "Character Equipment",
        "tab_tools": "Tools",
        "subtab_equipment": "Equipment",
        "subtab_accessories": "Accessories",
        "subtab_consumables": "Consumables",
        "subtab_components": "Components",
        "charequip_char_label": "Character:",
        "charequip_slot_weapon": "Weapon:",
        "charequip_slot_shield": "Shield/secondary:",
        "charequip_apply_btn": "Apply equipment",
        "charequip_applied_msg": "{name}'s equipment updated.",
        "tip_charequip": "What a character is ACTUALLY wearing (separate from the general "
                          "carried inventory). Works for ANY character, including ones the "
                          "game doesn't let you manually re-equip (they auto-equip randomly "
                          "on their own) - here you can set a specific item directly, "
                          "including a character's unique personal weapon (e.g. Emma's "
                          "Longsword). Found and confirmed via a controlled test (changing "
                          "Rush's weapon in-game, diffing before/after saves).",
        "subtab_monsters": "Captured Monsters",
        "subtab_special": "Special Items",
        "equip_db_status_ok": "Item database loaded: {n} items",
        "equip_db_status_missing": "⚠ Item database (EquipItems.csv) not found — item names and the dropdown won't work.",
        "equip_reload_btn": "Reload database",
        "equip_db_missing_msg": "Could not find or read {filename}.\n\n"
                                 "Searched in:\n{dirs}\n\n"
                                 "Make sure the file is next to the script. If the folder "
                                 "syncs via iCloud/OneDrive/Dropbox, wait for the file to "
                                 "finish downloading, then click \"Reload database\".",
        "items_col_qty": "Qty",
        "items_qty_label": "New quantity:",
        "err_grant_new_item": "Can't grant an item you currently have 0 of - not yet "
                               "verified safe (see chat for details). Only changing the "
                               "quantity of items you already own is supported.",
        "items_grant_label": "New item:",
        "items_grant_btn": "Grant",
        "items_granted_msg": "Granted: {name} x{qty}",
        "err_already_owned": "You already have this item - change its quantity via the "
                              "list above instead of granting it again.",
        "rush_max_stats_btn": "Max stats (HP 9999 / AP 999 / rest 255)",
        "union_select_label": "Union:",
        "union_roster_label": "Union roster (slots 2-5, EXPERIMENTAL):",
        "union_leader_label": "Leader:",
        "union_slot_n": "Slot {n}:",
        "union_slot_empty": "-- empty --",
        "union_roster_apply_btn": "Apply roster",
        "union_roster_applied_msg": "Union roster updated. The union's stats may look stale "
                                     "until you enter a battle or the formation screen - the "
                                     "game recalculates them itself.",
        "union_all_250_btn": "Whole union: 250",
        "union_all_max_btn": "Whole union: MAX (255)",
        "union_export_profile_btn": "Save profile...",
        "union_import_profile_btn": "Load profile...",
        "union_profile_saved_msg": "Equipment profile saved: {path}",
        "union_profile_loaded_msg": "Profile loaded into the fields. Click "
                                     "\"Apply roster\" to write it to the save.",
        "union_profile_load_error": "Could not load profile: {err}",
        "diff_label_br_exp": "Battle Rank EXP",
        "diff_label_br_cache": "Battle Rank (load-screen cache)",
        "diff_label_acc_slot": "Accessories (carried), slot {n}",
        "diff_label_equip_slot": "Inventory: weapon/equipment, slot {n}",
        "diff_label_item_slot": "Items, record {n} ({name})",
        "diff_label_union": "Union {n} (stats/roster)",
        "diff_label_charequip": "Character equipment: {char}, slot {slot}",
        "err_chars_db_missing": "Chars.csv not found (needed for the character list).",
        "err_unknown_char": "Unknown character: {name}",
        "err_duplicate_char_same_union": "The same character is selected in more than one slot.",
        "err_duplicate_char_other_union": "{name} is already in Union {union} - remove them "
                                           "from there first.",
        "tip_union_roster": "Leader + Union slots 2-5. CONFIRMED IN-GAME: setting a\n"
                             "leader on an empty union (6, 7, or 8) activates it\n"
                             "automatically - it shows up in the roster (first as\n"
                             "\"Dummy\" with zero stats, then with its real name and\n"
                             "stats after one battle) as a fully playable union you\n"
                             "can then recruit more members into. Clearing the leader\n"
                             "(empty) deactivates the union again. Duplicate\n"
                             "characters across multiple unions are also confirmed\n"
                             "safe. Be careful with un-recruited story characters\n"
                             "(bosses/uniques crashed the union-board screen\n"
                             "specifically in testing, though they worked fine in\n"
                             "battle).",
    },
}

README_UK = """TLR Save Editor — довідка

ФОРМАТ ФАЙЛУ
Сейв — це чистий zlib-потік. Розпакований буфер (1 719 936 байт) має
заголовок: "SAVE" + версія + розмір + 20-байтна SHA1 чек-сума + Battle
Rank (кеш) + рядок локації.

ЧЕК-СУМА (вирішено)
Байти [0x0C:0x20] — це SHA1(вміст[0x20:]). Формулу знайдено реверс-
інжинірингом .NET-утиліти TLRPSave (метод ChecksumFix). Інструмент
перераховує її автоматично при кожному збереженні — тому "corrupted
data" більше не з'являється.

GOLD — offset 0x1D978, int32 LE. Підтверджено контрольним тестом:
продаж предмета за 6 gold дав рівно +6 у цьому полі.

LIFETIME GOLD (ймовірно) — offset 0x25A5A, int32 LE. Завжди
змінюється синхронно з Gold, але лежить серед масиву дрібних
службових чисел. Найімовірніше — лічильник "всього золота за гру",
а не поточний гаманець. Редагуй з обережністю.

BATTLE RANK — offset 0x259DD, int16 LE. Це РЕАЛЬНИЙ Battle Rank,
який використовує гра (перевірено безпосередньо в грі на важких
монстрах). Є ще:
  • offset 0x28 — косметичний кеш тільки для екрану завантаження,
    не впливає на саму гру;
  • offset 0x259DF — лічильник BR EXP (0-499), рангап відбувається
    кожні 500 EXP (підтверджено на реальних сейвах гри і формулою
    з фан-вікі гри).
Інструмент при збереженні оновлює всі три поля одночасно, тож немає
розбіжностей між екраном завантаження і самою грою.

ТАБЛИЦЯ ІНВЕНТАРЮ (стара чернетка, дивись повний README.md для
актуальних офсетів Equipment/Accessories/Items) — база ~0x209E8,
записи по 12 байт:
  байти [0:4]  — невідомо/padding
  байти [4:6]  — int16, індекс слота
  байти [6:8]  — uint16, ID предмета
  байти [8:10] — int16, кількість
  байти [10:12]— невідомо/padding

ЗВІДКИ ДОВІДКОВІ CSV-ФАЙЛИ (EquipItems.csv, AccItems.csv, Items.csv)
Ці файли не наші — вони з бандлу "RemnantTrainer v1.2" для
оригінальної PC-версії гри (папка v1_2/, там же Cheat Engine
таблиця). Точного посилання на джерело завантаження немає (файли
просто лежали в проєктній папці), але в v1_2/readme.txt є перелік
контриб'юторів: lothrandier, saeri, sage_inferno, TheHologramMan,
VoxAngel, helodermatid, jesse_n, hlvietlong, artennoir, SunS_MMX,
suttyo, BR_Gamer, mikeyakame, Samsong69. Офсети з тих CSV не
підходять для Remastered-сейвів напряму — використовується лише
порядок рядків Items.csv, решта офсетів реверс-інжинирена окремо
для цього інструменту. Деталі — у README.md поряд зі скриптом.

Завжди роби бекап оригінального сейву перед експериментами.
"""

README_EN = """TLR Save Editor — reference

FILE FORMAT
The save is a plain zlib stream. The decompressed buffer (1,719,936
bytes) starts with a header: "SAVE" + version + size + a 20-byte SHA1
checksum + a Battle Rank cache + a location string.

CHECKSUM (solved)
Bytes [0x0C:0x20] are SHA1(content[0x20:]). The formula was found by
reverse-engineering the .NET utility TLRPSave (method ChecksumFix).
The tool recalculates it automatically on every save, so "corrupted
data" no longer occurs.

GOLD — offset 0x1D978, int32 LE. Confirmed by a controlled test:
selling an item for 6 gold produced exactly +6 in this field.

LIFETIME GOLD (likely) — offset 0x25A5A, int32 LE. Always changes in
sync with Gold, but sits among an array of small internal counters.
Most likely a "total gold earned this game" counter, not the current
wallet. Edit with caution.

BATTLE RANK — offset 0x259DD, int16 LE. This is the REAL Battle Rank
used by the game (confirmed directly in-game against tough enemies).
There's also:
  • offset 0x28 — a cosmetic cache used only on the load screen,
    doesn't affect the actual game;
  • offset 0x259DF — the BR EXP counter (0-499); rank-up happens
    every 500 EXP (confirmed against real game saves and the game's
    fan-wiki formula).
The tool updates all three fields together on save, so there's no
mismatch between the load screen and the actual game.

INVENTORY TABLE (old draft, see the full README.md for the current
Equipment/Accessories/Items offsets) — base ~0x209E8, 12-byte records:
  bytes [0:4]  — unknown/padding
  bytes [4:6]  — int16, slot index
  bytes [6:8]  — uint16, item ID
  bytes [8:10] — int16, quantity
  bytes [10:12]— unknown/padding

WHERE THE REFERENCE CSV FILES COME FROM (EquipItems.csv, AccItems.csv,
Items.csv)
These aren't ours - they're bundled from a "RemnantTrainer v1.2"
package for the original PC release of the game (v1_2/ folder, which
also has a Cheat Engine table). We don't have the exact download link
(the files were just present in the project folder), but
v1_2/readme.txt credits: lothrandier, saeri, sage_inferno,
TheHologramMan, VoxAngel, helodermatid, jesse_n, hlvietlong,
artennoir, SunS_MMX, suttyo, BR_Gamer, mikeyakame, Samsong69. Those
CSVs' own offsets don't apply to Remastered saves directly - only
Items.csv's row order is used; every actual save-file offset was
independently reverse-engineered for this tool. Full details in
README.md next to the script.

Always back up your original save before experimenting.
"""

STRINGS["uk"]["readme_content"] = README_UK
STRINGS["en"]["readme_content"] = README_EN


# ---------------------------------------------------------------------------
# Simple tooltip helper
# ---------------------------------------------------------------------------

class ToolTip:
    def __init__(self, widget, text_getter):
        self.widget = widget
        self.text_getter = text_getter
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, event=None):
        text = self.text_getter()
        if self.tip or not text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip, text=text, justify="left",
            background="#ffffe0", foreground="#000000",
            relief="solid", borderwidth=1,
            font=("TkDefaultFont", 9), wraplength=360
        )
        label.pack(ipadx=5, ipady=3)

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class NotebookTabTooltip:
    """Shows a tooltip when hovering a specific tab header of a
    ttk.Notebook, instead of an always-visible hint label under the
    section. `texts_getter` is a callable returning {tab_index: text}
    (called fresh every time, so it can be language-aware via self.t)."""

    def __init__(self, notebook, texts_getter):
        self.notebook = notebook
        self.texts_getter = texts_getter
        self.tip = None
        self.last_index = None
        notebook.bind("<Motion>", self.on_motion)
        notebook.bind("<Leave>", self.hide)

    def on_motion(self, event):
        try:
            idx = self.notebook.index(f"@{event.x},{event.y}")
        except Exception:
            self.hide()
            return
        if idx != self.last_index:
            self.hide()
        self.last_index = idx
        text = self.texts_getter().get(idx)
        if not text or self.tip:
            return
        x = self.notebook.winfo_rootx() + event.x + 10
        y = self.notebook.winfo_rooty() + event.y + 20
        self.tip = tk.Toplevel(self.notebook)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip, text=text, justify="left",
            background="#ffffe0", foreground="#000000",
            relief="solid", borderwidth=1,
            font=("TkDefaultFont", 9), wraplength=360
        )
        label.pack(ipadx=5, ipady=3)

    def hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None
        self.last_index = None


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class SaveEditorApp:
    def __init__(self, root):
        self.root = root
        self.lang = "uk"
        self.dec_buffer = None
        self.current_path = None
        self.current_filename = None
        self.original_gold1 = 0
        self.original_gold2 = 0
        self.updating_gold2 = False  # flag to prevent recursion

        self.root.geometry("960x700")
        self.root.minsize(680, 520)

        pad = {"padx": 10, "pady": 6}

        # --- Bottom: version (packed early so it always reserves its space) ---
        bottom = ttk.Frame(root)
        bottom.pack(fill="x", side="bottom", pady=(0, 4))
        self.version_label = ttk.Label(bottom, foreground="#888888")
        self.version_label.pack(side="right", padx=10)
        self.author_link_label = ttk.Label(bottom, text=AUTHOR_LINK_URL, foreground="#4a90d9", cursor="hand2")
        self.author_link_label.pack(side="left", padx=10)
        self.author_link_label.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_LINK_URL))

        # --- Top bar: open file + language toggle + README ---
        top = ttk.Frame(root)
        top.pack(fill="x", **pad)
        self.open_btn = ttk.Button(top, command=self.open_file)
        self.open_btn.pack(side="left")
        self.find_saves_btn = ttk.Button(top, command=self._find_saves)
        self.find_saves_btn.pack(side="left", padx=(6, 0))
        self.file_label = ttk.Label(top)
        self.file_label.pack(side="left", padx=10)

        self.readme_btn = ttk.Button(top, command=self.show_readme, width=8)
        self.readme_btn.pack(side="right", padx=(4, 0))
        self.lang_en_btn = ttk.Button(top, width=4, command=lambda: self.set_lang("en"))
        self.lang_en_btn.pack(side="right", padx=(4, 0))
        self.lang_uk_btn = ttk.Button(top, width=4, command=lambda: self.set_lang("uk"))
        self.lang_uk_btn.pack(side="right", padx=(4, 0))

        # --- Action bar: Save pinned right under Open, always visible ---
        action_bar = ttk.Frame(root)
        action_bar.pack(fill="x", padx=10, pady=(0, 6))
        self.save_btn = ttk.Button(action_bar, command=self.save_new_file)
        self.save_btn.pack(side="left")

        # --- Save info ---
        self.info_frame = ttk.LabelFrame(root)
        self.info_frame.pack(fill="x", **pad)
        self.info_text = tk.Text(self.info_frame, height=6, wrap="word")
        self.info_text.pack(fill="x", padx=6, pady=6)
        self.info_text.configure(state="disabled")

        # --- Main tabs: Gold/BR (default) -> Union -> Inventory -> Tools ---
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # ===== Tab 1: Gold / Battle Rank =====
        self.tab_gold = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_gold, text="")  # text set in retranslate()

        row1 = ttk.Frame(self.tab_gold)
        row1.pack(fill="x", padx=6, pady=(12, 4))
        self.gold_label = ttk.Label(row1, width=16, anchor="w")
        self.gold_label.pack(side="left")
        self.gold1_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.gold1_var, width=15).pack(side="left", padx=6)
        ToolTip(self.gold_label, lambda: self.t("tip_gold"))
        self.preset_max_gold_btn = ttk.Button(
            row1, command=lambda: self.gold1_var.set("9999999"))
        self.preset_max_gold_btn.pack(side="left", padx=(6, 0))

        row2 = ttk.Frame(self.tab_gold)
        row2.pack(fill="x", padx=6, pady=4)
        self.gold_lifetime_label = ttk.Label(row2, width=16, anchor="w")
        self.gold_lifetime_label.pack(side="left")
        self.gold2_var = tk.StringVar()
        # Use a disabled Entry with grey background to show it's read-only
        self.gold2_entry = ttk.Entry(row2, textvariable=self.gold2_var, width=15, state="disabled")
        self.gold2_entry.pack(side="left", padx=6)
        ToolTip(self.gold_lifetime_label, lambda: self.t("tip_gold_lifetime"))

        # Add trace to sync gold2 when gold1 changes
        try:
            self.gold1_var.trace_add("write", self._on_gold1_changed)
        except AttributeError:
            # Fallback for older tkinter versions
            self.gold1_var.trace("w", self._on_gold1_changed)

        row3 = ttk.Frame(self.tab_gold)
        row3.pack(fill="x", padx=6, pady=4)
        self.br_label = ttk.Label(row3, width=16, anchor="w")
        self.br_label.pack(side="left")
        self.br_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.br_var, width=15).pack(side="left", padx=6)
        ToolTip(self.br_label, lambda: self.t("tip_br"))
        self.preset_br_1_btn = ttk.Button(row3, width=6, command=lambda: self.br_var.set("1"))
        self.preset_br_1_btn.pack(side="left", padx=(6, 0))
        self.preset_br_99_btn = ttk.Button(row3, width=6, command=lambda: self.br_var.set("99"))
        self.preset_br_99_btn.pack(side="left", padx=(4, 0))
        self.preset_br_250_btn = ttk.Button(row3, width=6, command=lambda: self.br_var.set("250"))
        self.preset_br_250_btn.pack(side="left", padx=(4, 0))

        row4 = ttk.Frame(self.tab_gold)
        row4.pack(fill="x", padx=6, pady=4)
        self.playtime_label = ttk.Label(row4, width=16, anchor="w")
        self.playtime_label.pack(side="left")
        self.playtime_var = tk.StringVar()
        ttk.Entry(row4, textvariable=self.playtime_var, width=15).pack(side="left", padx=6)
        ToolTip(self.playtime_label, lambda: self.t("tip_playtime"))

        row5 = ttk.Frame(self.tab_gold)
        row5.pack(fill="x", padx=6, pady=4)
        self.diggs_attempts_label = ttk.Label(row5, width=16, anchor="w")
        self.diggs_attempts_label.pack(side="left")
        self.diggs_attempts_var = tk.StringVar()
        ttk.Entry(row5, textvariable=self.diggs_attempts_var, width=15).pack(side="left", padx=6)
        ToolTip(self.diggs_attempts_label, lambda: self.t("tip_diggs_attempts"))
        self.diggs_fill_btn = ttk.Button(row5, command=self._fill_diggs_attempts)
        self.diggs_fill_btn.pack(side="left", padx=(6, 0))

        row6 = ttk.Frame(self.tab_gold)
        row6.pack(fill="x", padx=6, pady=4)
        self.diggs_max_label = ttk.Label(row6, width=16, anchor="w")
        self.diggs_max_label.pack(side="left")
        self.diggs_max_var = tk.StringVar()
        ttk.Entry(row6, textvariable=self.diggs_max_var, width=15).pack(side="left", padx=6)
        ToolTip(self.diggs_max_label, lambda: self.t("tip_diggs_max"))

        row7 = ttk.Frame(self.tab_gold)
        row7.pack(fill="x", padx=6, pady=4)
        self.monster_kills_label = ttk.Label(row7, width=16, anchor="w")
        self.monster_kills_label.pack(side="left")
        self.monster_kills_var = tk.StringVar()
        ttk.Entry(row7, textvariable=self.monster_kills_var, width=15).pack(side="left", padx=6)
        ToolTip(self.monster_kills_label, lambda: self.t("tip_monster_kills"))

        # ===== Tab 2: Union (Rush's 12 discovered stat slots) =====
        self.tab_union = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_union, text="")

        # The roster rows (character + weapon + 6 stat fields + 2 quick-fill
        # buttons) are wide, and there can be many rows, so the tab content
        # is wrapped in a scrollable canvas (both directions) - this way
        # nothing gets clipped regardless of window/screen size.
        union_canvas = tk.Canvas(self.tab_union, highlightthickness=0)
        union_vscroll = ttk.Scrollbar(
            self.tab_union, orient="vertical", command=union_canvas.yview)
        union_hscroll = ttk.Scrollbar(
            self.tab_union, orient="horizontal", command=union_canvas.xview)
        union_canvas.configure(
            yscrollcommand=union_vscroll.set, xscrollcommand=union_hscroll.set)
        union_vscroll.pack(side="right", fill="y")
        union_hscroll.pack(side="bottom", fill="x")
        union_canvas.pack(side="left", fill="both", expand=True)

        union_content = ttk.Frame(union_canvas)
        union_canvas.create_window((0, 0), window=union_content, anchor="nw")

        def _on_union_content_configure(event):
            union_canvas.configure(scrollregion=union_canvas.bbox("all"))
        union_content.bind("<Configure>", _on_union_content_configure)

        def _union_mousewheel(event):
            if event.state & 0x0001:  # Shift held -> scroll horizontally
                union_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                union_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _union_bind_wheel(event):
            union_canvas.bind_all("<MouseWheel>", _union_mousewheel)

        def _union_unbind_wheel(event):
            union_canvas.unbind_all("<MouseWheel>")

        union_canvas.bind("<Enter>", _union_bind_wheel)
        union_canvas.bind("<Leave>", _union_unbind_wheel)

        self.selected_union_index = 0
        select_row = ttk.Frame(union_content)
        select_row.pack(fill="x", padx=6, pady=(10, 0), anchor="w")
        self.union_select_label = ttk.Label(select_row, width=12, anchor="w")
        self.union_select_label.pack(side="left")
        self.union_select_var = tk.StringVar(value="1")
        self.union_select_combo = ttk.Combobox(
            select_row, textvariable=self.union_select_var,
            values=[str(i) for i in range(1, UNION_COUNT + 1)], width=4, state="readonly")
        self.union_select_combo.pack(side="left", padx=6)
        self.union_select_combo.bind(
            "<<ComboboxSelected>>", self._on_union_select_changed)

        self.rush_stat_labels = {}
        self.rush_stat_vars = {}
        grid = ttk.Frame(union_content)
        grid.pack(fill="x", padx=6, pady=12)
        cols = 3
        for idx, (key, label_key, rel_off, size) in enumerate(RUSH_STATS):
            row = idx // cols
            col = idx % cols
            cell = ttk.Frame(grid)
            cell.grid(row=row, column=col, padx=6, pady=3, sticky="w")
            lbl = ttk.Label(cell, width=12, anchor="w")
            lbl.pack(side="left")
            var = tk.StringVar()
            ttk.Entry(cell, textvariable=var, width=8).pack(side="left")
            self.rush_stat_labels[key] = lbl
            self.rush_stat_vars[key] = var

        self.rush_max_stats_btn = ttk.Button(
            union_content, command=self._set_rush_stat_fields_max)
        self.rush_max_stats_btn.pack(padx=6, pady=(0, 10), anchor="w")

        # --- Union roster (slots 2-5) - EXPERIMENTAL, see comment above
        # union_member_addr() for what's confirmed vs not. ---
        self.chars_names = []
        self.union_roster_label = ttk.Label(union_content, anchor="w")
        self.union_roster_label.pack(padx=6, pady=(4, 0), anchor="w")
        self.union_member_labels = {}
        self.union_member_vars = {}
        self.union_member_combos = {}
        roster_frame = ttk.Frame(union_content)
        roster_frame.pack(fill="x", padx=6, pady=4)

        leader_row = ttk.Frame(roster_frame)
        leader_row.pack(fill="x", pady=2)
        self.union_leader_label = ttk.Label(leader_row, width=10, anchor="w")
        self.union_leader_label.pack(side="left")
        self.union_leader_var = tk.StringVar()
        self.union_leader_combo = ttk.Combobox(leader_row, textvariable=self.union_leader_var, width=24)
        self.union_leader_combo.pack(side="left", padx=6)
        self.union_leader_combo.bind(
            "<<ComboboxSelected>>", lambda e: self._on_union_roster_char_selected("leader"))
        self._make_combobox_searchable(
            self.union_leader_combo, lambda: list(self.chars_names))

        # --- Each roster row also shows/edits that member's currently
        # equipped weapon (CHAR_EQUIP slot 0), with the same 6 stat fields
        # used on the Inventory tab, so a weapon can be tweaked right where
        # the union composition is being edited. ---
        self.union_weapon_vars = {}
        self.union_weapon_combos = {}
        self.union_weapon_stat_vars = {}
        stat_display_labels = {
            "att": "Att:", "matt": "M-Att:", "def": "Def:",
            "mdef": "M-Def:", "eva": "Eva:", "meva": "M-Eva:",
        }

        def _add_weapon_widgets(parent, row_key):
            wvar = tk.StringVar()
            wcombo = ttk.Combobox(parent, textvariable=wvar, width=22)
            wcombo.pack(side="left", padx=(4, 4))
            self.union_weapon_vars[row_key] = wvar
            self.union_weapon_combos[row_key] = wcombo
            stat_vars = {}
            for stat_key in EQUIP_STAT_NAMES:
                ttk.Label(parent, text=stat_display_labels[stat_key],
                          width=6, anchor="e").pack(side="left")
                svar = tk.StringVar()
                ttk.Entry(parent, textvariable=svar, width=4).pack(side="left", padx=(2, 4))
                stat_vars[stat_key] = svar
            self.union_weapon_stat_vars[row_key] = stat_vars
            wcombo.bind(
                "<<ComboboxSelected>>",
                lambda e, rk=row_key: self._on_union_weapon_selected(rk))
            self._make_combobox_searchable(
                wcombo, lambda: sorted(set(self.equip_names.values())))
            ttk.Button(
                parent, width=4, text="175",
                command=lambda rk=row_key: self._set_union_weapon_stats(rk, 175)
            ).pack(side="left", padx=(4, 0))
            ttk.Button(
                parent, width=4, text="250",
                command=lambda rk=row_key: self._set_union_weapon_stats(rk, 250)
            ).pack(side="left", padx=(2, 0))

        _add_weapon_widgets(leader_row, "leader")

        for slot_pos in range(UNION_MEMBER_SLOT_COUNT):
            row = ttk.Frame(roster_frame)
            row.pack(fill="x", pady=2)
            lbl = ttk.Label(row, width=10, anchor="w")
            lbl.pack(side="left")
            var = tk.StringVar()
            combo = ttk.Combobox(row, textvariable=var, width=24)
            combo.pack(side="left", padx=6)
            combo.bind(
                "<<ComboboxSelected>>",
                lambda e, sp=slot_pos: self._on_union_roster_char_selected(sp))
            self._make_combobox_searchable(combo, lambda: list(self.chars_names))
            self.union_member_labels[slot_pos] = lbl
            self.union_member_vars[slot_pos] = var
            self.union_member_combos[slot_pos] = combo
            _add_weapon_widgets(row, slot_pos)

        union_bulk_row = ttk.Frame(union_content)
        union_bulk_row.pack(fill="x", padx=6, pady=(2, 4), anchor="w")
        self.union_all_250_btn = ttk.Button(
            union_bulk_row, command=lambda: self._set_all_union_weapon_stats(250))
        self.union_all_250_btn.pack(side="left")
        self.union_all_max_btn = ttk.Button(
            union_bulk_row, command=lambda: self._set_all_union_weapon_stats(255))
        self.union_all_max_btn.pack(side="left", padx=(6, 0))
        self.union_export_profile_btn = ttk.Button(
            union_bulk_row, command=self._export_union_profile)
        self.union_export_profile_btn.pack(side="left", padx=(18, 0))
        self.union_import_profile_btn = ttk.Button(
            union_bulk_row, command=self._import_union_profile)
        self.union_import_profile_btn.pack(side="left", padx=(6, 0))

        self.union_roster_apply_btn = ttk.Button(
            union_content, command=self.apply_union_members)
        self.union_roster_apply_btn.pack(padx=6, pady=(0, 10), anchor="w")
        ToolTip(self.union_roster_label, lambda: self.t("tip_union_roster"))

        self._load_chars_database()

        # ===== Tab 3: Inventory (sub-tabs per item category) =====
        self.tab_inventory = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_inventory, text="")

        self.equip_names = {}
        self.equip_stats = {}

        self.inv_notebook = ttk.Notebook(self.tab_inventory)
        self.inv_notebook.pack(fill="both", expand=True, padx=4, pady=4)

        # --- Equipment sub-tab (the only category implemented so far) ---
        self.subtab_equipment = ttk.Frame(self.inv_notebook)
        self.inv_notebook.add(self.subtab_equipment, text="")

        tree_frame = ttk.Frame(self.subtab_equipment)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=6)
        equip_scroll = ttk.Scrollbar(tree_frame)
        equip_scroll.pack(side="right", fill="y")
        self.equip_tree = ttk.Treeview(
            tree_frame, columns=("slot", "name"), show="headings",
            height=10, yscrollcommand=equip_scroll.set
        )
        self.equip_tree.heading("slot", text=self.t("equip_col_slot"))
        self.equip_tree.heading("name", text=self.t("equip_col_name"))
        self.equip_tree.column("slot", width=40, anchor="center")
        self.equip_tree.column("name", width=380, anchor="w")
        self.equip_tree.pack(side="left", fill="both", expand=True)
        equip_scroll.config(command=self.equip_tree.yview)
        self.equip_tree.bind("<<TreeviewSelect>>", self._on_equip_tree_select)

        equip_edit_row = ttk.Frame(self.subtab_equipment)
        equip_edit_row.pack(fill="x", padx=6, pady=(0, 4))
        self.equip_setitem_label = ttk.Label(equip_edit_row, width=16, anchor="w")
        self.equip_setitem_label.pack(side="left")
        ToolTip(self.equip_setitem_label, lambda: self.t("tip_equip_edit_existing"))
        self.equip_item_var = tk.StringVar()
        self.equip_item_combo = ttk.Combobox(
            equip_edit_row, textvariable=self.equip_item_var,
            values=[], width=35
        )
        self.equip_item_combo.pack(side="left", padx=6)
        self.equip_apply_btn = ttk.Button(equip_edit_row, command=self.apply_equip_to_selected)
        self.equip_apply_btn.pack(side="left", padx=(4, 0))
        self.equip_item_combo.bind("<<ComboboxSelected>>", self._on_equip_item_selected)
        self._make_combobox_searchable(
            self.equip_item_combo, lambda: sorted(set(self.equip_names.values())))

        # --- Item-database status + manual reload (in case EquipItems.csv
        # wasn't found/readable at startup - e.g. a cloud-synced folder
        # (iCloud Drive/OneDrive) that hadn't finished downloading the
        # file yet) ---
        equip_db_row = ttk.Frame(self.subtab_equipment)
        equip_db_row.pack(fill="x", padx=6, pady=(0, 4))
        self.equip_db_status_label = ttk.Label(equip_db_row, anchor="w")
        self.equip_db_status_label.pack(side="left")
        self.equip_reload_btn = ttk.Button(
            equip_db_row, command=lambda: self._load_equip_database(warn_on_empty=True))
        self.equip_reload_btn.pack(side="left", padx=(8, 0))

        # --- Editable stat fields (Att/M-Att/Def/M-Def/Eva/M-Eva), 0-255 each ---
        equip_stats_row = ttk.Frame(self.subtab_equipment)
        equip_stats_row.pack(fill="x", padx=6, pady=(0, 4))
        stat_display_labels = {
            "att": "Att:", "matt": "M-Att:", "def": "Def:",
            "mdef": "M-Def:", "eva": "Eva:", "meva": "M-Eva:",
        }
        self.equip_stat_vars = {}
        for stat_key in EQUIP_STAT_NAMES:
            ttk.Label(equip_stats_row, text=stat_display_labels[stat_key],
                      width=6, anchor="e").pack(side="left")
            var = tk.StringVar()
            ttk.Entry(equip_stats_row, textvariable=var, width=5).pack(
                side="left", padx=(2, 8))
            self.equip_stat_vars[stat_key] = var
        self.equip_max_stats_btn = ttk.Button(
            equip_stats_row, command=self._set_equip_stat_fields_max)
        self.equip_max_stats_btn.pack(side="left", padx=(4, 0))

        equip_fill_row = ttk.Frame(self.subtab_equipment)
        equip_fill_row.pack(fill="x", padx=6, pady=(0, 6))
        self.equip_fillempty_btn = ttk.Button(equip_fill_row, command=self.fill_empty_equip_slots)
        self.equip_fillempty_btn.pack(side="left")
        self.equip_clear_btn = ttk.Button(equip_fill_row, command=self.clear_selected_equip)
        self.equip_clear_btn.pack(side="left", padx=(6, 0))

        # Load the item name/stat database now that all the widgets that
        # depend on it (combobox, status label) exist. Warn right away if
        # it's missing so this isn't a silent, confusing "?(id)" bug.
        self._load_equip_database(warn_on_empty=True)

        # --- Accessories sub-tab ---
        self.accessory_names = {}

        self.subtab_accessories = ttk.Frame(self.inv_notebook)
        self.inv_notebook.add(self.subtab_accessories, text="")

        acc_tree_frame = ttk.Frame(self.subtab_accessories)
        acc_tree_frame.pack(fill="both", expand=True, padx=6, pady=6)
        acc_scroll = ttk.Scrollbar(acc_tree_frame)
        acc_scroll.pack(side="right", fill="y")
        self.accessory_tree = ttk.Treeview(
            acc_tree_frame, columns=("slot", "name"), show="headings",
            height=10, yscrollcommand=acc_scroll.set
        )
        self.accessory_tree.heading("slot", text=self.t("equip_col_slot"))
        self.accessory_tree.heading("name", text=self.t("equip_col_name"))
        self.accessory_tree.column("slot", width=40, anchor="center")
        self.accessory_tree.column("name", width=380, anchor="w")
        self.accessory_tree.pack(side="left", fill="both", expand=True)
        acc_scroll.config(command=self.accessory_tree.yview)

        acc_edit_row = ttk.Frame(self.subtab_accessories)
        acc_edit_row.pack(fill="x", padx=6, pady=(0, 4))
        self.accessory_setitem_label = ttk.Label(acc_edit_row, width=16, anchor="w")
        self.accessory_setitem_label.pack(side="left")
        self.accessory_item_var = tk.StringVar()
        self.accessory_item_combo = ttk.Combobox(
            acc_edit_row, textvariable=self.accessory_item_var,
            values=[], width=35
        )
        self.accessory_item_combo.pack(side="left", padx=6)
        self.accessory_apply_btn = ttk.Button(acc_edit_row, command=self.apply_accessory_to_selected)
        self.accessory_apply_btn.pack(side="left", padx=(4, 0))
        self._make_combobox_searchable(
            self.accessory_item_combo, lambda: sorted(set(self.accessory_names.values())))

        acc_db_row = ttk.Frame(self.subtab_accessories)
        acc_db_row.pack(fill="x", padx=6, pady=(0, 4))
        self.accessory_db_status_label = ttk.Label(acc_db_row, anchor="w")
        self.accessory_db_status_label.pack(side="left")
        self.accessory_reload_btn = ttk.Button(
            acc_db_row, command=lambda: self._load_accessory_database(warn_on_empty=True))
        self.accessory_reload_btn.pack(side="left", padx=(8, 0))

        acc_fill_row = ttk.Frame(self.subtab_accessories)
        acc_fill_row.pack(fill="x", padx=6, pady=(0, 6))
        self.accessory_fillempty_btn = ttk.Button(
            acc_fill_row, command=self.fill_empty_accessory_slots)
        self.accessory_fillempty_btn.pack(side="left")
        self.accessory_clear_btn = ttk.Button(acc_fill_row, command=self.clear_selected_accessory)
        self.accessory_clear_btn.pack(side="left", padx=(6, 0))

        self._load_accessory_database(warn_on_empty=True)

        # --- Consumables / Components / Captured Monsters / Special
        # Items sub-tabs - all four share the same underlying 1705-item
        # table (see ITEMS_TABLE_BASE), just filtered by category. Only
        # editing the quantity of items already owned (qty > 0) is
        # supported for now - see the comment on ITEMS_MIN_QTY_TO_EDIT. ---
        self.items_catalog = []
        self.items_trees = {}
        self.items_qty_vars = {}
        self.items_qty_labels = {}
        self.items_apply_btns = {}
        self.items_db_status_labels = {}
        self.items_reload_btns = {}
        self.items_subtab_frames = {}
        self.items_grant_labels = {}
        self.items_grant_vars = {}
        self.items_grant_combos = {}
        self.items_grant_qty_vars = {}
        self.items_grant_btns = {}

        self.subtab_consumables = self._build_items_subtab("consumables")
        self.subtab_components = self._build_items_subtab("components")
        self.subtab_monsters = self._build_items_subtab("captured_monsters")
        self.subtab_special = self._build_items_subtab("special_items")

        self._load_items_database(warn_on_empty=True)

        # ===== Tab: Character Equipment (what a character is actually
        # wearing, as opposed to the carried/unequipped pool above) =====
        self.tab_charequip = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_charequip, text="")

        charequip_select_row = ttk.Frame(self.tab_charequip)
        charequip_select_row.pack(fill="x", padx=6, pady=(12, 4), anchor="w")
        self.charequip_char_label = ttk.Label(charequip_select_row, width=14, anchor="w")
        self.charequip_char_label.pack(side="left")
        self.charequip_char_var = tk.StringVar()
        self.charequip_char_combo = ttk.Combobox(
            charequip_select_row, textvariable=self.charequip_char_var, width=28)
        self.charequip_char_combo.pack(side="left", padx=6)
        self.charequip_char_combo["values"] = list(self.chars_names)
        self.charequip_char_combo.bind(
            "<<ComboboxSelected>>", self._on_charequip_char_selected)
        self._make_combobox_searchable(
            self.charequip_char_combo, lambda: list(self.chars_names))

        self.charequip_slot_labels = {}
        self.charequip_slot_vars = {}
        self.charequip_slot_combos = {}
        charequip_slot_names = ["weapon", "shield"]
        for slot in range(CHAR_EQUIP_SLOTS_PER_CHAR):
            row = ttk.Frame(self.tab_charequip)
            row.pack(fill="x", padx=6, pady=4, anchor="w")
            lbl = ttk.Label(row, width=14, anchor="w")
            lbl.pack(side="left")
            var = tk.StringVar()
            combo = ttk.Combobox(row, textvariable=var, width=35)
            combo.pack(side="left", padx=6)
            combo["values"] = sorted(set(self.equip_names.values()))
            self.charequip_slot_labels[slot] = lbl
            self.charequip_slot_vars[slot] = var
            self.charequip_slot_combos[slot] = combo
            self._make_combobox_searchable(
                combo, lambda: sorted(set(self.equip_names.values())))

        self.charequip_apply_btn = ttk.Button(
            self.tab_charequip, command=self.apply_char_equip)
        self.charequip_apply_btn.pack(padx=6, pady=(6, 10), anchor="w")
        ToolTip(self.charequip_char_label, lambda: self.t("tip_charequip"))

        # ===== Tab 4: Tools (number search + save diff) =====
        self.tab_tools = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_tools, text="")

        self.search_frame = ttk.LabelFrame(self.tab_tools)
        self.search_frame.pack(fill="x", padx=6, pady=(12, 6))
        srow = ttk.Frame(self.search_frame)
        srow.pack(fill="x", padx=6, pady=6)
        self.search_number_label = ttk.Label(srow)
        self.search_number_label.pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(srow, textvariable=self.search_var, width=15).pack(side="left", padx=6)
        self.search_btn = ttk.Button(srow, command=self.search_value)
        self.search_btn.pack(side="left")

        self.search_result = tk.Text(self.search_frame, height=6, wrap="word")
        self.search_result.pack(fill="both", padx=6, pady=(0, 6), expand=True)

        self.diff_frame = ttk.LabelFrame(self.tab_tools)
        self.diff_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.diff_btn = ttk.Button(self.diff_frame, command=self.diff_with_other)
        self.diff_btn.pack(anchor="w", padx=6, pady=6)

        # --- Tooltips on hover: former "hint" texts, now shown only when
        # hovering the relevant tab header instead of always taking space ---
        self.notebook_tooltip = NotebookTabTooltip(
            self.notebook,
            lambda: {self.notebook.index(self.tab_union): self.t("char_hint")}
        )
        self.inv_notebook_tooltip = NotebookTabTooltip(
            self.inv_notebook,
            lambda: {self.inv_notebook.index(self.subtab_equipment): self.t("equip_hint")}
        )

        self.retranslate()

    # ------------------------------------------------------------------
    # Gold sync: when Gold changes, update Lifetime Gold by the same delta
    # ------------------------------------------------------------------

    def _on_gold1_changed(self, *args, **kwargs):
        """Called whenever gold1_var changes. Syncs gold2_var by the delta.
        Compatible with both trace() and trace_add() callback signatures."""
        if self.updating_gold2:
            return
        try:
            val = self.gold1_var.get()
            if not val:
                return
            new_gold1 = int(val)
            delta = new_gold1 - self.original_gold1
            new_gold2 = self.original_gold2 + delta

            self.updating_gold2 = True
            # Temporarily enable the entry to update its value
            self.gold2_entry.config(state="normal")
            self.gold2_var.set(str(new_gold2))
            self.gold2_entry.config(state="disabled")
            self.updating_gold2 = False
        except (ValueError, TypeError):
            pass

    # ------------------------------------------------------------------
    # Language handling
    # ------------------------------------------------------------------

    def t(self, key, **kwargs):
        text = STRINGS[self.lang][key]
        if kwargs:
            return text.format(**kwargs)
        return text

    def set_lang(self, lang):
        self.lang = lang
        self.retranslate()

    def _load_equip_database(self, warn_on_empty=False):
        """(Re)loads EquipItems.csv into self.equip_names/self.equip_stats,
        refreshes the item dropdown and status label, and re-renders the
        equipment list if a save is currently open. Called once at
        startup and again whenever the user clicks "Reload"."""
        self.equip_names = load_equip_names()
        self.equip_stats = load_equip_stats()

        sorted_names = sorted(set(self.equip_names.values()))
        self.equip_item_combo["values"] = sorted_names
        if hasattr(self, "charequip_slot_combos"):
            for combo in self.charequip_slot_combos.values():
                combo["values"] = sorted_names
        if hasattr(self, "union_weapon_combos"):
            for combo in self.union_weapon_combos.values():
                combo["values"] = sorted_names

        count = len(self.equip_names)
        if count:
            self.equip_db_status_label.config(
                text=self.t("equip_db_status_ok", n=count), foreground="#888888")
        else:
            self.equip_db_status_label.config(
                text=self.t("equip_db_status_missing"), foreground="#c0392b")

        if self.dec_buffer is not None:
            self._refresh_equip_tree()

        if warn_on_empty and count == 0:
            dirs = "\n".join(_equip_csv_candidate_dirs())
            messagebox.showwarning(
                self.t("warn_title"),
                self.t("equip_db_missing_msg", filename=EQUIP_CSV_FILENAME, dirs=dirs)
            )

    def _equip_display_name(self, item_id):
        if item_id == EQUIP_EMPTY_ID:
            return self.t("equip_empty_slot")
        return self.equip_names.get(item_id, f"?({item_id})")

    def _refresh_equip_tree(self):
        self.equip_tree.delete(*self.equip_tree.get_children())
        if self.dec_buffer is None:
            return
        for slot_index, item_id in read_equipment(self.dec_buffer):
            name = self._equip_display_name(item_id)
            self.equip_tree.insert(
                "", "end", iid=str(slot_index),
                values=(slot_index, name)
            )

    def _equip_id_by_name(self, name):
        for iid, iname in self.equip_names.items():
            if iname == name:
                return iid
        return None

    def _on_equip_tree_select(self, event=None):
        """When exactly one slot is selected in the list, pre-fill the
        name/stat fields with what's ACTUALLY in that slot right now
        (not the CSV baseline) - so editing an already-equipped item's
        stats just means: select it, tweak a number, click Apply."""
        if self.dec_buffer is None:
            return
        sel = self.equip_tree.selection()
        if len(sel) != 1:
            return
        slot_index = int(sel[0])
        item_id = dict(read_equipment(self.dec_buffer)).get(slot_index, EQUIP_EMPTY_ID)
        if item_id == EQUIP_EMPTY_ID:
            return
        self.equip_item_var.set(self._equip_display_name(item_id))
        stats = read_equip_slot_stats(self.dec_buffer, slot_index)
        for key, val in zip(EQUIP_STAT_NAMES, stats):
            self.equip_stat_vars[key].set(str(val))

    def _make_combobox_searchable(self, combo, get_values):
        """Turn a ttk.Combobox with a long values list into a live-filter
        search box: typing narrows the dropdown to names containing the
        typed text (case-insensitive substring match), and the full list
        is restored every time the box gains focus so filtering always
        starts fresh. `get_values` is a zero-arg callable returning the
        current full list of names (called lazily, so it stays correct
        even after the underlying database is reloaded)."""

        def _restore_full_list(event=None):
            combo["values"] = list(get_values())

        def _on_keyrelease(event=None):
            if event is not None and event.keysym in (
                    "Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R"):
                return
            filtered = filter_combo_values(list(get_values()), combo.get())
            combo["values"] = filtered
            if filtered:
                try:
                    combo.event_generate("<Down>")
                except Exception:
                    pass

        combo.bind("<FocusIn>", _restore_full_list)
        combo.bind("<KeyRelease>", _on_keyrelease)

    def _on_equip_item_selected(self, event=None):
        """When a name is picked from the dropdown, pre-fill the stat entry
        fields with that item's real stats from EquipItems.csv, so the
        user edits from a known baseline instead of blank/stale fields."""
        name = self.equip_item_var.get().strip()
        item_id = self._equip_id_by_name(name)
        stats = self.equip_stats.get(item_id, [0] * EQUIP_STAT_COUNT) if item_id is not None else [0] * EQUIP_STAT_COUNT
        for key, val in zip(EQUIP_STAT_NAMES, stats):
            self.equip_stat_vars[key].set(str(val))

    def _on_charequip_char_selected(self, event=None):
        self._load_char_equip_into_fields()

    def _load_char_equip_into_fields(self):
        """Fills the two slot comboboxes with what the selected character
        is actually wearing right now (from the CHAR_EQUIP table), or
        blank if nothing is selected/loaded."""
        if self.dec_buffer is None:
            return
        name = self.charequip_char_var.get().strip()
        if not name or name not in self.chars_names:
            return
        char_id = list(self.chars_names).index(name)
        for slot in range(CHAR_EQUIP_SLOTS_PER_CHAR):
            item_id = read_char_equip_item(self.dec_buffer, char_id, slot)
            self.charequip_slot_vars[slot].set(self._equip_display_name(item_id))

    def apply_char_equip(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        name = self.charequip_char_var.get().strip()
        if not name or name not in self.chars_names:
            messagebox.showerror(self.t("err_title"), self.t("err_unknown_char", name=name))
            return
        char_id = list(self.chars_names).index(name)

        buf = bytearray(self.dec_buffer)
        for slot in range(CHAR_EQUIP_SLOTS_PER_CHAR):
            slot_name = self.charequip_slot_vars[slot].get().strip()
            if not slot_name or slot_name == self.t("equip_empty_slot"):
                clear_char_equip_slot(buf, char_id, slot)
                continue
            item_id = self._equip_id_by_name(slot_name)
            if item_id is None:
                messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=slot_name))
                return
            stats = self.equip_stats.get(item_id, [0] * EQUIP_STAT_COUNT)
            write_char_equip_slot(buf, char_id, slot, item_id, stats=stats)
        self.dec_buffer = bytes(buf)
        self._load_char_equip_into_fields()
        messagebox.showinfo(self.t("done_title"), self.t("charequip_applied_msg", name=name))

    def _fill_diggs_attempts(self):
        try:
            self.diggs_attempts_var.set(self.diggs_max_var.get())
        except Exception:
            pass

    def _set_rush_stat_fields_max(self):
        for key, label_key, rel_off, size in RUSH_STATS:
            self.rush_stat_vars[key].set(str(RUSH_STAT_MAX[key]))

    def _load_union_stats_into_fields(self):
        if self.dec_buffer is None:
            return
        stats = read_union_stats(self.dec_buffer, self.selected_union_index)
        for key, label_key, rel_off, size in RUSH_STATS:
            self.rush_stat_vars[key].set(str(stats[key]))
        self._load_union_members_into_fields()

    def _char_name(self, char_id):
        if char_id == UNION_MEMBER_EMPTY_ID:
            return self.t("union_slot_empty")
        if 0 <= char_id < len(self.chars_names):
            return self.chars_names[char_id]
        return f"?({char_id})"

    def _load_union_members_into_fields(self):
        if self.dec_buffer is None:
            return
        leader_id = read_union_leader(self.dec_buffer, self.selected_union_index)
        self.union_leader_var.set(self._char_name(leader_id))
        self._load_union_weapon_fields_for_row("leader", leader_id)
        members = read_union_members(self.dec_buffer, self.selected_union_index)
        for slot_pos, char_id in enumerate(members):
            self.union_member_vars[slot_pos].set(self._char_name(char_id))
            self._load_union_weapon_fields_for_row(slot_pos, char_id)

    def _load_union_weapon_fields_for_row(self, row_key, char_id):
        """Fills a union roster row's weapon combobox + stat fields with
        what that character is actually wearing (CHAR_EQUIP slot 0),
        or clears them if the slot is empty/invalid."""
        if row_key not in self.union_weapon_vars:
            return
        wvar = self.union_weapon_vars[row_key]
        stat_vars = self.union_weapon_stat_vars[row_key]
        if self.dec_buffer is None or char_id is None or char_id == UNION_MEMBER_EMPTY_ID \
                or not (0 <= char_id < len(self.chars_names)):
            wvar.set("")
            for var in stat_vars.values():
                var.set("")
            return
        item_id = read_char_equip_item(self.dec_buffer, char_id, 0)
        wvar.set(self._equip_display_name(item_id))
        stats = read_char_equip_stats(self.dec_buffer, char_id, 0)
        for key, val in zip(EQUIP_STAT_NAMES, stats):
            stat_vars[key].set(str(val))

    def _set_all_union_weapon_stats(self, value):
        """Apply `value` to all 6 weapon stat fields, for every roster row
        (leader + all member slots) at once."""
        for row_key in self.union_weapon_stat_vars:
            self._set_union_weapon_stats(row_key, value)

    def _union_row_to_profile_dict(self, row_key, char_var):
        """Snapshot one roster row (character + weapon + weapon stats) as
        a plain dict, for JSON export."""
        return {
            "char": char_var.get(),
            "weapon": self.union_weapon_vars[row_key].get(),
            "stats": {k: v.get() for k, v in self.union_weapon_stat_vars[row_key].items()},
        }

    def _export_union_profile(self):
        """Save the currently-displayed union roster (who's in each slot +
        their weapon + weapon stats) to a JSON file, so the same loadout
        can be re-applied to this or another save later without manually
        re-entering everything."""
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        profile = {
            "leader": self._union_row_to_profile_dict("leader", self.union_leader_var),
            "members": {
                str(slot_pos): self._union_row_to_profile_dict(slot_pos, var)
                for slot_pos, var in self.union_member_vars.items()
            },
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror(self.t("err_title"), self.t("union_profile_load_error", err=str(e)))
            return
        messagebox.showinfo(self.t("done_title"), self.t("union_profile_saved_msg", path=path))

    def _import_union_profile(self):
        """Load a JSON profile saved by _export_union_profile() back into
        the roster fields. Only fills the on-screen fields - Apply roster
        still has to be clicked to actually write it into the save, same
        as picking a character/weapon from the dropdowns by hand."""
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                profile = json.load(f)
        except (OSError, ValueError) as e:
            messagebox.showerror(self.t("err_title"), self.t("union_profile_load_error", err=str(e)))
            return

        def _apply_row(row_key, char_var, data):
            char_var.set(data.get("char", ""))
            if row_key in self.union_weapon_vars:
                self.union_weapon_vars[row_key].set(data.get("weapon", ""))
            stat_vars = self.union_weapon_stat_vars.get(row_key, {})
            for k, v in data.get("stats", {}).items():
                if k in stat_vars:
                    stat_vars[k].set(v)

        leader_data = profile.get("leader")
        if isinstance(leader_data, dict):
            _apply_row("leader", self.union_leader_var, leader_data)
        for slot_key, data in profile.get("members", {}).items():
            if not isinstance(data, dict):
                continue
            try:
                slot_pos = int(slot_key)
            except ValueError:
                continue
            if slot_pos in self.union_member_vars:
                _apply_row(slot_pos, self.union_member_vars[slot_pos], data)

        messagebox.showinfo(self.t("done_title"), self.t("union_profile_loaded_msg"))

    # ------------------------------------------------------------------
    # Save diff tab: best-effort human labels for byte ranges, layered on
    # top of find_save_diff_regions()/merge_diff_regions(). This is
    # heuristic, not exhaustive - offsets that don't match a known single
    # field or table are still shown, just without a friendly label.
    # ------------------------------------------------------------------

    def _describe_diff_offset(self, offset):
        single_fields = [
            (GOLD_OFFSET, 4, self.t("gold_label")),
            (GOLD_LIFETIME_OFFSET, 4, self.t("gold_lifetime_label")),
            (BR_OFFSET, 2, self.t("br_label")),
            (BR_EXP_OFFSET, 2, self.t("diff_label_br_exp")),
            (BR_DISPLAY_CACHE_OFFSET, 2, self.t("diff_label_br_cache")),
            (PLAYTIME_OFFSET, 4, self.t("playtime_label")),
            (MR_DIGGS_ATTEMPTS_OFFSET, 4, self.t("diggs_attempts_label")),
            (MR_DIGGS_MAX_ATTEMPTS_OFFSET, 4, self.t("diggs_max_label")),
            (MONSTER_KILLS_OFFSET, 2, self.t("monster_kills_label")),
        ]
        for base, size, label in single_fields:
            if base <= offset < base + size:
                return label

        table_bases = [
            (ACCESSORY_TABLE_BASE, "acc"),
            (EQUIP_TABLE_BASE, "equip"),
            (ITEMS_TABLE_BASE, "items"),
            (RUSH_STRUCT_BASE, "union"),
            (CHAR_EQUIP_TABLE_BASE, "charequip"),
        ]
        chosen = None
        for base, kind in table_bases:
            if offset >= base:
                chosen = (base, kind)
        if chosen is None:
            return None
        base, kind = chosen
        rel = offset - base

        if kind == "acc" and rel < ACCESSORY_SLOT_COUNT * ACCESSORY_RECORD_SIZE:
            idx = rel // ACCESSORY_RECORD_SIZE
            return self.t("diff_label_acc_slot", n=idx)
        if kind == "equip" and rel < EQUIP_SLOT_COUNT * EQUIP_RECORD_SIZE:
            idx = rel // EQUIP_RECORD_SIZE
            return self.t("diff_label_equip_slot", n=idx)
        if kind == "items" and self.items_catalog and rel < len(self.items_catalog) * ITEMS_RECORD_SIZE:
            idx = rel // ITEMS_RECORD_SIZE
            name = self.items_catalog[idx]["name"] if idx < len(self.items_catalog) else "?"
            return self.t("diff_label_item_slot", n=idx, name=name)
        if kind == "union" and rel < UNION_COUNT * UNION_RECORD_STRIDE:
            idx = rel // UNION_RECORD_STRIDE
            return self.t("diff_label_union", n=idx + 1)
        if kind == "charequip":
            idx = rel // CHAR_EQUIP_RECORD_SIZE
            char_id = idx // CHAR_EQUIP_SLOTS_PER_CHAR
            slot = idx % CHAR_EQUIP_SLOTS_PER_CHAR
            char_name = (self.chars_names[char_id]
                         if self.chars_names and char_id < len(self.chars_names)
                         else f"id={char_id}")
            return self.t("diff_label_charequip", char=char_name, slot=slot)
        return None

    def _describe_diff_block(self, dec_a, dec_b, s, e):
        la, lb = dec_a[s:e], dec_b[s:e]
        length = e - s
        lines = [f"[{hex(s)}:{hex(e)}] len={length}"]
        label = self._describe_diff_offset(s)
        if label:
            lines.append(f"  {label}")
        decoded = False
        for size, fmt in [(2, "<h"), (4, "<i")]:
            if length == size:
                va = struct.unpack(fmt, la)[0]
                vb = struct.unpack(fmt, lb)[0]
                lines.append(f"  {va} -> {vb}  (diff={vb - va})")
                decoded = True
        if not decoded:
            lines.append(f"  before: {la.hex()}")
            lines.append(f"  after : {lb.hex()}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # "Find saves" button: scan a remembered/picked folder for .sav files
    # instead of always having to browse for the exact file by hand.
    # ------------------------------------------------------------------

    def _find_saves(self):
        cfg = load_app_config()
        search_dir = cfg.get("save_search_dir")
        if not search_dir or not os.path.isdir(search_dir):
            chosen = filedialog.askdirectory(title=self.t("find_saves_pick_dir_title"))
            if not chosen:
                return
            search_dir = chosen
            cfg["save_search_dir"] = search_dir
            save_app_config(cfg)
        self._scan_and_show_saves(search_dir)

    def _scan_and_show_saves(self, search_dir):
        results = scan_for_sav_files([search_dir])
        self._show_save_picker(results, search_dir)

    def _show_save_picker(self, results, search_dir):
        win = tk.Toplevel(self.root)
        win.title(self.t("find_saves_win_title"))
        win.geometry("560x420")

        info = ttk.Label(
            win, text=self.t("find_saves_dir_label", dir=search_dir),
            anchor="w", wraplength=540)
        info.pack(fill="x", padx=8, pady=(8, 4))

        list_frame = ttk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=8, pady=4)
        scroll = ttk.Scrollbar(list_frame)
        scroll.pack(side="right", fill="y")
        listbox = tk.Listbox(list_frame, yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True)
        scroll.config(command=listbox.yview)

        if not results:
            listbox.insert("end", self.t("find_saves_none_found"))
        else:
            for p in results:
                listbox.insert("end", os.path.relpath(p, search_dir))

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=8, pady=8)

        def _open_selected(event=None):
            sel = listbox.curselection()
            if not sel or not results:
                return
            path = results[sel[0]]
            win.destroy()
            self.load_save_file(path)

        open_btn = ttk.Button(btn_row, text=self.t("find_saves_open_btn"), command=_open_selected)
        open_btn.pack(side="left")
        listbox.bind("<Double-Button-1>", _open_selected)

        def _change_folder():
            chosen = filedialog.askdirectory(title=self.t("find_saves_pick_dir_title"))
            if not chosen:
                return
            cfg = load_app_config()
            cfg["save_search_dir"] = chosen
            save_app_config(cfg)
            win.destroy()
            self._scan_and_show_saves(chosen)

        change_btn = ttk.Button(
            btn_row, text=self.t("find_saves_change_dir_btn"), command=_change_folder)
        change_btn.pack(side="left", padx=(6, 0))

        cancel_btn = ttk.Button(btn_row, text=self.t("cancel_btn"), command=win.destroy)
        cancel_btn.pack(side="right")

    def _on_union_roster_char_selected(self, row_key):
        """When a character is picked/changed in a roster combo, refresh
        that row's weapon fields to match what that character wears."""
        name = (self.union_leader_var if row_key == "leader"
                else self.union_member_vars[row_key]).get().strip()
        char_id = None
        if name and name != self.t("union_slot_empty") and name in list(self.chars_names):
            char_id = list(self.chars_names).index(name)
        self._load_union_weapon_fields_for_row(row_key, char_id)

    def _set_union_weapon_stats(self, row_key, value):
        """Sets all 6 stat fields for one roster row's weapon to a fixed
        value (used by the 175/250 quick-fill buttons)."""
        for var in self.union_weapon_stat_vars[row_key].values():
            var.set(str(value))

    def _on_union_weapon_selected(self, row_key):
        """When a weapon name is picked from a roster row's dropdown,
        pre-fill its stat fields with that item's real CSV stats."""
        name = self.union_weapon_vars[row_key].get().strip()
        item_id = self._equip_id_by_name(name)
        stats = self.equip_stats.get(item_id, [0] * EQUIP_STAT_COUNT) if item_id is not None else [0] * EQUIP_STAT_COUNT
        for key, val in zip(EQUIP_STAT_NAMES, stats):
            self.union_weapon_stat_vars[row_key][key].set(str(val))

    def _load_chars_database(self):
        self.chars_names = load_chars_catalog()
        combo_values = [self.t("union_slot_empty")] + list(self.chars_names)
        self.union_leader_combo["values"] = combo_values
        for combo in self.union_member_combos.values():
            combo["values"] = combo_values
        self._load_union_members_into_fields()
        if hasattr(self, "charequip_char_combo"):
            self.charequip_char_combo["values"] = list(self.chars_names)

    def apply_union_members(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        if not self.chars_names:
            messagebox.showerror(self.t("err_title"), self.t("err_chars_db_missing"))
            return

        name_to_id = {name: i for i, name in enumerate(self.chars_names)}

        def resolve(name):
            name = name.strip()
            if name == self.t("union_slot_empty") or name == "":
                return UNION_MEMBER_EMPTY_ID
            if name not in name_to_id:
                return None
            return name_to_id[name]

        new_leader = resolve(self.union_leader_var.get())
        if new_leader is None:
            messagebox.showerror(
                self.t("err_title"), self.t("err_unknown_char", name=self.union_leader_var.get()))
            return

        new_ids = {}
        for slot_pos, var in self.union_member_vars.items():
            resolved = resolve(var.get())
            if resolved is None:
                messagebox.showerror(self.t("err_title"), self.t("err_unknown_char", name=var.get()))
                return
            new_ids[slot_pos] = resolved

        # Duplicates (same character in multiple slots/unions) used to be
        # blocked here defensively, before it was actually tested. The
        # user confirmed live in-game that duplicate assignments (a
        # character appearing in two unions at once) work fine in battle
        # and recalculate correctly - so that restriction was removed.
        buf = bytearray(self.dec_buffer)
        if new_leader == UNION_MEMBER_EMPTY_ID:
            deactivate_union(buf, self.selected_union_index)
        else:
            # activate_union() also handles previously-active unions
            # fine (it just re-writes the same active/populated/leader
            # fields), so this is safe whether the union was already
            # active or was one of the empty 6-7-8 slots.
            activate_union(buf, self.selected_union_index, new_leader)
        for slot_pos, char_id in new_ids.items():
            write_union_member(buf, self.selected_union_index, slot_pos, char_id)

        # Also apply each row's weapon field (CHAR_EQUIP slot 0) for every
        # non-empty character currently shown in the roster - lets you
        # tweak a union member's weapon right from this tab instead of
        # having to switch to the Character Equipment tab.
        row_keys = ["leader"] + list(new_ids.keys())
        row_char_ids = {"leader": new_leader, **new_ids}
        for row_key in row_keys:
            char_id = row_char_ids[row_key]
            if char_id == UNION_MEMBER_EMPTY_ID:
                continue
            weapon_name = self.union_weapon_vars[row_key].get().strip()
            if not weapon_name:
                continue  # field left blank - leave that character's weapon untouched
            if weapon_name == self.t("equip_empty_slot"):
                clear_char_equip_slot(buf, char_id, 0)
                continue
            item_id = self._equip_id_by_name(weapon_name)
            if item_id is None:
                messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=weapon_name))
                return
            stat_vars = self.union_weapon_stat_vars[row_key]
            stats = self._read_equip_stat_overrides_from(stat_vars, self.equip_stats.get(item_id))
            write_char_equip_slot(buf, char_id, 0, item_id, stats=stats)

        self.dec_buffer = bytes(buf)
        self._load_union_members_into_fields()
        messagebox.showinfo(self.t("done_title"), self.t("union_roster_applied_msg"))

    def _on_union_select_changed(self, event=None):
        try:
            new_index = int(self.union_select_var.get()) - 1
        except ValueError:
            return
        if self.dec_buffer is None:
            self.selected_union_index = new_index
            return
        # Commit the currently-displayed fields into the buffer for the
        # union we're switching AWAY from, so unsaved edits aren't lost
        # when hopping between unions before hitting Save.
        try:
            current_vals = {
                key: int(self.rush_stat_vars[key].get())
                for key, label_key, rel_off, size in RUSH_STATS
            }
        except ValueError:
            messagebox.showerror(self.t("err_title"), self.t("err_int"))
            self.union_select_var.set(str(self.selected_union_index + 1))
            return
        buf = bytearray(self.dec_buffer)
        write_union_stats(buf, self.selected_union_index, current_vals)
        self.dec_buffer = bytes(buf)

        self.selected_union_index = new_index
        self._load_union_stats_into_fields()

    def _set_equip_stat_fields_max(self):
        for key in EQUIP_STAT_NAMES:
            self.equip_stat_vars[key].set("255")

    def _read_equip_stat_overrides(self, fallback):
        """Reads the 6 stat entry fields, clamping each to 0-255. If a
        field is blank or not a number, falls back to the given default
        list (usually the item's CSV stats) for that one slot."""
        return self._read_equip_stat_overrides_from(self.equip_stat_vars, fallback)

    def _read_equip_stat_overrides_from(self, stat_vars, fallback):
        """Same as _read_equip_stat_overrides(), but reads from an
        arbitrary dict of StringVars (e.g. a union roster row's stat
        fields) instead of the Inventory tab's self.equip_stat_vars."""
        result = []
        for i, key in enumerate(EQUIP_STAT_NAMES):
            raw = stat_vars[key].get().strip()
            default = fallback[i] if fallback and i < len(fallback) else 0
            if not raw:
                result.append(default)
                continue
            try:
                val = int(raw)
            except ValueError:
                result.append(default)
                continue
            result.append(max(0, min(255, val)))
        return result

    def apply_equip_to_selected(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        sel = self.equip_tree.selection()
        if not sel:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_select_slot"))
            return
        name = self.equip_item_var.get().strip()
        if not name:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_pick_item"))
            return
        item_id = self._equip_id_by_name(name)
        if item_id is None:
            messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=name))
            return

        stats = self._read_equip_stat_overrides(self.equip_stats.get(item_id))
        buf = bytearray(self.dec_buffer)
        for slot_str in sel:
            slot_index = int(slot_str)
            write_equip_slot(buf, slot_index, item_id, stats=stats)
        self.dec_buffer = bytes(buf)
        self._refresh_equip_tree()
        for slot_str in sel:
            self.equip_tree.selection_add(slot_str)

    def fill_empty_equip_slots(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        name = self.equip_item_var.get().strip()
        if not name:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_pick_item"))
            return
        item_id = self._equip_id_by_name(name)
        if item_id is None:
            messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=name))
            return

        stats = self._read_equip_stat_overrides(self.equip_stats.get(item_id))
        buf = bytearray(self.dec_buffer)
        filled = 0
        for slot_index, current_id in read_equipment(self.dec_buffer):
            if current_id == EQUIP_EMPTY_ID:
                write_equip_slot(buf, slot_index, item_id, stats=stats)
                filled += 1
        self.dec_buffer = bytes(buf)
        self._refresh_equip_tree()
        messagebox.showinfo(self.t("done_title"), self.t("equip_filled_msg", n=filled))

    def clear_selected_equip(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        sel = self.equip_tree.selection()
        if not sel:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_select_slot"))
            return
        buf = bytearray(self.dec_buffer)
        for slot_str in sel:
            slot_index = int(slot_str)
            clear_equip_slot(buf, slot_index)
        self.dec_buffer = bytes(buf)
        self._refresh_equip_tree()
        for slot_str in sel:
            self.equip_tree.selection_add(slot_str)

    # ------------------------------------------------------------------
    # Accessories (carried, not equipped)
    # ------------------------------------------------------------------

    def _load_accessory_database(self, warn_on_empty=False):
        self.accessory_names = load_accessory_names()
        sorted_names = sorted(set(self.accessory_names.values()))
        self.accessory_item_combo["values"] = sorted_names

        count = len(self.accessory_names)
        if count:
            self.accessory_db_status_label.config(
                text=self.t("equip_db_status_ok", n=count), foreground="#888888")
        else:
            self.accessory_db_status_label.config(
                text=self.t("equip_db_status_missing"), foreground="#c0392b")

        if self.dec_buffer is not None:
            self._refresh_accessory_tree()

        if warn_on_empty and count == 0:
            dirs = "\n".join(_data_csv_candidate_dirs())
            messagebox.showwarning(
                self.t("warn_title"),
                self.t("equip_db_missing_msg", filename=ACCESSORY_CSV_FILENAME, dirs=dirs)
            )

    def _accessory_display_name(self, item_id):
        if item_id == ACCESSORY_EMPTY_ID:
            return self.t("equip_empty_slot")
        return self.accessory_names.get(item_id, f"?({item_id})")

    def _refresh_accessory_tree(self):
        self.accessory_tree.delete(*self.accessory_tree.get_children())
        if self.dec_buffer is None:
            return
        for slot_index, item_id, order in read_accessories(self.dec_buffer):
            name = self._accessory_display_name(item_id)
            self.accessory_tree.insert(
                "", "end", iid=str(slot_index),
                values=(slot_index, name)
            )

    def _accessory_id_by_name(self, name):
        for iid, iname in self.accessory_names.items():
            if iname == name:
                return iid
        return None

    def apply_accessory_to_selected(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        sel = self.accessory_tree.selection()
        if not sel:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_select_slot"))
            return
        name = self.accessory_item_var.get().strip()
        if not name:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_pick_item"))
            return
        item_id = self._accessory_id_by_name(name)
        if item_id is None:
            messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=name))
            return

        buf = bytearray(self.dec_buffer)
        for slot_str in sel:
            slot_index = int(slot_str)
            base = accessory_slot_base(slot_index)
            current_id, current_order = struct.unpack("<II", bytes(buf[base:base + 8]))
            # Keep the existing order if this slot already held an item
            # (just swapping items in place); otherwise it was empty, so
            # assign the next free order value to stay contiguous with
            # the game's own compacting behavior (confirmed by the
            # Superior Necklace sell test).
            if current_id != ACCESSORY_EMPTY_ID:
                order = current_order
            else:
                order = next_accessory_order(bytes(buf))
            write_accessory_slot(buf, slot_index, item_id, order)
        self.dec_buffer = bytes(buf)
        self._refresh_accessory_tree()
        for slot_str in sel:
            self.accessory_tree.selection_add(slot_str)

    def fill_empty_accessory_slots(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        name = self.accessory_item_var.get().strip()
        if not name:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_pick_item"))
            return
        item_id = self._accessory_id_by_name(name)
        if item_id is None:
            messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=name))
            return

        buf = bytearray(self.dec_buffer)
        filled = 0
        for slot_index, current_id, _ in read_accessories(bytes(buf)):
            if current_id == ACCESSORY_EMPTY_ID:
                order = next_accessory_order(bytes(buf))
                write_accessory_slot(buf, slot_index, item_id, order)
                filled += 1
        self.dec_buffer = bytes(buf)
        self._refresh_accessory_tree()
        messagebox.showinfo(self.t("done_title"), self.t("equip_filled_msg", n=filled))

    def clear_selected_accessory(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        sel = self.accessory_tree.selection()
        if not sel:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_select_slot"))
            return
        buf = bytearray(self.dec_buffer)
        # Clear in descending slot order isn't required (unlike the
        # order-compaction the *game* does when selling), because we
        # simply mark the slot empty and leave order values as-is. Any
        # gaps left in the order sequence are harmless - it's just a
        # display-order hint, and next_accessory_order() only cares
        # about the *count* of remaining non-empty items when computing
        # a value for the next added item.
        for slot_str in sel:
            slot_index = int(slot_str)
            clear_accessory_slot(buf, slot_index)
        self.dec_buffer = bytes(buf)
        self._refresh_accessory_tree()
        for slot_str in sel:
            self.accessory_tree.selection_add(slot_str)

    # ------------------------------------------------------------------
    # Consumables / Components / Captured Monsters / Special Items
    # (all four share the ITEMS_TABLE_BASE array, filtered by category)
    # ------------------------------------------------------------------

    def _build_items_subtab(self, category_key):
        frame = ttk.Frame(self.inv_notebook)
        self.inv_notebook.add(frame, text="")
        self.items_subtab_frames[category_key] = frame

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=6)
        scroll = ttk.Scrollbar(tree_frame)
        scroll.pack(side="right", fill="y")
        tree = ttk.Treeview(
            tree_frame, columns=("name", "qty"), show="headings",
            height=10, yscrollcommand=scroll.set
        )
        tree.column("name", width=320, anchor="w")
        tree.column("qty", width=60, anchor="center")
        tree.pack(side="left", fill="both", expand=True)
        scroll.config(command=tree.yview)
        self.items_trees[category_key] = tree

        if ITEMS_CATEGORY_EDITABLE[category_key]:
            edit_row = ttk.Frame(frame)
            edit_row.pack(fill="x", padx=6, pady=(0, 4))
            qty_label = ttk.Label(edit_row, width=16, anchor="w")
            qty_label.pack(side="left")
            self.items_qty_labels[category_key] = qty_label
            qty_var = tk.StringVar()
            ttk.Entry(edit_row, textvariable=qty_var, width=8).pack(side="left", padx=6)
            self.items_qty_vars[category_key] = qty_var
            apply_btn = ttk.Button(
                edit_row, command=lambda k=category_key: self.apply_item_qty(k))
            apply_btn.pack(side="left", padx=(4, 0))
            self.items_apply_btns[category_key] = apply_btn

        # --- Grant a brand-new item (currently owned quantity 0) -
        # separate from the list+Apply flow above, which only ever
        # touches items you already own. Uses grant_new_item(), which
        # also fills in the type-tag and discovery-order fields a
        # legitimately-obtained item gets (see the big comment above
        # ITEMS_ORDER_REL_OFFSET). Special Items are unique (own it or
        # not - confirmed every owned one is qty=1, never more), so
        # that tab gets this same grant flow but with no qty field: it
        # always grants exactly 1. ---
        grant_row = ttk.Frame(frame)
        grant_row.pack(fill="x", padx=6, pady=(0, 4))
        grant_label = ttk.Label(grant_row, width=16, anchor="w")
        grant_label.pack(side="left")
        self.items_grant_labels[category_key] = grant_label
        grant_var = tk.StringVar()
        type_filter = ITEMS_CATEGORY_TYPES[category_key]
        names_sorted = sorted({
            it["name"] for it in self.items_catalog if it["type"] in type_filter
        }) if self.items_catalog else []
        grant_combo = ttk.Combobox(
            grant_row, textvariable=grant_var, values=names_sorted, width=30)
        grant_combo.pack(side="left", padx=6)
        self.items_grant_vars[category_key] = grant_var
        self.items_grant_combos[category_key] = grant_combo
        self._make_combobox_searchable(
            grant_combo,
            lambda ck=category_key: sorted({
                it["name"] for it in self.items_catalog
                if it["type"] in ITEMS_CATEGORY_TYPES[ck]
            }) if self.items_catalog else [])
        if ITEMS_CATEGORY_EDITABLE[category_key]:
            grant_qty_var = tk.StringVar(value="1")
            ttk.Entry(grant_row, textvariable=grant_qty_var, width=5).pack(side="left", padx=(0, 6))
            self.items_grant_qty_vars[category_key] = grant_qty_var
        grant_btn = ttk.Button(
            grant_row, command=lambda k=category_key: self.grant_item(k))
        grant_btn.pack(side="left")
        self.items_grant_btns[category_key] = grant_btn

        db_row = ttk.Frame(frame)
        db_row.pack(fill="x", padx=6, pady=(0, 6))
        status_label = ttk.Label(db_row, anchor="w")
        status_label.pack(side="left")
        self.items_db_status_labels[category_key] = status_label
        reload_btn = ttk.Button(
            db_row, command=lambda: self._load_items_database(warn_on_empty=True))
        reload_btn.pack(side="left", padx=(8, 0))
        self.items_reload_btns[category_key] = reload_btn

        return frame

    def _load_items_database(self, warn_on_empty=False):
        self.items_catalog = load_items_catalog()
        count = len(self.items_catalog)
        for key, label in self.items_db_status_labels.items():
            if count:
                label.config(text=self.t("equip_db_status_ok", n=count), foreground="#888888")
            else:
                label.config(text=self.t("equip_db_status_missing"), foreground="#c0392b")

        for key, combo in self.items_grant_combos.items():
            type_filter = ITEMS_CATEGORY_TYPES[key]
            names_sorted = sorted({
                it["name"] for it in self.items_catalog if it["type"] in type_filter
            })
            combo["values"] = names_sorted

        if self.dec_buffer is not None:
            for key in self.items_trees:
                self._refresh_items_tree(key)

        if warn_on_empty and count == 0:
            dirs = "\n".join(_data_csv_candidate_dirs())
            messagebox.showwarning(
                self.t("warn_title"),
                self.t("equip_db_missing_msg", filename=ITEMS_CSV_FILENAME, dirs=dirs)
            )

    def _refresh_items_tree(self, category_key):
        tree = self.items_trees[category_key]
        tree.delete(*tree.get_children())
        if self.dec_buffer is None or not self.items_catalog:
            return
        type_filter = set(ITEMS_CATEGORY_TYPES[category_key])
        for row_index, item in enumerate(self.items_catalog):
            if item["type"] not in type_filter:
                continue
            qty = read_item_qty(self.dec_buffer, row_index)
            if qty < ITEMS_MIN_QTY_TO_EDIT:
                continue
            tree.insert("", "end", iid=str(row_index), values=(item["name"], qty))

    def apply_item_qty(self, category_key):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        tree = self.items_trees[category_key]
        sel = tree.selection()
        if not sel:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_select_slot"))
            return
        raw = self.items_qty_vars[category_key].get().strip()
        try:
            qty = int(raw)
        except ValueError:
            messagebox.showerror(self.t("err_title"), self.t("err_int_search"))
            return

        buf = bytearray(self.dec_buffer)
        for iid in sel:
            row_index = int(iid)
            try:
                write_item_qty(buf, row_index, qty)
            except ValueError:
                # Shouldn't normally happen since this list only shows
                # already-owned (qty > 0) items, but guard anyway.
                messagebox.showerror(self.t("err_title"), self.t("err_grant_new_item"))
                return
        self.dec_buffer = bytes(buf)
        self._refresh_items_tree(category_key)
        for iid in sel:
            if tree.exists(iid):
                tree.selection_add(iid)

    def grant_item(self, category_key):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        name = self.items_grant_vars[category_key].get().strip()
        if not name:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_pick_item"))
            return

        type_filter = set(ITEMS_CATEGORY_TYPES[category_key])
        row_index = None
        for i, item in enumerate(self.items_catalog):
            if item["type"] in type_filter and item["name"] == name:
                row_index = i
                break
        if row_index is None:
            messagebox.showerror(self.t("err_title"), self.t("err_unknown_item", name=name))
            return

        if category_key in self.items_grant_qty_vars:
            raw_qty = self.items_grant_qty_vars[category_key].get().strip()
            try:
                qty = int(raw_qty)
            except ValueError:
                messagebox.showerror(self.t("err_title"), self.t("err_int_search"))
                return
        else:
            # Categories without a qty field (Special Items) always
            # grant exactly 1 - they're unique, own-it-or-not items.
            qty = 1

        buf = bytearray(self.dec_buffer)
        try:
            grant_new_item(buf, self.items_catalog, row_index, qty)
        except ValueError:
            messagebox.showerror(self.t("err_title"), self.t("err_already_owned"))
            return
        self.dec_buffer = bytes(buf)
        self._refresh_items_tree(category_key)
        messagebox.showinfo(self.t("done_title"), self.t("items_granted_msg", name=name, qty=qty))

    def retranslate(self):
        self.root.title(self.t("title"))
        self.open_btn.config(text=self.t("open_button"))
        self.find_saves_btn.config(text=self.t("find_saves_btn"))
        if not self.current_filename:
            self.file_label.config(text=self.t("no_file"))
        self.readme_btn.config(text=self.t("readme_button"))
        self.lang_en_btn.config(text=self.t("lang_button_en"))
        self.lang_uk_btn.config(text=self.t("lang_button_uk"))

        self.info_frame.config(text=self.t("info_frame"))
        self.save_btn.config(text=self.t("save_button"))

        # --- Main tabs ---
        self.notebook.tab(self.tab_gold, text=self.t("tab_gold"))
        self.notebook.tab(self.tab_union, text=self.t("tab_union"))
        self.notebook.tab(self.tab_inventory, text=self.t("tab_inventory"))
        self.notebook.tab(self.tab_charequip, text=self.t("tab_charequip"))
        self.notebook.tab(self.tab_tools, text=self.t("tab_tools"))

        # --- Gold / BR tab ---
        self.gold_label.config(text=self.t("gold_label"))
        self.gold_lifetime_label.config(text=self.t("gold_lifetime_label"))
        self.br_label.config(text=self.t("br_label"))
        self.preset_max_gold_btn.config(text=self.t("preset_max_gold"))
        self.preset_br_1_btn.config(text=self.t("preset_br_1"))
        self.preset_br_99_btn.config(text=self.t("preset_br_99"))
        self.preset_br_250_btn.config(text=self.t("preset_br_250"))
        self.playtime_label.config(text=self.t("playtime_label"))
        self.diggs_attempts_label.config(text=self.t("diggs_attempts_label"))
        self.diggs_fill_btn.config(text=self.t("diggs_fill_btn"))
        self.diggs_max_label.config(text=self.t("diggs_max_label"))
        self.monster_kills_label.config(text=self.t("monster_kills_label"))

        # --- Union tab ---
        self.union_select_label.config(text=self.t("union_select_label"))
        for key, label_key, rel_off, size in RUSH_STATS:
            self.rush_stat_labels[key].config(text=self.t(label_key))
        self.rush_max_stats_btn.config(text=self.t("rush_max_stats_btn"))
        self.union_roster_label.config(text=self.t("union_roster_label"))
        self.union_leader_label.config(text=self.t("union_leader_label"))
        for slot_pos, lbl in self.union_member_labels.items():
            lbl.config(text=self.t("union_slot_n", n=slot_pos + 2))
        self.union_all_250_btn.config(text=self.t("union_all_250_btn"))
        self.union_all_max_btn.config(text=self.t("union_all_max_btn"))
        self.union_export_profile_btn.config(text=self.t("union_export_profile_btn"))
        self.union_import_profile_btn.config(text=self.t("union_import_profile_btn"))
        self.union_roster_apply_btn.config(text=self.t("union_roster_apply_btn"))
        combo_values = [self.t("union_slot_empty")] + list(self.chars_names)
        self.union_leader_combo["values"] = combo_values
        for combo in self.union_member_combos.values():
            combo["values"] = combo_values
        self._load_union_members_into_fields()

        # --- Character Equipment tab ---
        self.charequip_char_label.config(text=self.t("charequip_char_label"))
        slot_label_keys = ["charequip_slot_weapon", "charequip_slot_shield"]
        for slot, lbl in self.charequip_slot_labels.items():
            key = slot_label_keys[slot] if slot < len(slot_label_keys) else "charequip_slot_weapon"
            lbl.config(text=self.t(key))
        self.charequip_apply_btn.config(text=self.t("charequip_apply_btn"))

        # --- Tools tab ---
        self.search_frame.config(text=self.t("search_frame"))
        self.search_number_label.config(text=self.t("search_number_label"))
        self.search_btn.config(text=self.t("search_button"))

        self.diff_frame.config(text=self.t("diff_frame"))
        self.diff_btn.config(text=self.t("diff_button"))

        # --- Inventory tab / Equipment sub-tab ---
        self.inv_notebook.tab(self.subtab_equipment, text=self.t("subtab_equipment"))
        self.equip_tree.heading("slot", text=self.t("equip_col_slot"))
        self.equip_tree.heading("name", text=self.t("equip_col_name"))
        self.equip_setitem_label.config(text=self.t("equip_setitem_label"))
        self.equip_apply_btn.config(text=self.t("equip_apply_btn"))
        self.equip_fillempty_btn.config(text=self.t("equip_fillempty_btn"))
        self.equip_clear_btn.config(text=self.t("equip_clear_btn"))
        self.equip_max_stats_btn.config(text=self.t("equip_max_stats_btn"))
        self.equip_reload_btn.config(text=self.t("equip_reload_btn"))
        count = len(self.equip_names)
        if count:
            self.equip_db_status_label.config(text=self.t("equip_db_status_ok", n=count))
        else:
            self.equip_db_status_label.config(text=self.t("equip_db_status_missing"))
        if self.dec_buffer is not None:
            self._refresh_equip_tree()

        # --- Inventory tab / Accessories sub-tab ---
        self.inv_notebook.tab(self.subtab_accessories, text=self.t("subtab_accessories"))
        self.accessory_tree.heading("slot", text=self.t("equip_col_slot"))
        self.accessory_tree.heading("name", text=self.t("equip_col_name"))
        self.accessory_setitem_label.config(text=self.t("equip_setitem_label"))
        self.accessory_apply_btn.config(text=self.t("equip_apply_btn"))
        self.accessory_fillempty_btn.config(text=self.t("equip_fillempty_btn"))
        self.accessory_clear_btn.config(text=self.t("equip_clear_btn"))
        self.accessory_reload_btn.config(text=self.t("equip_reload_btn"))
        acc_count = len(self.accessory_names)
        if acc_count:
            self.accessory_db_status_label.config(text=self.t("equip_db_status_ok", n=acc_count))
        else:
            self.accessory_db_status_label.config(text=self.t("equip_db_status_missing"))
        if self.dec_buffer is not None:
            self._refresh_accessory_tree()

        # --- Inventory tab / Consumables, Components, Captured Monsters,
        # Special Items sub-tabs ---
        category_tab_title_keys = {
            "consumables": "subtab_consumables",
            "components": "subtab_components",
            "captured_monsters": "subtab_monsters",
            "special_items": "subtab_special",
        }
        items_count = len(self.items_catalog)
        for key, frame in self.items_subtab_frames.items():
            self.inv_notebook.tab(frame, text=self.t(category_tab_title_keys[key]))
            self.items_trees[key].heading("name", text=self.t("equip_col_name"))
            self.items_trees[key].heading("qty", text=self.t("items_col_qty"))
            if key in self.items_qty_labels:
                self.items_qty_labels[key].config(text=self.t("items_qty_label"))
            if key in self.items_apply_btns:
                self.items_apply_btns[key].config(text=self.t("equip_apply_btn"))
            if key in self.items_grant_labels:
                self.items_grant_labels[key].config(text=self.t("items_grant_label"))
            if key in self.items_grant_btns:
                self.items_grant_btns[key].config(text=self.t("items_grant_btn"))
            self.items_reload_btns[key].config(text=self.t("equip_reload_btn"))
            if items_count:
                self.items_db_status_labels[key].config(text=self.t("equip_db_status_ok", n=items_count))
            else:
                self.items_db_status_labels[key].config(text=self.t("equip_db_status_missing"))
        if self.dec_buffer is not None:
            for key in self.items_trees:
                self._refresh_items_tree(key)

        self.version_label.config(text=self.t("version_label", version=APP_VERSION))

        if self.dec_buffer is not None:
            self._refresh_info_text()

    # ------------------------------------------------------------------

    def _refresh_info_text(self):
        info = read_header_info(self.dec_buffer)
        text = (
            self.t("magic_line", magic=info["magic"], version=info["version"])
            + self.t("size_line", size=info["actual_size"], size_field=info["size_field"])
            + (self.t("checksum_ok_line") if info["checksum_ok"] else self.t("checksum_bad_line"))
            + self.t("location_line", loc=info["location"])
            + self.t("playtime_line", playtime=format_hms(info["playtime"]))
            + self.t("gold_line", gold1=info["gold1"], gold2=info["gold2"])
            + self.t("br_line", br=info["br"])
            + self.t("diggs_line", cur=info["diggs_attempts"], max=info["diggs_max_attempts"])
            + self.t("monster_kills_line", n=info["monster_kills"])
            + "\n"
        )

        text += self.t("unions_line_header")
        for i, stats in enumerate(info["union_stats"]):
            text += self.t(
                "union_line", n=i + 1, hp=stats["hp"], ap=stats["ap"], apf=stats["f3"])
        text += "\n"

        text += self.t("inventory_line_header")
        equip_owned = sum(
            1 for _, item_id in read_equipment(self.dec_buffer) if item_id != EQUIP_EMPTY_ID)
        acc_owned = sum(
            1 for _, item_id, _ in read_accessories(self.dec_buffer)
            if item_id != ACCESSORY_EMPTY_ID)
        text += self.t("inventory_line", label=self.t("subtab_equipment"), count=equip_owned)
        text += self.t("inventory_line", label=self.t("subtab_accessories"), count=acc_owned)
        if self.items_catalog:
            cat_label_keys = {
                "consumables": "subtab_consumables",
                "components": "subtab_components",
                "captured_monsters": "subtab_monsters",
                "special_items": "subtab_special",
            }
            for cat_key, label_key in cat_label_keys.items():
                type_filter = set(ITEMS_CATEGORY_TYPES[cat_key])
                count = sum(
                    1 for i, item in enumerate(self.items_catalog)
                    if item["type"] in type_filter
                    and read_item_qty(self.dec_buffer, i) > 0
                )
                text += self.t("inventory_line", label=self.t(label_key), count=count)

        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", text)
        self.info_text.configure(state="disabled")

    def open_file(self):
        path = filedialog.askopenfilename(
            title=self.t("select_sav_title"),
            filetypes=[(self.t("filetype_sav"), "*.sav"), (self.t("filetype_all"), "*.*")]
        )
        if not path:
            return
        self.load_save_file(path)

    def load_save_file(self, path):
        """Load a .sav file given its path directly, without a file dialog.
        Used both by open_file() and by startup auto-load (e.g. when the
        app is launched by double-clicking a .sav file)."""
        try:
            dec = decompress_save(path)
        except Exception as e:
            messagebox.showerror(self.t("err_title"), self.t("err_decompress", e=e))
            return

        self.dec_buffer = dec
        self.current_path = path
        self.current_filename = os.path.basename(path)
        self.file_label.config(text=self.current_filename)

        info = read_header_info(dec)
        self.original_gold1 = info["gold1"]
        self.original_gold2 = info["gold2"]
        self.gold1_var.set(str(info["gold1"]))
        # Temporarily enable to set the value
        self.gold2_entry.config(state="normal")
        self.gold2_var.set(str(info["gold2"]))
        self.gold2_entry.config(state="disabled")
        self.br_var.set(str(info["br"]))
        self.playtime_var.set(format_hms(info["playtime"]))
        self.diggs_attempts_var.set(str(info["diggs_attempts"]))
        self.diggs_max_var.set(str(info["diggs_max_attempts"]))
        self.monster_kills_var.set(str(info["monster_kills"]))
        self.selected_union_index = 0
        self.union_select_var.set("1")
        self._load_union_stats_into_fields()

        # If the item database failed to load at startup (e.g. a
        # cloud-synced folder that hadn't finished downloading
        # EquipItems.csv yet), quietly retry now - by the time the user
        # has picked a save file, the sync has often caught up.
        if not self.equip_names:
            self._load_equip_database(warn_on_empty=False)
        if not self.accessory_names:
            self._load_accessory_database(warn_on_empty=False)
        if not self.items_catalog:
            self._load_items_database(warn_on_empty=False)

        self._refresh_equip_tree()
        self._refresh_accessory_tree()
        for key in self.items_trees:
            self._refresh_items_tree(key)
        self._refresh_info_text()
        self._load_char_equip_into_fields()

    def save_new_file(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        try:
            new_gold1 = int(self.gold1_var.get())
            new_gold2 = int(self.gold2_var.get())  # Already synced via trace
            new_br = int(self.br_var.get())
            new_playtime = parse_hms(self.playtime_var.get())
            new_diggs_attempts = int(self.diggs_attempts_var.get())
            new_diggs_max = int(self.diggs_max_var.get())
            new_monster_kills = int(self.monster_kills_var.get())
            new_rush_stats = {}
            for key, label_key, rel_off, size in RUSH_STATS:
                new_rush_stats[key] = int(self.rush_stat_vars[key].get())
        except ValueError:
            messagebox.showerror(self.t("err_title"), self.t("err_int"))
            return

        initial_dir = os.path.dirname(self.current_path) if self.current_path else None
        out_path = filedialog.asksaveasfilename(
            title=self.t("save_as_title"),
            defaultextension=".sav",
            initialfile=self.current_filename,
            initialdir=initial_dir,
            filetypes=[(self.t("filetype_sav"), "*.sav")]
        )
        if not out_path:
            return

        buf = bytearray(self.dec_buffer)
        buf[GOLD_OFFSET:GOLD_OFFSET + 4] = struct.pack("<i", new_gold1)
        buf[GOLD_LIFETIME_OFFSET:GOLD_LIFETIME_OFFSET + 4] = struct.pack("<i", new_gold2)
        buf[BR_OFFSET:BR_OFFSET + 2] = struct.pack("<h", new_br)
        buf[BR_DISPLAY_CACHE_OFFSET:BR_DISPLAY_CACHE_OFFSET + 2] = struct.pack("<h", new_br)
        buf[BR_EXP_OFFSET:BR_EXP_OFFSET + 2] = struct.pack("<h", 0)
        write_playtime_seconds(buf, new_playtime)
        write_mr_diggs_attempts(buf, new_diggs_attempts)
        write_mr_diggs_max_attempts(buf, new_diggs_max)
        write_monster_kills(buf, new_monster_kills)

        # Union stats: write both in-struct copies for all 12 slots, for
        # whichever union is currently shown (0=Union1 .. 4=Union5).
        # Any OTHER union's edits were already committed into
        # self.dec_buffer when the user switched away from it via the
        # selector (see _on_union_select_changed) - that's why buf was
        # built from self.dec_buffer above.
        write_union_stats(buf, self.selected_union_index, new_rush_stats)

        buf = recalc_checksum(buf)

        backup_path = backup_if_exists(out_path)

        raw = compress_save(bytes(buf))
        with open(out_path, "wb") as f:
            f.write(raw)

        msg = self.t("done_msg", path=out_path)
        if backup_path:
            msg += self.t("backup_line", backup=backup_path)
        messagebox.showinfo(self.t("done_title"), msg)

    def search_value(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first"))
            return
        try:
            value = int(self.search_var.get())
        except ValueError:
            messagebox.showerror(self.t("err_title"), self.t("err_int_search"))
            return

        hits = search_value_in_buffer(self.dec_buffer, value)
        self.search_result.delete("1.0", "end")
        if not hits:
            self.search_result.insert("1.0", self.t("search_none", value=value))
            return
        seen = set()
        lines = [self.t("search_found", n=len(hits))]
        for idx, size in hits:
            key = (idx, size)
            if key in seen:
                continue
            seen.add(key)
            lines.append(self.t("search_offset_line", off=hex(idx), size=size))
        self.search_result.insert("1.0", "\n".join(lines))

    def diff_with_other(self):
        if self.dec_buffer is None:
            messagebox.showwarning(self.t("warn_title"), self.t("warn_open_first2"))
            return
        path2 = filedialog.askopenfilename(
            title=self.t("select_sav2_title"),
            filetypes=[(self.t("filetype_sav"), "*.sav"), (self.t("filetype_all"), "*.*")]
        )
        if not path2:
            return
        try:
            dec2 = decompress_save(path2)
        except Exception as e:
            messagebox.showerror(self.t("err_title"), self.t("err_decompress", e=e))
            return

        regions = find_diff_regions(self.dec_buffer, dec2)
        merged = merge_regions(regions, gap=8)

        win = tk.Toplevel(self.root)
        win.title(self.t("diff_title", a=os.path.basename(self.current_path), b=os.path.basename(path2)))
        win.geometry("680x560")
        txt_frame = ttk.Frame(win)
        txt_frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(txt_frame)
        scroll.pack(side="right", fill="y")
        txt = tk.Text(txt_frame, wrap="none", yscrollcommand=scroll.set)
        txt.pack(side="left", fill="both", expand=True)
        scroll.config(command=txt.yview)

        # Each block gets a best-effort human label (gold, BR, union N,
        # a character's equipped weapon slot, etc.) on top of the raw
        # before/after bytes, via _describe_diff_block() - same field
        # catalog used everywhere else in the app.
        txt.insert("end", self.t("diff_found", n=len(merged)) + "\n")
        max_print = 300
        for s, e in merged[:max_print]:
            txt.insert("end", "\n" + self._describe_diff_block(self.dec_buffer, dec2, s, e) + "\n")
        if len(merged) > max_print:
            txt.insert("end", "\n" + self.t("diff_more_hidden", n=len(merged) - max_print) + "\n")

    def show_readme(self):
        win = tk.Toplevel(self.root)
        win.title(self.t("readme_win_title"))
        win.geometry("560x520")

        text_frame = ttk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=8, pady=8)

        scrollbar = ttk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")

        txt = tk.Text(text_frame, wrap="word", yscrollcommand=scrollbar.set)
        txt.insert("1.0", self.t("readme_content"))
        txt.configure(state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=txt.yview)


def main():
    root = tk.Tk()
    app = SaveEditorApp(root)

    # If launched with a file path (e.g. double-clicked a .sav file, or
    # dragged onto the app/script), auto-load it on startup instead of
    # showing an empty window. Only argv[1] is used; any further args
    # (macOS sometimes passes extra launch-services args) are ignored.
    if len(sys.argv) > 1:
        candidate = sys.argv[1]
        if os.path.isfile(candidate) and not candidate.startswith("-"):
            root.after(50, lambda: app.load_save_file(candidate))

    root.mainloop()


if __name__ == "__main__":
    main()
