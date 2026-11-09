import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * «⛽ Топливо» (04.11.2026): кто сколько заправил и сжёг за период — по
 * людям и по машинам, отдельно ДТ и АИ-92. «В баке примерно» = все
 * заправки минус весь расход машины с начала учёта: если уходит в минус
 * или растёт без конца — кто-то не пишет расход или заправку.
 * Данные — из «Отчёта за смену» с телефона. Сервер: GET /api/smena/toplivo.
 */

const C = { pine: "#1a4331", line: "#e5e2db", muted: "#565f59", gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dt: "#2f5d8a", ai: "#8a4f2f" };
const VIDY = ["ДТ", "АИ-92", "—"];
const CVET = { "ДТ": C.dt, "АИ-92": C.ai, "—": C.muted };

function iso(d) {
  return d.toISOString().slice(0, 10);
}
function l(v) {
  return v ? `${Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} л` : "";
}

function Tablica({ title, rows, imya, extra }) {
  const est = VIDY.filter((t) => rows.some((r) => r.po_toplivu[t]));
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, overflowX: "auto" }}>
      <div style={{ padding: "8px 12px", fontWeight: 800, color: C.pine, borderBottom: `1px solid ${C.line}` }}>{title}</div>
      <table className="w-full" style={{ fontSize: 13, minWidth: 560 }}>
        <thead><tr style={{ color: C.muted, textAlign: "left" }}>
          <th style={{ padding: "6px 12px", fontWeight: 600 }}>{imya}</th>
          {est.map((t) => <th key={t} colSpan={2} style={{ padding: "6px 12px", fontWeight: 700, color: CVET[t] }}>{t === "—" ? "тип не указан" : t}: сжёг / заправил</th>)}
          <th style={{ padding: "6px 12px", fontWeight: 600 }}>л/час</th>
          <th style={{ padding: "6px 12px", fontWeight: 600 }}>л/м³</th>
          {extra && extra.head.map((h) => <th key={h} style={{ padding: "6px 12px", fontWeight: 600 }}>{h}</th>)}
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderTop: `1px solid ${C.line}` }}>
              <td style={{ padding: "6px 12px", fontWeight: 700 }}>{r.fio || r.nazvanie}
                {r.kto && <div style={{ fontWeight: 400, fontSize: 11.5, color: C.muted }}>{r.kto.join(", ")}</div>}</td>
              {est.map((t) => (
                <React.Fragment key={t}>
                  <td style={{ padding: "6px 12px", color: CVET[t], fontWeight: 700 }}>{l(r.po_toplivu[t]?.rashod)}</td>
                  <td style={{ padding: "6px 12px", color: CVET[t] }}>{l(r.po_toplivu[t]?.zapravka)}</td>
                </React.Fragment>
              ))}
              <td style={{ padding: "6px 12px" }}>{r.l_na_chas ?? ""}</td>
              <td style={{ padding: "6px 12px" }}>{r.l_na_m3 ?? ""}</td>
              {extra && extra.cells(r)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Toplivo() {
  const toast = useToast();
  const now = new Date();
  const [ot, setOt] = useState(() => iso(new Date(now.getFullYear(), now.getMonth(), 1, 12)));
  const [doD, setDoD] = useState(() => iso(now));
  const [d, setD] = useState(null);

  const load = useCallback(async () => {
    try {
      setD(await api.get("/smena/toplivo", { date_from: ot, date_to: doD }));
    } catch (e) {
      toast.show({ tone: "danger", title: "Сводка не загрузилась", description: e.message });
    }
  }, [ot, doD]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Считаю топливо…</div>;
  const pusto = d.lyudi.length === 0;

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
        <label style={{ fontSize: 12, color: C.muted }}>С<br /><input type="date" value={ot} onChange={(e) => setOt(e.target.value)} className="border border-border rounded-[8px] px-2 h-9" /></label>
        <label style={{ fontSize: 12, color: C.muted }}>По<br /><input type="date" value={doD} onChange={(e) => setDoD(e.target.value)} className="border border-border rounded-[8px] px-2 h-9" /></label>
      </div>

      <div className="flex flex-wrap" style={{ gap: 10 }}>
        {Object.entries(d.vsego).map(([t, v]) => (
          <div key={t} style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: "10px 14px", minWidth: 180 }}>
            <div style={{ fontSize: 12, color: C.muted }}>{t === "—" ? "Тип топлива не указан" : t}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: CVET[t] }}>{l(v.rashod) || "0 л"}</div>
            <div style={{ fontSize: 12, color: C.muted }}>сожгли · заправили {l(v.zapravka) || "0 л"}</div>
          </div>
        ))}
      </div>

      {pusto ? (
        <div style={{ padding: 24, textAlign: "center", color: C.muted, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12 }}>
          За период расход и заправки не вносили. Трактористы и харвестерщики пишут их в «Отчёте за смену» на телефоне.
        </div>
      ) : (
        <>
          <Tablica title="По людям" imya="Кто" rows={d.lyudi} extra={{ head: ["Смен"], cells: (r) => <td style={{ padding: "6px 12px" }}>{r.smen}</td> }} />
          <Tablica title="По машинам" imya="Машина" rows={d.mashiny} extra={{
            head: ["За кем", "В баке примерно", "📝 По путевым: сжёг / заправил"],
            cells: (r) => (
              <>
                <td style={{ padding: "6px 12px" }}>{r.zakreplen || ""}</td>
                <td style={{ padding: "6px 12px", fontWeight: 700, color: r.v_bake_primerno < 0 ? C.danger : C.pine }}>
                  {r.v_bake_primerno == null ? "" : r.v_bake_primerno < 0 ? `${l(r.v_bake_primerno)} ⚠` : l(r.v_bake_primerno) || "0 л"}
                </td>
                <td style={{ padding: "6px 12px", color: C.muted }}>{r.putevye ? `${l(r.putevye.rashod) || "0 л"} / ${l(r.putevye.zapravka) || "0 л"}` : "—"}</td>
              </>
            ),
          }} />
          <div style={{ fontSize: 11.5, color: C.muted }}>
            «В баке примерно» — все заправки минус весь расход машины с начала учёта. Минус значит, что заправки не вносят;
            если растёт месяц за месяцем — не вносят расход (или топливо уходит не туда 😏). Л/час и л/м³ помогают сравнить одинаковые машины.
          </div>
        </>
      )}
    </div>
  );
}
