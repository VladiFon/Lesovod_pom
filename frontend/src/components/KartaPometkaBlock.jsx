import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";

/** Карточка делянки: «Скрыть с карт» и «Лесные культуры» (app/karta_pometki.py).
 * Скрытая делянка не рисуется в QGIS-плагине и в телефоне, из базы никуда не
 * девается; общие правила (закрытые, виды рубок, старые лесосеки ГИСлесхоза) —
 * в Настройках → «Карты: что не показывать». */
export default function KartaPometkaBlock({ delyankaId }) {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get(`/karta/delyanka/${delyankaId}`).then(setD).catch(() => setD(null));
  useEffect(() => { load(); }, [delyankaId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return null;
  const send = async (body, title) => {
    setBusy(true);
    try {
      await api.post("/karta/pometki", { istochnik: "delyanka", klyuchi: [String(delyankaId)], ...body });
      toast.show({ tone: "success", title });
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const avtoLk = d.lesokultury_rezhim === "avto";
  return (
    <div className="rounded-[10px] border border-border px-3.5 py-3 flex flex-col gap-2.5">
      <div className="text-[12.5px] font-semibold text-muted-2">На картах (QGIS и телефон)</div>
      <label className="flex items-start gap-2 text-sm text-ink cursor-pointer">
        <input
          type="checkbox"
          className="h-4 w-4 mt-0.5 accent-pine"
          disabled={!d.mozhno || busy}
          checked={d.skryta_vruchnuyu}
          onChange={(e) => send({ skryta: e.target.checked }, e.target.checked ? "Делянка скрыта с карт" : "Делянка снова на картах")}
        />
        <span>
          <b>Скрыть с карт</b>
          <span className="text-muted-2"> — например, уборка захламлённости на весь выдел, чтобы не лезла поверх других лесосек</span>
          {d.skryta && !d.skryta_vruchnuyu && (
            <span className="block text-[12.5px] text-[var(--c-warn,#b26a00)]">Сейчас не видна на картах: {d.skryta_prichina} (правило в Настройках)</span>
          )}
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-2 text-sm text-ink">
        <span>🌲 Лесные культуры:</span>
        {[["avto", "само"], ["da", "да"], ["net", "нет"]].map(([k, label]) => (
          <label key={k} className="flex items-center gap-1 cursor-pointer">
            <input
              type="radio"
              name={`lk-${delyankaId}`}
              disabled={!d.mozhno || busy}
              checked={d.lesokultury_rezhim === k}
              onChange={() => send({ lesokultury: k }, k === "da" ? "Отмечено: лесные культуры" : k === "net" ? "Отмечено: не культуры" : "Культуры — определять само")}
            />
            {label}
          </label>
        ))}
        <span className="text-muted-2 text-[12.5px]">
          {avtoLk
            ? (d.lesokultury ? `на выделе есть культуры: ${d.lk_info}` : "на выделах делянки культур в Лесоводе нет")
            : (d.lesokultury ? "отмечено вручную" : "отмечено вручную: не культуры")}
        </span>
      </div>
    </div>
  );
}
