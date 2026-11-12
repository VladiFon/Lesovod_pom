# -*- coding: utf-8 -*-
"""Пометки лесосек на картах (12.11.2026, жалоба Влада на кашу из слоёв).

Беда: в ГИСлесхозе лесосеки копятся за все годы, уборка захламлённости,
санитарные и прочие рубки нарезаются на весь выдел, и в QGIS и в телефоне
полигоны ложатся друг на друга в несколько слоёв. Плюс нигде не видно, что
лесосека лежит на лесных культурах.

Здесь две вещи:

1. Пометка конкретного объекта (таблица karta_pometki):
   - istochnik = 'delyanka' — делянка Лесовода, klyuch = delyanka.id;
   - istochnik = 'gisleshoz' — лесосека ГИСлесхоза (таблица area), klyuch = uid;
   - istochnik = 'lk' — участок лесных культур, klyuch = lesokultury_uchastok.id.
   skryta = 1 — не рисовать на картах (QGIS-слои плагина, телефон, веб);
   lesokultury = 1 / 0 — вручную «это лесные культуры» / «это не культуры»,
   NULL — определять само: на выделе лесосеки есть живой участок культур.

2. Общие правила (таблица karta_nastroyki):
   - skryt_zakrytye — закрытые делянки (архив после акта) на картах не нужны;
   - skryt_vidy — коды видов рубки, которые не показывать вообще (например УЗ);
   - gisleshoz_let — лесосеки ГИСлесхоза старше N лет не показывать (0 — все).

Ничего не удаляется: скрытое видно в списке «Скрытые с карт» и
возвращается одной кнопкой."""
import json
import re
from datetime import date
from typing import Dict, Iterable, List, Optional, Set, Tuple

ISTOCHNIKI = ("delyanka", "gisleshoz", "lk")

SCHEMA = """
CREATE TABLE IF NOT EXISTS karta_pometki (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    istochnik TEXT NOT NULL,
    klyuch TEXT NOT NULL,
    skryta INTEGER NOT NULL DEFAULT 0,
    lesokultury INTEGER,
    opisanie TEXT,
    kto TEXT,
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(istochnik, klyuch)
);
CREATE TABLE IF NOT EXISTS karta_nastroyki (
    klyuch TEXT PRIMARY KEY,
    znachenie TEXT
);
"""

NASTROYKI_PO_UMOLCHANIYU = {
    "skryt_zakrytye": True,
    "skryt_vidy": [],
    "gisleshoz_let": 0,
}


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ------------------------------------------------------------- настройки --

def nastroyki(conn) -> dict:
    ensure_schema(conn)
    out = dict(NASTROYKI_PO_UMOLCHANIYU)
    for k, v in conn.execute("SELECT klyuch, znachenie FROM karta_nastroyki").fetchall():
        if k not in out:
            continue
        try:
            out[k] = json.loads(v)
        except (TypeError, ValueError):
            pass
    out["skryt_zakrytye"] = bool(out["skryt_zakrytye"])
    out["skryt_vidy"] = [str(x).strip() for x in (out["skryt_vidy"] or []) if str(x).strip()]
    try:
        out["gisleshoz_let"] = max(0, int(out["gisleshoz_let"] or 0))
    except (TypeError, ValueError):
        out["gisleshoz_let"] = 0
    return out


def sohranit_nastroyki(conn, izmeneniya: dict) -> dict:
    ensure_schema(conn)
    for k, v in izmeneniya.items():
        if k not in NASTROYKI_PO_UMOLCHANIYU or v is None:
            continue
        conn.execute("INSERT INTO karta_nastroyki (klyuch, znachenie) VALUES (?, ?) "
                     "ON CONFLICT(klyuch) DO UPDATE SET znachenie = excluded.znachenie",
                     (k, json.dumps(v, ensure_ascii=False)))
    conn.commit()
    return nastroyki(conn)


# --------------------------------------------------------------- пометки --

def _klyuch(value) -> str:
    s = str(value if value is not None else "").strip()
    # uid из ГИСлесхоза приходит то числом, то строкой «123.0»
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


def pometki(conn) -> Dict[Tuple[str, str], dict]:
    ensure_schema(conn)
    out = {}
    for (p_id, ist, kl, skryta, lk, opisanie, kto, upd) in conn.execute(
            "SELECT id, istochnik, klyuch, skryta, lesokultury, opisanie, kto, updated_at FROM karta_pometki").fetchall():
        out[(ist, kl)] = {"id": p_id, "istochnik": ist, "klyuch": kl, "skryta": bool(skryta),
                          "lesokultury": None if lk is None else bool(lk), "opisanie": opisanie,
                          "kto": kto, "updated_at": upd}
    return out


def postavit(conn, istochnik: str, klyuchi: Iterable, *, skryta: Optional[bool] = None,
             lesokultury: Optional[object] = "ne_menyat", opisaniya: Optional[Dict[str, str]] = None,
             kto: Optional[str] = None) -> int:
    """Поставить пометку пачкой. skryta=None — не менять; lesokultury:
    True/False — вручную, None — снова «само», "ne_menyat" — не трогать."""
    if istochnik not in ISTOCHNIKI:
        raise ValueError("Неизвестный источник лесосеки")
    ensure_schema(conn)
    opisaniya = opisaniya or {}
    n = 0
    for raw in klyuchi:
        kl = _klyuch(raw)
        if not kl:
            continue
        conn.execute("INSERT OR IGNORE INTO karta_pometki (istochnik, klyuch) VALUES (?, ?)", (istochnik, kl))
        sets, params = ["kto = ?", "updated_at = datetime('now', 'localtime')"], [kto]
        if skryta is not None:
            sets.append("skryta = ?")
            params.append(1 if skryta else 0)
        if lesokultury != "ne_menyat":
            sets.append("lesokultury = ?")
            params.append(None if lesokultury is None else (1 if lesokultury else 0))
        op = (opisaniya.get(kl) or opisaniya.get(str(raw)) or "").strip()
        if op:
            sets.append("opisanie = ?")
            params.append(op[:300])
        conn.execute(f"UPDATE karta_pometki SET {', '.join(sets)} WHERE istochnik = ? AND klyuch = ?",
                     (*params, istochnik, kl))
        n += 1
    # пустые пометки (не скрыта и культуры «само») не храним
    conn.execute("DELETE FROM karta_pometki WHERE skryta = 0 AND lesokultury IS NULL")
    conn.commit()
    return n


# ------------------------------------------------- лесные культуры по выделам --

def _norm(x) -> str:
    from app import map_features

    return map_features.norm_id(x)


def _vydely(text) -> List[str]:
    return [v for v in (_norm(p) for p in re.split(r"[,;/ ]+", str(text or ""))) if v]


def lk_po_vydelam(conn) -> Dict[Tuple[str, str], List[str]]:
    """(кв, выд) -> ["ЛК 2019 С 1,2 га", …] — живые участки культур
    (не списанные и не скрытые с карт). Лесничество не сверяем: номер
    квартала в лесхозе свой у каждого лесничества, но у Влада одно
    лесничество на сервер — так проще и не теряет совпадений, а ложное
    совпадение лечится ручной пометкой «не культуры»."""
    from app import map_features

    skrytye_lk = {kl for (ist, kl), p in pometki(conn).items() if ist == "lk" and p["skryta"]}
    out: Dict[Tuple[str, str], List[str]] = {}
    for u in map_features.lesokultury_for_map(conn, None):
        if str(u["id"]) in skrytye_lk:
            continue
        opis = " ".join(str(x) for x in (u.get("vid_kultur_kod") or "л/к", u.get("god_sozdaniya") or "",
                                          u.get("glavnaya_poroda") or "") if str(x).strip())
        spisok = out.setdefault((u["kvartal"], u["vydel"]), [])
        if opis not in spisok:
            spisok.append(opis)
    return out


# ------------------------------------------------------------ фильтр карт --

def _god(text) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", str(text or ""))
    return int(m.group(0)) if m else None


class Filtr:
    """Собирается один раз на запрос: что прятать и что метить л/к."""

    def __init__(self, conn):
        self.nast = nastroyki(conn)
        self.pom = pometki(conn)
        self.lk = lk_po_vydelam(conn)
        self.vidy: Set[str] = set(self.nast["skryt_vidy"])
        self.zakrytye: Set[int] = set()
        if self.nast["skryt_zakrytye"]:
            self.zakrytye = {r[0] for r in conn.execute(
                "SELECT id FROM delyanka WHERE status = 'архив'").fetchall()}
        let = self.nast["gisleshoz_let"]
        self.min_god = date.today().year - let + 1 if let else None

    def _pometka(self, istochnik, klyuch) -> Optional[dict]:
        return self.pom.get((istochnik, _klyuch(klyuch)))

    def lesokultury(self, istochnik, klyuch, kvartal, vydely: Iterable[str]) -> Tuple[bool, str]:
        p = self._pometka(istochnik, klyuch)
        if p is not None and p["lesokultury"] is not None:
            return p["lesokultury"], ("отмечено вручную" if p["lesokultury"] else "")
        kv = _norm(kvartal)
        naideno = []
        for vd in vydely:
            for opis in self.lk.get((kv, _norm(vd)), []):
                if opis not in naideno:
                    naideno.append(opis)
        return bool(naideno), ", ".join(naideno)

    def prichina_delyanki(self, delyanka_id, vid_kod) -> Optional[str]:
        """Почему делянку не рисовать (None — рисовать)."""
        p = self._pometka("delyanka", delyanka_id)
        if p is not None and p["skryta"]:
            return "скрыта вручную"
        if delyanka_id in self.zakrytye:
            return "закрыта (архив)"
        if vid_kod and vid_kod in self.vidy:
            return f"вид рубки {vid_kod} не показывается"
        return None

    def prichina_gisleshoz(self, uid, vid_kod, raw: dict) -> Optional[str]:
        p = self._pometka("gisleshoz", uid)
        if p is not None and p["skryta"]:
            return "скрыта вручную"
        if vid_kod and vid_kod in self.vidy:
            return f"вид рубки {vid_kod} не показывается"
        if self.min_god:
            god = _god(raw.get("date")) or _god(raw.get("info"))
            if god and god < self.min_god:
                return f"старше {self.nast['gisleshoz_let']} лет"
        return None

    def lk_skryt(self, uchastok_id) -> bool:
        p = self._pometka("lk", uchastok_id)
        return bool(p and p["skryta"])

    # --- разметка готовых признаков ---------------------------------------
    def razmetit_delyanku(self, props: dict, vse: bool = False) -> bool:
        """props с delyanka_id/kvartal/vydel/vid_rubki_kod: дописать
        lesokultury/lk_info/pometka/skryta. False — объект не отдавать."""
        d_id = props.get("delyanka_id")
        lk, info = self.lesokultury("delyanka", d_id, props.get("kvartal"), _vydely(props.get("vydel")))
        props["lesokultury"], props["lk_info"] = lk, info
        props["pometka"] = f"delyanka:{d_id}" if d_id is not None else None
        prichina = self.prichina_delyanki(d_id, props.get("vid_rubki_kod")) if d_id is not None else None
        props["skryta"] = prichina is not None
        props["skryta_prichina"] = prichina
        return vse or prichina is None

    def razmetit_gisleshoz(self, props: dict, vse: bool = False) -> bool:
        raw = {str(k).lower(): v for k, v in (props.get("raw") or {}).items()}
        uid = raw.get("uid")
        if uid is None:
            return True
        vydely = _vydely(raw.get("num_vds") or raw.get("num_vd") or props.get("vydel"))
        lk, info = self.lesokultury("gisleshoz", uid, raw.get("num_kv") or props.get("kvartal"), vydely)
        props["lesokultury"], props["lk_info"] = lk, info
        props["pometka"] = f"gisleshoz:{_klyuch(uid)}"
        prichina = self.prichina_gisleshoz(uid, props.get("vid_rubki_kod"), raw)
        props["skryta"] = prichina is not None
        props["skryta_prichina"] = prichina
        return vse or prichina is None


# ---------------------------------------------------------- список скрытых --

def spisok_skrytyh(conn) -> List[dict]:
    """Всё, что сейчас скрыто вручную, — с понятным описанием, для «Вернуть»."""
    out = []
    pom = pometki(conn)
    naz = {}
    ids = [int(kl) for (ist, kl) in pom if ist == "delyanka" and kl.isdigit()]
    if ids:
        q = ",".join("?" * len(ids))
        for d_id, nazvanie, kv, vd in conn.execute(
                f"SELECT d.id, d.nazvanie, MIN(i.kvartal), GROUP_CONCAT(i.vydel, ',') FROM delyanka d "
                f"LEFT JOIN delyanka_item i ON i.delyanka_id = d.id WHERE d.id IN ({q}) GROUP BY d.id", ids).fetchall():
            naz[str(d_id)] = f"{nazvanie or 'Делянка'} (кв. {kv or '?'}, выд. {vd or '?'})"
    lk_ids = [int(kl) for (ist, kl) in pom if ist == "lk" and kl.isdigit()]
    if lk_ids:
        q = ",".join("?" * len(lk_ids))
        for u_id, kv, vd, god, poroda in conn.execute(
                f"SELECT id, kvartal, vydel, god_sozdaniya, glavnaya_poroda FROM lesokultury_uchastok WHERE id IN ({q})",
                lk_ids).fetchall():
            naz["lk" + str(u_id)] = f"Культуры {poroda or ''} {god or ''} (кв. {kv}, выд. {vd})".replace("  ", " ")
    for (ist, kl), p in sorted(pom.items(), key=lambda x: x[1]["updated_at"] or "", reverse=True):
        if not p["skryta"] and p["lesokultury"] is None:
            continue
        if ist == "delyanka":
            nazvanie = naz.get(kl) or p["opisanie"] or f"Делянка №{kl}"
        elif ist == "lk":
            nazvanie = naz.get("lk" + kl) or p["opisanie"] or f"Участок культур №{kl}"
        else:
            nazvanie = p["opisanie"] or f"Лесосека ГИСлесхоза uid {kl}"
        out.append({**p, "nazvanie": nazvanie, "istochnik_label": {
            "delyanka": "Делянка Лесовода", "gisleshoz": "Лесосека ГИСлесхоза", "lk": "Лесные культуры"}[ist]})
    return out


def dlya_qgis(conn) -> dict:
    """Что плагину нужно для слоя «Лесосеки» самого ГИСлесхоза (его плагин
    рисует из своей базы, наш сервер его не фильтрует): скрытые uid, ручные
    пометки л/к, выделы с культурами и правила."""
    pom = pometki(conn)
    f = Filtr(conn)
    return {
        "nastroyki": f.nast,
        "gisleshoz_skryty": sorted(kl for (ist, kl), p in pom.items() if ist == "gisleshoz" and p["skryta"]),
        "gisleshoz_lk": sorted(kl for (ist, kl), p in pom.items() if ist == "gisleshoz" and p["lesokultury"] is True),
        "gisleshoz_ne_lk": sorted(kl for (ist, kl), p in pom.items() if ist == "gisleshoz" and p["lesokultury"] is False),
        "lk_vydely": [{"kvartal": kv, "vydel": vd, "info": ", ".join(opis)} for (kv, vd), opis in sorted(f.lk.items())],
    }
