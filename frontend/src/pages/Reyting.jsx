import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * «🏆 Рейтинг рабочих» (03.11.2026). Очки из табеля, нарядов (доля м³ по
 * табелю), выполненных задач плана и трелёвки; места с ничьими, сдвиг к
 * прошлому периоду, соперник впереди и кто догоняет, значки, звенья.
 * Сервер: backend/app/routers/reyting.py. Ничего не пишет.
 */

const C = {
  pine: "var(--color-pine)", leaf: "var(--c-green-2)", moss: "var(--color-mint-soft)", line: "var(--color-border)", muted: "var(--color-muted-2)", ink: "var(--color-ink)",
  gold: "var(--c-gold)", goldSoft: "var(--c-gold-soft)", danger: "var(--color-error)", sky: "var(--c-info-ink)", skySoft: "var(--c-info-soft-2)", wood: "#9a6a3a",
};
const PODIUM = [
  { h: 120, bg: "#f3c94a", medal: "🥇" },
  { h: 92, bg: "#d5d8dc", medal: "🥈" },
  { h: 72, bg: "#e0a76a", medal: "🥉" },
];
const RAZBIVKA = [["dni", "дни"], ["kuby", "м³"], ["zadachi", "задачи"], ["trelevka", "трелёвка"], ["smena", "смена"], ["universal", "универсал"]];
const RAZBIVKA_CVET = { dni: C.leaf, kuby: C.wood, zadachi: C.sky, trelevka: "#7a5a9a", smena: "#c06a2b", universal: C.gold };

function inicialy(fio) {
  const p = (fio || "").split(/\s+/);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase();
}
function korotko(fio) {
  const p = (fio || "").split(/\s+/);
  return p[0] + (p[1] ? ` ${p[1][0]}.` : "");
}
function ruDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function Avatar({ fio, size = 40, bg = C.pine }) {
  return (
    <span style={{
      width: size, height: size, borderRadius: size / 2, background: bg, color: "#fff", fontWeight: 800,
      display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: size * 0.36, flexShrink: 0,
    }}>{inicialy(fio)}</span>
  );
}

function Sdvig({ s }) {
  if (s == null) return <span style={{ color: C.muted, fontSize: 12 }} title="В прошлом периоде очков не было">new</span>;
  if (s === 0) return <span style={{ color: C.muted, fontSize: 12 }}>=</span>;
  return <span style={{ color: s > 0 ? C.leaf : C.danger, fontSize: 12, fontWeight: 800 }}>{s > 0 ? `▲${s}` : `▼${-s}`}</span>;
}

function Polosa({ r, max }) {
  return (
    <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: C.line, width: "100%" }}
      title={RAZBIVKA.filter(([k]) => r.ochki_po?.[k]).map(([k, l]) => `${l}: ${r.ochki_po[k]}`).join(" · ")}>
      {RAZBIVKA.map(([k]) => (r.ochki_po?.[k] ? (
        <span key={k} style={{ width: `${(r.ochki_po[k] / max) * 100}%`, background: RAZBIVKA_CVET[k] }} />
      ) : null))}
    </div>
  );
}

export default function Reyting() {
  const toast = useToast();
  const [period, setPeriod] = useState("mesyac");
  const [d, setD] = useState(null);
  const [vybran, setVybran] = useState(null);

  const load = useCallback(async () => {
    try {
      setD(await api.get("/reyting", { period }));
    } catch (e) {
      toast.show({ tone: "danger", title: "Рейтинг не загрузился", description: e.message });
    }
  }, [period]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Считаем очки… 🧮</div>;
  const r = d.reyting;
  const max = Math.max(1, ...r.map((x) => x.ochki));
  const top3 = r.filter((x) => x.mesto <= 3).slice(0, 3);
  const pr = d.pravila;

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 10 }}>
        <div style={{ fontSize: 14, color: C.muted, maxWidth: 820 }}>
          <b style={{ color: C.pine }}>🏆 Рейтинг рабочих</b> за {ruDate(d.ot)}–{ruDate(d.do)}. Очки: день в табеле +{pr.den},
          м³ по нарядам +{pr.m3} (кубы делянки за день делятся поровну на всех, кто по табелю работал там), задача из плана +{pr.zadacha},
          трелёвка +{pr.trelevka} за м³, из «Отчёта за смену»: уход/почва +{pr.ga} за га, населению +{pr.naseleniyu} за м³, ремонт +{pr.remont_chas} за час, {pr.universal_vidov}+ видов работ +{pr.universal}. Для азарта, а не для зарплаты 😉
        </div>
        <div className="flex" style={{ gap: 4, background: "var(--c-muted-bg)", padding: 3, borderRadius: 10 }}>
          {Object.entries(d.periody).map(([k, l]) => (
            <button key={k} type="button" onClick={() => setPeriod(k)} aria-pressed={period === k} style={{
              padding: "5px 12px", borderRadius: 8, fontSize: 13, fontWeight: 700,
              background: period === k ? "var(--color-surface)" : "transparent", color: period === k ? C.pine : C.muted,
              boxShadow: period === k ? "0 1px 2px rgba(0,0,0,.08)" : "none",
            }}>{l}</button>
          ))}
        </div>
      </div>

      {r.length === 0 ? (
        <div style={{ padding: 30, textAlign: "center", color: C.muted, border: `1px dashed ${C.line}`, borderRadius: 14 }}>
          За этот период очков ни у кого нет. Заполни табель — и гонка начнётся 🏁
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 320px", gap: 16, alignItems: "start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
            <div style={{
              display: "flex", justifyContent: "center", alignItems: "flex-end", gap: 14, padding: "18px 12px 0",
              background: `linear-gradient(180deg, ${C.moss}, var(--color-surface))`, borderRadius: 16, border: `1px solid ${C.line}`,
            }}>
              {[1, 0, 2].map((i) => {
                const x = top3[i];
                if (!x) return <div key={i} style={{ width: 150 }} />;
                const p = PODIUM[Math.min(x.mesto - 1, 2)];
                return (
                  <div key={x.sotrudnik_id} style={{ width: 150, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 26 }}>{p.medal}</span>
                    <Avatar fio={x.fio} size={52} />
                    <div style={{ fontWeight: 800, textAlign: "center", fontSize: 14 }}>{korotko(x.fio)}</div>
                    <div style={{ fontSize: 13, color: C.gold, fontWeight: 800 }}>{x.ochki} очк.</div>
                    <div style={{ width: "100%", height: p.h, background: p.bg, borderRadius: "10px 10px 0 0", display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: 8, fontSize: 28, fontWeight: 900, color: "rgba(0,0,0,.35)" }}>
                      {x.mesto}
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ background: "var(--color-surface)", border: `1px solid ${C.line}`, borderRadius: 14, overflow: "hidden" }}>
              {r.map((x) => {
                const open = vybran === x.sotrudnik_id;
                return (
                  <div key={x.sotrudnik_id} style={{ borderTop: `1px solid ${C.line}` }}>
                    <button type="button" onClick={() => setVybran(open ? null : x.sotrudnik_id)} style={{
                      width: "100%", display: "grid", gridTemplateColumns: "40px 44px minmax(0, 1fr) 120px 70px", gap: 10,
                      alignItems: "center", padding: "10px 14px", textAlign: "left", background: open ? "var(--c-muted-bg)" : "var(--color-surface)",
                    }}>
                      <span style={{ fontWeight: 900, fontSize: 18, color: x.mesto <= 3 ? C.gold : C.muted, textAlign: "center" }}>{x.mesto}</span>
                      <Avatar fio={x.fio} />
                      <span style={{ minWidth: 0 }}>
                        <span style={{ fontWeight: 700 }}>{x.fio} </span>
                        {x.znachki.map((z) => <span key={z.z} title={z.title} style={{ marginLeft: 2 }}>{z.z}</span>)}
                        <span style={{ display: "block", fontSize: 12, color: C.muted }}>
                          {x.dolzhnost || "—"} · {x.dni} дн. · {x.kuby} м³{x.zadachi ? ` · задач ${x.zadachi}` : ""}{x.trelevka ? ` · трелёвка ${x.trelevka} м³` : ""}
                        </span>
                      </span>
                      <span><Polosa r={x} max={max} /></span>
                      <span style={{ textAlign: "right" }}>
                        <span style={{ display: "block", fontWeight: 900, color: C.pine }}>{x.ochki}</span>
                        <Sdvig s={x.sdvig} />
                      </span>
                    </button>
                    {open && (
                      <div style={{ padding: "0 14px 12px 108px", fontSize: 13, color: C.ink, display: "flex", flexDirection: "column", gap: 4 }}>
                        {x.sopernik && <div>🎯 Впереди <b>{x.sopernik.fio}</b> — догнать {x.sopernik.otryv} очк. (это ~{Math.ceil(x.sopernik.otryv / pr.den)} раб. дн.)</div>}
                        {!x.sopernik && <div>👑 Впереди никого. Держи корону!</div>}
                        {x.ravnye?.length > 0 && <div>🤝 Ноздря в ноздрю с: {x.ravnye.join(", ")}</div>}
                        {x.dogonyaet && <div>👀 Догоняет <b>{x.dogonyaet.fio}</b> — отрыв {x.dogonyaet.otryv} очк.</div>}
                        <div style={{ color: C.muted }}>
                          Из чего очки: {RAZBIVKA.filter(([k]) => x.ochki_po?.[k]).map(([k, l]) => `${l} ${x.ochki_po[k]}`).join(" · ")}
                          {x.bylo_mesto ? ` · в прошлом периоде было ${x.bylo_mesto}-е место` : ""}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {d.v_zapase.length > 0 && (
              <div style={{ fontSize: 13, color: C.muted }}>🪑 В запасе (без очков за период): {d.v_zapase.map((x) => korotko(x.fio)).join(", ")}</div>
            )}
            {d.kuby_bez_lyudey > 0 && (
              <div style={{ fontSize: 13, color: C.muted }}>
                🪵 {d.kuby_bez_lyudey} м³ по нарядам без хозяина: в этот день по табелю на делянке никто не числится. Отметь в табеле место работы — кубы найдут своих.
              </div>
            )}
          </div>

          <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ background: "var(--color-surface)", border: `1px solid ${C.line}`, borderRadius: 14, padding: 12 }}>
              <div style={{ fontWeight: 800, color: C.pine, marginBottom: 4 }}>⚔️ Битва звеньев</div>
              <div style={{ fontSize: 12, color: C.muted, marginBottom: 8 }}>среднее очков на человека — большое звено не выигрывает числом</div>
              {d.zvenya.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>Звеньев нет — заведи их в «Перекличке» (Табель).</div>}
              {d.zvenya.map((z, i) => (
                <div key={z.id} style={{ padding: "6px 0", borderTop: i ? `1px solid ${C.line}` : "none" }}>
                  <div className="flex justify-between" style={{ fontSize: 14 }}>
                    <span style={{ fontWeight: 700 }}>{["🥇", "🥈", "🥉"][i] || "▫️"} {z.emoji} {z.nazvanie}</span>
                    <span style={{ fontWeight: 800, color: C.pine }}>{z.srednee}</span>
                  </div>
                  <div style={{ fontSize: 12, color: C.muted }}>{z.chlenov} чел. · всего {z.ochki} очк. · {z.kuby} м³</div>
                </div>
              ))}
            </div>
            <div style={{ background: C.goldSoft, border: "1px solid var(--c-gold-line)", borderRadius: 14, padding: 12, fontSize: 13, lineHeight: 1.6 }}>
              <div style={{ fontWeight: 800, color: C.gold, marginBottom: 4 }}>Значки</div>
              <div>👑 лидер периода</div>
              <div>🪵 больше всех кубов</div>
              <div>🚜 король трелёвки</div>
              <div>✅ больше всех задач из плана</div>
              <div>🧰 больше всех видов работ</div>
              <div>🛡 железный — без прогулов, 90%+ рабочих дней</div>
              <div>🚀 рывок — поднялся на 2+ места</div>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
