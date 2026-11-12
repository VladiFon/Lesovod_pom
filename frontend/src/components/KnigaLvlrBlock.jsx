import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";
import { useToast } from "./Toast.jsx";

/**
 * Карточка делянки → «📗 Книга ЛВ и ЛР» (Влад, 09.11.2026): в книге ли
 * делянка (№, разворот, строка) и своя ли она. Рубим и в чужом лесничестве /
 * лесхозе — такие делянки в книгу не идут: программа угадывает по
 * лесничеству, здесь можно поправить вручную. Сервер: routers/kniga_lvlr.py.
 */
export default function KnigaLvlrBlock({ delyankaId, canEdit }) {
  const toast = useToast();
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get(`/kniga-lvlr/delyanka/${delyankaId}`).then(setD).catch(() => setD(null));
  }, [delyankaId]);
  if (!d) return null;
  const pomenyat = async (flag) => {
    try {
      setD(await api.put(`/kniga-lvlr/delyanka/${delyankaId}`, { flag }));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не сохранилось", description: e.message });
    }
  };
  const svoe = [d.svoe.lesnichestvo, d.svoe.leshoz].filter(Boolean).join(", ") || "не задано";
  return (
    <div className="rounded-[10px] border border-border px-3.5 py-3 flex flex-col gap-2 text-sm text-ink">
      <div className="flex flex-wrap items-center gap-2">
        <b>📗 Книга ЛВ и ЛР:</b>
        {d.v_knige ? (
          <button type="button" className="underline" onClick={() => openScreen("formy", { tab: "kniga", kt: "kniga" })}>
            №{d.v_knige.nomer}{d.v_knige.razvorot ? `, разворот ${d.v_knige.razvorot}, строка ${d.v_knige.stroka}` : ""}
          </button>
        ) : d.chuzhaya ? (
          <span className="text-muted-2">не вносится — чужой участок</span>
        ) : (
          <span className="text-muted-2">{d.est_bilet ? "ещё не внесена — см. «Что вписать»" : "внесётся, когда будет лесорубочный билет"}</span>
        )}
      </div>
      <label className="flex items-start gap-2 cursor-pointer">
        <input type="checkbox" className="h-4 w-4 accent-pine mt-0.5" disabled={!canEdit} checked={d.chuzhaya}
          onChange={(e) => pomenyat(e.target.checked ? "chuzhaya" : (d.avto_chuzhaya ? "svoya" : ""))} />
        <span>
          <b>Чужой участок</b> (другое лесничество / лесхоз) — в книгу не вносить
          <span className="block text-[12px] text-muted-2">
            {d.flag ? "отмечено вручную" : d.avto_chuzhaya ? `программа сама считает чужой: своё — ${svoe}` : `своё — ${svoe}`}
            {d.flag && canEdit && <> · <button type="button" className="underline" onClick={() => pomenyat("")}>как определит программа</button></>}
            {d.v_knige && d.chuzhaya && " · уже в книге: уберите строку на экране книги (✏️ → «Чужая делянка — убрать»)"}
          </span>
        </span>
      </label>
    </div>
  );
}
