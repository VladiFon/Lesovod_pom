import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Card from "./Card.jsx";
import { useToast } from "./Toast.jsx";

/** Назначение пробы: рубка ухода или «хворост делянки» (документы на хворост
 * делянки главного пользования — legacy/hvorost.py). Хворост делянки не
 * ловит отчёты с телефона и может идти в лимиты/акт этой делянки. */
export default function HvorostProba({ probaId, delyankaId, delyankaNazvanie, onChanged }) {
  const toast = useToast();
  const [delyanki, setDelyanki] = useState(null);
  const [rezhim, setRezhim] = useState(delyankaId ? "hvorost" : "uhod");
  useEffect(() => setRezhim(delyankaId ? "hvorost" : "uhod"), [probaId, delyankaId]);
  useEffect(() => {
    if (rezhim === "hvorost" && delyanki === null) api.get("/hvorost/delyanki").then(setDelyanki).catch(() => setDelyanki([]));
  }, [rezhim, delyanki]);

  const save = async (id) => {
    try {
      const rec = await api.put(`/uhody/proby/${probaId}/hvorost`, { delyanka_id: id });
      toast.show({
        tone: "success",
        title: id ? `Проба — хворост делянки «${rec.delyanka_nazvanie || id}»` : "Проба снова — рубка ухода",
        description: id ? "На делянке выбери в блоке «🔥 Хворост», брать ли его в лимиты и акт." : undefined,
      });
      onChanged?.(rec);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    }
  };

  return (
    <Card title="Что это за проба">
      <div className="flex flex-wrap gap-2 mb-2">
        <button
          className={["px-3 py-1.5 rounded-md border text-sm", rezhim === "uhod" ? "bg-mint text-pine border-pine font-bold" : "border-border hover:bg-hover"].join(" ")}
          onClick={() => { setRezhim("uhod"); if (delyankaId) save(null); }}
        >✂️ Рубка ухода</button>
        <button
          className={["px-3 py-1.5 rounded-md border text-sm", rezhim === "hvorost" ? "bg-mint text-pine border-pine font-bold" : "border-border hover:bg-hover"].join(" ")}
          onClick={() => setRezhim("hvorost")}
        >🔥 Хворост делянки</button>
      </div>
      {rezhim === "hvorost" && (
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted">Делянка, к которой относится хворост</label>
          <select
            className="h-9 rounded-md border border-border bg-surface px-2 text-sm"
            value={delyankaId || ""}
            onChange={(e) => e.target.value && save(Number(e.target.value))}
          >
            <option value="">{delyankaId ? delyankaNazvanie : "— выбрать делянку —"}</option>
            {(delyanki || []).filter((x) => x.id !== delyankaId).map((x) => (
              <option key={x.id} value={x.id}>{x.nazvanie || `Делянка №${x.id}`}{x.kv_vyd ? ` · ${x.kv_vyd}` : ""}</option>
            ))}
          </select>
          {delyankaId ? (
            <div className="text-xs text-muted">
              Не попадает в рубки ухода и отчёты с телефона. В лимиты и акт идёт, если на делянке в блоке «🔥 Хворост» выбрано «из пробы».
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
