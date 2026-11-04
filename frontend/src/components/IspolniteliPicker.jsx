import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

let kesh = null;
/** Активные сотрудники для выбора исполнителей (один запрос на страницу). */
export function useSotrudniki() {
  const [list, setList] = useState(kesh || []);
  useEffect(() => {
    if (kesh) return;
    api.get("/brigady/sotrudniki").then((r) => { kesh = r; setList(r); }).catch(() => {});
  }, []);
  return list;
}

/** «Кто делал»: несколько сотрудников с поиском + сторонние (ФИО текстом).
 * value = { ids: number[], storonnie: string[] }. */
export default function IspolniteliPicker({ value, onChange, label = "Кто делал" }) {
  const sotrudniki = useSotrudniki();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const ids = value.ids || [];
  const storonnie = value.storonnie || [];
  const qq = q.trim().toLowerCase();
  const naydeno = sotrudniki
    .filter((s) => !ids.includes(s.id))
    .filter((s) => !qq || `${s.fio} ${s.dolzhnost || ""}`.toLowerCase().includes(qq))
    .slice(0, 8);
  const vybrany = ids.map((id) => sotrudniki.find((s) => s.id === id)).filter(Boolean);
  const dobavitStoronnego = () => {
    const name = q.trim();
    if (!name) return;
    if (!storonnie.some((n) => n.toLowerCase() === name.toLowerCase())) onChange({ ids, storonnie: [...storonnie, name] });
    setQ("");
  };
  return (
    <div className="flex flex-col gap-1.5">
      <label className="block text-[11.5px] font-semibold text-muted">{label}</label>
      {(vybrany.length > 0 || storonnie.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {vybrany.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1 rounded-full bg-mint text-pine text-xs px-2.5 py-1">
              👷 {s.fio}
              <button type="button" className="ml-0.5 opacity-70 hover:opacity-100" onClick={() => onChange({ ids: ids.filter((i) => i !== s.id), storonnie })}>✕</button>
            </span>
          ))}
          {storonnie.map((n) => (
            <span key={n} className="inline-flex items-center gap-1 rounded-full bg-hover text-ink text-xs px-2.5 py-1">
              {n} <span className="text-muted">(сторонний)</span>
              <button type="button" className="ml-0.5 opacity-70 hover:opacity-100" onClick={() => onChange({ ids, storonnie: storonnie.filter((x) => x !== n) })}>✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          className="w-full h-9 rounded-md border border-border bg-surface px-3 text-sm"
          placeholder="Поиск по фамилии…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (naydeno.length === 1) { onChange({ ids: [...ids, naydeno[0].id], storonnie }); setQ(""); }
            }
          }}
        />
        {open && (naydeno.length > 0 || q.trim()) && (
          <ul className="absolute z-20 left-0 right-0 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-surface shadow-lg">
            {naydeno.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="w-full text-left px-3 py-1.5 text-sm hover:bg-hover"
                  onMouseDown={(e) => { e.preventDefault(); onChange({ ids: [...ids, s.id], storonnie }); setQ(""); }}
                >
                  {s.fio}{s.dolzhnost ? <span className="text-muted"> · {s.dolzhnost}</span> : null}
                </button>
              </li>
            ))}
            {q.trim() && (
              <li>
                <button type="button" className="w-full text-left px-3 py-1.5 text-sm text-pine hover:bg-hover"
                  onMouseDown={(e) => { e.preventDefault(); dobavitStoronnego(); }}>
                  ＋ «{q.trim()}» — сторонний исполнитель
                </button>
              </li>
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
