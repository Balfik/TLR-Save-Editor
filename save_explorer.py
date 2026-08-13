#!/usr/bin/env python3
"""
save_explorer.py — інструмент для дослідження сейвів The Last Remnant Remastered

Формат файлу (встановлено реверс-інжинірингом):
  * Весь .sav файл — це один "сирий" zlib-потік (сигнатура 78 DA), без
    жодного контейнера/футера. zlib.decompress(raw) дає весь вміст одразу.
  * Розпакований буфер (в усіх трьох аналізованих сейвах — 1 719 936 байт)
    починається заголовком:
        offset 0x00  4 байти  ASCII "SAVE"           (магічна сигнатура)
        offset 0x04  int32    версія формату (=1)
        offset 0x08  int32    розмір розпакованих даних (= len(decompressed))
        offset 0x0C  20 байт  ЗЛАМАНО! Це SHA1-хеш решти файлу:
                                  hash = SHA1(dec[32:])
                                  dec[12:32] = hash
                              Знайдено реверс-інжинірингом .NET-утиліти
                              TLRPSave (метод ChecksumFix викликає
                              SHA1.Create().ComputeHash(Content, 32, len-32),
                              підтверджено на 4 реальних сейвах - 100% збіг).
                              Наш інструмент ПЕРЕРАХОВУЄ цей хеш автоматично
                              при кожному записі файлу (recalc_checksum()),
                              тож редагування тепер безпечне для гри.
        offset 0x20..0x2F   ще 4 байти лічильників/прапорців (0x20-0x2F)
        offset 0x30          UTF-16 рядок поточної локації виду
                              "NGP_0000_MP0::NGP_06PL::NGP"
                              (регіон_карта::регіон_зона::регіон)
        далі                 таблиця world-map міток "wm_loca_label_XXX"
                              (позначки відкритих локацій на мапі світу)

  Далі в файлі йдуть текстові UTF-16 таблиці ресурсів (назви зон, карт),
  а числові дані персонажів/інвентарю/квестів лежать без текстових підписів
  в окремих структурах.

GOLD — ПІДТВЕРДЖЕНО контрольним тестом (продаж 1 шт. предмета ID 137
за 6 gold/шт: обидва поля нижче зросли рівно на 6; раніше в тесті з
квестом обидва зросли на 6000):

  GOLD (offset 0x1D978, int32 LE) — це реальний поточний баланс Gold.
                                Лежить одразу перед таблицею інвентарю.
  GOLD_LIFETIME_CANDIDATE (offset 0x25A5A, int32 LE) — теж зростає
                                синхронно з Gold, але лежить серед
                                масиву дрібних службових чисел (457,
                                320, 15, 69, 3, 4...). Найімовірніше —
                                лічильник "всього золота зароблено за
                                гру" (lifetime), а НЕ поточний гаманець.
                                Не використовуй для редагування балансу.

ТАБЛИЦЯ ІНВЕНТАРЮ — знайдена тим самим тестом. База ~0x209E8,
записи по 12 байт:
    byte[0:4]   - невідомо/padding (0 у спостережених записах)
    byte[4:6]   - int16, порядковий індекс слота (0,1,2,3...)
    byte[6:8]   - uint16, ID предмета
    byte[8:10]  - int16, кількість (quantity)
    byte[10:12] - невідомо/padding
У тесті предмет ID 137 (0x0089) в слоті index=2 зменшився з 859 до 858
(продали 1 шт.) синхронно з ростом Gold на 6.

BATTLE RANK — уточнено після тестування в грі. Виявилось, що поле
0x28 — це ЛИШЕ кеш для екрану завантаження (гравець підтвердив: зміна
цього поля міняє число тільки на екрані load, не в самій грі). Реальні
поля знайдено повторним тестом (той самий сценарій: тільки Rush, один
бій, BR 61->62) і перевірено на ДВОХ незалежних парах сейвів:

  BR_OFFSET (0x259DD, int16 LE) — РЕАЛЬНИЙ Battle Rank, який
                                використовує гра (перевір саме це поле,
                                а не 0x28).
  BR_EXP_OFFSET (0x259DF, int16 LE) — лічильник BR EXP, 0-499,
                                скидається на 0 при переході рангу.
                                Формула підтверджена вікі-статтею гри
                                (500 EXP = +1 BR): у тесті 03->04
                                (BR лишився 59) EXP виріс 434->497
                                (не досяг порогу); у тесті 05->06
                                (BR виріс 61->62) EXP був 498, перейшов
                                поріг і скинувся на 0.
  BR_DISPLAY_CACHE_OFFSET (0x28, int16) — косметичний кеш для екрану
                                завантаження, не впливає на гру. Наш
                                setbr все одно оновлює й його, щоб не
                                було розбіжності в цифрах між екранами.


Використання:
    python3 save_explorer.py info <save.sav>
    python3 save_explorer.py diff <save1.sav> <save2.sav>
    python3 save_explorer.py search <save.sav> <число>
    python3 save_explorer.py dump <save.sav> <offset_hex> <довжина>
    python3 save_explorer.py getgold <save.sav>
    python3 save_explorer.py setgold <save.sav> <нове_значення> <output.sav>
    python3 save_explorer.py getbr <save.sav>
    python3 save_explorer.py setbr <save.sav> <нове_значення> <output.sav>
    python3 save_explorer.py fixchecksum <save.sav> <output.sav>
    python3 save_explorer.py unpack <save.sav> <output.bin>
    python3 save_explorer.py repack <input.bin> <output.sav>
"""
import sys
import zlib
import struct
import os
import hashlib

MAGIC = b"SAVE"
GOLD_OFFSET = 0x1D978
GOLD_LIFETIME_OFFSET = 0x25A5A
BR_DISPLAY_CACHE_OFFSET = 0x28   # тільки кеш для екрану завантаження (підтверджено користувачем!)
BR_OFFSET = 0x259DD              # РЕАЛЬНИЙ Battle Rank, що використовує гра (int16 LE)
BR_EXP_OFFSET = 0x259DF          # лічильник BR EXP, 0-499, скидається на 0 при рангап (int16 LE)
CHECKSUM_OFFSET = 0x0C       # де лежить сам хеш (20 байт)
CHECKSUM_DATA_START = 0x20  # з якого офсету рахується SHA1


# ---------------------------------------------------------------------------
# Базові операції з файлом
# ---------------------------------------------------------------------------

def load_raw(path):
    with open(path, "rb") as f:
        return f.read()


def decompress_save(path_or_bytes):
    """Розпаковує .sav (raw zlib stream) у сирий буфер даних."""
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else load_raw(path_or_bytes)
    if data[:2] != b"\x78\xda" and data[:2] != b"\x78\x9c" and data[:2] != b"\x78\x01":
        print(f"[!] Увага: файл не починається зі звичного zlib-заголовка "
              f"(отримано {data[:2].hex()}). Спробую розпакувати все одно.")
    return zlib.decompress(data)


def compress_save(decompressed_bytes, level=9):
    """Запаковує сирий буфер назад у zlib-потік (як .sav файл)."""
    return zlib.compress(decompressed_bytes, level)


def recalc_checksum(dec_bytes):
    """Перераховує SHA1-чек-суму та вписує її в заголовок.

    Формула (знайдена реверс-інжинірингом TLRPSave.exe, метод ChecksumFix,
    підтверджена на 4 реальних сейвах):
        hash = SHA1(dec[0x20:])
        dec[0x0C:0x20] = hash

    Приймає bytes/bytearray, повертає НОВИЙ bytearray з виправленим хешем
    (оригінал не змінює).
    """
    buf = bytearray(dec_bytes)
    new_hash = hashlib.sha1(bytes(buf[CHECKSUM_DATA_START:])).digest()
    buf[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 20] = new_hash
    return buf


def verify_checksum(dec_bytes):
    """Перевіряє, чи збігається збережений хеш із реальним вмістом файлу."""
    stored = bytes(dec_bytes[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 20])
    actual = hashlib.sha1(bytes(dec_bytes[CHECKSUM_DATA_START:])).digest()
    return stored == actual, stored, actual


def read_header(dec):
    magic = dec[0:4]
    version = struct.unpack("<i", dec[4:8])[0]
    size_field = struct.unpack("<i", dec[8:12])[0]
    session_field = dec[12:28]
    return {
        "magic": magic,
        "magic_ok": magic == MAGIC,
        "version": version,
        "size_field": size_field,
        "actual_size": len(dec),
        "size_matches": size_field == len(dec),
        "session_field_hex": session_field.hex(),
    }


def try_decode_location_string(dec, start=0x30, max_len=200):
    """Пробує прочитати UTF-16 рядок локації одразу після заголовка."""
    chunk = dec[start:start + max_len]
    # шукаємо подвійний нуль-термінатор (кінець UTF-16 рядка)
    end = len(chunk)
    for i in range(0, len(chunk) - 1, 2):
        if chunk[i] == 0 and chunk[i + 1] == 0:
            end = i
            break
    try:
        return chunk[:end].decode("utf-16-le", errors="replace")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------

def cmd_info(path):
    dec = decompress_save(path)
    hdr = read_header(dec)
    ok, stored, actual = verify_checksum(dec)
    print(f"Файл: {path}")
    print(f"  Розмір на диску (стиснутий): {os.path.getsize(path)} байт")
    print(f"  Розмір розпакований:         {len(dec)} байт")
    print(f"  Magic:                       {hdr['magic']!r}  (ok={hdr['magic_ok']})")
    print(f"  Версія формату:              {hdr['version']}")
    print(f"  Поле розміру в заголовку:    {hdr['size_field']} (matches={hdr['size_matches']})")
    print(f"  SHA1 чек-сума:               {'OK ✅' if ok else 'НЕ ЗБІГАЄТЬСЯ ⚠️'}")
    if not ok:
        print(f"    збережена: {stored.hex()}")
        print(f"    реальна:   {actual.hex()}")
    loc = try_decode_location_string(dec)
    print(f"  Рядок локації:               {loc!r}")
    print()
    print("  Кандидати на Gold:")
    for name, off in [("gold", GOLD_OFFSET), ("gold_lifetime_candidate", GOLD_LIFETIME_OFFSET)]:
        val = struct.unpack("<i", dec[off:off + 4])[0]
        print(f"    {name} @ {hex(off)} = {val}")
    br_cache = struct.unpack("<h", dec[BR_DISPLAY_CACHE_OFFSET:BR_DISPLAY_CACHE_OFFSET + 2])[0]
    br_real = struct.unpack("<h", dec[BR_OFFSET:BR_OFFSET + 2])[0]
    br_exp = struct.unpack("<h", dec[BR_EXP_OFFSET:BR_EXP_OFFSET + 2])[0]
    print(f"  Battle Rank (реальний) @ {hex(BR_OFFSET)} = {br_real}")
    print(f"  Battle Rank EXP @ {hex(BR_EXP_OFFSET)} = {br_exp} / 500")
    print(f"  Battle Rank (кеш екрану завантаження) @ {hex(BR_DISPLAY_CACHE_OFFSET)} = {br_cache}")


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def find_diff_regions(a, b):
    """Повертає список (start, end) байтових діапазонів, де a і b відрізняються."""
    regions = []
    i = 0
    n = min(len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            regions.append((i, j))
            i = j
        else:
            i += 1
    if len(a) != len(b):
        regions.append((n, max(len(a), len(b))))
    return regions


def merge_regions(regions, gap=8):
    merged = []
    for s, e in regions:
        if merged and s - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


def describe_region(a, b, s, e):
    la = a[s:e]
    lb = b[s:e]
    length = e - s
    parts = [f"[{hex(s)}:{hex(e)}] len={length}"]
    parts.append(f"  before: {la.hex()}")
    parts.append(f"  after : {lb.hex()}")

    # Спроба інтерпретувати як ціле число (якщо розмір підходить)
    for size, fmt, label in [(2, "<h", "int16"), (4, "<i", "int32"), (8, "<q", "int64")]:
        if length == size:
            try:
                va = struct.unpack(fmt, la)[0]
                vb = struct.unpack(fmt, lb)[0]
                parts.append(f"  as {label}: {va} -> {vb}  (diff={vb - va})")
            except struct.error:
                pass
            try:
                vau = struct.unpack(fmt.replace("<", "<").upper() if False else fmt.upper().replace("<", "<"), la)
            except Exception:
                pass

    # Спроба прочитати як UTF-16 текст (якщо це схоже на текст)
    try:
        txt_a = la.decode("utf-16-le", errors="ignore").strip("\x00")
        txt_b = lb.decode("utf-16-le", errors="ignore").strip("\x00")
        if txt_a.isprintable() and txt_b.isprintable() and (txt_a or txt_b):
            parts.append(f"  as utf16: {txt_a!r} -> {txt_b!r}")
    except Exception:
        pass

    return "\n".join(parts)


def cmd_diff(path_a, path_b, gap=8, max_print=200):
    a = decompress_save(path_a)
    b = decompress_save(path_b)
    if len(a) != len(b):
        print(f"[!] Розпаковані розміри відрізняються: {len(a)} vs {len(b)}")
    regions = find_diff_regions(a, b)
    merged = merge_regions(regions, gap=gap)
    total_bytes = sum(e - s for s, e in regions)
    print(f"Порівняння: {path_a}  ->  {path_b}")
    print(f"  Розпакований розмір: {len(a)} байт (обидва)")
    print(f"  Змінених ділянок (без об'єднання): {len(regions)}, разом байт: {total_bytes}")
    print(f"  Змінених блоків (об'єднано з gap<= {gap}): {len(merged)}")
    print()
    for idx, (s, e) in enumerate(merged[:max_print]):
        print(f"--- блок {idx + 1}/{len(merged)} ---")
        print(describe_region(a, b, s, e))
        print()
    if len(merged) > max_print:
        print(f"... ще {len(merged) - max_print} блоків не показано (збільш --max_print)")


# ---------------------------------------------------------------------------
# search — пошук конкретного числа у файлі (щоб самому знайти нове поле)
# ---------------------------------------------------------------------------

def cmd_search(path, value_str):
    dec = decompress_save(path)
    value = int(value_str)
    hits = []
    for size, fmt in [(1, "<b"), (2, "<h"), (4, "<i"), (8, "<q")]:
        try:
            packed_signed = struct.pack(fmt, value)
        except struct.error:
            packed_signed = None
        try:
            packed_unsigned = struct.pack(fmt.upper(), value) if value >= 0 else None
        except struct.error:
            packed_unsigned = None
        for packed, kind in [(packed_signed, "signed"), (packed_unsigned, "unsigned")]:
            if packed is None:
                continue
            start = 0
            while True:
                idx = dec.find(packed, start)
                if idx == -1:
                    break
                hits.append((idx, size, kind))
                start = idx + 1
    if not hits:
        print(f"Значення {value} не знайдено як int8/16/32/64 (LE) у файлі.")
        return
    print(f"Знайдено {len(hits)} співпадінь для значення {value}:")
    seen = set()
    for idx, size, kind in hits:
        key = (idx, size)
        if key in seen:
            continue
        seen.add(key)
        print(f"  offset={hex(idx)}  розмір={size} байт  ({kind})")


# ---------------------------------------------------------------------------
# dump — hex-дамп довільної ділянки
# ---------------------------------------------------------------------------

def cmd_dump(path, offset_hex, length_str):
    dec = decompress_save(path)
    off = int(offset_hex, 16)
    length = int(length_str)
    chunk = dec[off:off + length]
    print(f"Дамп {path} @ {hex(off)}, довжина {length}:")
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        hex_part = " ".join(f"{byte:02x}" for byte in row)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        print(f"  {hex(off + i):>10}: {hex_part:<48} {ascii_part}")


# ---------------------------------------------------------------------------
# gold get/set
# ---------------------------------------------------------------------------

def cmd_getgold(path):
    dec = decompress_save(path)
    for name, off in [("gold", GOLD_OFFSET),
                       ("gold_lifetime_candidate", GOLD_LIFETIME_OFFSET)]:
        val = struct.unpack("<i", dec[off:off + 4])[0]
        print(f"  {name} @ {hex(off)}: {val}")


def cmd_setgold(path, new_value_str, out_path, which="1"):
    dec = bytearray(decompress_save(path))
    off = GOLD_OFFSET if which == "1" else GOLD_LIFETIME_OFFSET
    new_value = int(new_value_str)
    old_value = struct.unpack("<i", dec[off:off + 4])[0]
    dec[off:off + 4] = struct.pack("<i", new_value)
    dec = recalc_checksum(dec)
    raw = compress_save(bytes(dec))
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"Записав {out_path}: gold @ {hex(off)} змінено з {old_value} на {new_value}.")
    print("SHA1 чек-суму перераховано автоматично — файл має коректно завантажитись у грі.")


def cmd_getbr(path):
    dec = decompress_save(path)
    br_real = struct.unpack("<h", dec[BR_OFFSET:BR_OFFSET + 2])[0]
    br_exp = struct.unpack("<h", dec[BR_EXP_OFFSET:BR_EXP_OFFSET + 2])[0]
    br_cache = struct.unpack("<h", dec[BR_DISPLAY_CACHE_OFFSET:BR_DISPLAY_CACHE_OFFSET + 2])[0]
    print(f"  Battle Rank (реальний) @ {hex(BR_OFFSET)}: {br_real}")
    print(f"  Battle Rank EXP @ {hex(BR_EXP_OFFSET)}: {br_exp} / 500")
    print(f"  Battle Rank (кеш екрану завантаження) @ {hex(BR_DISPLAY_CACHE_OFFSET)}: {br_cache}")


def cmd_setbr(path, new_value_str, out_path, reset_exp=True):
    """Змінює РЕАЛЬНИЙ Battle Rank і одразу узгоджує кеш екрану завантаження,
    щоб обидва місця в грі показували однакове число. За замовчуванням також
    обнуляє лічильник BR EXP (як це робить сама гра після рангапу)."""
    dec = bytearray(decompress_save(path))
    new_value = int(new_value_str)
    old_value = struct.unpack("<h", dec[BR_OFFSET:BR_OFFSET + 2])[0]
    dec[BR_OFFSET:BR_OFFSET + 2] = struct.pack("<h", new_value)
    dec[BR_DISPLAY_CACHE_OFFSET:BR_DISPLAY_CACHE_OFFSET + 2] = struct.pack("<h", new_value)
    if reset_exp:
        dec[BR_EXP_OFFSET:BR_EXP_OFFSET + 2] = struct.pack("<h", 0)
    dec = recalc_checksum(dec)
    raw = compress_save(bytes(dec))
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"Записав {out_path}: Battle Rank змінено з {old_value} на {new_value} "
          f"(оновлено і реальне поле {hex(BR_OFFSET)}, і кеш {hex(BR_DISPLAY_CACHE_OFFSET)}).")
    if reset_exp:
        print(f"BR EXP @ {hex(BR_EXP_OFFSET)} скинуто на 0.")
    print("SHA1 чек-суму перераховано автоматично — файл має коректно завантажитись у грі.")


def cmd_fixchecksum(path, out_path):
    """Перераховує SHA1 чек-суму файлу без інших змін (ручний ремонт)."""
    dec = bytearray(decompress_save(path))
    ok, stored, actual = verify_checksum(dec)
    dec = recalc_checksum(dec)
    raw = compress_save(bytes(dec))
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"Чек-сума була {'коректна' if ok else 'НЕ коректна'} до перерахунку.")
    print(f"Записав {out_path} з оновленою SHA1 чек-сумою.")


# ---------------------------------------------------------------------------
# unpack / repack — сирі операції для ручного дослідження в hex-редакторі
# ---------------------------------------------------------------------------

def cmd_unpack(path, out_path):
    dec = decompress_save(path)
    with open(out_path, "wb") as f:
        f.write(dec)
    print(f"Розпаковано {path} -> {out_path} ({len(dec)} байт)")


def cmd_repack(path, out_path, fix_checksum=False):
    with open(path, "rb") as f:
        dec = bytearray(f.read())
    if fix_checksum:
        ok, stored, actual = verify_checksum(dec)
        dec = recalc_checksum(dec)
        print(f"Чек-сума була {'коректна' if ok else 'НЕ коректна'} — перерахував SHA1.")
    raw = compress_save(bytes(dec))
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"Запаковано {path} -> {out_path} ({len(raw)} байт)")
    # sanity check
    check = zlib.decompress(raw)
    print(f"  Перевірка round-trip: {'OK' if check == bytes(dec) else 'FAIL!'}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    args = sys.argv[2:]
    try:
        if cmd == "info":
            cmd_info(args[0])
        elif cmd == "diff":
            gap = 8
            if "--gap" in args:
                i = args.index("--gap")
                gap = int(args[i + 1])
                del args[i:i + 2]
            cmd_diff(args[0], args[1], gap=gap)
        elif cmd == "search":
            cmd_search(args[0], args[1])
        elif cmd == "dump":
            cmd_dump(args[0], args[1], args[2])
        elif cmd == "getgold":
            cmd_getgold(args[0])
        elif cmd == "getbr":
            cmd_getbr(args[0])
        elif cmd == "setbr":
            keep_exp = "--keepexp" in args
            if keep_exp:
                args.remove("--keepexp")
            cmd_setbr(args[0], args[1], args[2], reset_exp=not keep_exp)
        elif cmd == "setgold":
            which = "1"
            if "--candidate2" in args:
                args.remove("--candidate2")
                which = "2"
            cmd_setgold(args[0], args[1], args[2], which=which)
        elif cmd == "fixchecksum":
            cmd_fixchecksum(args[0], args[1])
        elif cmd == "unpack":
            cmd_unpack(args[0], args[1])
        elif cmd == "repack":
            fix = "--fixchecksum" in args
            if fix:
                args.remove("--fixchecksum")
            cmd_repack(args[0], args[1], fix_checksum=fix)
        else:
            print(__doc__)
    except IndexError:
        print("Бракує аргументів. Дивись довідку нижче:\n")
        print(__doc__)


if __name__ == "__main__":
    main()
