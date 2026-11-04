import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Modal from "./Modal.jsx";
import { openChelovek } from "./ChelovekLink.jsx";

const ISTOCHNIK = { smena: "отчёт с телефона", zhurnal: "журнал выполненных работ", uhody: "рубки ухода (офис)" };
const ruData = (s) => {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s || "";
  const d = new Date(`${m[1]}-${m[2]}-${m[3]}T12:00:00`);
  const dn = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"][d.getDay()];
  return `${m[3]}.${m[2]} ${dn}`;
};

/** Одна работа: эмодзи, что, где, сколько. */
export function RabotaStroka({ r, kratko = false }) {
  return (
    <div className="leading-5" title={ISTOCHNIK[r.istochnik] || ""}>
      <span>{r.emoji} </span>
      <span className="text-ink">{r.chto}</span>
      {r.gde && <span className="text-muted"> · {r.gde}</span>}
      {r.skolko && <span className="text-pine font-semibold"> · {r.skolko}</span>}
      {!kratko && r.s_kem && <span className="text-muted"> · с {r.s_kem}</span>}
      {!kratko && r.tehnika && <span className="text-muted"> · {r.tehnika}</span>}
    </div>
  );
}

/** «Где был и что делал» человек за период: табель + отчёты + журнал работ. */
export default function IstoriyaRabot({ sotrudnikId, onClose }) {
  const [dney, setDney] = useState(31);
  const [d, setD] = useState(null);
  useEffect(() => {
    if (!sotrudnikId) return;
    setD(null);
    api.get(`/tabel/raboty/${sotrudnikId}`, { dney }).then(setD).catch(() => setD({ dni: [], itogo: [] }));
  }, [sotrudnikId, dney]);
  return (
    <Modal open={!!sotrudnikId} onClose={onClose} title={d?.fio ? `Где был и что делал — ${d.fio}` : "Где был и что делал"} size="lg">
      <div className="flex flex-col gap-3 text-[13px]">
        <div className="flex gap-1.5 items-center">
          {[[7, "Неделя"], [31, "Месяц"], [92, "3 месяца"]].map(([n, t]) => (
            <button key={n} onClick={() => setDney(n)}
              className={["px-3 py-1 rounded-md border text-sm", dney === n ? "bg-mint text-pine border-pine font-bold" : "border-border hover:bg-hover"].join(" ")}>
              {t}
            </button>
          ))}
          <button onClick={() => { onClose?.(); openChelovek(sotrudnikId); }}
            className="ml-auto px-3 py-1 rounded-md border border-pine text-pine text-sm font-semibold hover:bg-mint-soft">
            👤 Вся карточка человека →
          </button>
        </div>
        {!d ? (
          <div className="text-muted">Загрузка…</div>
        ) : (
          <>
            {d.itogo?.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {d.itogo.map((x) => (
                  <span key={x.chto} className="rounded-full bg-hover px-2.5 py-1 text-xs">{x.chto}: <b>{x.dney}</b></span>
                ))}
              </div>
            )}
            {d.dni.length === 0 ? (
              <div className="text-muted">За этот период о нём ничего нет — ни табеля, ни отчётов.</div>
            ) : (
              <div className="flex flex-col divide-y divide-border">
                {d.dni.map((x) => (
                  <div key={x.data} className="py-2 flex gap-3">
                    <div className="w-[70px] shrink-0 font-semibold text-ink">{ruData(x.data)}</div>
                    <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                      {x.tabel && (
                        <div className="text-muted">
                          📋 {x.tabel.status}{x.tabel.vid ? ` · ${x.tabel.vid}` : ""}{x.tabel.gde ? ` · ${x.tabel.gde}` : ""}
                          {x.tabel.kommentariy ? ` · ${x.tabel.kommentariy}` : ""}
                        </div>
                      )}
                      {x.raboty.map((r, i) => <RabotaStroka key={i} r={r} />)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
