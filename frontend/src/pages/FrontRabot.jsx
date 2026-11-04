import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * «🗺 Фронт работ» — игровой вид экрана «Распределение бригад» (просьба
 * Влада 03.11.2026). Бригады у Влада не сидят на одной делянке, поэтому
 * «кто где» — из табеля, а план на день — обычные задачи «Плана работ»:
 * перетащи звено/человека на делянку (или выдели и нажми «Сюда»).
 * Сервер: backend/app/routers/front_rabot.py.
 */

const MONO = "'JetBrains Mono', monospace";
const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dangerSoft: "#fdecea", sky: "#2c5d8a",
};
const AVA = ["#3f7d4e", "#2c5d8a", "#9a6200", "#7a3f8a", "#a0442c", "#2f7a78", "#5a6b2c", "#8a3f5a"];
const TON = {
  bad: { bg: C.dangerSoft, fg: C.danger, border: "#f3c2bd" },
  ok: { bg: C.moss, fg: C.pine, border: "#bcefc5" },
  idle: { bg: "#f6f3ec", fg: C.muted, border: C.line },
};
const XP_ZA_NAZNACHENIE = 3;

function inic(fio) {
  const p = (fio || "?").split(/\s+/);
  return (((p[0] || "")[0] || "") + ((p[1] || "")[0] || "")).toUpperCase();
}
function korotko(fio) {
  return (fio || "").split(/\s+/)[0];
}
function sdvig(iso, n) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
function krasivo(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" });
}

function Ava({ l, size = 26, dim }) {
  return (
    <span
      title={l.fio}
      style={{
        width: size, height: size, borderRadius: 8, display: "inline-grid", placeItems: "center", flexShrink: 0,
        background: dim ? "#d9d5cc" : AVA[l.sotrudnik_id % AVA.length], color: "#fff", fontWeight: 800, fontSize: size * 0.38,
      }}
    >
      {inic(l.fio)}
    </span>
  );
}

export default function FrontRabot() {
  const toast = useToast();
  const [data, setData] = useState("");
  const [f, setF] = useState(null);
  const [err, setErr] = useState("");
  const [vybor, setVybor] = useState([]);
  const [over, setOver] = useState(null);
  const [xp, setXp] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (d = data) => {
    try {
      const r = await api.get("/front-rabot", d ? { data: d } : undefined);
      setF(r);
      if (!d) setData(r.data);
      setErr("");
    } catch (e) {
      setErr(e.message);
    }
  }, [data]);
  useEffect(() => { load(data); }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const poId = useMemo(() => Object.fromEntries((f?.lyudi || []).map((l) => [l.sotrudnik_id, l])), [f]);
  const delPoId = useMemo(() => Object.fromEntries((f?.delyanki || []).map((d) => [d.id, d])), [f]);

  const naznachit = async (ids, del) => {
    if (!ids.length) return;
    setBusy(true);
    let n = 0;
    try {
      for (const sid of ids) {
        const l = poId[sid];
        if (!l) continue;
        // Уже стоит на эту делянку в этот день — не дублируем.
        if (l.plan.some((p) => p.delyanka_id === del.id)) continue;
        // Стоял на другой делянке в этот день — переносим (старую задачу снимаем).
        for (const p of l.plan.filter((p) => p.delyanka_id && p.delyanka_id !== del.id)) {
          await api.delete(`/work-plan/${p.id}`);
        }
        const item = del.items.find((i) => i.item_id === l.gde?.delyanka_item_id) || del.items[0];
        await api.post("/work-plan/", {
          sotrudnik_id: sid, data, zadacha: `Работа на делянке: ${del.nazvanie || del.vydely}`,
          delyanka_item_id: item?.item_id || null,
        });
        n += 1;
      }
      if (n) setXp((x) => x + n * XP_ZA_NAZNACHENIE);
      setVybor([]);
      await load(data);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не получилось поставить в план", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const snyat = async (sid, del) => {
    const l = poId[sid];
    try {
      for (const p of l.plan.filter((p) => p.delyanka_id === del.id)) await api.delete(`/work-plan/${p.id}`);
      await load(data);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не снялось", description: e.message });
    }
  };

  const kakBylo = async () => {
    const grup = {};
    (f?.lyudi || []).forEach((l) => {
      if (!l.plan.length && l.gde?.status === "работал" && l.gde.delyanka_id && delPoId[l.gde.delyanka_id]) {
        (grup[l.gde.delyanka_id] = grup[l.gde.delyanka_id] || []).push(l.sotrudnik_id);
      }
    });
    for (const [did, ids] of Object.entries(grup)) await naznachit(ids, delPoId[did]);
  };

  const onDrop = (e, del) => {
    e.preventDefault();
    setOver(null);
    try {
      const ids = JSON.parse(e.dataTransfer.getData("text/plain") || "[]");
      naznachit(ids, del);
    } catch {
      /* не наш перетаскиваемый объект */
    }
  };
  const drag = (ids) => (e) => e.dataTransfer.setData("text/plain", JSON.stringify(ids));
  const toggle = (ids) => {
    const vse = ids.every((i) => vybor.includes(i));
    setVybor(vse ? vybor.filter((i) => !ids.includes(i)) : [...new Set([...vybor, ...ids])]);
  };

  if (!f) return <div className="p-8 text-muted text-[13px]">{err ? `Фронт не загрузился: ${err}` : "Разворачиваю карту…"}</div>;

  const bezPlana = f.lyudi.filter((l) => !l.plan.length);
  const vPlane = f.lyudi.filter((l) => l.plan.length);
  const mozhnoKakBylo = bezPlana.filter((l) => l.gde?.status === "работал" && l.gde.delyanka_id && delPoId[l.gde.delyanka_id]).length;
  const gorit = f.delyanki.filter((d) => d.ton === "bad").length;

  return (
    <div className="flex flex-col" style={{ padding: 18, gap: 14 }}>
      <div style={{ fontSize: 12.5, color: C.muted }}>
        <b style={{ color: C.pine }}>🗺 Фронт работ</b> — кто где работает (по табелю) и план на день. Перетащи звено или человека на делянку —
        ему уйдёт задача в «План работ». Темп — по нарядам за {f.temp_dney} дней.
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ fontWeight: 800, color: C.pine, fontSize: 15 }}>План на</span>
        <button type="button" onClick={() => setData(sdvig(data, -1))} style={btn()}>◀</button>
        <input id="front-data" type="date" value={data} onChange={(e) => e.target.value && setData(e.target.value)}
          style={{ height: 30, border: `1px solid ${C.line}`, borderRadius: 8, padding: "0 8px", fontSize: 13 }} />
        <button type="button" onClick={() => setData(sdvig(data, 1))} style={btn()}>▶</button>
        <span style={{ fontWeight: 700, color: C.ink }}>{krasivo(data)}</span>
        <span style={{ flex: 1 }} />
        {gorit > 0 && <span style={{ ...chip(), background: C.dangerSoft, color: C.danger }}>🔥 горит: {gorit}</span>}
        <span style={chip()}>👷 в плане {vPlane.length} из {f.lyudi.length}</span>
        {xp > 0 && <span style={{ ...chip(), background: C.goldSoft, color: C.gold }}>+{xp} XP</span>}
        <button type="button" disabled={!mozhnoKakBylo || busy} onClick={kakBylo}
          title="Каждого, у кого нет плана на этот день, — на делянку, где он работал в последний раз"
          style={{ ...btn(), background: C.gold, color: "#fff", border: 0, opacity: mozhnoKakBylo ? 1 : 0.45 }}>
          ⚡ Все как в прошлый раз ({mozhnoKakBylo})
        </button>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 260px", gap: 14, alignItems: "start" }}>
        {/* карта делянок */}
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 10, padding: 10, borderRadius: 12,
          background: "repeating-linear-gradient(45deg, #dfe9d6 0 14px, #d4e2c9 14px 28px)" }}>
          {f.delyanki.map((d) => {
            const t = TON[d.ton];
            const bylo = d.bylo.map((id) => poId[id]).filter(Boolean);
            const plan = d.v_plane.map((id) => poId[id]).filter(Boolean);
            return (
              <div
                key={d.id}
                onDragOver={(e) => { e.preventDefault(); setOver(d.id); }}
                onDragLeave={() => setOver(null)}
                onDrop={(e) => onDrop(e, d)}
                style={{
                  background: "#fffdf8", borderRadius: 12, padding: 10, display: "flex", flexDirection: "column", gap: 6,
                  border: `2px solid ${over === d.id ? C.gold : d.ton === "bad" ? "#e9a39c" : "transparent"}`,
                  transform: over === d.id ? "scale(1.02)" : "none", transition: "transform .12s, border-color .12s",
                }}
              >
                <div>
                  <div style={{ fontWeight: 800, fontSize: 13.5, color: C.ink }}>{d.nazvanie || d.vydely}</div>
                  <div style={{ fontSize: 11.5, color: C.muted }}>{d.vydely}{d.zagotovitel ? ` · рубит ${d.zagotovitel}` : ""}</div>
                </div>
                {d.pct != null && (
                  <div style={{ height: 7, borderRadius: 4, background: C.line, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${Math.min(d.pct, 100)}%`, background: d.pct > 100 ? C.danger : C.leaf }} />
                  </div>
                )}
                <div className="flex justify-between flex-wrap" style={{ gap: 4, fontFamily: MONO, fontSize: 11, color: C.muted }}>
                  <span>{d.pct != null ? `${d.pct}% · ост. ${Math.round(d.ostatok)} м³` : "лимита нет"}</span>
                  <span>{d.temp ? `${d.temp} м³/день` : "темп —"}</span>
                </div>
                {d.srok && <div style={{ fontSize: 11.5, color: C.muted }}>срок заготовки {d.srok}{d.dni_do != null ? ` · ${d.dni_do} дн.` : ""}</div>}
                <div style={{ fontSize: 12, fontWeight: 700, borderRadius: 7, padding: "4px 7px", background: t.bg, color: t.fg }}>{d.verdikt}</div>

                <div style={{ minHeight: 34, border: `1.5px dashed ${C.line}`, borderRadius: 8, padding: 4, display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
                  {plan.length === 0 && <span style={{ fontSize: 11, color: "#8a938c", padding: "0 4px" }}>перетащи людей сюда</span>}
                  {plan.map((l) => (
                    <span key={l.sotrudnik_id} className="flex items-center" style={{ gap: 3, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 8, padding: "2px 4px 2px 2px" }}>
                      <Ava l={l} size={20} />
                      <span style={{ fontSize: 11.5 }}>{korotko(l.fio)}</span>
                      <button type="button" onClick={() => snyat(l.sotrudnik_id, d)} aria-label={`Снять ${l.fio}`}
                        style={{ border: 0, background: "transparent", color: "#8a938c", cursor: "pointer", fontSize: 12, padding: 0 }}>×</button>
                    </span>
                  ))}
                </div>
                {bylo.length > 0 && (
                  <div className="flex items-center flex-wrap" style={{ gap: 3, fontSize: 11, color: C.muted }}>
                    недавно были: {bylo.map((l) => <Ava key={l.sotrudnik_id} l={l} size={18} dim={!d.v_plane.includes(l.sotrudnik_id)} />)}
                  </div>
                )}
                {vybor.length > 0 && (
                  <button type="button" disabled={busy} onClick={() => naznachit(vybor, d)}
                    style={{ ...btn(), background: C.pine, color: "#fff", border: 0 }}>
                    ➕ Сюда ({vybor.length})
                  </button>
                )}
              </div>
            );
          })}
          {f.delyanki.length === 0 && <div style={{ padding: 20, color: C.muted }}>Активных делянок нет.</div>}
        </div>

        {/* отряд */}
        <div className="flex flex-col" style={{ gap: 10, position: "sticky", top: 0 }}>
          {f.zvenya.length > 0 && (
            <div className="flex flex-col" style={{ gap: 6 }}>
              <div style={{ fontSize: 11, fontFamily: MONO, textTransform: "uppercase", letterSpacing: ".06em", color: C.muted }}>Звенья</div>
              {f.zvenya.map((z) => {
                const chl = z.sostav.filter((id) => poId[id]);
                const on = chl.length && chl.every((id) => vybor.includes(id));
                return (
                  <div key={z.id} draggable onDragStart={drag(chl)} onClick={() => toggle(chl)} role="button" tabIndex={0}
                    onKeyDown={(e) => e.key === "Enter" && toggle(chl)}
                    style={{ cursor: "grab", display: "flex", alignItems: "center", gap: 6, padding: "6px 8px", borderRadius: 10, background: "#fff",
                      border: `2px solid ${on ? C.gold : C.line}` }}>
                    <span style={{ fontSize: 16 }}>{z.emoji}</span>
                    <span className="min-w-0 flex-1 truncate" style={{ fontWeight: 700, fontSize: 12.5 }}>{z.nazvanie}</span>
                    <span className="flex">{chl.map((id, i) => <span key={id} style={{ marginLeft: i ? -5 : 0 }}><Ava l={poId[id]} size={18} /></span>)}</span>
                  </div>
                );
              })}
            </div>
          )}
          {[["Без плана", bezPlana], ["Уже в плане", vPlane]].map(([title, spisok]) => spisok.length > 0 && (
            <div key={title} className="flex flex-col" style={{ gap: 5 }}>
              <div style={{ fontSize: 11, fontFamily: MONO, textTransform: "uppercase", letterSpacing: ".06em", color: C.muted }}>{title} · {spisok.length}</div>
              {spisok.map((l) => {
                const on = vybor.includes(l.sotrudnik_id);
                const gde = l.gde?.delyanka_id ? delPoId[l.gde.delyanka_id] : null;
                return (
                  <div key={l.sotrudnik_id} draggable onDragStart={drag([l.sotrudnik_id])} onClick={() => toggle([l.sotrudnik_id])}
                    role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && toggle([l.sotrudnik_id])}
                    style={{ cursor: "grab", display: "flex", alignItems: "center", gap: 7, padding: "5px 7px", borderRadius: 9, background: "#fff",
                      border: `2px solid ${on ? C.gold : "transparent"}`, boxShadow: `0 0 0 1px ${C.line}` }}>
                    <Ava l={l} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate" style={{ fontWeight: 700, fontSize: 12.5 }}>{l.fio}</span>
                      <span className="block truncate" style={{ fontSize: 11, color: C.muted }}>
                        {l.plan.length ? `📅 ${l.plan.map((p) => delPoId[p.delyanka_id]?.nazvanie || p.zadacha).join(", ")}`
                          : l.gde ? (l.gde.status === "работал" ? `был: ${gde ? (gde.nazvanie || gde.vydely) : l.gde.lesokultury_uchastok_id ? "культуры" : "—"}` : l.gde.status)
                            : "в табеле давно не было"}
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
          {vybor.length > 0 && (
            <button type="button" onClick={() => setVybor([])} style={btn()}>Снять выделение ({vybor.length})</button>
          )}
        </div>
      </div>
    </div>
  );
}

function btn() {
  return { height: 30, padding: "0 11px", borderRadius: 8, fontSize: 12.5, fontWeight: 700, cursor: "pointer", border: `1px solid ${C.line}`, background: "#fff", color: "#414944", whiteSpace: "nowrap" };
}
function chip() {
  return { fontSize: 12.5, fontWeight: 700, padding: "5px 10px", borderRadius: 999, background: "#fff", border: `1px solid ${C.line}`, color: C.ink };
}
