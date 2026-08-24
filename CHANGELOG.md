# Changelog

Version history for TLR Save Editor. Kept in this file from v0.25.2 onward;
versions before 0.21.0 weren't tracked in a dedicated changelog at the
time, so the entry for them below is a general summary of what already
existed by then, not a step-by-step list of changes.

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
