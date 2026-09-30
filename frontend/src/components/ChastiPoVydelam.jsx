import React, { useState } from "react";
import Button from "./Button.jsx";
import TextField from "./TextField.jsx";

const num = (v) => Number(String(v ?? "").replace(",", "."));

/** Номера выделов из строки «1, 2, 9» / «1-2» (как vydel_tokens на сервере, упрощённо). */
export function vydelyIz(text) {
  return String(text || "").split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
}

/** info для ChastiForm из выдела делянки / участка культур. */
export function chastiInfo(obj) {
  let chasti = [];
  try {
    chasti = obj.chasti_json ? JSON.parse(obj.chasti_json) : [];
  } catch {
    chasti = [];
  }
  return {
    kvartal: obj.kvartal || "", vydel: obj.vydel || "", ploshad: obj.ploshad ?? "",
    vydely: vydelyIz(obj.vydel), chasti: Array.isArray(chasti) ? chasti : [], taks: {},
  };
}

/**
 * Участок культур или лесосека в нескольких таксационных выделах: площадь
 * (и подвыдел) по каждому выделу. Сохраняется в сам участок / выдел делянки,
 * в ведомости — строка на каждую часть.
 */
export default function ChastiForm({ info, onSave, onCancel }) {
  const [parts, setParts] = useState(() =>
    (info.chasti.length ? info.chasti
      : info.vydely.map((v) => ({ vydel: v, ploshad: info.vydely.length === 1 ? info.ploshad : "" })))
      .map((c) => ({ vydel: c.vydel ?? "", podvydel: c.podvydel ?? "", ploshad: c.ploshad ?? "" }))
  );
  const [novyy, setNovyy] = useState(info.novyy || "");
  // Один выдел — новый номер целиком (33), несколько — 33.1, 33.2, 33.3.
  const prisvoit = () => setParts((ps) => ps.map((c, i) => ({
    ...c, podvydel: ps.length === 1 ? String(novyy).trim() : `${String(novyy).trim()}.${i + 1}`,
  })));
  const bezNovogo = () => setParts((ps) => ps.map((c) => ({ ...c, podvydel: "" })));
  const [saving, setSaving] = useState(false);
  const set = (i, key, v) => setParts((ps) => ps.map((c, j) => (j === i ? { ...c, [key]: v } : c)));
  const total = Math.round(parts.reduce((s, c) => s + (num(c.ploshad) || 0), 0) * 100) / 100;
  const vsego = num(info.ploshad);
  const submit = async (list) => {
    setSaving(true);
    try {
      await onSave(list.map((c) => ({
        vydel: String(c.vydel).trim(), podvydel: String(c.podvydel).trim(),
        ploshad: String(c.ploshad).trim() === "" ? null : num(c.ploshad),
      })));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-2.5 bg-surface-alt text-xs">
      <div className="font-semibold text-pine">
        {parts.length > 1
          ? <>Кв. {info.kvartal}, выделы {info.vydel}: площадь по каждому выделу{info.ploshad && ` (всего ${info.ploshad} га)`}</>
          : <>Кв. {info.kvartal}, выдел {info.vydel}{info.ploshad && `, ${info.ploshad} га`}</>}
      </div>
      {info.novyy !== undefined && (
        <div className="flex flex-wrap gap-2 items-end">
          <TextField label="Новый выдел (если занимает не весь выдел)" value={novyy}
            onChange={(e) => setNovyy(e.target.value)} />
          <Button variant="secondary" size="sm" onClick={prisvoit} disabled={!String(novyy).trim()}>
            Присвоить {parts.length > 1 && String(novyy).trim() ? `${String(novyy).trim()}.1–${String(novyy).trim()}.${parts.length}` : String(novyy).trim()}
          </Button>
          <Button variant="ghost" size="sm" onClick={bezNovogo}>Без нового выдела</Button>
          <span className="text-muted">
            {info.posledniy
              ? `Последний выдел кв. ${info.kvartal} по таксации — ${info.posledniy}; номера, уже данные в этом году другим участкам квартала, пропущены.`
              : `Таксации кв. ${info.kvartal} в базе нет — впишите номер сами.`}
          </span>
        </div>
      )}
      {parts.map((c, i) => (
        <div key={i} className="grid gap-2 grid-cols-[repeat(3,minmax(110px,1fr))_auto] items-end">
          <TextField label="Выдел" value={c.vydel} onChange={(e) => set(i, "vydel", e.target.value)} />
          <TextField label="Новый выдел (подвыдел)" placeholder="нет — остаётся прежний"
            value={c.podvydel} onChange={(e) => set(i, "podvydel", e.target.value)} />
          <TextField label={`Площадь, га${info.taks?.[c.vydel] ? ` (выдел по таксации ${info.taks[c.vydel]})` : ""}`}
            value={c.ploshad} onChange={(e) => set(i, "ploshad", e.target.value)} />
          <Button variant="ghost" size="sm" onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}>Убрать</Button>
        </div>
      ))}
      <div className={total && vsego && Math.abs(total - vsego) > 0.05 ? "text-oak" : "text-muted"}>
        Сумма: {total} га{vsego ? ` из ${vsego} га` : ""}
        {total && vsego && Math.abs(total - vsego) > 0.05 ? " — не сходится с общей площадью" : ""}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={() => submit(parts)} loading={saving}>Сохранить</Button>
        <Button variant="secondary" size="sm" onClick={() => setParts((ps) => [...ps, { vydel: "", podvydel: "", ploshad: "" }])}>
          Добавить выдел
        </Button>
        {info.chasti.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => submit([])}>Убрать разбивку</Button>
        )}
        <Button variant="ghost" size="sm" onClick={onCancel}>Отмена</Button>
      </div>
    </div>
  );
}

