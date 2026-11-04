import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";

const f1 = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 }));

/** Хворост делянки (legacy/hvorost.py): откуда брать «разрешено» по хворосту
 * для Расхода и акта освидетельствования — МДО («ликвид из кроны»), проба
 * «хворост делянки» из Рубок ухода или не учитывать. Карточка делянки и Инспекция. */
export default function HvorostBlock({ delyankaId, onChanged }) {
  const toast = useToast();
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get(`/hvorost/delyanka/${delyankaId}`).then(setD).catch(() => setD(null));
  }, [delyankaId]);
  if (!d) return null;

  const set = async (istochnik) => {
    try {
      setD(await api.put(`/hvorost/delyanka/${delyankaId}`, { istochnik }));
      onChanged?.();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    }
  };
  const varianty = [
    ["net", "Не учитывать"],
    ["mdo", `Из МДО${d.mdo ? ` · ${f1(d.mdo)} м³` : " · нет данных"}`],
    ["proba", `Из пробы${d.po_probe !== null ? ` · ${f1(d.po_probe)} м³` : " · пробы нет"}`],
  ];
  return (
    <div className="rounded-[10px] border border-border px-3.5 py-3 flex flex-col gap-2">
      <div className="text-sm font-bold text-ink">🔥 Хворост в лимиты и акт</div>
      <div className="flex flex-wrap gap-2">
        {varianty.map(([k, t]) => (
          <button
            key={k}
            onClick={() => k !== d.istochnik && set(k)}
            className={["px-3 py-1.5 rounded-md border text-sm", d.istochnik === k ? "bg-mint text-pine border-pine font-bold" : "border-border hover:bg-hover"].join(" ")}
          >{t}</button>
        ))}
      </div>
      {d.istochnik !== "net" ? (
        <div className="text-xs text-muted">
          Разрешено {f1(d.limit)} м³ · по нарядам {f1(d.fakt)} м³ · осталось {f1(d.ostatok)} м³. Строка «хворост» в акте заполнится сама.
        </div>
      ) : (
        <div className="text-xs text-muted">
          Хворост не входит в лимиты, в акт идёт только факт по нарядам{d.fakt ? ` (${f1(d.fakt)} м³)` : ""}.
        </div>
      )}
      {d.proby.length > 0 && (
        <div className="text-xs text-muted">
          Пробы хвороста: {d.proby.map((p) => `№${p.id} кв.${p.kvartal} выд.${p.vydel} — ${f1(p.zapas_na_1ga)} м³/га`).join("; ")}
        </div>
      )}
    </div>
  );
}
