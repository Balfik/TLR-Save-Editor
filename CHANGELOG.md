# Changelog

Version history for TLR Save Editor. Kept in this file from v0.25.2 onward;
versions before 0.21.0 weren't tracked in a dedicated changelog at the
time, so the entry for them below is a general summary of what already
existed by then, not a step-by-step list of changes.

## 0.35.0
- New integrity check on open: before a save is loaded, the app now
  verifies the magic signature, decompressed size, and checksum, and
  warns (with a chance to cancel) if anything looks off - instead of
  only finding out something's wrong once you're mid-edit.
- New "Clone..." button on the Union tab: copies a union's full roster
  (leader + slots 2-5) and stat block straight into another union slot
  in one click, without going through the profile export/import flow.
- Equipment, Accessories, and item-quantity lists (Consumables,
  Components, Captured Monsters, Special Items) are now sortable by
  clicking a column heading - click again to reverse the order.
- New "Export inventory (CSV)..." button next to the Save Info panel:
  exports every individually owned item (Equipment, Accessories, and
  all 4 item categories) with its quantity to a single CSV file -
  distinct from the existing "Export report..." button, which only
  covers summary counts.

## 0.34.0
- New startup update check: on launch, the app quietly checks GitHub for a
  newer release and offers to open the release page if one exists.
  Silent and non-blocking if offline or the check fails for any reason.
- New "Search (Ctrl/Cmd+F)..." global search: jump straight to any
  tab/section (Gold, Union, Equipment, Accessories, Character Equipment,
  Tools sections, Item Catalog, etc.) by typing part of its name, instead
  of hunting for it by hand.
- New "Item Catalog" tab: a reference-only, searchable list of every known
  item name across Equipment, Accessories, and the 4 Items.csv categories
  - independent of what the currently-loaded save actually owns.
- New persistent undo history: undo now survives closing and reopening
  the app for the same save file (previously session-only), mirrored to a
  small on-disk log per file.
- Diff results (both "Diff..." and "Compare 3+ saves...") now color the
  changed values instead of showing everything in one plain color, so
  what actually changed stands out at a glance.

## 0.33.0
- New "Clean up old..." button in the Snapshots list: pick how many of the
  most recent snapshots to keep and remove the rest. Snapshots are also
  now auto-pruned to the newest 30 every time a new one is saved, so the
  snapshots folder doesn't grow without bound on its own. Also fixed a bug
  where two snapshots taken within the same second could silently
  overwrite each other.
- New "Fix checksum..." button on the Tools tab: repairs the checksum of
  any .sav file that won't load due to a broken checksum (e.g. edited by
  hand in another tool), without needing the command-line version.
- New Gold/Battle Rank presets on the Tools tab's batch section: pick a
  ready-made combo ("Endgame test" or "Reset") to quick-fill both fields
  instead of typing the numbers by hand.
- New equipment profile library on the Character Equipment tab ("To
  library..." / "From library..."): save/load a single character's
  weapon+shield loadout by name, same idea as the existing union profile
  library but scoped to one character.
- Added a hover tooltip on the Equipment/Accessories/item-quantity lists
  noting that multiple rows can be selected at once (Ctrl/Cmd or
  Shift-click) and edited together - this already worked, it just wasn't
  obvious.

## 0.32.4
- Union tab: gave up trying to color-match the scrollable canvas to the
  themed frames around it (unreliable across platforms) - the content
  frame now always stretches to cover the full visible area instead, so
  there's no bare strip of canvas left showing through at all.

## 0.32.3
- Union tab: fixed the previous 0.32.2 attempt at the background-seam fix,
  which silently did nothing on macOS (its native theme doesn't report a
  plain background color the way the fix was checking for) - now uses the
  actual macOS system background color on Mac, and still falls back to the
  themed color on Windows/Linux.

## 0.32.2
- Tools tab: the Diff section no longer stretches to fill leftover window
  space, so the Batch processing section below it sits right underneath
  instead of leaving a large empty gap.
- Union tab: the scrollable content area now matches the app's actual
  background color instead of a plain default, removing the visible seam
  where the two used to meet.

## 0.32.1
- Union tab: the stats grid (HP/AP/STR/etc.) is now 6 columns instead of
  3, cutting its height roughly in half.
- Union roster rows (character + weapon + 6 stats) are more compact -
  narrower dropdowns and stat fields, so more fits without scrolling.
- The still-unconfirmed stat fields (marked "(?)" - Stat #4, Stat #5,
  INT, SPD) now show an explanatory tooltip on hover instead of just a
  "?" in the label.
- Added a "175" quick-fill button next to the existing "255" one on the
  Inventory -> Equipment stats row.

## 0.32.0
- New "Undo" button next to Save: reverts the last Applied change in the
  current session (union roster/stats, equipment, accessories, items,
  character equipment, gold/BR/etc. via Save) without reloading the file
  from disk. Session-only - has no effect on files already written.
- New "Snapshot..." / "Snapshots..." buttons: save a timestamped, checksummed
  copy of the current buffer (with an optional comment) into a
  `snapshots` folder next to the program, and browse/restore past
  snapshots from a list - independent of the automatic ".bak" backup and
  the Undo button above.
- New "Compare 3+ saves..." button on the Tools tab: pick three or more
  `.sav` files and see every differing region (vs. the first file as the
  base) with each file's value listed side by side, for tracking
  progress across several checkpoints at once.
- New "Batch processing" section on the Tools tab: set Gold and/or Battle
  Rank across several selected `.sav` files in one action (each gets a
  `.bak` backup and a recalculated checksum), instead of opening and
  saving each file by hand.

## 0.31.1
- The union profile library now saves into a `union_profiles` folder next
  to the program itself (not the user's home folder), so it's easy to find
  and moves with the app.
- The "From library..." picker now shows who's actually in each profile
  (leader + slots 2-5) right next to its name, instead of just the file
  name.

## 0.31.0
- Union profile export now suggests a default file name ("Union N") instead
  of an empty one.
- New in-app union profile library: "To library..." / "From library..."
  buttons save/load profiles by name from a small local folder, without a
  file dialog every time (the existing "Save profile..." / "Load
  profile..." buttons for arbitrary .json files are unchanged).
- New opt-in "Warn about duplicate characters across unions" checkbox on
  the Union tab - if enabled, applying a roster that puts a character in
  more than one union/slot at once now asks for confirmation first
  (duplicates themselves are still allowed, same as before).
- New "Export report..." button next to the Save Info panel - saves the
  current gold/Battle Rank/playtime/unions/inventory summary to a plain
  text or CSV file, for sharing progress without handing over the save
  file itself.
- Saving now checks gold, Battle Rank, playtime, Mr. Diggs attempts/max,
  and monster kills against generous plausible ranges, and asks for
  confirmation before writing if any value looks like a typo (e.g.
  negative, or far outside the field's normal range).

## 0.30.0
- New "Find saves..." button at the top of the window: pick a folder once
  (it's remembered), and the app recursively scans it for `.sav` files and
  shows a list to open with one click - no more browsing the "Open file"
  dialog by hand every time. A "Different folder..." button lets you
  change the search location.

## 0.29.0
- The save comparison window (the "Diff" button on the Tools tab) now
  labels found differences in plain language (Gold, Battle Rank, Union N,
  a specific character's equipment, etc.) instead of just raw bytes and
  offsets. Added a scrollbar to the results window.

## 0.28.0
- Union equipment profiles: "Save profile" / "Load profile" buttons on the
  Union tab - save/restore a union roster (leader + 4 slots), each
  member's weapon, and weapon stats to a JSON file, so the same loadout
  can be re-applied to other saves without re-entering everything by hand.

## 0.27.0
- Live search/filter in the item and character dropdowns: typing narrows
  the list (case-insensitive substring match) on the Inventory tab
  (weapons, accessories, item granting), Character Equipment, and Union
  (character and weapon pickers).

## 0.26.0
- Added two bulk weapon-stat buttons on the Union tab for the whole union
  at once (leader + all 4 slots): "Whole union: 250" and
  "Whole union: MAX (255)".

## 0.25.2
- The Union tab is now wrapped in a scrollable container (vertical and
  horizontal scroll, mouse wheel / Shift+wheel) - rows no longer get
  clipped if the window is smaller than the content.
- Default window size increased to 960x700.

## 0.25.1
- Added two quick-fill buttons to each union roster row (leader + slots
  2-5): "175" and "250" - set all 6 weapon stat fields for that row in
  one click.

## 0.25.0
- On the Union tab, each roster row now also shows and lets you edit that
  character's current weapon (item + 6 stats) - the same fields used on
  the Inventory tab, right where the union roster is edited.

## 0.24.0
- New "Character Equipment" tab: view and edit what a character (not just
  Rush) is actually wearing (weapon + shield/secondary slot), based on the
  newly discovered CHAR_EQUIP table (base `0x25F00`, record stride
  `0x78`, 2 slots per character).

## 0.23.0
- The app can now be launched by double-clicking a `.sav` file (accepts
  the save path as a command-line argument and auto-loads it on startup)
  - enables wrapping it into a macOS app via Platypus.

## 0.22.0
- Added a clickable author link (https://github.com/Balfik) at the
  bottom-left of the window.

## 0.21.0
- Activation of previously-empty union slots 6-8 (the game supports 8
  unions; the default UI only shows 5).

## Before 0.21.0 (no dedicated changelog, summarized)
- Tabbed GUI with a UA/EN language toggle.
- Editing gold, Battle Rank (+ EXP counter), playtime, Mr. Diggs attempts,
  monster kill count.
- Inventory editor: Equipment, Accessories, Consumables, Components,
  Captured Monsters, Special Items - granting new items, editing
  quantity, and editing stats on items already owned/equipped.
- Union editor: stats for all 8 unions, leader and roster (slots 1-5),
  duplicate character assignments across slots/unions.
- Automatic SHA1 checksum recalculation on every save.
- CLI tool `save_explorer.py` (info / diff / search / setgold / setbr /
  fixchecksum).
