import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";
import { useToast } from "../components/Toast.jsx";
import QgisButton from "../components/QgisButton.jsx";

/**
 * «Склады и остатки» (11.11.2026, просьба Влада): что лежит на складах по
 * данным ЕГАИС прямо сейчас. Данные каждый вечер привозит робот выгрузки
 * (отчёты «Склады» и «Наличие продукции на складах»); можно залить и руками.
 * Сервер: app/egais_sklady.py, адреса /api/raskhod/egais/ostatki (обзор) и /api/raskhod/egais/sklady/import, …/{id}/sostav.
 *
 * Сверху — сколько всего леса лежит и что «горит»: срок вывозки делянки
 * близко/прошёл, а на складе лес, либо склад давно без движения.
 */

const num = (v) => (v == null ? "" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 }));
const ddmmgg = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "");
const kogda = (s) => (s ? `${s.slice(8, 10)}.${s.slice(5, 7)} в ${s.slice(11, 16)}` : "ещё ни разу");

const FLAG = {
  prosrocheno: { t: "срок вывозки прошёл", bg: "var(--color-error-soft)", ink: "var(--color-error)" },
  gorit: { t: "горит срок вывозки", bg: "var(--c-gold-soft)", ink: "var(--c-gold)" },
  zalezhalsya: { t: "залежался", bg: "var(--c-muted-bg)", ink: "var(--color-muted-2)" },
};

function Plashka({ title, value, sub, tone }) {
  return (
    <div className="rounded-[12px] border border-border bg-surface px-4 py-2.5 min-w-[150px]">
      <div className="text-[12px] text-muted">{title}</div>
      <div className="text-[22px] font-bold leading-tight" style={{ color: tone || "var(--color-pine)" }}>{value}</div>
      {sub ? <div className="text-[12px] text-muted">{sub}</div> : null}
    </div>
  );
}

function Sostav({ id }) {
  const [stroki, setStroki] = useState(null);
  useEffect(() => {
    let zhiv = true;
    api.get(`/raskhod/egais/sklady/${id}/sostav`).then((r) => zhiv && setStroki(r.stroki)).catch(() => zhiv && setStroki([]));
    return () => { zhiv = false; };
  }, [id]);
  if (stroki == null) return <div className="text-muted text-[13px] py-2">Загружаю…</div>;
  if (!stroki.length) return <div className="text-muted text-[13px] py-2">На складе пусто.</div>;
  return (
    <table className="w-full text-[13px] my-1">
      <thead>
        <tr className="text-muted text-left">
          <th className="font-medium py-1">Номенклатура</th><th className="font-medium">Порода</th>
          <th className="font-medium">Годность</th><th className="font-medium text-right">Шт.</th>
          <th className="font-medium text-right">м³</th>
        </tr>
      </thead>
      <tbody>
        {stroki.map((r, i) => (
          <tr key={i} className="border-t border-border">
            <td className="py-1 pr-2">{r.nomenklatura}</td><td>{r.poroda}</td><td>{r.godnost}</td>
            <td className="text-right">{r.kol ? num(r.kol) : ""}</td><td className="text-right font-semibold">{num(r.obyom)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const FILTRY = [
  ["s_lesom", "С лесом"], ["trevoga", "Требуют внимания"], ["bez_delyanki", "Без делянки"],
  ["bez_koordinat", "Без координат"], ["pustye", "Пустые"], ["vse", "Все"],
];

export default function SkladyEgais() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [oshibka, setOshibka] = useState("");
  const [filtr, setFiltr] = useState("s_lesom");
  const [poisk, setPoisk] = useState("");
  const [otkryt, setOtkryt] = useState(null);
  const [zalivayu, setZalivayu] = useState(false);
  const fileRef = useRef(null);

  const zagruzit = useCallback(() => {
    api.get("/raskhod/egais/ostatki").then((r) => { setData(r); setOshibka(""); }).catch((e) => setOshibka(e.message));
  }, []);
  useEffect(() => { zagruzit(); }, [zagruzit]);

  const zalit = async (files) => {
    setZalivayu(true);
    try {
      for (const f of files) {
        const fd = new FormData();
        fd.append("file", f);
        const r = await api.upload("/raskhod/egais/sklady/import", fd);
        toast.show({
          tone: "success",
          title: r.vid === "sklady" ? "Склады залиты" : "Остатки залиты",
          description: r.vid === "sklady"
            ? `${r.skladov} складов, новых ${r.novyh}, с координатами ${r.s_koordinatami}`
            : `${r.strok} строк, ${r.skladov} складов, всего ${num(r.m3)} м³`,
        });
      }
      zagruzit();
    } catch (e) {
      toast.show({ tone: "danger", title: "Файл не залился", description: e.message });
    } finally {
      setZalivayu(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  // склады, заведённые руками (старые точки на карте телефона) — теперь дубли складов ЕГАИС
  const ubratRuchnye = async () => {
    try {
      const r = await api.delete("/map/sklady/ruchnye");
      zagruzit();
      toast.show({
        tone: "success",
        title: `Ручные склады убраны: ${r.udaleno.length}`,
        description: "На карте остаются склады из ЕГАИС, на которых лежит лес.",
        duration: 10000,
        action: {
          label: "↩ Вернуть",
          onClick: async () => {
            for (const s of r.udaleno) {
              await api.post("/map/sklady", { nazvanie: s.nazvanie, lat: s.lat, lon: s.lon, comment: s.comment || null });
            }
            zagruzit();
          },
        },
      });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось убрать", description: e.message });
    }
  };

  const spisok = useMemo(() => {
    if (!data) return [];
    const q = poisk.trim().toLowerCase().replace(",", ".");
    const m = q.match(/^(\d+)\s*[/ ]\s*(\d+)$/);
    return data.sklady.filter((x) => {
      if (filtr === "s_lesom" && !(x.vsego > 0.05)) return false;
      if (filtr === "trevoga" && !x.flag) return false;
      if (filtr === "bez_delyanki" && (x.delyanka || !(x.vsego > 0.05))) return false;
      if (filtr === "bez_koordinat" && x.lat != null) return false;
      if (filtr === "pustye" && x.vsego > 0.05) return false;
      if (!q) return true;
      if (m) return String(x.kvartal) === m[1] && String(x.vydel).split(/[,\s]+/).includes(m[2]);
      return `${x.nazvanie} ${x.lesoseka} кв${x.kvartal} ${x.delyanka?.nazvanie || ""}`.toLowerCase().includes(q)
        || String(x.kvartal) === q;
    });
  }, [data, filtr, poisk]);

  if (oshibka) return <div className="p-6 text-error">Не загрузилось: {oshibka}</div>;
  if (!data) return <div className="p-6 text-muted">Загружаю склады…</div>;
  const it = data.itogo;
  const pusto = !data.sklady.length;
  const schet = {
    s_lesom: it.s_lesom, trevoga: it.trevozhnyh, bez_delyanki: it.bez_delyanki, bez_koordinat: it.bez_koordinat,
    pustye: it.skladov - it.s_lesom, vse: it.skladov,
  };

  return (
    <div className="p-[18px] flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <Plashka title="Лежит на складах" value={`${num(it.vsego)} м³`} sub={`на ${it.s_lesom} складах из ${it.skladov}`} />
        <Plashka title="Деловая" value={`${num(it.delovaya)} м³`} />
        <Plashka title="Дрова" value={`${num(it.drova)} м³`} />
        <Plashka
          title="Требуют внимания"
          value={it.trevozhnyh}
          sub={it.trevozhnyh ? "горит срок вывозки или залежался" : "всё спокойно"}
          tone={it.trevozhnyh ? "var(--color-error)" : undefined}
        />
        <div className="ml-auto flex flex-col items-end gap-1" data-no-print>
          <input ref={fileRef} type="file" accept=".xlsx" multiple className="hidden" onChange={(e) => zalit([...e.target.files])} />
          <button
            type="button"
            disabled={zalivayu}
            onClick={() => fileRef.current?.click()}
            className="h-9 px-3 rounded-[8px] border border-border bg-surface text-pine font-semibold hover:bg-mint-soft disabled:opacity-60"
            title="Файлы «Склады» и «Наличие продукции на складах» из ЕГАИС — можно оба сразу"
          >
            {zalivayu ? "Заливаю…" : "⬆ Залить файлы из ЕГАИС"}
          </button>
          <div className="text-[12px] text-muted">
            остатки: {kogda(data.nalichie_zalito)} · склады: {kogda(data.sklady_zalito)}
          </div>
        </div>
      </div>

      {data.ruchnyh > 0 ? (
        <div className="rounded-[12px] border border-border bg-surface px-4 py-2.5 flex flex-wrap items-center gap-3" data-no-print>
          <div className="text-[13.5px]">
            Складов, заведённых рукой, на карте ещё: <b>{data.ruchnyh}</b>. Теперь склады приходят из ЕГАИС сами, с координатами и остатком — ручные точки будут двоиться.
          </div>
          <button type="button" onClick={ubratRuchnye} className="ml-auto h-8 px-3 rounded-[8px] border border-border bg-surface text-error font-semibold hover:bg-mint-soft">
            🗑 Убрать ручные ({data.ruchnyh})
          </button>
        </div>
      ) : null}

      {it.po_porodam.length ? (
        <div className="flex flex-wrap gap-1.5">
          {it.po_porodam.map((p) => (
            <span key={p.poroda} className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-[12.5px]" title={`деловая ${num(p.delovaya)} · дрова ${num(p.drova)}`}>
              {p.poroda} <b>{num(p.vsego)}</b>
            </span>
          ))}
        </div>
      ) : null}

      {pusto ? (
        <div className="rounded-[12px] border border-border bg-surface p-6 text-muted">
          Данных о складах ещё нет. Их каждый вечер привозит робот выгрузки ЕГАИС (версия 3.3 и новее). Можно залить и руками:
          в ЕГАИС «Склад → Склады» и «Склад → Наличие продукции на складах» → «Получить» → Excel, и оба файла сюда кнопкой сверху.
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5" data-no-print>
            {FILTRY.map(([k, t]) => (
              <button
                key={k}
                type="button"
                onClick={() => setFiltr(k)}
                className={[
                  "h-8 px-3 rounded-full border text-[13px] font-semibold",
                  filtr === k ? "bg-pine text-white border-pine" : "bg-surface text-pine border-border hover:bg-mint-soft",
                ].join(" ")}
              >
                {t} <span className="opacity-70">{schet[k]}</span>
              </button>
            ))}
            <input
              value={poisk}
              onChange={(e) => setPoisk(e.target.value)}
              placeholder="Поиск: 107/10, название, делянка"
              className="ml-auto border border-border rounded-[8px] px-3 h-9 w-[260px] max-w-full"
            />
          </div>

          <div className="rounded-[12px] border border-border bg-surface overflow-x-auto">
            <table className="w-full text-[13.5px]">
              <thead>
                <tr className="text-left text-muted border-b border-border">
                  <th className="font-medium px-3 py-2">Склад</th>
                  <th className="font-medium px-2">Кв / выд</th>
                  <th className="font-medium px-2">Делянка</th>
                  <th className="font-medium px-2 text-right">Деловая</th>
                  <th className="font-medium px-2 text-right">Дрова</th>
                  <th className="font-medium px-2 text-right">Всего, м³</th>
                  <th className="font-medium px-2">Породы</th>
                  <th className="font-medium px-2">Движение</th>
                  <th className="font-medium px-2">Вывозка до</th>
                  <th className="px-2" data-no-print />
                </tr>
              </thead>
              <tbody>
                {spisok.map((x) => {
                  const f = FLAG[x.flag];
                  const raskryt = otkryt === x.id_sklada;
                  return (
                    <React.Fragment key={x.id_sklada}>
                      <tr
                        className="border-b border-border hover:bg-mint-soft/40 cursor-pointer align-top"
                        onClick={() => setOtkryt(raskryt ? null : x.id_sklada)}
                        title="Нажмите — что лежит на складе построчно"
                      >
                        <td className="px-3 py-2">
                          <div className="font-semibold">{x.nazvanie}</div>
                          <div className="text-[12px] text-muted">
                            {x.vid === "Франко-лесосека" ? "ФЛС" : x.vid ? "ПЛС" : ""}{x.data_otkrytiya ? ` · открыт ${ddmmgg(x.data_otkrytiya)}` : ""}
                            {!x.v_vygruzke ? " · нет среди активных" : ""}{x.lat == null ? " · без координат" : ""}
                          </div>
                          {f ? (
                            <span className="inline-block mt-1 rounded-full px-2 py-0.5 text-[12px] font-semibold" style={{ background: f.bg, color: f.ink }} title={x.pochemu}>
                              ⚠ {f.t}: {x.pochemu}
                            </span>
                          ) : null}
                        </td>
                        <td className="px-2 py-2 whitespace-nowrap">{x.kvartal} / {x.vydel}</td>
                        <td className="px-2 py-2">
                          {x.delyanka ? (
                            <button type="button" className="text-pine underline text-left" onClick={(e) => { e.stopPropagation(); openScreen("plots", { d: x.delyanka.id }); }}>
                              {x.delyanka.nazvanie || `делянка №${x.delyanka.id}`}
                            </button>
                          ) : <span className="text-muted">—</span>}
                        </td>
                        <td className="px-2 py-2 text-right">{x.delovaya ? num(x.delovaya) : ""}</td>
                        <td className="px-2 py-2 text-right">{x.drova ? num(x.drova) : ""}</td>
                        <td className="px-2 py-2 text-right font-bold">{x.vsego > 0.05 ? num(x.vsego) : <span className="text-muted font-normal">пусто</span>}</td>
                        <td className="px-2 py-2 text-[12.5px]">{x.porody.slice(0, 4).map((p) => `${p.poroda} ${num(p.vsego)}`).join(", ")}{x.porody.length > 4 ? "…" : ""}</td>
                        <td className="px-2 py-2 whitespace-nowrap text-[12.5px]">
                          {x.posl_dvizhenie ? <>{ddmmgg(x.posl_dvizhenie)}<div className="text-muted">{x.dney_bez_dvizheniya} дн. назад</div></> : <span className="text-muted">—</span>}
                        </td>
                        <td className="px-2 py-2 whitespace-nowrap text-[12.5px]">
                          {x.srok_vyvozki ? <>{ddmmgg(x.srok_vyvozki)}<div className="text-muted">{x.dney_do_sroka < 0 ? `прошёл ${-x.dney_do_sroka} дн.` : `ещё ${x.dney_do_sroka} дн.`}</div></> : <span className="text-muted">—</span>}
                        </td>
                        <td className="px-2 py-2" data-no-print onClick={(e) => e.stopPropagation()}>
                          {x.lat != null || x.kvartal ? (
                            <QgisButton tip="sklad" id={x.lat != null ? x.id_sklada : null} kvartal={x.kvartal} vydel={String(x.vydel).split(/[,\s]+/)[0]} nazvanie={x.nazvanie} />
                          ) : null}
                        </td>
                      </tr>
                      {raskryt ? (
                        <tr className="border-b border-border bg-paper">
                          <td colSpan={10} className="px-4 py-1"><Sostav id={x.id_sklada} /></td>
                        </tr>
                      ) : null}
                    </React.Fragment>
                  );
                })}
                {!spisok.length ? <tr><td colSpan={10} className="px-3 py-6 text-center text-muted">Под этот фильтр ничего не попало.</td></tr> : null}
              </tbody>
              {spisok.length > 1 ? (
                <tfoot>
                  <tr className="font-bold">
                    <td className="px-3 py-2" colSpan={3}>Итого по списку: {spisok.length}</td>
                    <td className="px-2 text-right">{num(spisok.reduce((a, x) => a + x.delovaya, 0))}</td>
                    <td className="px-2 text-right">{num(spisok.reduce((a, x) => a + x.drova, 0))}</td>
                    <td className="px-2 text-right">{num(spisok.reduce((a, x) => a + x.vsego, 0))}</td>
                    <td colSpan={4} />
                  </tr>
                </tfoot>
              ) : null}
            </table>
          </div>
          <div className="text-[12px] text-muted">
            «Залежался» — на складе лес, а документов по нему в ЕГАИС нет {data.porogi.zalezhalsya_dney} дней и больше. «Горит» — до конца срока вывозки делянки
            {" "}{data.porogi.vyvozka_skoro_dney} дней или меньше. Точки складов с остатком есть в QGIS: «Слои Лесовода → Склады ЕГАИС».
          </div>
        </>
      )}
    </div>
  );
}
