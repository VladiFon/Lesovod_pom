# -*- coding: utf-8 -*-
"""Чтение Word-файлов «как есть»: .docx и старый .doc (Word 97–2003) без
Word и LibreOffice на сервере.

Нужно для загрузки проектов лесных культур из АРМ ЛВ (app/lk_proekt.py):
АРМ сохраняет проекты в .doc. Разбору формы важен только порядок текста —
абзацы и ячейки таблиц подряд, — поэтому оба формата сводятся к одному
списку «кусков» (chunks): каждый абзац вне таблицы и каждая ячейка таблицы —
отдельная строка, в порядке документа. Плюс картинки (план участка).

.doc читается напрямую: контейнер OLE (Compound File) → поток WordDocument →
таблица кусков текста (piece table, CLX) → текст. Ячейка таблицы в .doc
заканчивается символом \\x07, абзац — \\r. Картинки вынимаются из потока Data
по сигнатурам PNG/JPEG.
"""
import io
import re
import struct
import zipfile
from typing import Dict, List, Optional, Tuple


class WordError(Exception):
    """Ошибка, понятная человеку."""


# --------------------------------------------------------------------------- #
#   Compound File (OLE2) — минимальный читатель потоков
# --------------------------------------------------------------------------- #
_OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREE, _ENDCHAIN = 0xFFFFFFFF, 0xFFFFFFFE


def _ole_streams(data: bytes) -> Dict[str, bytes]:
    if data[:8] != _OLE_SIG:
        raise WordError("Это не файл Word 97–2003 (.doc)")
    ssz = 1 << struct.unpack_from("<H", data, 0x1E)[0]
    mssz = 1 << struct.unpack_from("<H", data, 0x20)[0]
    n_fat = struct.unpack_from("<I", data, 0x2C)[0]
    dir_start = struct.unpack_from("<I", data, 0x30)[0]
    cutoff = struct.unpack_from("<I", data, 0x38)[0]
    minifat_start, n_minifat = struct.unpack_from("<II", data, 0x3C)
    difat_start, n_difat = struct.unpack_from("<II", data, 0x44)

    def sector(i: int) -> bytes:
        off = (i + 1) * ssz
        return data[off:off + ssz]

    difat = list(struct.unpack_from("<109I", data, 0x4C))
    s = difat_start
    for _ in range(n_difat):
        if s in (_FREE, _ENDCHAIN):
            break
        blk = struct.unpack("<%dI" % (ssz // 4), sector(s))
        difat.extend(blk[:-1])
        s = blk[-1]
    fat: List[int] = []
    for fs in difat[:n_fat]:
        if fs in (_FREE, _ENDCHAIN):
            continue
        fat.extend(struct.unpack("<%dI" % (ssz // 4), sector(fs)))

    def chain(start: int, table: List[int], limit: int) -> List[int]:
        out, s, seen = [], start, set()
        while s not in (_FREE, _ENDCHAIN) and s < len(table) and s not in seen and len(out) < limit:
            seen.add(s)
            out.append(s)
            s = table[s]
        return out

    big_limit = len(data) // ssz + 2
    dir_bytes = b"".join(sector(x) for x in chain(dir_start, fat, big_limit))
    entries = []
    for off in range(0, len(dir_bytes) - 127, 128):
        e = dir_bytes[off:off + 128]
        nlen = struct.unpack_from("<H", e, 0x40)[0]
        name = e[:max(0, nlen - 2)].decode("utf-16-le", "replace")
        typ = e[0x42]
        start = struct.unpack_from("<I", e, 0x74)[0]
        size = struct.unpack_from("<I", e, 0x78)[0]
        entries.append((name, typ, start, size))
    if not entries:
        raise WordError("Файл .doc повреждён: нет каталога")
    root = entries[0]
    ministream = b"".join(sector(x) for x in chain(root[2], fat, big_limit))
    minifat: List[int] = []
    for x in chain(minifat_start, fat, big_limit)[:max(n_minifat, 0) or big_limit]:
        minifat.extend(struct.unpack("<%dI" % (ssz // 4), sector(x)))

    out: Dict[str, bytes] = {}
    for name, typ, start, size in entries[1:]:
        if typ != 2:  # только потоки
            continue
        if size < cutoff:
            blob = b"".join(ministream[m * mssz:(m + 1) * mssz]
                            for m in chain(start, minifat, len(minifat) + 1))
        else:
            blob = b"".join(sector(x) for x in chain(start, fat, big_limit))
        out[name] = blob[:size]
    return out


# --------------------------------------------------------------------------- #
#   .doc → текст
# --------------------------------------------------------------------------- #
def _doc_text(streams: Dict[str, bytes]) -> str:
    wd = streams.get("WordDocument")
    if not wd or len(wd) < 0x1AA:
        raise WordError("В файле нет текста Word (поток WordDocument)")
    if struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
        raise WordError("Файл не похож на документ Word")
    flags = struct.unpack_from("<H", wd, 0x0A)[0]
    if flags & 0x0100:
        raise WordError("Файл защищён паролем — снимите защиту и сохраните заново")
    table = streams.get("1Table" if flags & 0x0200 else "0Table")
    if table is None:
        raise WordError("Файл .doc повреждён: нет таблицы текста")
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x1A2)
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # Prc — пропускаем
        cb = struct.unpack_from("<H", clx, i + 1)[0]
        i += 3 + cb
    if i >= len(clx) or clx[i] != 0x02:
        raise WordError("Файл .doc: не найдена таблица кусков текста")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from("<%dI" % (n + 1), plc, 0)
    parts = []
    for k in range(n):
        pcd = plc[4 * (n + 1) + 8 * k:4 * (n + 1) + 8 * (k + 1)]
        fc = struct.unpack_from("<I", pcd, 2)[0]
        ln = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            off = (fc & 0x3FFFFFFF) // 2
            parts.append(wd[off:off + ln].decode("cp1252", "replace"))
        else:
            parts.append(wd[fc:fc + 2 * ln].decode("utf-16-le", "replace"))
    return "".join(parts)


def _ubrat_polya(t: str) -> str:
    """Поля Word: \\x13 код \\x14 результат \\x15 → результат."""
    out, stek = [], []  # stek: True — сейчас идёт код поля (не печатаем)
    for ch in t:
        if ch == "\x13":
            stek.append(True)
        elif ch == "\x14":
            if stek:
                stek[-1] = False
        elif ch == "\x15":
            if stek:
                stek.pop()
        elif not any(stek):
            out.append(ch)
    return "".join(out)


def _kartinki_iz(blob: bytes) -> List[Tuple[str, bytes]]:
    out = []
    pos = 0
    while True:
        i = blob.find(b"\x89PNG\r\n\x1a\n", pos)
        if i < 0:
            break
        j = blob.find(b"IEND", i)
        if j < 0:
            break
        out.append(("png", blob[i:j + 8]))
        pos = j + 8
    pos = 0
    while True:
        i = blob.find(b"\xff\xd8\xff", pos)
        if i < 0:
            break
        j = blob.find(b"\xff\xd9", i + 3)
        if j < 0:
            break
        out.append(("jpg", blob[i:j + 2]))
        pos = j + 2
    return out


def _chunks_iz_teksta(t: str) -> List[str]:
    t = _ubrat_polya(t)
    t = t.replace("\x0b", " ").replace("\x0c", "\r").replace("\x01", "").replace("\x08", "")
    kuski = re.split(r"[\r\x07]", t)
    return [_chist(k) for k in kuski]


def _chist(s: str) -> str:
    s = s.replace("\xa0", " ").replace("\t", " ")
    s = "".join(ch for ch in s if ch >= " ")
    return re.sub(r"\s+", " ", s).strip()


def prochitat_doc(data: bytes) -> dict:
    streams = _ole_streams(data)
    text = _doc_text(streams)
    kartinki = []
    for name in ("Data", "WordDocument"):
        if streams.get(name):
            kartinki = _kartinki_iz(streams[name])
            if kartinki:
                break
    return {"chunks": _chunks_iz_teksta(text), "kartinki": kartinki}


# --------------------------------------------------------------------------- #
#   .docx → те же куски
# --------------------------------------------------------------------------- #
def prochitat_docx(data: bytes) -> dict:
    try:
        import docx  # python-docx
        from docx.oxml.ns import qn
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise WordError(f"Не удалось открыть .docx: {exc}")
    chunks: List[str] = []

    def txt(el) -> str:
        parts = []
        for x in el.iter():
            if x.tag == qn("w:t"):
                parts.append(x.text or "")
            elif x.tag in (qn("w:br"), qn("w:tab")):
                parts.append(" ")
        return _chist("".join(parts))

    def walk(parent):
        for el in parent.iterchildren():
            if el.tag == qn("w:p"):
                chunks.append(txt(el))
            elif el.tag == qn("w:tbl"):
                for tr in el.iterchildren(qn("w:tr")):
                    for tc in tr.iterchildren(qn("w:tc")):
                        paras = [txt(p) for p in tc.iterchildren(qn("w:p"))]
                        chunks.append(_chist(" ".join(p for p in paras if p)))
                        for vlozh in tc.iterchildren(qn("w:tbl")):
                            walk_tbl(vlozh)
            elif el.tag == qn("w:sdt"):
                c = el.find(qn("w:sdtContent"))
                if c is not None:
                    walk(c)

    def walk_tbl(tbl):
        for tr in tbl.iterchildren(qn("w:tr")):
            for tc in tr.iterchildren(qn("w:tc")):
                chunks.append(txt(tc))

    walk(d.element.body)
    kartinki = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in sorted(z.namelist()):
            if n.startswith("word/media/"):
                ext = n.rsplit(".", 1)[-1].lower()
                if ext in ("png", "jpg", "jpeg", "gif", "bmp", "emf", "wmf"):
                    kartinki.append(("jpg" if ext == "jpeg" else ext, z.read(n)))
    return {"chunks": chunks, "kartinki": kartinki}


def prochitat(data: bytes, filename: str = "") -> dict:
    """{"chunks": [str, ...], "kartinki": [(ext, bytes), ...]} — по содержимому,
    а не по расширению (АРМ иногда пишет .doc, а внутри .docx, и наоборот)."""
    if data[:8] == _OLE_SIG:
        return prochitat_doc(data)
    if data[:2] == b"PK":
        return prochitat_docx(data)
    if data[:5] == b"{\\rtf":
        raise WordError(f"{filename or 'Файл'}: это RTF — откройте в Word и сохраните как .doc или .docx")
    raise WordError(f"{filename or 'Файл'}: не Word-документ (.doc/.docx)")
