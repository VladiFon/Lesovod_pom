import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import ChelovekLink from "../components/ChelovekLink.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * «🚜 Техника» (04.11.2026): трактора, харвестеры, пилы. За машиной
 * закрепляется человек — в «Отчёте за смену» на телефоне она подставляется
 * сама. Тип топлива (ДТ / АИ-92) идёт в сводку «⛽ Топливо».
 * Сервер: routers/tehnika.py.
 */

const C = { pine: "#1a4331", line: "#e5e2db", muted: "#565f59", moss: "#eaf7ec", danger: "#ba1a1a" };
const PUSTO = { nazvanie: "", tip: "Трактор", nomer: "", toplivo: "ДТ", zakreplen_sotrudnik_id: "", kommentariy: "", bak_l: "" };
const EMOJI = { Трактор: "🚜", Харвестер: "🌲", Форвардер: "🚛", Автомобиль: "🚙", Бензопила: "🪚" };
const inp = "border border-border rounded-[8px] px-2 h-9";

export default function Tehnika() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [vse, setVse] = useState(false);
  const [f, setF] = useState(null); // форма: {id?, ...}

  const load = useCallback(async () => {
    try {
      setD(await api.get("/tehnika", vse ? { vse: true } : {}));
    } catch (e) {
      toast.show({ tone: "danger", title: "Техника не загрузилась", description: e.message });
    }
  }, [vse]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const sohranit = async () => {
    const bak = f.bak_l === "" || f.bak_l == null ? null : Number(String(f.bak_l).replace(",", "."));
    if (Number.isNaN(bak)) return toast.show({ tone: "danger", title: "Объём бака — число литров" });
    const body = { ...f, bak_l: bak, zakreplen_sotrudnik_id: f.zakreplen_sotrudnik_id ? Number(f.zakreplen_sotrudnik_id) : null };
    delete body.id;
    try {
      if (f.id) await api.put(`/tehnika/${f.id}`, body);
      else await api.post("/tehnika", body);
      setF(null);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не сохранилось", description: e.message });
    }
  };
  const aktivna = async (t, on) => {
    if (!on && !window.confirm(`Списать «${t.nazvanie}»? Отчёты по ней останутся, в телефоне её больше не будет.`)) return;
    try {
      await api.post(`/tehnika/${t.id}/aktivna?on=${on}`);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не получилось", description: e.message });
    }
  };

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Загружаю технику…</div>;
  const zanyato = Object.fromEntries(d.tehnika.filter((t) => t.aktivna && t.zakreplen_sotrudnik_id).map((t) => [t.zakreplen_sotrudnik_id, t.nazvanie]));
  const bezMashiny = d.lyudi.filter((l) => /трактор|машинист|харвест|форвард/i.test(l.dolzhnost || "") && !zanyato[l.id]);

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <button type="button" onClick={() => setF({ ...PUSTO })} style={{ background: C.pine, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>＋ Добавить технику</button>
        <label style={{ fontSize: 13, color: C.muted }}><input type="checkbox" checked={vse} onChange={(e) => setVse(e.target.checked)} /> показать списанную</label>
      </div>

      {bezMashiny.length > 0 && (
        <div style={{ background: "#fbf1d6", border: "1px solid #f0dca6", borderRadius: 12, padding: 10, fontSize: 13 }}>
          🔑 Без закреплённой машины: {bezMashiny.map((l) => l.fio).join(", ")} — им в отчёте придётся выбирать технику каждый раз.
        </div>
      )}

      {f && (
        <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: 12, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
          <label style={{ fontSize: 12, color: C.muted }}>Название<br /><input className={inp} value={f.nazvanie} onChange={(e) => setF({ ...f, nazvanie: e.target.value })} placeholder="МТЗ-82, Ponsse Ergo…" autoFocus /></label>
          <label style={{ fontSize: 12, color: C.muted }}>Тип<br />
            <select className={inp} value={f.tip || ""} onChange={(e) => setF({ ...f, tip: e.target.value })}>{d.tipy.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label style={{ fontSize: 12, color: C.muted }}>Гос./инв. номер<br /><input className={inp} value={f.nomer || ""} onChange={(e) => setF({ ...f, nomer: e.target.value })} /></label>
          <label style={{ fontSize: 12, color: C.muted }}>Топливо<br />
            <select className={inp} value={f.toplivo || ""} onChange={(e) => setF({ ...f, toplivo: e.target.value })}>
              <option value="">—</option>{d.toplivo.map((t) => <option key={t}>{t}</option>)}</select></label>
          <label style={{ fontSize: 12, color: C.muted }}>⛽ Бак, л<br /><input className={inp} style={{ width: 80 }} value={f.bak_l ?? ""} onChange={(e) => setF({ ...f, bak_l: e.target.value })} placeholder="78" inputMode="decimal" /></label>
          <label style={{ fontSize: 12, color: C.muted }}>Закреплена за<br />
            <select className={inp} value={f.zakreplen_sotrudnik_id || ""} onChange={(e) => setF({ ...f, zakreplen_sotrudnik_id: e.target.value })}>
              <option value="">— никем —</option>
              {d.lyudi.map((l) => <option key={l.id} value={l.id}>{l.fio}{zanyato[l.id] && zanyato[l.id] !== f.nazvanie ? ` (уже: ${zanyato[l.id]})` : ""}</option>)}
            </select></label>
          <label style={{ fontSize: 12, color: C.muted, flex: 1, minWidth: 160 }}>Комментарий<br /><input className={inp + " w-full"} value={f.kommentariy || ""} onChange={(e) => setF({ ...f, kommentariy: e.target.value })} /></label>
          <button type="button" onClick={sohranit} disabled={!f.nazvanie.trim()} style={{ background: C.pine, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>Сохранить</button>
          <button type="button" onClick={() => setF(null)} style={{ color: C.muted }}>Отмена</button>
        </div>
      )}

      <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, overflow: "hidden" }}>
        {d.tehnika.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: C.muted }}>Техники пока нет. Добавьте трактора и харвестеры и закрепите за людьми — в телефоне машина будет подставляться сама.</div>
        ) : d.tehnika.map((t) => (
          <div key={t.id} className="flex items-center" style={{ gap: 12, padding: "10px 12px", borderTop: `1px solid ${C.line}`, opacity: t.aktivna ? 1 : 0.55 }}>
            <span style={{ fontSize: 22 }}>{EMOJI[t.tip] || "🔧"}</span>
            <div style={{ flex: 1, minWidth: 0, fontSize: 13 }}>
              <div><b>{t.nazvanie}</b>{t.nomer && <span style={{ color: C.muted }}> · {t.nomer}</span>}{t.toplivo && <span style={{ color: C.muted }}> · {t.toplivo}</span>}{t.bak_l && <span style={{ color: C.muted }}> · бак {t.bak_l} л</span>}{!t.aktivna && <span style={{ color: C.danger }}> · списана</span>}</div>
              <div style={{ color: C.muted }}>
                {t.zakreplen ? <>🔑 <ChelovekLink id={t.zakreplen_sotrudnik_id} fio={t.zakreplen} className="font-normal" /></> : "не закреплена"}
                {t.otchetov > 0 && <> · отчётов: {t.otchetov}, последний {t.posledniy_otchet}</>}
                {t.kommentariy && <> · {t.kommentariy}</>}
              </div>
            </div>
            <button type="button" onClick={() => setF({ ...PUSTO, ...t, bak_l: t.bak_l ?? "", zakreplen_sotrudnik_id: t.zakreplen_sotrudnik_id || "" })} title="Изменить">✏️</button>
            <button type="button" onClick={() => aktivna(t, !t.aktivna)} title={t.aktivna ? "Списать" : "Вернуть"} style={{ color: C.muted }}>{t.aktivna ? "🗑" : "↩"}</button>
          </div>
        ))}
      </div>
    </div>
  );
}
