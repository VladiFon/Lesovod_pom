import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import AuthImage from "./AuthImage.jsx";

/**
 * 📷 Фотолента делянки (шаг 6 разбора сайта 09.11.2026): фото из отчётов
 * с телефона, выполненных работ и меток на карте — одной лентой, новые
 * слева. Сервер: GET /api/delyanki/{id}/foto (app/fotolenta.py).
 */
function dd(s) {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(s || "").slice(0, 10);
}

export default function Fotolenta({ delyankaId }) {
  const [foto, setFoto] = useState(null);
  useEffect(() => {
    let zhiv = true;
    setFoto(null);
    api.get(`/delyanki/${delyankaId}/foto`).then((x) => zhiv && setFoto(x || [])).catch(() => zhiv && setFoto([]));
    return () => { zhiv = false; };
  }, [delyankaId]);
  if (!foto || !foto.length) return null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <span className="text-[13px] font-bold text-ink">📷 Фотолента</span>
        <span className="text-[11.5px] text-faint">{foto.length} фото с делянки · из отчётов, работ и меток</span>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-1">
        {foto.map((f, i) => (
          <div key={i} className="shrink-0 w-[170px] flex flex-col gap-1">
            <div className="h-[120px] rounded-lg overflow-hidden bg-hover [&_img]:h-[120px] [&_img]:w-full [&_img]:object-cover">
              <AuthImage path={f.path} />
            </div>
            <div className="text-[11.5px] leading-snug">
              <b className="text-ink">{dd(f.kogda)}</b> <span className="text-faint">· {f.otkuda}</span>
              <div className="text-muted truncate" title={[f.chto, f.kto, f.podpis].filter(Boolean).join(" · ")}>
                {[f.chto, f.kto].filter(Boolean).join(" · ")}
              </div>
              {f.podpis && <div className="text-faint truncate" title={f.podpis}>{f.podpis}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
