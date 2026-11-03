import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";
import { useToast } from "../components/Toast.jsx";

/**
 * Режим «Квесты» (просьба Влада 03.11.2026) — та же работа, что в «Ждёт
 * меня», но в виде квестов дня с опытом, уровнем и серией дней. Обычный
 * интерфейс не меняется: экран открывается вкладкой (обычно во второй
 * панели, кнопка «🎯 Квесты» в шапке). Квест закрывается сам, когда дело
 * сделано в обычном экране. Свои дела — с галочкой. Сервер:
 * backend/app/routers/kvesty.py.
 */

const POLL_MS = 60000;
const MONO = "'JetBrains Mono', monospace";
const C = {
  pine: "#1a4331", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6",
  danger: "#ba1a1a", dangerSoft: "#fdecea", warn: "#8a5a00", info: "#2c5d8a",
};
const VID = {
  boss: { label: "Боссы дня", note: "просрочено — бей первым", border: C.danger, bg: C.dangerSoft },
  main: { label: "Основные квесты", note: "сроки на этой неделе", border: C.warn, bg: "#fff" },
  side: { label: "Побочные", note: "мелочь, но копится", border: C.info, bg: "#fff" },
};
const DNI = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function Ring({ pct, n }) {
  return (
    <div
      style={{
        width: 70, height: 70, borderRadius: "50%", flexShrink: 0, position: "relative",
        background: `conic-gradient(${C.gold} ${pct}%, ${C.line} 0)`, display: "grid", placeItems: "center",
      }}
      title={`${pct}% до следующего уровня`}
    >
      <div style={{ position: "absolute", inset: 7, borderRadius: "50%", background: "#fcf9f2" }} />
      <span style={{ position: "relative", fontSize: 22, fontWeight: 800, color: C.pine }}>{n}</span>
    </div>
  );
}

function Pop({ text }) {
  return (
    <span
      className="kv-pop"
      style={{ position: "absolute", right: 14, top: -4, fontFamily: MONO, fontWeight: 700, fontSize: 13, color: C.gold, pointerEvents: "none" }}
    >
      {text}
    </span>
  );
}

function Check({ done, onClick, label }) {
  // Без onClick — просто значок (квест «Ждёт меня» закрывается сам; кнопка
  // внутри кнопки-строки была бы невалидной).
  const Tag = onClick ? "button" : "span";
  return (
    <Tag
      {...(onClick ? { type: "button", onClick } : { "aria-hidden": true })}
      aria-label={onClick ? label : undefined}
      title={label}
      className="kv-check"
      style={{
        width: 22, height: 22, borderRadius: 6, flexShrink: 0, border: `2px solid ${C.pine}`,
        background: done ? C.pine : "transparent", color: "#fff", fontSize: 13, lineHeight: 1,
        display: "grid", placeItems: "center", cursor: onClick ? "pointer" : "default",
      }}
    >
      {done ? "✓" : ""}
    </Tag>
  );
}

function Kvest({ q, pop }) {
  const v = VID[q.vid];
  const part = !q.done && q.count0 > 1 && q.count_now < q.count0;
  return (
    <button
      type="button"
      onClick={() => openScreen(q.screen, q.params || {})}
      className="w-full text-left hover:!shadow-md transition-shadow"
      style={{
        position: "relative", display: "flex", alignItems: "center", gap: 12, padding: "10px 13px",
        borderRadius: 10, border: `1px solid ${q.vid === "boss" ? v.border : C.line}`,
        borderLeft: `4px solid ${v.border}`, background: q.done || q.proval ? "#f6f3ec" : v.bg,
        opacity: q.done || q.proval ? 0.6 : 1, cursor: "pointer",
      }}
      title="Открыть, где это делается"
    >
      <Check done={q.done} label={q.done ? "Выполнено" : "Закроется сам, когда сделаешь"} />
      <span className="min-w-0 flex-1">
        <span className="block" style={{ fontWeight: 700, fontSize: 14, color: C.ink, textDecoration: q.done ? "line-through" : "none" }}>
          {q.title}
          {q.count0 > 1 && <span style={{ fontWeight: 500, color: C.muted }}> · {part ? `${q.count0 - q.count_now} из ${q.count0}` : `×${q.count0}`}</span>}
        </span>
        <span className="block" style={{ fontSize: 12.5, color: C.muted, lineHeight: 1.35, marginTop: 2 }}>
          {q.proval ? "Не успели — превратился в босса. Бывает 🤷" : `${q.podpis}${q.hint ? ` · ${q.hint}` : ""}`}
        </span>
      </span>
      <span style={{ fontFamily: MONO, fontSize: 12, color: q.proval ? C.muted : C.gold, whiteSpace: "nowrap" }}>
        {q.proval ? "0 XP" : `+${q.xp} XP`}
      </span>
      {pop && <Pop text={`+${q.xp} XP`} />}
    </button>
  );
}

function Sect({ vid, items, pops }) {
  if (!items.length) return null;
  const v = VID[vid];
  return (
    <div className="flex flex-col" style={{ gap: 8 }}>
      <div style={{ fontSize: 13, color: C.muted, display: "flex", gap: 8, alignItems: "baseline" }}>
        <span style={{ fontWeight: 700, color: C.ink }}>{v.label}</span>
        <span style={{ fontFamily: MONO, fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".06em" }}>{v.note}</span>
      </div>
      {items.map((q) => <Kvest key={q.id} q={q} pop={pops.has(q.id)} />)}
    </div>
  );
}

export default function Kvesty() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [novyy, setNovyy] = useState("");
  const [pops, setPops] = useState(new Set());
  const [pravila, setPravila] = useState(false);
  const prev = useRef(null);

  const load = useCallback(() => {
    api.get("/kvesty").then((d) => {
      // Квесты, которые закрылись с прошлой загрузки, — вспышка «+XP».
      const was = prev.current;
      if (was) {
        const done0 = new Set([...was.kvesty, ...was.svoi.map((s) => ({ ...s, id: `s:${s.id}` }))].filter((q) => q.done).map((q) => q.id));
        const fresh = [...d.kvesty.filter((q) => q.done && !done0.has(q.id)).map((q) => q.id),
          ...d.svoi.filter((s) => s.done && !done0.has(`s:${s.id}`)).map((s) => `s:${s.id}`)];
        if (fresh.length) {
          setPops(new Set(fresh));
          setTimeout(() => setPops(new Set()), 1000);
        }
        if (d.uroven.n > was.uroven.n) {
          toast.show({ tone: "success", title: `Новый уровень: ${d.uroven.n}!`, description: `Теперь ты «${d.uroven.zvanie}» 🌲` });
        }
      }
      prev.current = d;
      setData(d);
      setErr("");
    }).catch((e) => setErr(e.message));
  }, [toast]);

  useEffect(() => {
    load();
    const t = setInterval(load, POLL_MS);
    window.addEventListener("focus", load);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", load);
    };
  }, [load]);

  const dobavit = async (e) => {
    e.preventDefault();
    const title = novyy.trim();
    if (!title) return;
    try {
      await api.post("/kvesty/svoi", { title });
      setNovyy("");
      load();
    } catch (ex) {
      toast.show({ tone: "danger", title: "Не добавился квест", description: ex.message });
    }
  };
  const otmetit = async (s) => {
    try {
      await api.post(`/kvesty/svoi/${s.id}/done`, null, { done: !s.done });
      load();
    } catch (ex) {
      toast.show({ tone: "danger", title: "Не получилось отметить", description: ex.message });
    }
  };
  const udalit = async (s) => {
    try {
      await api.delete(`/kvesty/svoi/${s.id}`);
      load();
    } catch (ex) {
      toast.show({ tone: "danger", title: "Не удалилось", description: ex.message });
    }
  };

  if (!data) {
    return <div className="p-8 text-muted text-[13px]">{err ? `Квесты не загрузились: ${err}` : "Загружаю квесты…"}</div>;
  }

  const u = data.uroven;
  const pct = Math.round((u.xp_v_urovne / u.nado) * 100);
  const po = (vid) => data.kvesty.filter((q) => q.vid === vid);
  const otkryto = data.kvesty.filter((q) => !q.done && !q.proval).length + data.svoi.filter((s) => !s.done).length;

  return (
    <div className="flex flex-col" style={{ padding: 18, gap: 18, maxWidth: 820 }}>
      <style>{`
        @keyframes kvUp { from { opacity: 1; transform: translateY(0) } to { opacity: 0; transform: translateY(-22px) } }
        .kv-pop { animation: kvUp .95s ease-out forwards }
        @media (prefers-reduced-motion: reduce) { .kv-pop { animation: none; opacity: 0 } }
        .kv-check:focus-visible { outline: 2px solid ${C.gold}; outline-offset: 2px }
      `}</style>

      {/* уровень, опыт, серия */}
      <div className="flex flex-wrap items-center" style={{ gap: 16 }}>
        <Ring pct={pct} n={u.n} />
        <div className="min-w-0" style={{ flex: "1 1 220px" }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: C.pine }}>{u.zvanie}</div>
          <div style={{ fontSize: 12.5, color: C.muted }}>
            Уровень {u.n} · до следующего {u.nado - u.xp_v_urovne} XP
          </div>
          <div style={{ height: 8, borderRadius: 5, background: C.line, marginTop: 8, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${pct}%`, background: C.gold, transition: "width .5s" }} />
          </div>
          <div style={{ fontFamily: MONO, fontSize: 11.5, color: C.muted, marginTop: 4 }}>
            {data.xp.toLocaleString("ru-RU")} XP всего · сегодня +{data.segodnya_xp}
            {data.segodnya_za_chto.length > 0 && (
              <span> ({data.segodnya_za_chto.map((z) => `${z.title.toLowerCase()} ×${z.n}`).join(", ")})</span>
            )}
          </div>
        </div>
        <div style={{ textAlign: "center", padding: "8px 12px", borderRadius: 10, background: C.goldSoft }} title="Рабочих дней подряд с делом: закрыт квест или набрано 50 XP. Выходные серию не рвут.">
          <div style={{ fontSize: 22, fontWeight: 800, color: C.gold, lineHeight: 1.1 }}>🔥 {data.seriya}</div>
          <div style={{ fontSize: 11, color: C.muted }}>дней подряд</div>
          <div className="flex justify-center" style={{ gap: 4, marginTop: 6 }}>
            {data.nedelya.map((d) => (
              <span
                key={d.den}
                title={`${DNI[new Date(d.den).getDay()]} ${d.den.slice(8)}.${d.den.slice(5, 7)}: +${d.xp} XP`}
                style={{
                  width: 10, height: 10, borderRadius: 3,
                  background: d.zachten ? C.gold : d.vyhodnoy ? "transparent" : C.line,
                  border: d.vyhodnoy && !d.zachten ? `1px dashed ${C.line}` : "none",
                }}
              />
            ))}
          </div>
        </div>
      </div>

      <div style={{ fontSize: 13, color: C.muted, fontStyle: "italic" }}>🌲 {data.shutka}</div>

      {/* квесты дня */}
      {data.kvesty.length === 0 && data.svoi.length === 0 && (
        <div style={{ padding: "18px 14px", borderRadius: 10, border: `1px dashed ${C.line}`, textAlign: "center", color: C.muted, fontSize: 13.5 }}>
          Квестов на сегодня нет — «Ждёт меня» пуст. Лес спокоен, можно и чаю 🍵
        </div>
      )}
      {otkryto === 0 && (data.kvesty.length > 0 || data.svoi.length > 0) && (
        <div style={{ padding: "10px 14px", borderRadius: 10, background: C.moss, color: C.pine, fontSize: 13.5, fontWeight: 600 }}>
          Все квесты дня закрыты. Красавчик 💪
        </div>
      )}
      <Sect vid="boss" items={po("boss")} pops={pops} />
      <Sect vid="main" items={po("main")} pops={pops} />
      <Sect vid="side" items={po("side")} pops={pops} />

      {/* свои квесты */}
      <div className="flex flex-col" style={{ gap: 8 }}>
        <div style={{ fontSize: 13, color: C.muted, display: "flex", gap: 8, alignItems: "baseline" }}>
          <span style={{ fontWeight: 700, color: C.ink }}>Свои квесты</span>
          <span style={{ fontFamily: MONO, fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".06em" }}>
            +{data.pravila.svoi} XP, до {data.pravila.svoi_limit} в день
          </span>
        </div>
        <form onSubmit={dobavit} className="flex" style={{ gap: 8 }}>
          <input
            id="kvest-novyy"
            value={novyy}
            onChange={(e) => setNovyy(e.target.value)}
            placeholder="Например: позвонить в лесхоз насчёт билета"
            maxLength={200}
            className="flex-1 min-w-0"
            style={{ height: 34, border: `1px solid ${C.line}`, borderRadius: 8, padding: "0 10px", fontSize: 13.5, background: "#fff" }}
          />
          <button
            type="submit"
            disabled={!novyy.trim()}
            style={{ height: 34, padding: "0 14px", borderRadius: 8, border: 0, background: C.pine, color: "#fff", fontWeight: 600, fontSize: 13, cursor: "pointer", opacity: novyy.trim() ? 1 : 0.5 }}
          >
            ＋ Квест
          </button>
        </form>
        {data.svoi.map((s) => (
          <div
            key={s.id}
            className="group"
            style={{
              position: "relative", display: "flex", alignItems: "center", gap: 12, padding: "9px 13px", borderRadius: 10,
              border: `1px solid ${C.line}`, borderLeft: `4px solid ${C.pine}`, background: s.done ? "#f6f3ec" : "#fff", opacity: s.done ? 0.6 : 1,
            }}
          >
            <Check done={s.done} onClick={() => otmetit(s)} label={s.done ? "Снять отметку" : "Сделано"} />
            <span className="min-w-0 flex-1" style={{ fontSize: 14, fontWeight: 600, color: C.ink, textDecoration: s.done ? "line-through" : "none", overflowWrap: "anywhere" }}>
              {s.title}
            </span>
            <span style={{ fontFamily: MONO, fontSize: 12, color: C.gold }}>+{s.xp} XP</span>
            <button
              type="button"
              onClick={() => udalit(s)}
              title="Удалить квест"
              aria-label="Удалить квест"
              className="hover:!text-[#ba1a1a]"
              style={{ border: 0, background: "transparent", color: "#8a938c", fontSize: 15, cursor: "pointer" }}
            >
              ×
            </button>
            {pops.has(`s:${s.id}`) && <Pop text={`+${s.xp} XP`} />}
          </div>
        ))}
      </div>

      {/* лут и ачивки */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
        <div style={{ border: `1px dashed ${C.line}`, borderRadius: 10, padding: "11px 13px" }}>
          <div style={{ fontFamily: MONO, fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".06em", color: C.muted }}>Лут за неделю</div>
          {data.lut.length === 0 ? (
            <div style={{ fontSize: 13, color: C.muted, marginTop: 6 }}>Пока пусто. Сформируй документ — он выпадет сюда.</div>
          ) : (
            <div className="flex flex-col" style={{ gap: 4, marginTop: 6 }}>
              {data.lut.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => openScreen("documents")}
                  className="flex justify-between text-left hover:!text-[#1a4331]"
                  style={{ gap: 8, border: 0, background: "transparent", padding: 0, fontSize: 13, color: C.ink, cursor: "pointer" }}
                >
                  <span className="min-w-0 truncate">📜 {l.file_name}</span>
                  <span style={{ fontFamily: MONO, fontSize: 11, color: C.muted, whiteSpace: "nowrap" }}>
                    {l.created_at.slice(8, 10)}.{l.created_at.slice(5, 7)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div style={{ border: `1px dashed ${C.line}`, borderRadius: 10, padding: "11px 13px" }}>
          <div style={{ fontFamily: MONO, fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".06em", color: C.muted }}>
            Ачивки · {data.achivki.filter((a) => a.est).length} из {data.achivki.length}
          </div>
          <div className="flex flex-wrap" style={{ gap: 5, marginTop: 6 }}>
            {data.achivki.map((a) => (
              <span
                key={a.kod}
                title={a.hint}
                style={{
                  fontSize: 12, padding: "3px 9px", borderRadius: 999,
                  background: a.est ? C.moss : "transparent", color: a.est ? C.pine : "#8a938c",
                  border: a.est ? "1px solid #bcefc5" : `1px dashed ${C.line}`,
                }}
              >
                {a.est ? "🏅 " : ""}{a.title}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* правила */}
      <div>
        <button
          type="button"
          onClick={() => setPravila(!pravila)}
          aria-expanded={pravila}
          style={{ border: 0, background: "transparent", padding: 0, fontSize: 12.5, color: C.pine, fontWeight: 600, cursor: "pointer" }}
        >
          {pravila ? "▾" : "▸"} Откуда берётся опыт
        </button>
        {pravila && (
          <div style={{ fontSize: 12.5, color: C.muted, marginTop: 8, lineHeight: 1.55 }}>
            Квест «Ждёт меня» закрывается сам, когда дело пропало из списка: босс +{data.pravila.kvest.danger},
            основной +{data.pravila.kvest.warning}, побочный +{data.pravila.kvest.info}. Если квест не сделали и он стал боссом — 0.
            <br />
            За работу в обычных экранах (считается и задним числом):{" "}
            {data.pravila.rabota.map((r) => `${r.title.toLowerCase()} +${r.xp}`).join(", ")}.
            Наряды и документы — тому, кто их внёс; остальное общее.
            <br />
            Серия: рабочий день засчитан, если закрыт хоть один квест или набрано {data.pravila.seriya_min_xp} XP. Выходные серию не рвут.
          </div>
        )}
      </div>
    </div>
  );
}
