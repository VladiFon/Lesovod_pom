import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * «Огород уходов» — игровой вид экрана «Лесокультуры» (просьба Влада
 * 03.11.2026): где уход нужен, где осветление, где не трогать — на сезон.
 * Нормы: 1-й год 2 ухода, 2-й — 2, 3-й — 3; осветление после.
 * «✅ Сделано» пишет обычную запись в журнал участка, «📅 В план» — обычную
 * задачу «Плана работ» (уйдёт мастеру на телефон). Сервер:
 * backend/app/routers/uhody_igra.py.
 */

const MONO = "'JetBrains Mono', monospace";
const C = {
  pine: "var(--color-pine)", leaf: "var(--c-green-2)", moss: "var(--color-mint-soft)", line: "var(--color-border)", muted: "var(--color-muted-2)", ink: "var(--color-ink)",
  gold: "var(--c-gold)", goldSoft: "var(--c-gold-soft)", danger: "var(--color-error)", dangerSoft: "var(--c-error-soft-2)", sky: "var(--c-info-ink)", skySoft: "var(--c-info-soft-2)",
};
const KOLONKI = [
  { vid: "uhod", title: "🔥 Жаждут ухода", note: "уходов меньше нормы", bg: C.dangerSoft, border: "var(--c-error-line)" },
  { vid: "osvetlenie", title: "🪓 Ждут осветления", note: "уходы позади, осветления ещё не было", bg: C.goldSoft, border: "var(--c-gold-line)" },
  { vid: "uhod_ok", title: "✅ Норма выполнена", note: "в этом сезоне больше не надо", bg: C.moss, border: "var(--color-mint)" },
  { vid: "pokoy", title: "🌲 Не трогать", note: "переведены или уже осветлены", bg: "var(--color-surface-alt)", border: C.line },
];
const POKAZ = 25;
const SHUTKI = {
  uhod: ["Сорняк не дремлет 🌿", "Культуры просят пить 💧", "Ещё чуть-чуть — и норма"],
  osvetlenie: ["Берёзка душит сосну — спасай!", "Пора дать света 🌞"],
};

function ruDate(d = new Date()) {
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
}
function isoDate(d = new Date()) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function korotko(fio) {
  const p = (fio || "").split(/\s+/);
  return p[0] + (p[1] ? ` ${p[1][0]}.` : "");
}

function Hp({ sdelano, norma }) {
  if (!norma) return null;
  return (
    <span className="flex" style={{ gap: 3 }} title={`Уходов в сезоне: ${sdelano} из ${norma}`}>
      {Array.from({ length: norma }).map((_, i) => (
        <span key={i} style={{ width: 16, height: 8, borderRadius: 2, background: i < sdelano ? C.leaf : C.line }} />
      ))}
    </span>
  );
}

function PlanForma({ u, sotrudniki, sezon, onDone, onCancel }) {
  const toast = useToast();
  const segodnya = new Date();
  const start = sezon > segodnya.getFullYear() ? `${sezon}-05-15` : isoDate(segodnya);
  const [kto, setKto] = useState(sotrudniki[0]?.id || "");
  const [data, setData] = useState(start);
  const [busy, setBusy] = useState(false);
  const chto = u.vid === "osvetlenie" ? "Осветление" : "Агротехнический уход";
  const save = async () => {
    if (!kto || !data) return;
    setBusy(true);
    try {
      await api.post("/work-plan/", {
        sotrudnik_id: Number(kto), data, zadacha: `${chto}: ${u.label}`, lesokultury_uchastok_id: u.id,
      });
      toast.show({ tone: "success", title: "В плане 📅", description: `${chto} · ${u.label} — задача ушла в «План работ»` });
      onDone();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не получилось поставить в план", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center" style={{ gap: 6, padding: 8, borderRadius: 8, background: "var(--color-surface)", border: `1px dashed ${C.gold}` }}>
      <select
        id={`plan-kto-${u.id}`}
        value={kto}
        onChange={(e) => setKto(e.target.value)}
        style={{ height: 28, border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 12.5, maxWidth: 170 }}
      >
        {sotrudniki.map((s) => <option key={s.id} value={s.id}>{s.fio}</option>)}
      </select>
      <input
        id={`plan-data-${u.id}`}
        type="date"
        value={data}
        onChange={(e) => setData(e.target.value)}
        style={{ height: 28, border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 12.5, padding: "0 6px" }}
      />
      <button type="button" disabled={busy || !kto} onClick={save}
        style={{ height: 28, padding: "0 10px", border: 0, borderRadius: 6, background: C.gold, color: "#fff", fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>
        В план
      </button>
      <button type="button" onClick={onCancel} style={{ border: 0, background: "transparent", color: C.muted, cursor: "pointer", fontSize: 12.5 }}>
        отмена
      </button>
    </div>
  );
}

function Karta({ u, sotrudniki, sezon, idetSezon, onChanged }) {
  const toast = useToast();
  const [forma, setForma] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pop, setPop] = useState(false);
  const mozhnoSdelat = u.vid === "uhod" || u.vid === "osvetlenie";
  const sdelano = async () => {
    setBusy(true);
    try {
      const tip = u.vid === "osvetlenie" ? "Осветление" : "Агротехнический уход";
      await api.post(`/lesokultury/uchastki/${u.id}/meropriyatiya`, undefined, { tip, data: ruDate(), primechaniya: "Отмечено в «Огороде уходов»" });
      setPop(true);
      setTimeout(() => { setPop(false); onChanged(); }, 700);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не записалось в журнал", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ position: "relative", background: "var(--color-surface)", border: `1px solid ${C.line}`, borderRadius: 10, padding: "9px 10px", display: "flex", flexDirection: "column", gap: 5 }}>
      <div className="flex items-start justify-between" style={{ gap: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 13.5, color: C.ink }}>{u.label}</span>
        <span style={{ fontFamily: MONO, fontSize: 11, color: C.muted, whiteSpace: "nowrap" }}>{u.ploshad ? `${u.ploshad} га` : ""}</span>
      </div>
      <div className="flex items-center justify-between flex-wrap" style={{ gap: 6, fontSize: 12, color: C.muted }}>
        <span>{u.god_kultur}-й год · культуры {u.god_sozdaniya}{u.status === "переведён" ? " · переведены" : ""}</span>
        <Hp sdelano={u.sdelano} norma={u.norma} />
      </div>
      {(u.posledniy_uhod || u.osvetlenie) && (
        <div style={{ fontSize: 11.5, color: C.muted }}>
          {u.posledniy_uhod && <>последний уход: {u.posledniy_uhod}</>}
          {u.osvetlenie && <> · осветление: {u.osvetlenie}</>}
        </div>
      )}
      {u.plan.length > 0 && (
        <div style={{ fontSize: 11.5, color: C.sky }}>
          📅 {u.plan.map((p) => `${p.data.slice(8, 10)}.${p.data.slice(5, 7)} · ${korotko(p.kto)}`).join(", ")}
        </div>
      )}
      {mozhnoSdelat && !forma && (
        <div className="flex flex-wrap" style={{ gap: 6, marginTop: 2 }}>
          {idetSezon || u.vid === "osvetlenie" ? (
            <button type="button" disabled={busy} onClick={sdelano}
              title="Записать в журнал участка сегодняшней датой"
              style={{ fontSize: 12, fontWeight: 700, padding: "3px 9px", borderRadius: 7, border: `1px solid ${C.pine}`, background: C.pine, color: "#fff", cursor: "pointer" }}>
              ✅ Сделано
            </button>
          ) : null}
          <button type="button" onClick={() => setForma(true)}
            style={{ fontSize: 12, fontWeight: 700, padding: "3px 9px", borderRadius: 7, border: `1px solid ${C.gold}`, background: "var(--color-surface)", color: "#7a5600", cursor: "pointer" }}>
            📅 В план
          </button>
        </div>
      )}
      {forma && <PlanForma u={u} sotrudniki={sotrudniki} sezon={sezon} onCancel={() => setForma(false)} onDone={() => { setForma(false); onChanged(); }} />}
      {pop && <span className="og-pop" style={{ position: "absolute", right: 10, top: -6, fontFamily: MONO, fontWeight: 800, color: C.gold }}>+10 XP</span>}
    </div>
  );
}

export default function UhodyIgra() {
  const [sezon, setSezon] = useState(0);
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [lesn, setLesn] = useState("");
  const [skolko, setSkolko] = useState({});
  const [pokoyOpen, setPokoyOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/uhody-igra", sezon ? { sezon } : undefined);
      setD(r);
      if (!sezon) setSezon(r.sezon);
      setErr("");
    } catch (e) {
      setErr(e.message);
    }
  }, [sezon]);
  useEffect(() => { load(); }, [load]);

  const lesnichestva = useMemo(() => [...new Set((d?.uchastki || []).map((u) => u.lesnichestvo).filter(Boolean))].sort(), [d]);
  const spisok = useMemo(() => {
    const s = q.trim().toLowerCase().replace(/\//g, " ");
    return (d?.uchastki || []).filter((u) => {
      if (lesn && u.lesnichestvo !== lesn) return false;
      if (!s) return true;
      const parts = s.split(/\s+/);
      if (parts.length === 2 && /^\d+$/.test(parts[0])) {
        return u.label.toLowerCase().startsWith(`кв.${parts[0]} выд.${parts[1]}`);
      }
      return parts.every((p) => `${u.label} ${u.lesnichestvo} ${u.god_sozdaniya}`.toLowerCase().includes(p));
    });
  }, [d, q, lesn]);

  if (!d) return <div className="p-8 text-muted text-[13px]">{err ? `Огород не загрузился: ${err}` : "Обхожу участки…"}</div>;

  const it = d.itogo;
  const pct = it.uhodov_nado ? Math.round((it.uhodov_sdelano / it.uhodov_nado) * 100) : 100;
  const god = new Date().getFullYear();

  return (
    <div className="flex flex-col" style={{ padding: 18, gap: 14 }}>
      <style>{`
        @keyframes ogUp { from { opacity: 1; transform: translateY(0) } to { opacity: 0; transform: translateY(-20px) } }
        .og-pop { animation: ogUp .9s ease-out forwards }
        @media (prefers-reduced-motion: reduce) { .og-pop { animation: none; opacity: 0 } }
      `}</style>

      <div style={{ fontSize: 12.5, color: C.muted }}>
        <b style={{ color: C.pine }}>🌱 Огород уходов</b> — где уход нужен, где не надо. Нормы: 1-й год {d.normy["1"]}, 2-й — {d.normy["2"]}, 3-й — {d.normy["3"]} агроухода; осветление на {d.osvetlenie[0]}–{d.osvetlenie[1]}-й год.
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ fontWeight: 800, color: C.pine, fontSize: 15 }}>Сезон</span>
        {[god, god + 1].map((g) => (
          <button key={g} type="button" onClick={() => setSezon(g)} aria-pressed={sezon === g}
            style={{
              height: 30, padding: "0 12px", borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: "pointer",
              border: `1px solid ${sezon === g ? C.pine : C.line}`, background: sezon === g ? C.pine : "var(--color-surface)", color: sezon === g ? "#fff" : C.ink,
            }}>
            {g}{g === god + 1 ? " (план)" : ""}
          </button>
        ))}
        {!d.idet_sezon && sezon === god && <span style={{ fontSize: 12, color: C.muted }}>сезон уходов закончился — здесь итог, кто недополучил</span>}
        <span style={{ flex: 1 }} />
        <input id="ogorod-poisk" value={q} onChange={(e) => setQ(e.target.value)} placeholder="8/3, сосна, 2024…"
          style={{ height: 30, width: 180, border: `1px solid ${C.line}`, borderRadius: 8, padding: "0 10px", fontSize: 13 }} />
        {lesnichestva.length > 1 && (
          <select id="ogorod-lesn" value={lesn} onChange={(e) => setLesn(e.target.value)}
            style={{ height: 30, border: `1px solid ${C.line}`, borderRadius: 8, fontSize: 13 }}>
            <option value="">все лесничества</option>
            {lesnichestva.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        )}
      </div>

      {/* урожай сезона */}
      <div className="flex flex-wrap items-center" style={{ gap: 12 }}>
        <div style={{ flex: "1 1 260px" }}>
          <div className="flex justify-between" style={{ fontSize: 12.5, color: C.muted, marginBottom: 4 }}>
            <span>Урожай сезона: уходов {it.uhodov_sdelano} из {it.uhodov_nado}</span>
            <span style={{ fontFamily: MONO }}>{pct}%</span>
          </div>
          <div style={{ height: 12, borderRadius: 7, background: C.line, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${pct}%`, background: pct >= 100 ? C.leaf : C.gold, transition: "width .4s" }} />
          </div>
        </div>
        {[
          ["🔥", `${it.uchastkov_uhod} уч. · ${it.ga_uhod} га`, "ждут ухода"],
          ["🪓", `${it.uchastkov_osvetlenie} уч. · ${it.ga_osvetlenie} га`, "ждут осветления"],
          ["📅", `${it.v_plane} уч.`, "уже в плане"],
        ].map(([e, v, l]) => (
          <span key={l} style={{ padding: "6px 10px", borderRadius: 9, background: "var(--color-surface)", border: `1px solid ${C.line}`, fontSize: 12.5 }}>
            {e} <b>{v}</b> <span style={{ color: C.muted }}>{l}</span>
          </span>
        ))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 12, alignItems: "start" }}>
        {KOLONKI.map((k) => {
          const vse = spisok.filter((u) => u.vid === k.vid);
          if (k.vid === "pokoy" && !pokoyOpen) {
            return (
              <div key={k.vid} style={{ background: k.bg, border: `1px solid ${k.border}`, borderRadius: 12, padding: 10 }}>
                <div style={{ fontWeight: 800, fontSize: 13.5, color: C.ink }}>{k.title} · {vse.length}</div>
                <div style={{ fontSize: 12, color: C.muted, margin: "2px 0 8px" }}>{k.note}</div>
                <button type="button" onClick={() => setPokoyOpen(true)}
                  style={{ fontSize: 12.5, border: `1px solid ${C.line}`, background: "var(--color-surface)", borderRadius: 7, padding: "4px 10px", cursor: "pointer" }}>
                  Показать
                </button>
              </div>
            );
          }
          const n = skolko[k.vid] || POKAZ;
          const shutka = SHUTKI[k.vid]?.[(d.sezon + vse.length) % (SHUTKI[k.vid]?.length || 1)];
          return (
            <div key={k.vid} style={{ background: k.bg, border: `1px solid ${k.border}`, borderRadius: 12, padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
              <div>
                <div style={{ fontWeight: 800, fontSize: 13.5, color: C.ink }}>{k.title} · {vse.length}</div>
                <div style={{ fontSize: 12, color: C.muted }}>{k.note}{shutka && vse.length ? ` · ${shutka}` : ""}</div>
              </div>
              {vse.length === 0 && <div style={{ fontSize: 12.5, color: C.muted, padding: "6px 0" }}>Пусто 🎉</div>}
              {vse.slice(0, n).map((u) => (
                <Karta key={u.id} u={u} sotrudniki={d.sotrudniki} sezon={d.sezon} idetSezon={d.idet_sezon} onChanged={load} />
              ))}
              {vse.length > n && (
                <button type="button" onClick={() => setSkolko({ ...skolko, [k.vid]: n + POKAZ })}
                  style={{ fontSize: 12.5, border: `1px solid ${C.line}`, background: "var(--color-surface)", borderRadius: 7, padding: "5px 10px", cursor: "pointer" }}>
                  Ещё {Math.min(POKAZ, vse.length - n)} из {vse.length - n}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
