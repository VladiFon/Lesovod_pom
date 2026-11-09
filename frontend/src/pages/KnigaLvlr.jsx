import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";
import { useScreenParam } from "../nav.js";

/**
 * «📗 Книга ЛВ и ЛР» (Влад, 09.11.2026) — книга учёта площадей
 * лесовосстановления и лесоразведения, прил. 6 к Положению о порядке ЛВ и ЛР.
 * Бумажная книга ведётся ручкой, распечатку можно вклеивать: слева часть 1
 * (графы 1–19), справа часть 2 (графы 20–29), 19 строк по 6 мм на развороте.
 * Здесь — электронная копия: очередь «что вписать», книга по разворотам и
 * печать вклейки по точным размерам. Сервер: routers/kniga_lvlr.py.
 */

const C = { pine: "#1a4331", line: "#e5e2db", muted: "#565f59", moss: "#eaf7ec", sun: "#fbf1d6", sunLine: "#f0dca6", danger: "#ba1a1a", avto: "#eef4fb" };
const CHAST_1 = Array.from({ length: 19 }, (_, i) => i + 1);
const CHAST_2 = Array.from({ length: 10 }, (_, i) => i + 20);
const inp = "border border-border rounded-[8px] px-2 h-9";
const btn = { background: C.pine, color: "#fff", borderRadius: 8, padding: "7px 12px", fontWeight: 700, fontSize: 13 };
const btn2 = { border: `1px solid ${C.line}`, background: "#fff", borderRadius: 8, padding: "6px 10px", fontSize: 13 };
const karta = { background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: 12 };

async function skachat(path, imya) {
  const token = localStorage.getItem("lesovod_token");
  const res = await fetch(`${API_BASE_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Ошибка сервера (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = imya;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const adres = (z) => (z.razvorot ? `разв. ${z.razvorot}, стр. ${z.stroka}` : "до начала учёта в программе");

export default function KnigaLvlr() {
  const toast = useToast();
  const [tabParam, setTabState] = useScreenParam("kniga_lvlr", "tab");
  const tab = tabParam || "vpisat";
  const [kniga, setKniga] = useState(null);
  const [vpisat, setVpisat] = useState(null);
  const [vseRubki, setVseRubki] = useState(false);
  const [red, setRed] = useState(null); // строка в редакторе

  const oshibka = (title) => (e) => toast.show({ tone: "danger", title, description: e.message });

  const load = useCallback(async () => {
    try {
      const [k, v] = await Promise.all([api.get("/kniga-lvlr"), api.get("/kniga-lvlr/chto-vpisat", { vse_rubki: vseRubki })]);
      setKniga(k);
      setVpisat(v);
    } catch (e) {
      oshibka("Книга не загрузилась")(e);
    }
  }, [vseRubki]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!kniga || !vpisat) return <div style={{ padding: 24, color: C.muted }}>Открываю книгу…</div>;

  const TABS = [
    ["vpisat", `📝 Что вписать${vpisat.novye.length + vpisat.dopisat.length + vpisat.na_bumagu.length ? ` (${vpisat.novye.length + vpisat.dopisat.length + vpisat.na_bumagu.length})` : ""}`],
    ["kniga", `📗 Книга (${kniga.zapisi.length})`],
    ["pechat", "🖨 Печать и настройки"],
  ];

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="flex flex-wrap" style={{ gap: 6 }}>
        {TABS.map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTabState(k)}
            style={{ ...btn2, fontWeight: tab === k ? 700 : 400, background: tab === k ? C.moss : "#fff", borderColor: tab === k ? C.pine : C.line }}>{l}</button>
        ))}
      </div>
      {tab === "vpisat" && <ChtoVpisat d={vpisat} kniga={kniga} vseRubki={vseRubki} setVseRubki={setVseRubki} reload={load} oshibka={oshibka} otkryt={setRed} />}
      {tab === "kniga" && <Kniga kniga={kniga} otkryt={setRed} />}
      {tab === "pechat" && <Pechat kniga={kniga} reload={load} oshibka={oshibka} toast={toast} />}
      {red && <Redaktor z={red} kniga={kniga} zakryt={() => setRed(null)} reload={load} oshibka={oshibka} />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Grafy({ grafy, nazvaniya }) {
  const kl = Object.keys(grafy || {}).map(Number).sort((a, b) => a - b);
  if (!kl.length) return <span style={{ color: C.muted }}>пока пусто</span>;
  return (
    <span style={{ fontSize: 12, color: C.muted }}>
      {kl.map((k, i) => <span key={k} title={nazvaniya[k]}>{i > 0 && " · "}<b style={{ color: "#333" }}>гр.{k}</b> {grafy[k]}</span>)}
    </span>
  );
}

function ChtoVpisat({ d, kniga, vseRubki, setVseRubki, reload, oshibka, otkryt }) {
  const [zanyat, setZanyat] = useState(false);
  const raz = async (fn, title) => {
    setZanyat(true);
    try { await fn(); await reload(); } catch (e) { oshibka(title)(e); } finally { setZanyat(false); }
  };
  const vnesti = (x) => raz(() => api.post("/kniga-lvlr", x.tip === "delyanka"
    ? { delyanka_id: x.delyanka_id }
    : { uchastok_id: x.uchastok_id, vid: x.tip === "spisanie" ? "spisanie" : null }), "Не внеслось");
  const dopisat = (spisok) => raz(async () => {
    const po = {};
    spisok.forEach((x) => { (po[x.id] = po[x.id] || {})[x.grafa] = x.znachenie || x.seychas; });
    for (const [id, grafy] of Object.entries(po)) await api.put(`/kniga-lvlr/${id}`, { grafy });
  }, "Не дописалось");
  const mesto = (did, flag) => raz(() => api.put(`/kniga-lvlr/delyanka/${did}`, { flag }), "Не отметилось");
  const vpisal = (z, grafy) => raz(() => api.post(`/kniga-lvlr/${z.id}/na-bumage`, { grafy: grafy || null }), "Не отметилось");
  const vkladysh = (x) => {
    const z = kniga.zapisi.find((q) => q.id === x.id);
    const po = x.stroka + (z?.strok || 1) - 1;
    skachat(`/kniga-lvlr/vkleyka.docx?razvorot=${x.razvorot}&s=${x.stroka}&po=${po}&ids=${x.id}`, `vkleyka_${x.nomer}.docx`).catch(oshibka("Вкладыш не скачался"));
  };
  const pusto = !d.novye.length && !d.dopisat.length && !d.rashozhdeniya.length && !d.na_bumagu.length;

  return (
    <>
      <div style={{ ...karta, background: C.moss, borderColor: "#cfe5d3", fontSize: 13 }}>
        Следующий № п/п — <b>{d.sleduyushchiy_nomer}</b>. В книгу идут делянки сразу после выписки лесорубочного билета
        (все рубки, кроме выборочных и рубок ухода, в том числе сторонние) и списанные лесные культуры. Акт освидетельствования,
        посадка культур и перевод потом сами попадут в «дописать» — с адресом в бумажной книге.
      </div>
      {pusto && <div style={{ ...karta, textAlign: "center", color: C.muted }}>Всё вписано 👌 Новое появится, когда на делянку выпишут билет, будет акт или запись в журнале культур.</div>}

      {d.chuzhie?.length > 0 && (
        <details style={{ ...karta, fontSize: 13 }}>
          <summary style={{ cursor: "pointer" }}>🚫 Чужие делянки и участки — не в книгу ({d.chuzhie.length}). Своё: <b>{d.svoe.lesnichestvo || "лесничество не задано"}</b>{d.svoe.leshoz ? `, ${d.svoe.leshoz}` : ""} (меняется в «Печать и настройки»)</summary>
          {d.chuzhie.map((x) => (
            <div key={`${x.tip}${x.id}`} className="flex items-center" style={{ color: C.muted, paddingTop: 4, gap: 8 }}>
              <span>{x.tip === "delyanka" ? "🪓" : "🥀"} {x.mesto} — {x.vruchnuyu ? "помечена чужой вручную" : x.gde || "?"}</span>
              {x.tip === "delyanka" && <button type="button" disabled={zanyat} onClick={() => mesto(x.id, x.vruchnuyu ? "" : "svoya")} style={{ ...btn2, fontSize: 12, padding: "2px 8px" }}>{x.vruchnuyu ? "↩ не чужая" : "это наша"}</button>}
            </div>
          ))}
        </details>
      )}

      {(d.novye.length > 0 || vseRubki) && (
        <div style={karta}>
          <div className="flex flex-wrap items-center" style={{ gap: 10, marginBottom: 8 }}>
            <b>Новые строки ({d.novye.length})</b>
            <label style={{ fontSize: 12, color: C.muted }}><input type="checkbox" checked={vseRubki} onChange={(e) => setVseRubki(e.target.checked)} /> показать и выборочные рубки / рубки ухода</label>
          </div>
          {d.novye.map((x) => (
            <div key={`${x.tip}${x.delyanka_id || ""}${x.uchastok_id || ""}`} className="flex items-start" style={{ gap: 10, padding: "8px 0", borderTop: `1px solid ${C.line}` }}>
              <span style={{ fontSize: 20 }}>{x.tip === "delyanka" ? "🪓" : "🥀"}</span>
              <div style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
                <div><b>{x.mesto || "без места"}</b>
                  <span style={{ color: C.muted }}>{x.tip === "delyanka"
                    ? ` · билет ${x.bilet || ""}${x.akt_data ? ` · акт от ${x.akt_data}` : " · без акта (гр. 10 допишется после освид.)"}${x.vid_rubki ? ` · ${x.vid_rubki}` : ""}${x.storonnyaya ? " · рубит сторонний" : ""}`
                    : ` · списанные лесные культуры${x.akt_data ? `, ${x.akt_data}` : ""}`}</span>
                  {x.vid_neizvesten && <span style={{ color: "#a06800", fontSize: 12 }}> · ⚠ вид рубки не определён — проверьте, что она не выборочная</span>}</div>
                <Grafy grafy={x.grafy} nazvaniya={kniga.nazvaniya} />
              </div>
              <div className="flex flex-col" style={{ gap: 4 }}>
                <button type="button" disabled={zanyat} onClick={() => vnesti(x)} style={btn}>Внести №{d.sleduyushchiy_nomer}</button>
                {x.tip === "delyanka" && <button type="button" disabled={zanyat} onClick={() => mesto(x.delyanka_id, "chuzhaya")} style={{ ...btn2, fontSize: 12 }} title="Делянка в другом лесничестве / лесхозе — в книгу не вносить">🚫 Чужая</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {d.dopisat.length > 0 && (
        <div style={karta}>
          <div className="flex flex-wrap items-center" style={{ gap: 10, marginBottom: 8 }}>
            <b>Программа знает больше, чем записано ({d.dopisat.length})</b>
            <button type="button" disabled={zanyat} onClick={() => dopisat(d.dopisat)} style={btn2}>Внести всё</button>
          </div>
          {d.dopisat.map((x) => (
            <div key={`${x.id}-${x.grafa}`} className="flex items-center" style={{ gap: 10, padding: "6px 0", borderTop: `1px solid ${C.line}`, fontSize: 13 }}>
              <span style={{ minWidth: 60, color: C.muted }}>№{x.nomer}</span>
              <span style={{ flex: 1 }}><b>гр.{x.grafa}</b> <span style={{ color: C.muted }}>({x.nazvanie})</span>: {x.znachenie}</span>
              <button type="button" disabled={zanyat} onClick={() => dopisat([x])} style={btn2}>Внести</button>
            </div>
          ))}
        </div>
      )}

      {d.rashozhdeniya.length > 0 && (
        <div style={{ ...karta, background: C.sun, borderColor: C.sunLine }}>
          <b>⚠ В источнике теперь другое ({d.rashozhdeniya.length})</b>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 6 }}>Например, поправили площадь делянки после того, как строку внесли. В книге оставлено как было — решите сами.</div>
          {d.rashozhdeniya.map((x) => (
            <div key={`${x.id}-${x.grafa}`} className="flex items-center" style={{ gap: 10, padding: "6px 0", borderTop: `1px solid ${C.sunLine}`, fontSize: 13 }}>
              <span style={{ minWidth: 60 }}>№{x.nomer}</span>
              <span style={{ flex: 1 }}><b>гр.{x.grafa}</b>: в книге «{x.v_knige}», сейчас «{x.seychas}»</span>
              <button type="button" disabled={zanyat} onClick={() => dopisat([x])} style={btn2}>Взять новое</button>
            </div>
          ))}
        </div>
      )}

      {d.na_bumagu.length > 0 && (
        <div style={karta}>
          <b>Перенести на бумагу ({d.na_bumagu.length})</b>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 6 }}>Впишите ручкой по адресу или распечатайте вкладыш (только эти строки, по размерам книги) и отметьте.</div>
          {d.na_bumagu.map((x) => (
            <div key={x.id} className="flex flex-wrap items-start" style={{ gap: 10, padding: "8px 0", borderTop: `1px solid ${C.line}`, fontSize: 13 }}>
              <div style={{ minWidth: 150 }}>
                <b>№{x.nomer}</b> <span style={{ color: C.muted }}>{x.mesto}</span><br />
                <span style={{ background: C.moss, borderRadius: 6, padding: "1px 6px" }}>📍 {adres(x)}</span>
              </div>
              <div style={{ flex: 1, minWidth: 220 }}>
                {x.vsya ? <span>вся строка, графы: {x.grafy.map((g) => g.grafa).join(", ")}</span>
                  : x.grafy.map((g) => <div key={g.grafa}><b>гр.{g.grafa}</b>: {g.znachenie || <i style={{ color: C.muted }}>очистить</i>}{g.bylo && <span style={{ color: C.muted }}> (было «{g.bylo}»)</span>}</div>)}
              </div>
              <div className="flex flex-wrap" style={{ gap: 6 }}>
                <button type="button" onClick={() => otkryt(kniga.zapisi.find((z) => z.id === x.id))} style={btn2}>✏️</button>
                {x.razvorot && <button type="button" onClick={() => vkladysh(x)} style={btn2}>🖨 Вкладыш</button>}
                <button type="button" disabled={zanyat} onClick={() => vpisal(x)} style={btn}>✍ Вписал / вклеил</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
function Kniga({ kniga, otkryt }) {
  const zap = kniga.zapisi;
  const razvoroty = useMemo(() => [...new Set(zap.map((z) => z.razvorot).filter(Boolean))].sort((a, b) => a - b), [zap]);
  const [r, setR] = useState(() => razvoroty[razvoroty.length - 1] || kniga.nastroyki.nachalo_razvorot);
  const [chast, setChast] = useState(1);
  const [poisk, setPoisk] = useState("");
  const grafy = chast === 1 ? CHAST_1 : CHAST_2;
  const shiriny = chast === 1 ? kniga.nastroyki.shiriny_1 : kniga.nastroyki.shiriny_2;

  const naydeno = poisk.trim()
    ? zap.filter((z) => `${z.nomer} ${Object.values(z.grafy).join(" ")}`.toLowerCase().includes(poisk.trim().toLowerCase()))
    : null;
  const stroki = Array.from({ length: kniga.strok_na_razvorote }, () => null);
  zap.filter((z) => z.razvorot === r).forEach((z) => {
    stroki[z.stroka - 1] = z;
    for (let i = 1; i < (z.strok || 1); i += 1) if (z.stroka - 1 + i < stroki.length) stroki[z.stroka - 1 + i] = "prodolzhenie";
  });

  return (
    <>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" style={btn2} onClick={() => setR(Math.max(1, r - 1))}>←</button>
        <b>Разворот {r}</b>
        <button type="button" style={btn2} onClick={() => setR(r + 1)}>→</button>
        <span style={{ width: 10 }} />
        {[1, 2].map((c) => (
          <button key={c} type="button" onClick={() => setChast(c)} style={{ ...btn2, fontWeight: chast === c ? 700 : 400, background: chast === c ? C.moss : "#fff" }}>
            {c === 1 ? "Часть 1 · гр. 1–19 (слева)" : "Часть 2 · гр. 20–29 (справа)"}</button>
        ))}
        <input className={inp} style={{ marginLeft: "auto", minWidth: 200 }} placeholder="Поиск: 71/2, №850, Е…" value={poisk} onChange={(e) => setPoisk(e.target.value)} />
      </div>

      {naydeno ? (
        <div style={karta}>
          {naydeno.length === 0 ? <span style={{ color: C.muted }}>Ничего не нашлось</span> : naydeno.map((z) => (
            <div key={z.id} className="flex items-center" style={{ gap: 10, padding: "6px 0", borderTop: `1px solid ${C.line}`, fontSize: 13, cursor: "pointer" }} onClick={() => otkryt(z)}>
              <b style={{ minWidth: 50 }}>№{z.nomer}</b><span style={{ minWidth: 130, color: C.muted }}>{adres(z)}</span><Grafy grafy={z.grafy} nazvaniya={kniga.nazvaniya} />
            </div>
          ))}
        </div>
      ) : (
        <div style={{ ...karta, padding: 0, overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", tableLayout: "fixed", fontSize: 11, minWidth: "100%" }}>
            <colgroup>
              <col style={{ width: 36 }} />
              {grafy.map((g, i) => <col key={g} style={{ width: Math.max(44, shiriny[i] * 34) }} />)}
            </colgroup>
            <thead>
              <tr>
                <th style={{ border: `1px solid ${C.line}`, background: "#f6f5f1", padding: 3 }}>стр.</th>
                {grafy.map((g) => <th key={g} title={kniga.nazvaniya[g]} style={{ border: `1px solid ${C.line}`, background: "#f6f5f1", padding: 3, cursor: "help" }}>{g}</th>)}
              </tr>
            </thead>
            <tbody>
              {stroki.map((z, i) => {
                if (z === "prodolzhenie") return null;
                const span = z?.strok || 1;
                return (
                  <tr key={i} style={{ height: 26 * span, cursor: z ? "pointer" : "default" }} onClick={() => z && otkryt(z)}>
                    <td style={{ border: `1px solid ${C.line}`, color: C.muted, textAlign: "center" }}>{i + 1}</td>
                    {grafy.map((g) => {
                      const v = z ? (g === 1 ? String(z.nomer) : (z.vid === "zamazana" && g === 2 ? "— замазана —" : z.grafy[g] || "")) : "";
                      const nado = z && g !== 1 && z.ne_na_bumage.includes(g);
                      return (
                        <td key={g} title={v ? `${kniga.nazvaniya[g]}: ${v}${nado ? " — ещё не на бумаге" : ""}` : kniga.nazvaniya[g]}
                          style={{ border: `1px solid ${C.line}`, padding: "1px 3px", textAlign: "center", overflow: "hidden", background: nado ? C.sun : undefined, fontWeight: g === 1 ? 700 : 400 }}>{v}</td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ fontSize: 12, color: C.muted }}>Жёлтым — то, что ещё не перенесено в бумажную книгу. Наведите на номер графы — подсказка, что в ней. Клик по строке — правка.</div>
    </>
  );
}

/* ------------------------------------------------------------------ */
function Redaktor({ z, kniga, zakryt, reload, oshibka }) {
  const toast = useToast();
  const [g, setG] = useState(() => ({ ...z.grafy }));
  const [strok, setStrok] = useState(z.strok || 1);
  const [prim, setPrim] = useState(z.primechanie || "");
  const [zanyat, setZanyat] = useState(false);
  // Удалить можно, пока ни эта строка, ни следующие не на бумаге (номера ниже сдвинутся).
  const mozhnoUdalit = !kniga.zapisi.some((q) => q.nomer >= z.nomer && Object.keys(q.na_bumage || {}).length);

  const sohranit = async (iBumaga) => {
    setZanyat(true);
    try {
      const grafy = {};
      for (let k = 2; k <= 29; k += 1) if ((g[k] || "") !== (z.grafy[k] || "")) grafy[k] = g[k] || "";
      await api.put(`/kniga-lvlr/${z.id}`, { grafy, strok, primechanie: prim });
      if (iBumaga) await api.post(`/kniga-lvlr/${z.id}/na-bumage`, {});
      await reload();
      zakryt();
    } catch (e) { oshibka("Не сохранилось")(e); } finally { setZanyat(false); }
  };
  const udalit = async (chuzhaya) => {
    const dalshe = kniga.zapisi.filter((q) => q.nomer > z.nomer).length;
    const tekst = mozhnoUdalit
      ? `Убрать строку №${z.nomer}? Её ещё нет на бумаге — удалится${dalshe ? `, номера ${dalshe} строк ниже сдвинутся на один вверх` : ""}.`
      : `Строка №${z.nomer} (или строки после неё) уже в бумажной книге. Строка будет «замазана»: № и место остаются, графы очищаются — замажьте её в книге корректором.`;
    if (!window.confirm(tekst + (chuzhaya ? "\nДелянка будет помечена чужой и больше не предложится." : ""))) return;
    try {
      const r = await api.delete(`/kniga-lvlr/${z.id}${chuzhaya ? "?chuzhaya=true" : ""}`);
      toast.show({ tone: "success", title: r.kak === "zamazana" ? `Строка №${z.nomer} замазана` : `Строка №${z.nomer} убрана` });
      await reload(); zakryt();
    } catch (e) { oshibka("Не убралось")(e); }
  };
  const pole = (k) => {
    const avto = kniga.avto_grafy.includes(k);
    const nado = z.ne_na_bumage.includes(k);
    return (
      <label key={k} style={{ fontSize: 12, color: C.muted, display: "block" }}>
        <b style={{ color: "#333" }}>{k}.</b> {kniga.nazvaniya[k]}{avto && <span title="Подставляется из делянки / культур"> ⚙</span>}{nado && <span style={{ color: "#a06800" }}> · не на бумаге</span>}
        {k === 3 ? (
          <>
            <input className={inp + " w-full"} list="kniga-vidy-zemel" value={g[k] || ""} onChange={(e) => setG({ ...g, [k]: e.target.value })} />
            <datalist id="kniga-vidy-zemel">{kniga.vidy_zemel.map((v) => <option key={v} value={v} />)}</datalist>
          </>
        ) : (
          <input className={inp + " w-full"} value={g[k] || ""} onChange={(e) => setG({ ...g, [k]: e.target.value })}
            style={{ background: avto && g[k] ? C.avto : undefined }} />
        )}
      </label>
    );
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", zIndex: 60, display: "flex", alignItems: "flex-start", justifyContent: "center", overflowY: "auto", padding: 16 }} onClick={zakryt}>
      <div style={{ ...karta, width: "min(980px, 100%)", marginTop: 20 }} onClick={(e) => e.stopPropagation()}>
        <div className="flex flex-wrap items-center" style={{ gap: 10, marginBottom: 10 }}>
          <b style={{ fontSize: 16 }}>Строка №{z.nomer}</b>
          <span style={{ background: C.moss, borderRadius: 6, padding: "1px 6px", fontSize: 13 }}>📍 {adres(z)}</span>
          {z.delyanka_id && <span style={{ fontSize: 12, color: C.muted }}>🪓 делянка #{z.delyanka_id}</span>}
          {z.uchastok_id && <span style={{ fontSize: 12, color: C.muted }}>🌱 участок культур #{z.uchastok_id}</span>}
          <button type="button" onClick={zakryt} style={{ marginLeft: "auto", color: C.muted }}>✕</button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
          <div style={{ gridColumn: "1 / -1", fontWeight: 700, fontSize: 13 }}>Часть 1 — участок, вырубка, проект (левая страница)</div>
          {CHAST_1.slice(1).map(pole)}
          <div style={{ gridColumn: "1 / -1", fontWeight: 700, fontSize: 13, marginTop: 6 }}>Часть 2 — ход и результаты (правая страница)</div>
          {CHAST_2.map(pole)}
        </div>
        <div className="flex flex-wrap items-end" style={{ gap: 10, marginTop: 12 }}>
          <label style={{ fontSize: 12, color: C.muted }}>Строк в книге<br />
            <select className={inp} value={strok} onChange={(e) => setStrok(Number(e.target.value))}>{[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
          <label style={{ fontSize: 12, color: C.muted, flex: 1, minWidth: 200 }}>Примечание (только для себя)<br />
            <input className={inp + " w-full"} value={prim} onChange={(e) => setPrim(e.target.value)} /></label>
          <button type="button" disabled={zanyat} onClick={() => sohranit(false)} style={btn}>Сохранить</button>
          <button type="button" disabled={zanyat} onClick={() => sohranit(true)} style={btn2}>Сохранить и ✍ вписал</button>
          {z.vid !== "zamazana" && <button type="button" onClick={() => udalit(false)} style={{ ...btn2, color: C.danger }}>{mozhnoUdalit ? "🗑 Убрать из книги" : "🩹 Замазать строку"}</button>}
          {z.vid !== "zamazana" && z.delyanka_id && <button type="button" onClick={() => udalit(true)} style={{ ...btn2, color: C.danger }}>🚫 Чужая делянка — убрать</button>}
        </div>
        <div style={{ fontSize: 12, color: C.muted, marginTop: 8 }}>⚙ — графа подставляется сама из делянки, акта и лесных культур. Если поправить её вручную, программа покажет расхождение, но молча не перезапишет.</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
function Pechat({ kniga, reload, oshibka, toast }) {
  const n = kniga.nastroyki;
  const posl = kniga.zapisi.filter((z) => z.razvorot).slice(-1)[0];
  const [p, setP] = useState({ razvorot: posl?.razvorot || n.nachalo_razvorot, chast: "obe", s: 1, po: kniga.strok_na_razvorote, nomera: true, setka: true });
  const [f, setF] = useState(() => ({ ...n, shiriny_1: n.shiriny_1.join("; "), shiriny_2: n.shiriny_2.join("; ") }));

  const pechat = () => skachat(`/kniga-lvlr/vkleyka.docx?razvorot=${p.razvorot}&chast=${p.chast}&s=${p.s}&po=${p.po}&nomera_graf=${p.nomera}&setka=${p.setka}`,
    `kniga_lvlr_razvorot_${p.razvorot}.docx`).catch(oshibka("Не скачалось"));
  const sohranit = async () => {
    const chisla = (s) => String(s).split(/[;\s]+/).filter(Boolean).map((x) => Number(x.replace(",", ".")));
    try {
      await api.put("/kniga-lvlr/nastroyki", {
        nachalo_nomer: Number(f.nachalo_nomer), nachalo_razvorot: Number(f.nachalo_razvorot), nachalo_stroka: Number(f.nachalo_stroka),
        kultury_s_goda: Number(f.kultury_s_goda), shrift_pt: Number(f.shrift_pt), nazvanie_lesnichestva: f.nazvanie_lesnichestva || "", nazvanie_leshoza: f.nazvanie_leshoza || "",
        shiriny_1: chisla(f.shiriny_1), shiriny_2: chisla(f.shiriny_2),
      });
      toast.show({ tone: "success", title: "Настройки книги сохранены" });
      reload();
    } catch (e) { oshibka("Не сохранилось")(e); }
  };
  const num = (k, label, w = 90) => (
    <label style={{ fontSize: 12, color: C.muted }}>{label}<br /><input className={inp} style={{ width: w }} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  );
  const sum = (s) => String(s).split(/[;\s]+/).filter(Boolean).reduce((a, x) => a + (Number(x.replace(",", ".")) || 0), 0);

  return (
    <>
      <div style={karta}>
        <b>Вкладыш в книгу (Word)</b>
        <div className="flex flex-wrap items-end" style={{ gap: 10, marginTop: 8 }}>
          <label style={{ fontSize: 12, color: C.muted }}>Разворот<br /><input className={inp} style={{ width: 80 }} type="number" min={1} value={p.razvorot} onChange={(e) => setP({ ...p, razvorot: Number(e.target.value) })} /></label>
          <label style={{ fontSize: 12, color: C.muted }}>Часть<br />
            <select className={inp} value={p.chast} onChange={(e) => setP({ ...p, chast: e.target.value })}>
              <option value="obe">обе (2 листа)</option><option value="1">часть 1 · гр. 1–19</option><option value="2">часть 2 · гр. 20–29</option></select></label>
          <label style={{ fontSize: 12, color: C.muted }}>Строки с<br /><input className={inp} style={{ width: 64 }} type="number" min={1} max={kniga.strok_na_razvorote} value={p.s} onChange={(e) => setP({ ...p, s: Number(e.target.value) })} /></label>
          <label style={{ fontSize: 12, color: C.muted }}>по<br /><input className={inp} style={{ width: 64 }} type="number" min={1} max={kniga.strok_na_razvorote} value={p.po} onChange={(e) => setP({ ...p, po: Number(e.target.value) })} /></label>
          <label style={{ fontSize: 13 }}><input type="checkbox" checked={p.nomera} onChange={(e) => setP({ ...p, nomera: e.target.checked })} /> строка номеров граф</label>
          <label style={{ fontSize: 13 }}><input type="checkbox" checked={p.setka} onChange={(e) => setP({ ...p, setka: e.target.checked })} /> сетка</label>
          <button type="button" onClick={pechat} style={btn}>🖨 Скачать вкладыш</button>
          <button type="button" onClick={() => skachat("/kniga-lvlr/kalibrovka.docx", "kniga_proverka_pechati.docx").catch(oshibka("Не скачалось"))} style={btn2}>📏 Пробный лист</button>
        </div>
        <div style={{ fontSize: 12, color: C.muted, marginTop: 8 }}>
          Печатать с масштабом <b>100% / «Фактический размер»</b>, не «по размеру страницы». Сначала распечатайте пробный лист и приложите к книге: линия должна быть ровно 100 мм, графы — совпасть с книгой.
        </div>
      </div>

      <div style={karta}>
        <b>Настройки книги</b>
        <div className="flex flex-wrap items-end" style={{ gap: 10, marginTop: 8 }}>
          {num("nachalo_nomer", "Первый № в программе")}
          {num("nachalo_razvorot", "Он стоит на развороте")}
          {num("nachalo_stroka", "в строке")}
          {num("kultury_s_goda", "Билеты и списания с года")}
          {num("shrift_pt", "Шрифт, pt", 70)}
        </div>
        <div className="flex flex-wrap items-end" style={{ gap: 10, marginTop: 10 }}>
          <label style={{ fontSize: 12, color: C.muted }}>Своё лесничество (пусто — {kniga.svoe.lesnichestvo || "из Настроек"})<br />
            <input className={inp} style={{ width: 240 }} list="kniga-lesn" value={f.nazvanie_lesnichestva || ""} onChange={(e) => setF({ ...f, nazvanie_lesnichestva: e.target.value })} placeholder={kniga.svoe.lesnichestvo} /></label>
          <label style={{ fontSize: 12, color: C.muted }}>Свой лесхоз (пусто — {kniga.svoe.leshoz || "самый частый"})<br />
            <input className={inp} style={{ width: 240 }} list="kniga-lx" value={f.nazvanie_leshoza || ""} onChange={(e) => setF({ ...f, nazvanie_leshoza: e.target.value })} placeholder={kniga.svoe.leshoz} /></label>
          <datalist id="kniga-lesn">{[...new Set(kniga.lesnichestva.map((x) => x.lesnichestvo).filter(Boolean))].map((v) => <option key={v} value={v} />)}</datalist>
          <datalist id="kniga-lx">{[...new Set(kniga.lesnichestva.map((x) => x.leshoz).filter(Boolean))].map((v) => <option key={v} value={v} />)}</datalist>
          <span style={{ fontSize: 12, color: C.muted, maxWidth: 360 }}>Делянки и культуры другого лесничества или лесхоза (рубим у соседей) в книгу не предлагаются.</span>
        </div>
        <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
          <label style={{ fontSize: 12, color: C.muted }}>Ширины граф части 1 (19 чисел, см) — сумма {sum(f.shiriny_1).toFixed(2)} см
            <input className={inp + " w-full"} value={f.shiriny_1} onChange={(e) => setF({ ...f, shiriny_1: e.target.value })} /></label>
          <label style={{ fontSize: 12, color: C.muted }}>Ширины граф части 2 (10 чисел, см) — сумма {sum(f.shiriny_2).toFixed(2)} см
            <input className={inp + " w-full"} value={f.shiriny_2} onChange={(e) => setF({ ...f, shiriny_2: e.target.value })} /></label>
        </div>
        <button type="button" onClick={sohranit} style={{ ...btn, marginTop: 10 }}>Сохранить</button>
      </div>
    </>
  );
}
