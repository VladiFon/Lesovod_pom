import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Button from "./Button.jsx";
import TextField from "./TextField.jsx";
import DateField from "./DateField.jsx";
import { useToast } from "./Toast.jsx";

const SORTIMENTY = [
  ["KR", "крупная"], ["SR", "средняя"], ["ML", "мелкая"], ["DROVA", "дрова"], ["HVOROST", "хворост"],
];

/** Сторонняя заготовка: документы оформляем мы, рубит другой лесхоз /
 * лесопункт (app/storonnyaya.py на сервере). Наряды пишем мы или сам
 * заготовитель — на телефоне делянка видна только в первом случае. «Фактически» в акт — из справки заготовителя, если в ней есть
 * объёмы, иначе из нарядов. Используется в Инспекции и карточке делянки. */
export default function StoronnyayaBlock({ row, onChanged }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    api.get(`/inspection/${row.id}/storonnyaya`).then((d) => setData({
      ...d,
      naryady: d.naryady || "my",
      ploshad_fakt: d.ploshad_fakt ?? "",
      fakt: Object.fromEntries(SORTIMENTY.map(([k]) => [k, d.fakt?.[k] ?? ""])),
    })).catch(() => setData(null));
  }, [row.id]);
  if (!data) return null;
  const set = (k) => (v) => setData((d) => ({ ...d, [k]: v }));
  const save = async (next = data) => {
    setSaving(true);
    try {
      const num = (v) => (v === "" || v == null ? null : Number(String(v).replace(",", ".")));
      await api.put(`/inspection/${row.id}/storonnyaya`, {
        storonnyaya: next.storonnyaya,
        zagotovitel: next.zagotovitel || "",
        naryady: next.naryady || "my",
        spravka_nomer: next.spravka_nomer || "",
        spravka_data: next.spravka_data || "",
        ploshad_fakt: num(next.ploshad_fakt),
        fakt: Object.fromEntries(SORTIMENTY.map(([k]) => [k, num(next.fakt[k])])),
      });
      toast.show({ tone: "success", title: next.storonnyaya ? "Сторонняя заготовка сохранена" : "Делянку снова рубим мы" });
      onChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    } finally {
      setSaving(false);
    }
  };
  const vsego = SORTIMENTY.reduce((s, [k]) => s + (Number(String(data.fakt[k]).replace(",", ".")) || 0), 0);
  const limitVsego = SORTIMENTY.reduce((s, [k]) => s + (data.limity?.[k] || 0), 0);
  return (
    <div className="rounded-[10px] border border-border px-3.5 py-3 flex flex-col gap-3">
      <label className="flex items-center gap-2 text-sm text-ink cursor-pointer">
        <input
          type="checkbox"
          checked={!!data.storonnyaya}
          onChange={(e) => {
            const next = { ...data, storonnyaya: e.target.checked };
            setData(next);
            if (!e.target.checked) save(next);
          }}
          className="h-4 w-4 accent-pine"
        />
        <b>Заготовку ведёт сторонняя организация</b>
        <span className="text-muted-2">— не наша бригада; в Расходе, бригадах и на телефоне делянка помечается «рубит …»</span>
      </label>
      {data.storonnyaya && (
        <>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(170px,1fr))]">
            <TextField label="Заготовитель" value={data.zagotovitel || ""} onChange={(e) => set("zagotovitel")(e.target.value)} hint="пойдёт в акт как лесопользователь" />
            <TextField label="Справка №" value={data.spravka_nomer || ""} onChange={(e) => set("spravka_nomer")(e.target.value)} />
            <DateField label="Справка от" value={data.spravka_data || ""} onChange={set("spravka_data")} />
            <TextField label="Площадь пройдена, га" type="number" step="0.01" value={data.ploshad_fakt} onChange={(e) => set("ploshad_fakt")(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-semibold text-muted-2">Кто пишет наряды</span>
            <div className="flex flex-wrap gap-4 text-sm text-ink">
              {[
                ["my", "Мы", "делянка видна на телефоне с пометкой «рубит …»"],
                ["zagotovitel", "Сам заготовитель", "на телефоне делянку не видно"],
              ].map(([v, label, hint]) => (
                <label key={v} className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name={`naryady-${row.id}`}
                    checked={data.naryady === v}
                    onChange={() => set("naryady")(v)}
                    className="h-4 w-4 accent-pine"
                  />
                  {label} <span className="text-muted-2 text-xs">— {hint}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="text-[12.5px] text-muted-2">
            Справка заготовителя — если заполнена, объёмы и площадь для акта берутся из неё, иначе из нарядов.
          </div>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(120px,1fr))]">
            {SORTIMENTY.map(([k, label]) => (
              <TextField
                key={k}
                label={`${label}, м³`}
                type="number"
                step="0.01"
                value={data.fakt[k]}
                onChange={(e) => setData((d) => ({ ...d, fakt: { ...d.fakt, [k]: e.target.value } }))}
                hint={`по билету ${data.limity?.[k] ?? 0}`}
              />
            ))}
          </div>
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-[12.5px] text-muted-2">
              Всего по справке <b className="text-ink">{Math.round(vsego * 100) / 100} м³</b> из {Math.round(limitVsego * 100) / 100} по билету
              {limitVsego ? ` (${Math.round((vsego / limitVsego) * 1000) / 10}%)` : ""}
            </span>
            <Button variant="secondary" size="sm" onClick={() => save()} loading={saving}>Сохранить</Button>
          </div>
        </>
      )}
    </div>
  );
}

