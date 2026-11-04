import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Button from "../components/Button.jsx";
import Modal from "../components/Modal.jsx";
import TextField from "../components/TextField.jsx";
import { useToast } from "../components/Toast.jsx";
import { openScreen } from "../nav.js";

/**
 * «🔥 Челленджи» — общие цели на всю команду (этап 5, 03.11.2026).
 * Одна общая шкала с отметкой «где должны быть по графику», темп, прогноз,
 * сколько надо в рабочий день, кто больше вложился. Победа даёт команде
 * звание в «Зале славы». Сервер: routers/chellendzhi.py.
 */

const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dangerSoft: "#fdecea", fire: "#d9480f",
};
const SELECT_CLS =
  "w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-10 text-[13.5px] text-ink outline-none";

function chislo(v) {
  return Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}
function ru(iso) {
  return iso ? new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long" }) : "";
}

function Shkala({ x }) {
  const pct = Math.min(x.pct || 0, 100);
  const graf = x.ozhid != null && x.cel ? Math.min((x.ozhid / x.cel) * 100, 100) : null;
  const color = x.status === "pobeda" ? C.gold : x.status === "proval" ? C.danger : x.tip === "bez_prosr" ? C.leaf : C.fire;
  return (
    <div style={{ position: "relative", height: 22, borderRadius: 11, background: "#efece5", overflow: "visible" }}>
      <div style={{ height: "100%", width: `${pct}%`, borderRadius: 11, background: `linear-gradient(90deg, ${color}cc, ${color})`, transition: "width .6s" }} />
      {graf != null && x.status === "idet" && (
        <div title={`по графику сегодня: ${chislo(x.ozhid)} ${x.ed}`} style={{
          position: "absolute", top: -4, bottom: -4, left: `calc(${graf}% - 1px)`, width: 2, background: C.ink,
        }} />
      )}
      <span style={{ position: "absolute", right: 10, top: 2, fontSize: 12.5, fontWeight: 800, color: pct > 85 ? "#fff" : C.ink }}>{x.pct || 0}%</span>
    </div>
  );
}

function Kartochka({ x, onDel }) {
  const bez = x.tip === "bez_prosr";
  const pob = x.status === "pobeda";
  const prov = x.status === "proval";
  return (
    <div style={{
      background: pob ? C.goldSoft : prov ? C.dangerSoft : "#fff", border: `1.5px solid ${pob ? "#e0b94a" : prov ? "#f3c2bd" : C.line}`,
      borderRadius: 16, padding: 16, display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div className="flex items-start justify-between" style={{ gap: 10 }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={{ fontSize: 32, lineHeight: 1 }}>{x.emoji}</span>
          <div>
            <div style={{ fontWeight: 800, fontSize: 16, color: C.pine }}>{x.nazvanie}</div>
            <div style={{ fontSize: 12, color: C.muted }}>
              {ru(x.ot)} – {ru(x.do)}
              {x.status === "idet" && ` · осталось ${x.dney_ostalos} дн. (${x.rab_ostalos} раб.)`}
              {x.status === "skoro" && ` · старт через ${x.dney_do_starta} дн.`}
            </div>
          </div>
        </div>
        <button type="button" onClick={onDel} title="Удалить челлендж" style={{ color: C.muted, fontSize: 14 }}>🗑</button>
      </div>

      {!bez ? (
        <div className="flex items-baseline" style={{ gap: 8 }}>
          <span style={{ fontSize: 28, fontWeight: 900, color: C.ink }}>{chislo(x.fakt)}</span>
          <span style={{ fontSize: 15, color: C.muted }}>из {chislo(x.cel)} {x.ed}</span>
        </div>
      ) : (
        <div style={{ fontSize: 15, fontWeight: 700, color: prov ? C.danger : C.pine }}>
          {prov ? `💥 Сорвано сроков: ${x.fakt}` : `🛡 Сорвано сроков: 0 · прошло ${x.pct}% периода`}
        </div>
      )}
      <Shkala x={x} />
      {x.temp && <div style={{ fontSize: 13.5, fontWeight: 700, color: pob ? C.gold : prov ? C.danger : C.ink }}>{x.temp}</div>}

      {x.status === "idet" && !bez && (
        <div style={{ fontSize: 12.5, color: C.muted }}>
          Прогноз к финишу: <b style={{ color: x.prognoz >= x.cel ? C.leaf : C.danger }}>{chislo(x.prognoz)} {x.ed}</b>
          {x.nado_v_den > 0 && <> · чтобы взять, нужно <b>{chislo(x.nado_v_den)} {x.ed}</b> в рабочий день</>}
        </div>
      )}

      {bez && x.podrobno && (
        <div style={{ fontSize: 12.5 }}>
          {x.podrobno.sorvano?.length > 0 && (
            <div style={{ color: C.danger, marginBottom: 4 }}>
              Сорвано: {x.podrobno.sorvano.map((s) => `${s.delyanka} — ${s.chto.toLowerCase()} (${s.data.slice(0, 5)})`).join("; ")}
            </div>
          )}
          {x.podrobno.vperedi?.length > 0 ? (
            <>
              <div style={{ color: C.muted }}>Сроки впереди — не дай сорваться:</div>
              {x.podrobno.vperedi.map((s, i) => (
                <button key={i} type="button" onClick={() => openScreen("plots", { tab: "put" })} className="block" style={{ textAlign: "left" }}>
                  🎯 <b>{s.data.slice(0, 5)}</b> — {s.delyanka}: {s.chto.toLowerCase()}
                </button>
              ))}
            </>
          ) : !prov && <div style={{ color: C.muted }}>Сроков до конца периода больше нет.</div>}
          <div style={{ color: C.muted, fontSize: 11.5, marginTop: 4 }}>Считаются сроки заготовки, вывозки и акта, выпавшие на период.</div>
        </div>
      )}

      {x.podrobno?.spisok?.length > 0 && <div style={{ fontSize: 12.5, color: C.muted }}>Акты: {x.podrobno.spisok.join(", ")}</div>}

      {x.vklad?.length > 0 && (
        <div style={{ borderTop: `1px dashed ${C.line}`, paddingTop: 8 }}>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 4 }}>Больше всех вложились:</div>
          <div className="flex flex-wrap" style={{ gap: 6 }}>
            {x.vklad.map((v, i) => (
              <span key={v.kto} style={{ fontSize: 12.5, background: i === 0 ? C.goldSoft : "#f3f1ec", borderRadius: 999, padding: "3px 10px" }}>
                {["🥇", "🥈", "🥉"][i] || "•"} {v.kto} <b>{chislo(v.znach)}</b>
              </span>
            ))}
          </div>
        </div>
      )}
      {x.priz && (
        <div style={{ fontSize: 12.5, color: pob ? C.gold : C.muted, fontWeight: pob ? 800 : 400 }}>
          {pob ? "🏆 Звание получено: " : "🎁 Приз: звание "}«{x.priz}»
        </div>
      )}
    </div>
  );
}

function NovyyModal({ open, onClose, d, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (open) setF(null); }, [open]);

  const sozdat = async (body) => {
    setSaving(true);
    try {
      await api.post("/chellendzhi", body);
      toast.show({ tone: "success", title: "Челлендж запущен 🔥", description: body.nazvanie });
      onSaved();
      onClose();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не получилось", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const svoy = f || { tip: "kuby", nazvanie: "", cel: "", ot: d.shablony[0]?.ot, do: d.shablony[0]?.do, priz: "" };
  const set = (k, v) => setF({ ...svoy, [k]: v });

  return (
    <Modal open={open} onClose={onClose} title="🔥 Новый челлендж для команды" size="lg"
      footer={f && (
        <>
          <Button variant="secondary" onClick={() => setF(null)}>Назад к готовым</Button>
          <Button variant="primary" loading={saving} onClick={() => sozdat({ ...f, cel: Number(f.cel) || 0 })}>Запустить</Button>
        </>
      )}>
      {!f ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 13, color: C.muted }}>
            {d.shablony.length ? "Готовые цели на этот месяц. Число взято от прошлого месяца плюс 10%: чуть выше, чем было."
              : "Все готовые цели на этот месяц уже запущены 💪 Можно придумать свою."}
          </div>
          {d.shablony.map((s) => (
            <div key={s.tip} className="flex items-center justify-between" style={{ gap: 10, border: `1px solid ${C.line}`, borderRadius: 12, padding: "10px 12px" }}>
              <div>
                <div style={{ fontWeight: 800 }}>{s.emoji} {s.nazvanie}</div>
                <div style={{ fontSize: 12, color: C.muted }}>
                  {s.podskazka ? `${s.podskazka} · ` : ""}приз: «{s.priz}»
                </div>
              </div>
              <div className="flex" style={{ gap: 6 }}>
                <Button variant="secondary" size="sm" onClick={() => setF({ ...s })}>Изменить</Button>
                <Button variant="primary" size="sm" loading={saving} onClick={() => sozdat(s)}>Запустить</Button>
              </div>
            </div>
          ))}
          <button type="button" onClick={() => setF(svoy)} style={{ color: C.pine, fontWeight: 700, textDecoration: "underline", textAlign: "left" }}>
            ＋ Свой челлендж
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted font-medium">Что считаем</label>
            <select value={f.tip} onChange={(e) => set("tip", e.target.value)} className={SELECT_CLS}>
              {Object.entries(d.tipy).map(([k, t]) => <option key={k} value={k}>{t.emoji} {t.title}</option>)}
            </select>
          </div>
          <TextField label="Название" value={f.nazvanie} onChange={(e) => set("nazvanie", e.target.value)} placeholder="Например: Вывезти 500 м³ до конца месяца" />
          <div className="flex gap-3">
            {f.tip !== "bez_prosr" && (
              <TextField label={`Цель, ${d.tipy[f.tip].ed}`} type="number" value={f.cel} onChange={(e) => set("cel", e.target.value)} />
            )}
            <TextField label="С" type="date" value={f.ot || ""} onChange={(e) => set("ot", e.target.value)} />
            <TextField label="По" type="date" value={f.do || ""} onChange={(e) => set("do", e.target.value)} />
          </div>
          <TextField label="Звание за победу" value={f.priz || ""} onChange={(e) => set("priz", e.target.value)} placeholder="🚛 Короли вывозки" />
        </div>
      )}
    </Modal>
  );
}

export default function Chellendzhi() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [novyy, setNovyy] = useState(false);

  const load = useCallback(async () => {
    try {
      setD(await api.get("/chellendzhi"));
    } catch (e) {
      toast.show({ tone: "danger", title: "Челленджи не загрузились", description: e.message });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const udalit = async (x) => {
    if (!window.confirm(`Удалить челлендж «${x.nazvanie}»?`)) return;
    try {
      await api.delete(`/chellendzhi/${x.id}`);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалилось", description: e.message });
    }
  };

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Разжигаем костёр… 🔥</div>;

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="flex flex-wrap items-center justify-between" style={{
        gap: 12, background: `linear-gradient(120deg, ${C.pine}, #2d5e45)`, color: "#fff", borderRadius: 16, padding: "16px 18px",
      }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>🔥 Челленджи всей команды</div>
          <div style={{ fontSize: 13, color: "#bcefc5", marginTop: 2 }}>
            Одна шкала на всех, чёрная черта на ней — где должны быть по графику. Взяли цель, и команда получает звание. Побед {d.pobed} · провалов {d.provalov}
          </div>
        </div>
        <button type="button" onClick={() => setNovyy(true)} style={{
          background: "#fff", color: C.pine, fontWeight: 800, borderRadius: 10, padding: "8px 16px", fontSize: 14,
        }}>＋ Новый челлендж</button>
      </div>

      {d.aktivnye.length === 0 ? (
        <div style={{ padding: 30, textAlign: "center", color: C.muted, border: `1px dashed ${C.line}`, borderRadius: 14 }}>
          Сейчас нет ни одного челленджа. Нажми «＋ Новый челлендж», там есть готовые цели на месяц 🎯
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 14 }}>
          {d.aktivnye.map((x) => <Kartochka key={x.id} x={x} onDel={() => udalit(x)} />)}
        </div>
      )}

      {(d.zvaniya.length > 0 || d.proshlye.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 14 }}>
          <div style={{ background: C.goldSoft, border: "1px solid #f0dca6", borderRadius: 14, padding: 14 }}>
            <div style={{ fontWeight: 800, color: C.gold, marginBottom: 8 }}>🏛 Зал славы команды</div>
            {d.zvaniya.length === 0 ? <div style={{ fontSize: 13, color: C.muted }}>Званий пока нет — первая победа впереди.</div> : (
              d.zvaniya.map((z, i) => (
                <div key={i} style={{ fontSize: 14, padding: "4px 0" }}>
                  🏆 <b>{z.priz}</b> <span style={{ color: C.muted, fontSize: 12 }}>— за «{z.nazvanie}», {ru(z.do)}</span>
                </div>
              ))
            )}
          </div>
          <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 14, padding: 14 }}>
            <div style={{ fontWeight: 800, color: C.pine, marginBottom: 8 }}>📜 Прошлые челленджи</div>
            {d.proshlye.map((x) => (
              <div key={x.id} className="flex justify-between" style={{ fontSize: 13, padding: "4px 0", borderTop: `1px solid ${C.line}`, gap: 8 }}>
                <span>{x.status === "pobeda" ? "✅" : "❌"} {x.nazvanie}</span>
                <span style={{ color: x.status === "pobeda" ? C.leaf : C.danger, fontWeight: 700, whiteSpace: "nowrap" }}>
                  {x.tip === "bez_prosr" ? (x.status === "pobeda" ? "без срывов" : `сорвано ${x.fakt}`) : `${chislo(x.fakt)} / ${chislo(x.cel)}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <NovyyModal open={novyy} onClose={() => setNovyy(false)} d={d} onSaved={load} />
    </div>
  );
}
