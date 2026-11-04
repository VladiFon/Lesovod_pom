import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Card from "./Card.jsx";
import Button from "./Button.jsx";
import TextField from "./TextField.jsx";
import DateField from "./DateField.jsx";
import { useToast } from "./Toast.jsx";

const f1 = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 }));
const ruDate = (s) => {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : s || "";
};
const today = () => {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
};

/** Поле «Кто делал» с поиском по справочнику сотрудников (можно и вписать
 * стороннего человека руками). */
function SotrudnikPoisk({ value, onChange, sotrudniki }) {
  const [open, setOpen] = useState(false);
  const q = value.trim().toLowerCase();
  const naydeno = sotrudniki
    .filter((s) => !q || `${s.fio} ${s.dolzhnost || ""}`.toLowerCase().includes(q))
    .slice(0, 8);
  return (
    <div className="relative">
      <TextField
        label="Кто делал"
        placeholder="Начни вводить фамилию…"
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && naydeno.length > 0 && !(naydeno.length === 1 && naydeno[0].fio === value) && (
        <ul className="absolute z-20 left-0 right-0 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-surface shadow-lg">
          {naydeno.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                className="w-full text-left px-3 py-1.5 text-sm hover:bg-hover"
                onMouseDown={(e) => { e.preventDefault(); onChange(s.fio); setOpen(false); }}
              >
                {s.fio}{s.dolzhnost ? <span className="text-muted"> · {s.dolzhnost}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** «Выполнение» по пробе рубок ухода (app/uhody_vypolnenie.py): сколько га
 * уже сделано по отчётам с телефона и вручную, кубы = м³/га пробы × га. */
export default function UhodyVypolnenie({ probaId, onChanged }) {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [nov, setNov] = useState({ data: today(), ga: "", ispolnitel: "", kommentariy: "" });
  const [saving, setSaving] = useState(false);
  const [sotrudniki, setSotrudniki] = useState([]);
  useEffect(() => {
    api.get("/uhody/sotrudniki").then(setSotrudniki).catch(() => {});
  }, []);

  useEffect(() => {
    setD(null);
    api.get(`/uhody/proby/${probaId}/vypolnenie`).then(setD).catch(() => setD(null));
  }, [probaId]);

  if (!d) return null;

  const add = async () => {
    const ga = Number(String(nov.ga).replace(",", "."));
    if (!ga || ga <= 0) {
      toast.show({ tone: "danger", title: "Укажи, сколько га сделано" });
      return;
    }
    setSaving(true);
    try {
      const r = await api.post(`/uhody/proby/${probaId}/vypolnenie`, { ...nov, ga });
      setD(r);
      setNov((n) => ({ ...n, ga: "", kommentariy: "" }));
      if (r.zakryli_seychas) {
        toast.show({ tone: "success", title: "🏁 Проба закрыта", description: "Вся площадь пройдена — проба ушла из списка на телефоне." });
      }
      onChanged?.(r);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось добавить", description: e.message });
    } finally {
      setSaving(false);
    }
  };
  const del = async (id) => {
    try {
      const r = await api.delete(`/uhody/vypolnenie/${id}`);
      setD(r);
      onChanged?.(r);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить", description: e.message });
    }
  };

  const pct = Math.min(d.pct || 0, 100);
  const stroki = [
    ...d.otchety.map((o) => ({ ...o, kto: o.fio + (o.naparnikov ? ` +${o.naparnikov}` : ""), otkuda: "📱" })),
    ...d.ruchnye.map((r) => ({ ...r, kto: r.ispolnitel || "—", otkuda: "✍️" })),
  ].sort((a, b) => String(a.data).localeCompare(String(b.data)));

  return (
    <Card
      title="✂️ Выполнение"
      subtitle="Подтягивается из отчётов с телефона (рубка ухода на этом выделе / участке культур) — можно добавить и руками. Кубы = м³/га пробы × сделанные га."
    >
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm mb-2">
        <div>Сделано: <b>{f1(d.sdelano_ga)}</b>{d.ploshad ? ` из ${f1(d.ploshad)} га` : " га"}</div>
        {d.ostatok_ga !== null && <div>Осталось: <b>{f1(d.ostatok_ga)} га</b></div>}
        <div>Кубов: <b>{f1(d.kubov)}</b>{d.kubov_vsego ? ` из ${f1(d.kubov_vsego)} м³` : " м³"}</div>
        <div className="text-muted">{f1(d.zapas_na_1ga)} м³/га по пробе</div>
      </div>
      <div className="text-xs mb-2">
        {d.zakryta ? (
          <span className="text-pine">✅ Проба закрыта {ruDate(d.zakryta_data)}</span>
        ) : d.ploshad ? (
          <span className="text-muted">Проба закроется сама, когда будет сделана вся площадь (или кнопкой «🏁 Закрыть пробу» внизу).</span>
        ) : (
          <span className="text-muted">Площадь выдела не указана — закрой пробу кнопкой «🏁 Закрыть пробу», когда закончите.</span>
        )}
      </div>
      {d.ploshad ? (
        <div className="h-2 rounded-full bg-hover overflow-hidden mb-3">
          <div className="h-full bg-pine" style={{ width: `${pct}%` }} />
        </div>
      ) : (
        <div className="text-xs text-muted mb-3">Площадь лесосеки в шапке не указана — остаток не посчитать.</div>
      )}
      {stroki.length > 0 && (
        <table className="w-full text-sm mb-3">
          <thead>
            <tr className="text-left text-muted text-xs">
              <th className="py-1 pr-2">Дата</th><th className="py-1 pr-2">Кто</th>
              <th className="py-1 pr-2 text-right">га</th><th className="py-1 pr-2 text-right">м³</th><th />
            </tr>
          </thead>
          <tbody>
            {stroki.map((s) => (
              <tr key={`${s.otkuda}${s.id}`} className="border-t border-border">
                <td className="py-1 pr-2 whitespace-nowrap">{s.otkuda} {ruDate(s.data)}</td>
                <td className="py-1 pr-2">{s.kto}{s.kommentariy ? <span className="text-muted"> · {s.kommentariy}</span> : null}</td>
                <td className="py-1 pr-2 text-right">{f1(s.ga)}</td>
                <td className="py-1 pr-2 text-right">{f1(s.kubov)}</td>
                <td className="py-1 text-right">
                  {s.otkuda === "✍️" && (
                    <button className="text-muted hover:text-danger" title="Удалить строку" onClick={() => del(s.id)}>✕</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-[150px]"><DateField label="Дата" value={nov.data} onChange={(v) => setNov((n) => ({ ...n, data: v }))} /></div>
        <div className="w-[90px]"><TextField label="Га" value={nov.ga} onChange={(e) => setNov((n) => ({ ...n, ga: e.target.value }))} /></div>
        <div className="w-[240px]"><SotrudnikPoisk value={nov.ispolnitel} sotrudniki={sotrudniki} onChange={(v) => setNov((n) => ({ ...n, ispolnitel: v }))} /></div>
        <div className="flex-1 min-w-[140px]"><TextField label="Примечание" value={nov.kommentariy} onChange={(e) => setNov((n) => ({ ...n, kommentariy: e.target.value }))} /></div>
        <Button variant="primary" onClick={add} disabled={saving}>＋ Добавить</Button>
      </div>
    </Card>
  );
}
