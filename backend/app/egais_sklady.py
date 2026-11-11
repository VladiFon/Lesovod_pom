# -*- coding: utf-8 -*-
"""Склады ЕГАИС и остатки на них (11.11.2026, просьба Влада).

Робот вечерней выгрузки (deploy/egais_avto, 3.3+) кроме реестра движения
выгружает из ЕГАИС ещё два отчёта и заливает сюда:

  «Склад → Склады»                          — справочник складов: название,
      квартал/выдел, лесосека, КООРДИНАТЫ, дата открытия, вид, id Склада;
  «Склад → Наличие продукции на складах»    — что лежит на каждом складе
      прямо сейчас: порода, сортимент, деловая/дрова, объём.

Оба файла связаны через «id Склада». Здесь:
  * импорт (вид файла определяется по шапке, строка «Записей: N» в конце
    пропускается);
  * обзор для сайта: остаток по складам (деловая / дрова / по породам),
    к какой делянке склад относится (тот же разбор, что и у журнала —
    raskhod_v2.resolve_egais_sklady), сколько дней склад без движения,
    срок вывозки делянки → «лес залежался»;
  * GeoJSON для QGIS (точки складов с остатком в подписи) и точки для
    карты телефона.

Справочник складов копится (склад, пропавший из выгрузки «Активен», помечается
v_vygruzke=0, но не удаляется). Наличие — снимок: каждая заливка заменяет
прошлую; итог по складу за день дополнительно пишется в egais_nalichie_den
(история — по ней видно, двигается ли остаток).
"""
import datetime
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS egais_sklad (
    id_sklada INTEGER PRIMARY KEY,
    nazvanie TEXT NOT NULL,
    vid TEXT,
    data_otkrytiya TEXT,
    kvartal TEXT,
    vydel TEXT,
    lesoseka TEXT,
    lat REAL,
    lon REAL,
    adres TEXT,
    sostoyanie TEXT,
    vid_deyatelnosti TEXT,
    podrazdelenie TEXT,
    vladelec TEXT,
    yurlico TEXT,
    data_zakrytiya TEXT,
    data_izmeneniya TEXT,
    v_vygruzke INTEGER NOT NULL DEFAULT 1,
    obnovleno TEXT
);
CREATE TABLE IF NOT EXISTS egais_nalichie (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_sklada INTEGER,
    sklad TEXT,
    kvartal TEXT,
    vydel TEXT,
    nomenklatura TEXT,
    metod TEXT,
    poroda TEXT,
    kol REAL,
    obyom REAL,
    diametr TEXT,
    dlina TEXT,
    sortiment TEXT,
    godnost TEXT,
    sort TEXT
);
CREATE INDEX IF NOT EXISTS idx_egais_nalichie_sklad ON egais_nalichie(id_sklada);
CREATE TABLE IF NOT EXISTS egais_nalichie_den (
    data TEXT NOT NULL,
    id_sklada INTEGER NOT NULL,
    delovaya REAL NOT NULL DEFAULT 0,
    drova REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (data, id_sklada)
);
CREATE TABLE IF NOT EXISTS egais_sklady_meta (
    klyuch TEXT PRIMARY KEY,
    znachenie TEXT
);
"""

ZALEZHALSYA_DNEY = 14   # склад с остатком без движения столько дней — «залежался»
VYVOZKA_SKORO_DNEY = 30  # срок вывозки делянки ближе — «горит»


class SkladyError(Exception):
    pass


def ensure(conn):
    conn.executescript(SCHEMA)


def _s(v):
    return "" if v is None else str(v).strip()


def _f(v):
    try:
        return float(_s(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _data(v):
    """«28.10.2026» / «28.10.2026 12:51:26» → ISO; пусто → None."""
    s = _s(v)
    if not s:
        return None
    for fmt, n in (("%d.%m.%Y %H:%M:%S", 19), ("%d.%m.%Y", 10), ("%Y-%m-%d", 10)):
        try:
            d = datetime.datetime.strptime(s[:n], fmt)
            return d.strftime("%Y-%m-%d %H:%M:%S" if n == 19 else "%Y-%m-%d")
        except ValueError:
            continue
    return None


def _prochitat(put):
    import openpyxl
    wb = openpyxl.load_workbook(put, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        shapka = [_s(h) for h in next(it, [])]
        stroki = [dict(zip(shapka, r)) for r in it]
    finally:
        wb.close()
    return shapka, stroki


def vid_fayla(shapka):
    nizh = [h.lower() for h in shapka]
    if "id склада" not in nizh:
        return None
    if any("геокоординаты" in h for h in nizh):
        return "sklady"
    if "номенклатура" in nizh and any(h.startswith("объем") or h.startswith("объём") for h in nizh):
        return "nalichie"
    return None


def _meta(conn, klyuch, znachenie=None):
    if znachenie is None:
        r = conn.execute("SELECT znachenie FROM egais_sklady_meta WHERE klyuch = ?", (klyuch,)).fetchone()
        return r[0] if r else None
    conn.execute("INSERT INTO egais_sklady_meta (klyuch, znachenie) VALUES (?, ?) "
                 "ON CONFLICT(klyuch) DO UPDATE SET znachenie = excluded.znachenie", (klyuch, znachenie))
    return znachenie


def importirovat(conn, put, segodnya=None):
    """Заливает файл «Склады» или «Наличие продукции на складах» (что это —
    видно по шапке). Возвращает {"vid", ...счётчики}."""
    ensure(conn)
    try:
        shapka, stroki = _prochitat(put)
    except Exception as e:  # noqa: BLE001
        raise SkladyError(f"Файл не читается как Excel: {e}")
    vid = vid_fayla(shapka)
    if vid is None:
        raise SkladyError("Это не выгрузка «Склады» и не «Наличие продукции на складах» из ЕГАИС "
                          f"(нет колонки «id Склада»). Шапка: {', '.join(shapka[:6])}…")
    stroki = [r for r in stroki if _i(r.get("id Склада")) is not None]
    seychas = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if vid == "sklady":
        if not stroki:
            raise SkladyError("В файле «Склады» нет ни одного склада — выгрузка пустая, ничего не меняю.")
        byli = {r[0] for r in conn.execute("SELECT id_sklada FROM egais_sklad").fetchall()}
        novye, s_koord = 0, 0
        conn.execute("UPDATE egais_sklad SET v_vygruzke = 0")
        for r in stroki:
            sid = _i(r.get("id Склада"))
            lat, lon = _f(r.get("Геокоординаты - широта")), _f(r.get("Геокоординаты - долгота"))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                lat = lon = None
            else:
                s_koord += 1
            novye += sid not in byli
            conn.execute(
                "INSERT INTO egais_sklad (id_sklada, nazvanie, vid, data_otkrytiya, kvartal, vydel, lesoseka, lat, lon, "
                "adres, sostoyanie, vid_deyatelnosti, podrazdelenie, vladelec, yurlico, data_zakrytiya, data_izmeneniya, "
                "v_vygruzke, obnovleno) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?) "
                "ON CONFLICT(id_sklada) DO UPDATE SET nazvanie=excluded.nazvanie, vid=excluded.vid, "
                "data_otkrytiya=excluded.data_otkrytiya, kvartal=excluded.kvartal, vydel=excluded.vydel, "
                "lesoseka=excluded.lesoseka, lat=excluded.lat, lon=excluded.lon, adres=excluded.adres, "
                "sostoyanie=excluded.sostoyanie, vid_deyatelnosti=excluded.vid_deyatelnosti, "
                "podrazdelenie=excluded.podrazdelenie, vladelec=excluded.vladelec, yurlico=excluded.yurlico, "
                "data_zakrytiya=excluded.data_zakrytiya, data_izmeneniya=excluded.data_izmeneniya, "
                "v_vygruzke=1, obnovleno=excluded.obnovleno",
                (sid, _s(r.get("Наименование склада")) or f"склад {sid}", _s(r.get("Вид склада")),
                 _data(r.get("Дата открытия")), _s(r.get("Номер лесного квартала")),
                 _s(r.get("Номер таксационного выдела")), _s(r.get("Лесосека")), lat, lon,
                 _s(r.get("Адрес склада (Место размещения склада)")), _s(r.get("Состояние склада")),
                 _s(r.get("Вид деятельности")), _s(r.get("Структурное подразделение")), _s(r.get("Владелец склада")),
                 _s(r.get("Юр.лицо (л/х учреждение)")), _data(r.get("Дата закрытия")),
                 _data(r.get("Дата изменения")), seychas))
        propali = conn.execute("SELECT COUNT(*) FROM egais_sklad WHERE v_vygruzke = 0").fetchone()[0]
        _meta(conn, "sklady_zalito", seychas)
        conn.commit()
        return {"vid": "sklady", "skladov": len(stroki), "novyh": novye, "s_koordinatami": s_koord,
                "bez_koordinat": len(stroki) - s_koord, "net_v_vygruzke": propali}

    # наличие — снимок: заменяет прошлый целиком (пустой файл = на складах пусто)
    den = (segodnya or datetime.date.today()).isoformat()
    conn.execute("DELETE FROM egais_nalichie")
    po_skladu = {}
    for r in stroki:
        sid = _i(r.get("id Склада"))
        ob = _f(r.get("Объем") if "Объем" in r else r.get("Объём")) or 0.0
        godnost = _s(r.get("Техническая годность"))
        conn.execute(
            "INSERT INTO egais_nalichie (id_sklada, sklad, kvartal, vydel, nomenklatura, metod, poroda, kol, obyom, "
            "diametr, dlina, sortiment, godnost, sort) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, _s(r.get("Склад")), _s(r.get("Номер лесного квартала")), _s(r.get("Номер таксационного выдела")),
             _s(r.get("Номенклатура")), _s(r.get("Метод опр. объема")), _s(r.get("Порода")), _f(r.get("Кол-во")), ob,
             _s(r.get("Диаметр")) or _s(r.get("Группа диаметров")), _s(r.get("Длина")), _s(r.get("Сортимент")),
             godnost, _s(r.get("Сорт"))))
        x = po_skladu.setdefault(sid, [0.0, 0.0])
        x[1 if _eto_drova(godnost) else 0] += ob
    conn.execute("DELETE FROM egais_nalichie_den WHERE data = ?", (den,))
    for sid, (del_, dr) in po_skladu.items():
        conn.execute("INSERT INTO egais_nalichie_den (data, id_sklada, delovaya, drova) VALUES (?,?,?,?)",
                     (den, sid, round(del_, 3), round(dr, 3)))
    _meta(conn, "nalichie_zalito", seychas)
    conn.commit()
    vsego = sum(a + b for a, b in po_skladu.values())
    return {"vid": "nalichie", "strok": len(stroki), "skladov": len(po_skladu), "m3": round(vsego, 1),
            "delovaya": round(sum(a for a, _ in po_skladu.values()), 1),
            "drova": round(sum(b for _, b in po_skladu.values()), 1)}


def _eto_drova(godnost):
    return "дров" in _s(godnost).lower()


def _r1(v):
    return round(float(v or 0), 1)


def _privyazki(conn, sklady=()):
    """Название склада → {delyanka_id, nazvanie, item_id, srok_vyvozki, status}
    — тем же разбором, что относит строки журнала ЕГАИС к выделам делянок.
    sklady — [(название, квартал, выдел)] из справочника: склад, по которому
    в журнале ещё нет ни одного документа, подбирается тем же автоподбором."""
    out = {}
    try:
        from app import legacy_bridge  # noqa: F401
        import raskhod_v2
        items_list = raskhod_v2._load_items_for_sklad_match(conn)
        items = {it["id"]: it for it in items_list}
        resolution = raskhod_v2.resolve_egais_sklady(conn)
    except Exception:  # noqa: BLE001 — старая база
        return out
    sroki = {}
    try:
        for did, sv in conn.execute("SELECT id, srok_okonchaniya_vyvozki FROM delyanka").fetchall():
            sroki[did] = sv
    except sqlite3.OperationalError:
        pass
    naydeno = {key: info.get("item_id") for key, info in resolution.items()}
    try:
        po_kv = {}
        for it in items_list:
            po_kv.setdefault(raskhod_v2._egais_clean_number(it.get("kvartal")), []).append(it)
        try:
            links = {r[0]: (r[1], r[2]) for r in conn.execute(
                "SELECT sklad, delyanka_item_id, status FROM egais_sklad_link").fetchall()}
        except sqlite3.OperationalError:
            links = {}
        for nazv, kv, vd in sklady:
            if not nazv or nazv in naydeno:
                continue
            link = links.get(nazv)
            if link is not None:
                naydeno[nazv] = link[0] if link[1] != "ignored" and link[0] in items else None
                continue
            info = {"sklad": nazv, "real_sklad": nazv, "kvartaly": {kv} if kv else set(),
                    "vydely": {vd} if vd else set(), "lesnichestva": set(), "rows": 0,
                    "parsed": raskhod_v2.parse_egais_sklad_name(nazv)}
            naydeno[nazv] = raskhod_v2._auto_match_sklad(info, po_kv)[1]
    except Exception:  # noqa: BLE001 — автоподбор не обязателен
        pass
    for key, item_id in naydeno.items():
        it = items.get(item_id)
        if it:
            out[key] = {"delyanka_id": it["delyanka_id"], "nazvanie": it.get("delyanka_nazvanie") or "",
                        "item_id": it["id"], "status": it.get("delyanka_status") or "",
                        "srok_vyvozki": sroki.get(it["delyanka_id"])}
    return out


def _poslednee_dvizhenie(conn):
    """Название склада → дата последнего документа в журнале ЕГАИС (ISO)."""
    try:
        return {r[0]: r[1] for r in conn.execute(
            "SELECT sklad, MAX(data_dokumenta_sort) FROM egais_operation WHERE COALESCE(sklad, '') <> '' GROUP BY sklad"
        ).fetchall() if r[1]}
    except sqlite3.OperationalError:
        return {}


def _iso(v):
    d = _data(v)
    return d[:10] if d else None


def obzor(conn, segodnya=None):
    """Все склады из последней выгрузки + склады, на которых лежит лес."""
    ensure(conn)
    segodnya = segodnya or datetime.date.today()
    sklady = {}
    cols = ("id_sklada", "nazvanie", "vid", "data_otkrytiya", "kvartal", "vydel", "lesoseka", "lat", "lon",
            "adres", "vid_deyatelnosti", "podrazdelenie", "v_vygruzke")
    for r in conn.execute(f"SELECT {', '.join(cols)} FROM egais_sklad").fetchall():
        s = dict(zip(cols, r))
        s.update(delovaya=0.0, drova=0.0, porody={}, pozitsiy=0)
        sklady[s["id_sklada"]] = s
    for sid, sklad, kv, vd, poroda, ob, godnost in conn.execute(
            "SELECT id_sklada, sklad, kvartal, vydel, poroda, obyom, godnost FROM egais_nalichie").fetchall():
        s = sklady.get(sid)
        if s is None:  # наличие есть, а в справочнике склада нет (ещё не залит / закрыт)
            s = sklady[sid] = {"id_sklada": sid, "nazvanie": sklad or f"склад {sid}", "vid": "", "data_otkrytiya": None,
                               "kvartal": kv, "vydel": vd, "lesoseka": "", "lat": None, "lon": None, "adres": "",
                               "vid_deyatelnosti": "", "podrazdelenie": "", "v_vygruzke": 0,
                               "delovaya": 0.0, "drova": 0.0, "porody": {}, "pozitsiy": 0}
        drova = _eto_drova(godnost)
        s["drova" if drova else "delovaya"] += ob or 0
        p = s["porody"].setdefault(poroda or "?", [0.0, 0.0])
        p[1 if drova else 0] += ob or 0
        s["pozitsiy"] += 1

    privyazki = _privyazki(conn, [(s["nazvanie"], s["kvartal"], s["vydel"]) for s in sklady.values()])
    dvizhenie = _poslednee_dvizhenie(conn)
    out = []
    for s in sklady.values():
        vsego = s["delovaya"] + s["drova"]
        if not vsego and not s["v_vygruzke"]:
            continue  # закрытый пустой склад — не интересен
        d = privyazki.get(s["nazvanie"])
        posl = dvizhenie.get(s["nazvanie"])
        dney = None
        if posl:
            try:
                dney = (segodnya - datetime.date.fromisoformat(posl[:10])).days
            except ValueError:
                dney = None
        srok, do_sroka = _iso(d.get("srok_vyvozki")) if d else None, None
        if srok:
            do_sroka = (datetime.date.fromisoformat(srok) - segodnya).days
        flag, pochemu = "", ""
        if vsego > 0.05:
            if do_sroka is not None and do_sroka < 0:
                flag, pochemu = "prosrocheno", f"срок вывозки прошёл {-do_sroka} дн. назад, а на складе {_r1(vsego)} м³"
            elif do_sroka is not None and do_sroka <= VYVOZKA_SKORO_DNEY:
                flag, pochemu = "gorit", f"до конца срока вывозки {do_sroka} дн., на складе {_r1(vsego)} м³"
            elif dney is not None and dney >= ZALEZHALSYA_DNEY:
                flag, pochemu = "zalezhalsya", f"{dney} дн. без движения, лежит {_r1(vsego)} м³"
        out.append({
            "id_sklada": s["id_sklada"], "nazvanie": s["nazvanie"], "vid": s["vid"],
            "data_otkrytiya": s["data_otkrytiya"], "kvartal": s["kvartal"], "vydel": s["vydel"],
            "lesoseka": s["lesoseka"], "lat": s["lat"], "lon": s["lon"], "podrazdelenie": s["podrazdelenie"],
            "vid_deyatelnosti": s["vid_deyatelnosti"], "v_vygruzke": bool(s["v_vygruzke"]),
            "delovaya": _r1(s["delovaya"]), "drova": _r1(s["drova"]), "vsego": _r1(vsego), "pozitsiy": s["pozitsiy"],
            "porody": [{"poroda": k, "delovaya": _r1(v[0]), "drova": _r1(v[1]), "vsego": _r1(v[0] + v[1])}
                       for k, v in sorted(s["porody"].items(), key=lambda kv: -(kv[1][0] + kv[1][1]))],
            "delyanka": ({"id": d["delyanka_id"], "nazvanie": d["nazvanie"], "status": d["status"]} if d else None),
            "posl_dvizhenie": posl[:10] if posl else None, "dney_bez_dvizheniya": dney,
            "srok_vyvozki": srok, "dney_do_sroka": do_sroka, "flag": flag, "pochemu": pochemu,
        })
    poryadok = {"prosrocheno": 0, "gorit": 1, "zalezhalsya": 2, "": 3}
    out.sort(key=lambda x: (poryadok[x["flag"]], -x["vsego"], x["nazvanie"]))
    s_lesom = [x for x in out if x["vsego"] > 0.05]
    po_porodam = {}
    for x in s_lesom:
        for p in x["porody"]:
            y = po_porodam.setdefault(p["poroda"], [0.0, 0.0])
            y[0] += p["delovaya"]
            y[1] += p["drova"]
    return {
        "sklady": out,
        "itogo": {
            "skladov": len(out), "s_lesom": len(s_lesom),
            "delovaya": _r1(sum(x["delovaya"] for x in s_lesom)), "drova": _r1(sum(x["drova"] for x in s_lesom)),
            "vsego": _r1(sum(x["vsego"] for x in s_lesom)),
            "bez_koordinat": sum(1 for x in out if x["lat"] is None),
            "bez_delyanki": sum(1 for x in s_lesom if not x["delyanka"]),
            "trevozhnyh": sum(1 for x in out if x["flag"]),
            "po_porodam": [{"poroda": k, "delovaya": _r1(v[0]), "drova": _r1(v[1]), "vsego": _r1(v[0] + v[1])}
                           for k, v in sorted(po_porodam.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))],
        },
        "sklady_zalito": _meta(conn, "sklady_zalito"), "nalichie_zalito": _meta(conn, "nalichie_zalito"),
        "porogi": {"zalezhalsya_dney": ZALEZHALSYA_DNEY, "vyvozka_skoro_dney": VYVOZKA_SKORO_DNEY},
    }


def sostav(conn, id_sklada):
    """Что лежит на складе построчно (как в ЕГАИС)."""
    ensure(conn)
    cols = ("nomenklatura", "poroda", "sortiment", "godnost", "sort", "diametr", "dlina", "kol", "obyom")
    return [dict(zip(cols, r)) for r in conn.execute(
        f"SELECT {', '.join(cols)} FROM egais_nalichie WHERE id_sklada = ? ORDER BY godnost, poroda, obyom DESC",
        (id_sklada,)).fetchall()]


def trevozhnye(conn, segodnya=None):
    """Склады, где лес горит по сроку вывозки или залежался — для «Ждёт меня»."""
    try:
        return [x for x in obzor(conn, segodnya)["sklady"] if x["flag"]]
    except sqlite3.OperationalError:
        return []


def _podpis(x):
    if x["vsego"] <= 0.05:
        return "пусто"
    chasti = []
    if x["delovaya"]:
        chasti.append(f"дел. {x['delovaya']:g}")
    if x["drova"]:
        chasti.append(f"др. {x['drova']:g}")
    return f"{x['vsego']:g} м³" + (f" ({', '.join(chasti)})" if len(chasti) > 1 else "")


CVETA = {"prosrocheno": "#d32f2f", "gorit": "#f9a825", "zalezhalsya": "#8d6e63", "s_lesom": "#2e7d32", "pusto": "#bdbdbd"}


def geojson(conn, tolko_s_lesom=False):
    """Точки складов для QGIS (EPSG:4326)."""
    features = []
    for x in obzor(conn)["sklady"]:
        if x["lat"] is None or (tolko_s_lesom and x["vsego"] <= 0.05):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [x["lon"], x["lat"]]},
            "properties": {
                "id": x["id_sklada"], "nazvanie": x["nazvanie"], "vid": x["vid"],
                "kvartal": x["kvartal"], "vydel": x["vydel"], "lesoseka": x["lesoseka"],
                "data_otkrytiya": x["data_otkrytiya"], "vsego": x["vsego"], "delovaya": x["delovaya"],
                "drova": x["drova"], "ostatok": _podpis(x),
                "porody": "; ".join(f"{p['poroda']} {p['vsego']:g}" for p in x["porody"]),
                "delyanka_id": x["delyanka"]["id"] if x["delyanka"] else None,
                "delyanka": x["delyanka"]["nazvanie"] if x["delyanka"] else "",
                "sostoyanie": x["flag"] or ("s_lesom" if x["vsego"] > 0.05 else "pusto"),
                "color": CVETA[x["flag"] or ("s_lesom" if x["vsego"] > 0.05 else "pusto")],
                "pochemu": x["pochemu"], "dney_bez_dvizheniya": x["dney_bez_dvizheniya"],
                "srok_vyvozki": x["srok_vyvozki"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


def tochki_dlya_telefona(conn):
    """Склады ЕГАИС, на которых сейчас лежит лес, в виде точек «Склады» карты
    телефона (GET /api/map/sklady). id отрицательный — чтобы не пересекаться
    с ручными точками и чтобы «удалить» с телефона их не трогало."""
    try:
        sklady = obzor(conn)["sklady"]
    except sqlite3.OperationalError:
        return []
    return [{"id": -int(x["id_sklada"]), "nazvanie": x["nazvanie"], "lat": x["lat"], "lon": x["lon"],
             "comment": f"ЕГАИС: {_podpis(x)}" + (f" · ⚠ {x['pochemu']}" if x["pochemu"] else ""),
             "created_at": x["data_otkrytiya"]}
            for x in sklady if x["lat"] is not None and x["vsego"] > 0.05]
