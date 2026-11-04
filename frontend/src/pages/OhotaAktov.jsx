import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useCan } from "../auth.jsx";
import { useToast } from "../components/Toast.jsx";
import { openScreen, useScreenParam } from "../nav.js";

/**
 * «🏹 Охота на акты» — игровой вид экрана «Инспекция» (03.11.2026).
 * Тот же список /api/inspection/, только разложен по-охотничьи:
 *   🐗 Ушли      — срок акта прошёл;
 *   🎯 На мушке  — срок акта в ближайшие 14 дней;
 *   🐾 На следу  — площадь пройдена / лимит почти выбран, срока ещё нет;
 *   🔒 В капкане — акт есть, делянку осталось закрыть;
 *   🏆 Трофеи    — закрыты с актом в этом году.
 * Сам акт составляется в обычной форме — «🎯 Составить акт» открывает
 * вкладку «Список» с этой делянкой. Ничего своего не пишет.
 */

const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dangerSoft: "#fdecea", sky: "#2c5d8a", skySoft: "#e6eef7",
};
const MUSHKA_DNEY = 14;
const OKNO_DNEY = 30;
const ZVERI = ["🦌", "🐗", "🦊", "🐇", "🦫", "🐺", "🦡", "🐻"];
const ZVANIYA = [
  [0, "Новичок с рогаткой"], [3, "Следопыт"], [10, "Егерь"], [25, "Главный егерь"], [50, "Гроза делянок"],
];
const SHUTKI = {
  ushla: ["Зверь уходит — догоняй!", "Лесничество уже косо смотрит 👀", "Без акта не отпустим"],
  mushka: ["Прицелься и составь акт", "Дичь сама не освидетельствуется", "Один выстрел — один акт"],
  sled: ["Следы свежие — скоро созреет", "Подкрадываемся тихо 🤫"],
};

function parseRu(s) {
  const m = /^(\d{2})\.(\d{2})\.(\d{4})/.exec(String(s || "").trim());
  if (m) return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
  const i = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || "").trim());
  return i ? new Date(Number(i[1]), Number(i[2]) - 1, Number(i[3])) : null;
}
function dney(ot, d) {
  return Math.round((d - ot) / 86400000);
}
function shutka(vid, id) {
  const s = SHUTKI[vid] || [];
  return s.length ? s[id % s.length] : "";
}
function zvanie(n) {
  let z = ZVANIYA[0][1], next = null;
  for (const [porog, t] of ZVANIYA) {
    if (n >= porog) z = t;
    else if (next == null) next = porog;
  }
  return { z, next };
}

export function srokAkta(r) {
  const s = [];
  if (r.akt_po_ploshadi_do && !r.akt_po_ploshadi_sostavlen) s.push(parseRu(r.akt_po_ploshadi_do));
  if (r.srok_osvidetelstvovaniya) s.push(parseRu(r.srok_osvidetelstvovaniya));
  const ok = s.filter(Boolean);
  return ok.length ? new Date(Math.min(...ok.map((d) => d.getTime()))) : null;
}

export function razlozhit(rows, segodnya) {
  const out = { ushla: [], mushka: [], sled: [], les: [], kapkan: [], trofei: [] };
  const god = segodnya.getFullYear();
  for (const r of rows) {
    if (r.zakryta) {
      const d = parseRu(r.posledniy_akt_data);
      if (r.osvidetelstvovana && d && d.getFullYear() === god) out.trofei.push({ ...r, aktData: d });
      continue;
    }
    if (r.osvidetelstvovana) { out.kapkan.push(r); continue; }
    const srok = srokAkta(r);
    const dni = srok ? dney(segodnya, srok) : null;
    const x = { ...r, srokAkta: srok, dni };
    if (dni != null && dni < 0) out.ushla.push(x);
    else if (dni != null && dni <= MUSHKA_DNEY) out.mushka.push(x);
    else if (r.ploshad_zakryta || r.po_spravke || (r.pct_osvoeniya_limita ?? 0) >= 90 || (r.pct_ploshadi ?? 0) >= 90) out.sled.push(x);
    else out.les.push(x);
  }
  const poSroku = (a, b) => (a.dni ?? 9999) - (b.dni ?? 9999);
  out.ushla.sort(poSroku); out.mushka.sort(poSroku); out.sled.sort(poSroku);
  out.les.sort((a, b) => (b.pct_osvoeniya_limita ?? 0) - (a.pct_osvoeniya_limita ?? 0));
  out.trofei.sort((a, b) => b.aktData - a.aktData);
  return out;
}

function Chip({ children, bg, color, title }) {
  return (
    <span title={title} className="inline-flex items-center" style={{
      gap: 4, padding: "5px 11px", borderRadius: 999, background: bg, color, fontWeight: 700, fontSize: 13,
    }}>{children}</span>
  );
}

function Patron({ ok, children, title }) {
  return (
    <span title={title} style={{
      fontSize: 12, padding: "2px 7px", borderRadius: 6, whiteSpace: "nowrap",
      background: ok ? C.moss : "#f3f1ec", color: ok ? C.leaf : C.muted, border: `1px solid ${ok ? "#bcefc5" : C.line}`,
    }}>{ok ? "✓" : "·"} {children}</span>
  );
}

function Zhizn({ dni }) {
  if (dni == null) return null;
  const pct = Math.max(0, Math.min(1, dni / OKNO_DNEY));
  const color = dni < 0 ? C.danger : dni <= 7 ? "#d9661f" : dni <= MUSHKA_DNEY ? C.gold : C.leaf;
  return (
    <div title="Сколько осталось до срока акта (из 30 дней)">
      <div style={{ height: 8, borderRadius: 4, background: C.line, overflow: "hidden" }}>
        <div style={{ width: `${dni < 0 ? 100 : pct * 100}%`, height: "100%", background: color }} />
      </div>
    </div>
  );
}

function Mishen({ r, vid, onAkt }) {
  const cl = r.checklist || [];
  const clDone = cl.filter((c) => c.is_done).length;
  const ploshadOk = !!(r.ploshad_zakryta || r.po_spravke || (r.pct_ploshadi ?? 0) >= 99);
  const limitPct = r.pct_osvoeniya_limita;
  const bg = vid === "ushla" ? C.dangerSoft : vid === "mushka" ? C.goldSoft : "#fff";
  const border = vid === "ushla" ? "#f3c2bd" : vid === "mushka" ? "#efd9a4" : C.line;
  const zver = ZVERI[r.id % ZVERI.length];
  return (
    <div style={{ background: bg, border: `1.5px solid ${border}`, borderRadius: 12, padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="flex items-start" style={{ gap: 10 }}>
        <span style={{ fontSize: 30, lineHeight: 1, filter: vid === "sled" ? "grayscale(.6)" : "none" }}>{zver}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, color: C.ink }}>{r.nazvanie || `Делянка №${r.id}`}</div>
          <div style={{ fontSize: 12, color: C.muted }}>
            {r.nomer_lesorubochnogo_bileta ? `билет №${r.nomer_lesorubochnogo_bileta}` : "билета нет"}
            {r.storonnyaya?.zagotovitel ? ` · рубит ${r.storonnyaya.zagotovitel}` : ""}
            {r.otsrochek ? ` · отсрочек ${r.otsrochek}` : ""}
          </div>
        </div>
        {r.dni != null && (
          <div style={{ textAlign: "right", fontWeight: 800, color: r.dni < 0 ? C.danger : r.dni <= 7 ? "#d9661f" : C.pine, fontSize: 13 }}>
            {r.dni < 0 ? `ушёл ${-r.dni} дн. назад` : r.dni === 0 ? "сегодня!" : `${r.dni} дн.`}
            <div style={{ fontSize: 11, fontWeight: 400, color: C.muted }}>акт до {r.srokAkta?.toLocaleDateString("ru-RU")}</div>
          </div>
        )}
      </div>
      <Zhizn dni={r.dni} />
      <div className="flex flex-wrap" style={{ gap: 4 }}>
        <Patron ok={!!r.nomer_lesorubochnogo_bileta}>билет</Patron>
        <Patron ok={ploshadOk} title={r.ploshad_zakryta ? `площадь пройдена ${r.ploshad_zakryta}` : ""}>
          площадь {r.pct_ploshadi != null ? `${Math.round(r.pct_ploshadi)}%` : ""}
        </Patron>
        <Patron ok={(limitPct ?? 0) >= 90}>лимит {limitPct != null ? `${Math.round(limitPct)}%` : "—"}{r.po_spravke ? " (справка)" : ""}</Patron>
        {cl.length > 0 && <Patron ok={clDone === cl.length}>чек-лист {clDone}/{cl.length}</Patron>}
      </div>
      <div className="flex items-center justify-between" style={{ gap: 8 }}>
        <span style={{ fontSize: 12, color: C.muted, fontStyle: "italic" }}>{shutka(vid, r.id)}</span>
        <button type="button" onClick={() => onAkt(r)} style={{
          padding: "6px 12px", borderRadius: 8, fontWeight: 700, fontSize: 13, whiteSpace: "nowrap",
          background: vid === "sled" ? "#fff" : C.pine, color: vid === "sled" ? C.pine : "#fff", border: `1px solid ${C.pine}`,
        }}>🎯 Составить акт</button>
      </div>
    </div>
  );
}

function Kolonka({ title, note, rows, vid, onAkt, pusto }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <div>
        <div style={{ fontWeight: 800, color: C.pine, fontSize: 15 }}>{title} <span style={{ color: C.muted, fontWeight: 600 }}>· {rows.length}</span></div>
        <div style={{ fontSize: 12, color: C.muted }}>{note}</div>
      </div>
      {rows.length === 0 && (
        <div style={{ padding: 14, border: `1px dashed ${C.line}`, borderRadius: 12, color: C.muted, fontSize: 13, textAlign: "center" }}>{pusto}</div>
      )}
      {rows.map((r) => <Mishen key={r.id} r={r} vid={vid} onAkt={onAkt} />)}
    </section>
  );
}

export default function OhotaAktov() {
  const toast = useToast();
  const can = useCan();
  const [rows, setRows] = useState(null);
  const [lesOpen, setLesOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dParam] = useScreenParam("inspection", "d");

  // Пришли по ссылке на конкретную делянку («Ждёт меня», квест) — сразу в форму.
  useEffect(() => {
    if (dParam) openScreen("inspection", { tab: "spisok" });
  }, [dParam]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    try {
      setRows((await api.get("/inspection/")) || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить делянки", description: e.message });
      setRows([]);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const segodnya = useMemo(() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }, []);
  const r = useMemo(() => razlozhit(rows || [], segodnya), [rows, segodnya]);
  const { z, next } = zvanie(r.trofei.length);

  const onAkt = (row) => openScreen("inspection", { tab: "spisok", d: row.id });

  const zakrytVse = async () => {
    if (!window.confirm(`Закрыть все делянки с актом (${r.kapkan.length})? Уйдут в архив, вернуть можно в «Списке» → фильтр «Закрыты».`)) return;
    setBusy(true);
    try {
      const res = await api.post("/inspection/zakryt-osvidetelstvovannye");
      toast.show({ tone: "success", title: `🏆 В трофеи: ${res?.zakryto ?? 0}`, description: "Делянки закрыты" });
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось закрыть", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  if (rows == null) return <div style={{ padding: 24, color: C.muted }}>Выслеживаем делянки… 🔭</div>;

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 14, color: C.muted }}>
        <b style={{ color: C.pine }}>🏹 Охота на акты</b> — делянки, которым пора акт освидетельствования. Срок — 30 дней от
        окончания вывозки или от дня, когда площадь пройдена по нарядам. За каждый акт +80 XP в квестах.
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Chip bg={r.ushla.length ? C.dangerSoft : "#f3f1ec"} color={r.ushla.length ? C.danger : C.muted}>🐗 Ушли: {r.ushla.length}</Chip>
        <Chip bg={C.goldSoft} color={C.gold}>🎯 На мушке: {r.mushka.length}</Chip>
        <Chip bg={C.skySoft} color={C.sky}>🐾 На следу: {r.sled.length}</Chip>
        <Chip bg={C.moss} color={C.leaf} title={next ? `До следующего звания — ${next - r.trofei.length} акт(ов)` : ""}>
          🏆 Трофеев за {segodnya.getFullYear()}: {r.trofei.length} · {z}
        </Chip>
        {r.ushla.length === 0 && r.mushka.length === 0 && (
          <span style={{ fontSize: 13, color: C.leaf, fontWeight: 600 }}>Тишина в лесу — все акты в срок 🌲</span>
        )}
      </div>

      {r.kapkan.length > 0 && (
        <div className="flex flex-wrap items-center justify-between" style={{
          gap: 10, padding: "10px 14px", borderRadius: 12, background: C.moss, border: "1px solid #bcefc5",
        }}>
          <div>
            <div style={{ fontWeight: 800, color: C.pine }}>🔒 В капкане: {r.kapkan.length}</div>
            <div style={{ fontSize: 12, color: C.muted }}>
              Акт есть, делянку осталось закрыть: {r.kapkan.slice(0, 4).map((x) => x.nazvanie).join(", ")}
              {r.kapkan.length > 4 ? ` и ещё ${r.kapkan.length - 4}` : ""}
            </div>
          </div>
          {can("delyanka.edit") && (
            <button type="button" disabled={busy} onClick={zakrytVse} style={{
              padding: "7px 14px", borderRadius: 8, fontWeight: 700, background: C.leaf, color: "#fff", opacity: busy ? 0.6 : 1,
            }}>🏆 Забрать трофеи ({r.kapkan.length})</button>
          )}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, alignItems: "start" }}>
        <Kolonka title="🐗 Ушли" note="срок акта прошёл — в первую очередь" rows={r.ushla} vid="ushla" onAkt={onAkt}
          pusto="Никто не ушёл. Красота 👌" />
        <Kolonka title="🎯 На мушке" note={`срок акта в ближайшие ${MUSHKA_DNEY} дней`} rows={r.mushka} vid="mushka" onAkt={onAkt}
          pusto="На мушке пусто" />
        <Kolonka title="🐾 На следу" note="площадь пройдена или лимит почти выбран — скоро пора" rows={r.sled} vid="sled" onAkt={onAkt}
          pusto="Следов нет — рубят дальше" />
      </div>

      {r.les.length > 0 && (
        <div>
          <button type="button" onClick={() => setLesOpen(!lesOpen)} style={{ fontSize: 13, color: C.muted, fontWeight: 600 }}>
            🌲 Ещё в лесу (рубят): {r.les.length} {lesOpen ? "▲" : "▼"}
          </button>
          {lesOpen && (
            <div className="flex flex-wrap" style={{ gap: 6, marginTop: 8 }}>
              {r.les.map((x) => (
                <button key={x.id} type="button" onClick={() => onAkt(x)} style={{
                  fontSize: 12, padding: "4px 10px", borderRadius: 999, border: `1px solid ${C.line}`, background: "#fff", color: C.ink,
                }}>{x.nazvanie} · {x.pct_osvoeniya_limita != null ? `${Math.round(x.pct_osvoeniya_limita)}%` : "—"}</button>
              ))}
            </div>
          )}
        </div>
      )}

      <section>
        <div style={{ fontWeight: 800, color: C.pine, fontSize: 15, marginBottom: 8 }}>🏆 Трофейная стена {segodnya.getFullYear()}</div>
        {r.trofei.length === 0 ? (
          <div style={{ fontSize: 13, color: C.muted }}>Пока пусто. Первый закрытый с актом — и тут появятся рога на стене 🦌</div>
        ) : (
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            {r.trofei.slice(0, 24).map((x) => (
              <div key={x.id} title={`Акт ${x.posledniy_akt_data}`} style={{
                display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", borderRadius: 10,
                background: "#fff", border: `1px solid ${C.line}`, fontSize: 13,
              }}>
                <span style={{ fontSize: 20 }}>{ZVERI[x.id % ZVERI.length]}</span>
                <span><b>{x.nazvanie}</b> <span style={{ color: C.muted }}>· {x.posledniy_akt_data}</span></span>
              </div>
            ))}
            {r.trofei.length > 24 && <span style={{ fontSize: 13, color: C.muted, alignSelf: "center" }}>и ещё {r.trofei.length - 24}</span>}
          </div>
        )}
      </section>
    </div>
  );
}
