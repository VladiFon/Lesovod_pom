# -*- coding: utf-8 -*-
"""Корзина (удалённое можно вернуть 30 дней) и автокопия базы перед
массовым импортом — «защита от ошибок» из анализа удобства (01.10.2026).

Корзина устроена как снимок строк: перед настоящим удалением делянки или
участка лесокультур все его строки (сама запись + дочерние таблицы, которые
удаление чистит) сохраняются JSON-ом в таблицу korzina, а потом выполняется
прежнее удаление без изменений. Восстановление вставляет строки обратно с
теми же id. Так остальные запросы системы (списки, ведомости, ЕГАИС) ничего
не знают о корзине — удалённое из них исчезает так же, как раньше.
"""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.paths import STORAGE_DIR

KORZINA_DNEI = 30
BACKUPS_DIR = STORAGE_DIR / "backups"
BACKUPS_HRANIT = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS korzina (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tip TEXT NOT NULL,
    obj_id INTEGER NOT NULL,
    nazvanie TEXT,
    snapshot TEXT NOT NULL,
    deleted_by TEXT,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

TIPY = {"delyanka": "Делянка", "lesokultury_uchastok": "Участок лесных культур"}


def ensure_schema(conn):
    conn.executescript(SCHEMA)


def _rows(conn, table, where, params):
    cur = conn.execute(f"SELECT * FROM {table} WHERE {where}", params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _in(ids):
    return ",".join("?" for _ in ids) or "NULL"


# Таблицы, которые ссылаются на делянку / её выделы / участок культур.
# «Дети» удаляются вместе с объектом (без него они бессмысленны), у
# «ссылок» ссылка обнуляется — сами записи (табель, трелёвка, план работ,
# разбор ЕГАИС) остаются в истории. Без этого удаление делянки, у которой
# есть акт освидетельствования или бригада, падало с ошибкой FOREIGN KEY.
_DETI_DELYANKI = [
    ("osvidetelstvovanie_checklist", "delyanka_id"),
    ("osvidetelstvovanie_acts", "delyanka_id"),
    ("brigada_naznachenie", "delyanka_id"),
]
_SSYLKI_DELYANKI = [("lesokultury_uchastok", "delyanka_id"),
                    ("egais_unmatched_delyanka", "linked_delyanka_id")]
_SSYLKI_ITEM = [("egais_sklad_link", "delyanka_item_id"), ("work_plan", "delyanka_item_id"),
                ("trelevka", "delyanka_item_id"), ("tabel_zapis", "delyanka_item_id")]
_SSYLKI_UCHASTKA = [("work_plan", "lesokultury_uchastok_id"),
                    ("tabel_zapis", "lesokultury_uchastok_id")]

NULL_KEY = "__ssylki__"


def _est_tablica(conn, table, col=None):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return bool(cols) and (col is None or col in cols)


def _pk(conn, table):
    pk = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[5]]
    return pk[0] if pk else "rowid"


def _ssylki(conn, spisok_ssylok, ids):
    """[{t, pk, pkv, col, val}] — строки, у которых при удалении обнулится ссылка."""
    out = []
    if not ids:
        return out
    for table, col in spisok_ssylok:
        if not _est_tablica(conn, table, col):
            continue
        pk = _pk(conn, table)
        for pkv, val in conn.execute(
            f"SELECT {pk}, {col} FROM {table} WHERE {col} IN ({_in(ids)})", list(ids)
        ):
            out.append({"t": table, "pk": pk, "pkv": pkv, "col": col, "val": val})
    return out


def snapshot_delyanka(conn, delyanka_id):
    """Все строки, которые удаляются вместе с делянкой, — в порядке
    вставки при восстановлении (родители раньше детей) + обнуляемые ссылки."""
    d = _rows(conn, "delyanka", "id = ?", (delyanka_id,))
    items = _rows(conn, "delyanka_item", "delyanka_id = ?", (delyanka_id,))
    item_ids = [i["id"] for i in items]
    naryady = _rows(conn, "raskhod_naryad", f"item_id IN ({_in(item_ids)})", item_ids) if item_ids else []
    n_ids = [n["id"] for n in naryady]
    pozicii = _rows(conn, "raskhod_pozitsiya", f"naryad_id IN ({_in(n_ids)})", n_ids) if n_ids else []
    out = [("delyanka", d), ("delyanka_item", items), ("raskhod_naryad", naryady), ("raskhod_pozitsiya", pozicii)]
    for table, col in _DETI_DELYANKI:
        if _est_tablica(conn, table, col):
            out.append((table, _rows(conn, table, f"{col} = ?", (delyanka_id,))))
    ssylki = _ssylki(conn, _SSYLKI_DELYANKI, [delyanka_id]) + _ssylki(conn, _SSYLKI_ITEM, item_ids)
    out.append((NULL_KEY, ssylki))
    return out


def snapshot_uchastok(conn, uchastok_id):
    u = _rows(conn, "lesokultury_uchastok", "id = ?", (uchastok_id,))
    m = _rows(conn, "lesokultury_meropriyatiya", "uchastok_id = ?", (uchastok_id,))
    return [("lesokultury_uchastok", u), ("lesokultury_meropriyatiya", m),
            (NULL_KEY, _ssylki(conn, _SSYLKI_UCHASTKA, [uchastok_id]))]


def otvyazat(conn, snapshot):
    """Перед прежним удалением: убрать «детей» сверх тех, что чистит
    старая функция удаления, и обнулить ссылки из истории."""
    main_tables = {"delyanka", "delyanka_item", "raskhod_naryad", "raskhod_pozitsiya",
                   "lesokultury_uchastok", "lesokultury_meropriyatiya"}
    for table, rows in snapshot:
        if table == NULL_KEY:
            for r in rows:
                conn.execute(f"UPDATE {r['t']} SET {r['col']} = NULL WHERE {r['pk']} = ?", (r["pkv"],))
        elif table not in main_tables and rows:
            pk = _pk(conn, table)
            conn.execute(f"DELETE FROM {table} WHERE {pk} IN ({_in(rows)})", [r[pk] for r in rows])


def polozhit(conn, tip, obj_id, nazvanie, snapshot, user_login):
    ensure_schema(conn)
    conn.execute(
        "INSERT INTO korzina (tip, obj_id, nazvanie, snapshot, deleted_by) VALUES (?, ?, ?, ?, ?)",
        (tip, obj_id, nazvanie, json.dumps(snapshot, ensure_ascii=False, default=str), user_login),
    )
    # Без commit: запись в корзину, отвязка и само удаление — одна
    # транзакция (её завершает commit в delete_delyanka / delete_uchastok).


def ochistit_starye(conn):
    ensure_schema(conn)
    granica = (datetime.now() - timedelta(days=KORZINA_DNEI)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM korzina WHERE deleted_at < ?", (granica,))
    conn.commit()


def spisok(conn):
    ochistit_starye(conn)
    cur = conn.execute(
        "SELECT id, tip, obj_id, nazvanie, deleted_by, deleted_at, snapshot FROM korzina ORDER BY id DESC"
    )
    out = []
    for kid, tip, obj_id, nazvanie, by, at, snap in cur.fetchall():
        try:
            udalit_do = (datetime.strptime(at, "%Y-%m-%d %H:%M:%S") + timedelta(days=KORZINA_DNEI)).strftime("%d.%m.%Y")
        except (TypeError, ValueError):
            udalit_do = None
        tables = json.loads(snap)
        sostav = {t: len(rows) for t, rows in tables if t != NULL_KEY}
        out.append({
            "id": kid, "tip": tip, "tip_label": TIPY.get(tip, tip), "obj_id": obj_id,
            "nazvanie": nazvanie, "deleted_by": by, "deleted_at": at, "udalit_do": udalit_do,
            "sostav": sostav,
        })
    return out


def vosstanovit(conn, korzina_id):
    """Вставляет строки снимка обратно с прежними id. Колонки берутся
    только те, что есть в таблице сейчас (схема могла вырасти), чтобы
    восстановление не падало после обновления программы."""
    ensure_schema(conn)
    row = conn.execute("SELECT tip, obj_id, snapshot FROM korzina WHERE id = ?", (korzina_id,)).fetchone()
    if row is None:
        raise KeyError("Запись корзины не найдена")
    tip, obj_id, snap = row
    tables = json.loads(snap)
    main_table = tables[0][0]
    if conn.execute(f"SELECT 1 FROM {main_table} WHERE id = ?", (obj_id,)).fetchone():
        raise ValueError("Объект с таким номером уже есть в базе — восстановление не нужно")
    try:
        for table, rows in tables:
            if table == NULL_KEY:
                continue
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for r in rows:
                cols = [c for c in r if c in existing]
                conn.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [r[c] for c in cols],
                )
        for table, rows in tables:
            if table == NULL_KEY:
                for r in rows:
                    if _est_tablica(conn, r["t"], r["col"]):
                        conn.execute(
                            f"UPDATE {r['t']} SET {r['col']} = ? WHERE {r['pk']} = ? AND {r['col']} IS NULL",
                            (r["val"], r["pkv"]),
                        )
        conn.execute("DELETE FROM korzina WHERE id = ?", (korzina_id,))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return {"tip": tip, "obj_id": obj_id}


def udalit_navsegda(conn, korzina_id):
    ensure_schema(conn)
    conn.execute("DELETE FROM korzina WHERE id = ?", (korzina_id,))
    conn.commit()


# --------------------------------------------------------------------------- #
#   Автокопия базы перед массовыми операциями
# --------------------------------------------------------------------------- #
def avtokopiya(conn, prichina):
    """Копия всей базы (sqlite backup API — безопасно при работающем
    сервере и WAL) в storage/backups/. Хранятся последние BACKUPS_HRANIT.
    Ошибка копирования не должна ломать сам импорт — возвращаем None."""
    try:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in prichina)[:40]
        path = BACKUPS_DIR / f"lesovod_{datetime.now():%Y%m%d_%H%M%S}_{safe}.db"
        dest = sqlite3.connect(str(path))
        try:
            conn.backup(dest)
        finally:
            dest.close()
        kopii = sorted(BACKUPS_DIR.glob("lesovod_*.db"))
        for old in kopii[:-BACKUPS_HRANIT]:
            old.unlink(missing_ok=True)
        return path
    except Exception:  # noqa: BLE001
        return None


def spisok_kopiy():
    if not BACKUPS_DIR.exists():
        return []
    out = []
    for p in sorted(BACKUPS_DIR.glob("lesovod_*.db"), reverse=True):
        st = p.stat()
        out.append({"file": p.name, "size_mb": round(st.st_size / 1024 / 1024, 1),
                    "created": datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")})
    return out


def put_kopii(name: str) -> Path:
    p = (BACKUPS_DIR / name).resolve()
    if p.parent != BACKUPS_DIR.resolve() or not p.name.startswith("lesovod_") or not p.exists():
        raise FileNotFoundError(name)
    return p
