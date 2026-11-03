import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * «🚜 Отчёты за смену» — что трактористы и рабочие прислали с телефона
 * (03.11.2026): трелёвка, вывозка населению, уход за культурами,
 * подготовка почвы, ремонт. Итоги по людям за период, недоделанные участки
 * (остаток га), удаление ошибочного отчёта. Сервер: routers/smena.py.
 */

const C = { pine: "#1a4331", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18", moss: "#eaf7ec", gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a" };

function iso(d) {
  return d.toISOString().slice(0, 10);
}
function ru(s) {
  return s ? new Date(s).toLocaleDateString("ru-RU", { day: "numeric", month: "short", weekday: "short" }) : "";
}
function ch(v, ed) {
  if (v === null || v === undefined || v === "") return "";
  return `${Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}${ed ? ` ${ed}` : ""}`;
}

export default function OtchetySmeny() {
  const toast = useToast();
  const [ot, setOt] = useState(() => iso(new Date(Date.now() - 13 * 864e5)));
  const [doD, setDoD] = useState(() => iso(new Date()));
  const [vid, setVid] = useState("");
  const [d, setD] = useState(null);

  const load = useCallback(async () => {
    try {
      setD(await api.get("/smena", { date_from: ot, date_to: doD, ...(vid ? { vid } : {}) }));
    } catch (e) {
      toast.show({ tone: "danger", title: "Отчёты не загрузились", description: e.message });
    }
  }, [ot, doD, vid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const itogi = useMemo(() => {
    const m = {};
    for (const r of d?.otchety || []) {
      for (const who of [{ id: r.sotrudnik_id, fio: r.fio }, ...r.naparniki]) {
        const x = m[who.id] || (m[who.id] = { fio: who.fio, chasy: 0, trel: 0, nas: 0, reysov: 0, ga: 0, remont: 0, dney: new Set() });
        x.dney.add(r.data);
        if (who.id !== r.sotrudnik_id) continue; // объём — у автора, чтобы не задваивать
        x.chasy += r.chasy || 0;
        if (r.vid === "trelevka") x.trel += r.obyom || 0;
        if (r.vid === "naseleniyu") x.nas += r.obyom || 0;
        x.reysov += r.reysov || 0;
        if (r.vid === "uhod" || r.vid === "pochva") x.ga += r.ga || 0;
        if (r.vid === "remont") x.remont += r.chasy || 0;
      }
    }
    return Object.values(m).sort((a, b) => b.chasy - a.chasy);
  }, [d]);

  const udalit = async (r) => {
    if (!window.confirm(`Удалить отчёт «${r.vid_title}» ${r.fio} за ${ru(r.data)}?${r.zakryl_cikl ? " Запись ухода в журнале участка тоже удалится." : ""}`)) return;
    try {
      await api.delete(`/smena/${r.id}`);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалилось", description: e.message });
    }
  };

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Загружаю отчёты…</div>;

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
        <label style={{ fontSize: 12, color: C.muted }}>С<br /><input type="date" value={ot} onChange={(e) => setOt(e.target.value)} className="border border-border rounded-[8px] px-2 h-9" /></label>
        <label style={{ fontSize: 12, color: C.muted }}>По<br /><input type="date" value={doD} onChange={(e) => setDoD(e.target.value)} className="border border-border rounded-[8px] px-2 h-9" /></label>
        <div className="flex flex-wrap" style={{ gap: 4 }}>
          {[["", "Все"], ...Object.entries(d.vidy).map(([k, v]) => [k, `${v.emoji} ${v.title}`])].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setVid(k)} aria-pressed={vid === k} style={{
              padding: "6px 10px", borderRadius: 999, fontSize: 12.5, fontWeight: 700,
              background: vid === k ? C.pine : "#fff", color: vid === k ? "#fff" : C.pine, border: `1px solid ${vid === k ? C.pine : C.line}`,
            }}>{l}</button>
          ))}
        </div>
      </div>

      {d.otkrytye.length > 0 && (
        <div style={{ background: C.goldSoft, border: "1px solid #f0dca6", borderRadius: 12, padding: 12 }}>
          <div style={{ fontWeight: 800, color: C.gold, marginBottom: 6 }}>⏳ Участки в работе — пройдены не полностью</div>
          {d.otkrytye.map((x) => (
            <div key={`${x.uchastok_id}-${x.vid}`} style={{ fontSize: 13 }}>
              {x.vid === "uhod" ? "🌱" : "🪚"} {x.vid_title}: <b>{x.mesto}</b> — сделано {ch(x.sdelano, "га")}
              {x.ploshad ? ` из ${ch(x.ploshad, "га")}, осталось ${ch(x.ostatok, "га")}` : ""} <span style={{ color: C.muted }}>(посл. {ru(x.posledniy)})</span>
            </div>
          ))}
          <div style={{ fontSize: 11.5, color: C.muted, marginTop: 4 }}>Когда участок пройден целиком, уход сам записывается в журнал участка лесокультур.</div>
        </div>
      )}

      {itogi.length > 0 && (
        <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, overflow: "hidden" }}>
          <div style={{ padding: "8px 12px", fontWeight: 800, color: C.pine, borderBottom: `1px solid ${C.line}` }}>Итоги по людям за период</div>
          <table className="w-full" style={{ fontSize: 13 }}>
            <thead><tr style={{ color: C.muted, textAlign: "left" }}>
              {["Кто", "Дней", "Часов", "Трелёвка", "Населению", "Рейсов", "Уход/почва", "Ремонт"].map((h) => <th key={h} style={{ padding: "6px 12px", fontWeight: 600 }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {itogi.map((x) => (
                <tr key={x.fio} style={{ borderTop: `1px solid ${C.line}` }}>
                  <td style={{ padding: "6px 12px", fontWeight: 700 }}>{x.fio}</td>
                  <td style={{ padding: "6px 12px" }}>{x.dney.size}</td>
                  <td style={{ padding: "6px 12px" }}>{ch(x.chasy)}</td>
                  <td style={{ padding: "6px 12px" }}>{ch(x.trel || "", "м³")}</td>
                  <td style={{ padding: "6px 12px" }}>{ch(x.nas || "", "м³")}</td>
                  <td style={{ padding: "6px 12px" }}>{x.reysov || ""}</td>
                  <td style={{ padding: "6px 12px" }}>{ch(x.ga || "", "га")}</td>
                  <td style={{ padding: "6px 12px" }}>{ch(x.remont || "", "ч")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: "6px 12px", fontSize: 11.5, color: C.muted }}>Объёмы и часы — у того, кто отправил отчёт; напарникам засчитываются дни.</div>
        </div>
      )}

      <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, overflow: "hidden" }}>
        {d.otchety.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: C.muted }}>За период отчётов нет. Их присылают с телефона: «Отчёт за смену».</div>
        ) : d.otchety.map((r) => (
          <div key={r.id} className="flex items-start" style={{ gap: 12, padding: "10px 12px", borderTop: `1px solid ${C.line}` }}>
            <span style={{ fontSize: 22 }}>{r.emoji}</span>
            <div style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
              <div><b>{r.vid_title}</b> · {r.fio}{r.naparniki.length > 0 && <span style={{ color: C.muted }}> + {r.naparniki.map((n) => n.fio).join(", ")}</span>}
                <span style={{ color: C.muted }}> · {ru(r.data)}</span></div>
              <div>
                {r.mesto && <span>{r.mesto} · </span>}
                {r.reysov != null && <span>{r.reysov} рейс. · </span>}
                {r.obyom != null && <span><b>{ch(r.obyom, "м³")}</b> · </span>}
                {r.ga != null && <span><b>{ch(r.ga, "га")}</b>{r.ploshad_uchastka ? ` из ${ch(r.ploshad_uchastka, "га")}` : ""} · </span>}
                {r.chasy != null && <span>{ch(r.chasy, "ч")}</span>}
                {r.zakryl_cikl && <span style={{ color: C.pine, fontWeight: 700 }}> · ✅ участок пройден, уход записан в журнал</span>}
              </div>
              {(r.poluchatel || r.tehnika || r.kommentariy) && (
                <div style={{ color: C.muted }}>
                  {r.poluchatel && <>кому: {r.poluchatel}. </>}{r.tehnika && <>техника: {r.tehnika}. </>}{r.kommentariy}
                </div>
              )}
            </div>
            <button type="button" onClick={() => udalit(r)} title="Удалить ошибочный отчёт" style={{ color: C.muted }}>🗑</button>
          </div>
        ))}
      </div>
    </div>
  );
}
