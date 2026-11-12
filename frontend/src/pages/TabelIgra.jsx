import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * «Перекличка» — игровой ввод табеля (просьба Влада 03.11.2026). Показывается
 * в экране «Табель» вместо обычного ввода, когда включён игровой вид
 * (переключатель в шапке / Настройках, src/vid.jsx); пишет в тот же
 * tabel_zapis через POST /api/tabel/day.
 *
 * Место НЕ берётся из распределения бригад (у Влада бригада работает на
 * разных делянках, а пара-тройка людей всё время вместе и делает разное).
 * Вместо этого: выделяешь людей (или звено одним кликом) → «где» и «что» →
 * «Отметить». Плюс «Как в прошлый раз», частые места, подсказки звеньев.
 * Сервер: backend/app/routers/tabel_igra.py.
 */

const MONO = "'JetBrains Mono', monospace";
const C = {
  pine: "var(--color-pine)", moss: "var(--color-mint-soft)", line: "var(--color-border)", muted: "var(--color-muted-2)", ink: "var(--color-ink)",
  gold: "var(--c-gold)", goldSoft: "var(--c-gold-soft)", danger: "var(--color-error)", dangerSoft: "var(--c-error-soft-2)", sky: "var(--c-info-ink)",
};
const STATUSY = [
  { v: "работал", label: "Работал", emoji: "🪓", bg: C.moss, fg: C.pine },
  { v: "выходной", label: "Выходной", emoji: "🛌", bg: "var(--color-hover)", fg: C.muted },
  { v: "больничный", label: "Больничный", emoji: "🤒", bg: C.dangerSoft, fg: C.danger },
  { v: "отпуск", label: "Отпуск", emoji: "🏖", bg: "var(--c-info-soft-2)", fg: C.sky },
  { v: "ремонт", label: "Ремонт", emoji: "🔧", bg: C.goldSoft, fg: C.gold },
  { v: "командировка", label: "Командировка", emoji: "🧳", bg: "var(--c-info-soft-2)", fg: C.sky },
  { v: "не работал", label: "Не работал", emoji: "✖", bg: "var(--color-hover)", fg: C.muted },
];
// На работе — можно указать место и вид работы.
const NA_RABOTE = ["работал", "ремонт", "командировка"];
const ST = Object.fromEntries(STATUSY.map((s) => [s.v, s]));
const MOBILE_TO_TABEL = { "работаю": "работал", "не работаю": "не работал", "больничный": "больничный" };
const XP_ZA_STROKU = 2;
const AVA = ["var(--c-green-2)", "var(--c-info-ink)", "#9a6200", "#7a3f8a", "#a0442c", "#2f7a78", "#5a6b2c", "#8a3f5a"];
const ZVENO_EMOJI = ["🪓", "🚜", "🌲", "🌱", "🐺", "🦫", "🐻", "🦉"];

function rolEmoji(d) {
  const s = (d || "").toLowerCase();
  if (s.includes("вальщ") || s.includes("лесоруб")) return "🪓";
  if (s.includes("тракт")) return "🚜";
  if (s.includes("водит")) return "🚛";
  if (s.includes("мастер") || s.includes("лесничий")) return "🧭";
  if (s.includes("лесник")) return "🌲";
  if (s.includes("бригад")) return "⭐";
  return "👷";
}
function inicialy(fio) {
  const p = (fio || "?").split(/\s+/);
  return ((p[0] || "")[0] || "") + ((p[1] || "")[0] || "");
}
function korotko(fio) {
  return (fio || "").split(/\s+/)[0];
}
function sdvig(iso, n) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
function segodnya() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function krasivo(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" });
}

function Ava({ r, size = 34 }) {
  return (
    <span
      style={{
        width: size, height: size, borderRadius: 9, flexShrink: 0, display: "grid", placeItems: "center",
        background: AVA[r.sotrudnik_id % AVA.length], color: "#fff", fontWeight: 800, fontSize: size * 0.36,
      }}
    >
      {inicialy(r.fio).toUpperCase()}
    </span>
  );
}

function Btn({ children, onClick, tone = "plain", disabled, title, style }) {
  const t = {
    plain: { border: `1px solid ${C.line}`, background: "var(--color-surface)", color: "var(--color-muted)" },
    gold: { border: 0, background: C.gold, color: "#fff" },
    pine: { border: 0, background: C.pine, color: "#fff" },
  }[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        height: 32, padding: "0 12px", borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: disabled ? "default" : "pointer",
        whiteSpace: "nowrap", opacity: disabled ? 0.45 : 1, ...t, ...style,
      }}
    >
      {children}
    </button>
  );
}

/** Панель «миссии» для выделенных людей: статус, где, что. */
function Missiya({ den, vybrany, lyudi, onPrimenit, onZveno, onSbros, onSteret }) {
  const toast = useToast();
  const [status, setStatus] = useState("работал");
  const [mesto, setMesto] = useState(null); // {delyanka_item_id|lesokultury_uchastok_id, mesto}
  const [vid, setVid] = useState(null); // {id, nazvanie}
  const [q, setQ] = useState("");
  const [nayd, setNayd] = useState([]);
  const [noviyVid, setNoviyVid] = useState("");
  const [zvenoNaz, setZvenoNaz] = useState(null);

  // Одно и то же «в прошлый раз» у всех выделенных — место и/или работу
  // подставляем сразу; разное — пусто, выберешь сам.
  useEffect(() => {
    const pr = vybrany.map((id) => lyudi.find((l) => l.sotrudnik_id === id)?.proshloe);
    const rab = pr.every((x) => x && NA_RABOTE.includes(x.status));
    const p = pr[0];
    const odnoMesto = rab && p.mesto && pr.every((x) => x.mesto === p.mesto);
    const odinVid = rab && p.vid_raboty_id && pr.every((x) => x.vid_raboty_id === p.vid_raboty_id);
    setMesto(odnoMesto ? { delyanka_item_id: p.delyanka_item_id, lesokultury_uchastok_id: p.lesokultury_uchastok_id, uhody_proba_id: p.uhody_proba_id, mesto: p.mesto } : null);
    setVid(odinVid ? { id: p.vid_raboty_id, nazvanie: p.vid_raboty } : null);
  }, [vybrany.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const s = q.trim();
    if (s.length < 1) {
      setNayd([]);
      return undefined;
    }
    const t = setTimeout(async () => {
      try {
        const [d, l, pr] = await Promise.all([
          api.get("/tabel/delyanki", { search: s, limit: 8 }),
          api.get("/tabel/lesokultury-uchastki", { search: s }),
          api.get("/tabel/uhody-proby", { search: s }).catch(() => []),
        ]);
        setNayd([
          ...d.map((i) => ({
            delyanka_item_id: i.item_id, lesokultury_uchastok_id: null,
            mesto: `кв.${i.kvartal || "—"} выд.${i.vydel || "—"}`,
            pod: [i.lesoseka_nomer ? `лесосека ${i.lesoseka_nomer}` : null, i.nazvanie, i.zagotovitel ? `рубит ${i.zagotovitel}` : null].filter(Boolean).join(" · "),
          })),
          ...pr.slice(0, 6).map((p) => ({
            delyanka_item_id: null, lesokultury_uchastok_id: null, uhody_proba_id: p.id,
            mesto: `✂️ рубки ухода кв.${p.kvartal || "—"} выд.${p.vydel || "—"}`,
            pod: [p.zakryta ? "выполнена" : p.sdelano_ga ? `в работе ${p.sdelano_ga} га` : "заложена", p.lesnichestvo].filter(Boolean).join(" · "),
          })),
          ...l.slice(0, 6).map((u) => ({
            delyanka_item_id: null, lesokultury_uchastok_id: u.id,
            mesto: `🌱 кв.${u.kvartal || "—"} выд.${u.vydel || "—"}${u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}`,
            pod: [u.god_sozdaniya ? `культуры ${u.god_sozdaniya}` : null, u.lesnichestvo].filter(Boolean).join(" · "),
          })),
        ]);
      } catch {
        setNayd([]);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const dobavitVid = async () => {
    const n = noviyVid.trim();
    if (!n) return;
    try {
      const r = await api.post("/tabel/vidy-rabot", { nazvanie: n });
      setVid({ id: r.id, nazvanie: r.nazvanie });
      setNoviyVid("");
    } catch (e) {
      toast.show({ tone: "danger", title: "Вид работы не добавился", description: e.message });
    }
  };

  const imena = vybrany.map((id) => korotko(lyudi.find((l) => l.sotrudnik_id === id)?.fio)).join(", ");
  const chip = (on) => ({
    fontSize: 12.5, fontWeight: 600, padding: "5px 10px", borderRadius: 999, cursor: "pointer", textAlign: "left",
    border: `1px solid ${on ? C.pine : C.line}`, background: on ? C.pine : "var(--color-surface)", color: on ? "#fff" : C.ink,
  });

  return (
    <div
      style={{
        position: "sticky", top: 0, zIndex: 5, background: "#fffdf7", border: `2px solid ${C.gold}`, borderRadius: 14,
        padding: 14, display: "flex", flexDirection: "column", gap: 10, boxShadow: "0 10px 28px rgba(26,67,49,.14)",
      }}
    >
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <span style={{ fontWeight: 800, color: C.pine, fontSize: 14.5 }}>🎯 Миссия для {vybrany.length}:</span>
        <span className="min-w-0" style={{ fontSize: 13, color: C.muted, flex: "1 1 160px" }}>{imena}</span>
        <Btn onClick={onSbros}>Снять выделение</Btn>
      </div>

      <div className="flex flex-wrap" style={{ gap: 6 }}>
        {STATUSY.map((s) => (
          <button key={s.v} type="button" onClick={() => setStatus(s.v)} style={chip(status === s.v)}>
            {s.emoji} {s.label}
          </button>
        ))}
      </div>

      {NA_RABOTE.includes(status) && (
        <>
          <div style={{ fontSize: 12, color: C.muted, fontFamily: MONO, textTransform: "uppercase", letterSpacing: ".06em" }}>Где</div>
          {den.chastye.length > 0 && (
            <div className="flex flex-wrap" style={{ gap: 6 }}>
              {den.chastye.map((c, i) => {
                const on = mesto && mesto.mesto === c.mesto && (!c.vid_raboty_id || vid?.id === c.vid_raboty_id);
                return (
                  <button
                    key={i}
                    type="button"
                    title={`За 30 дней ставили ${c.raz} раз`}
                    onClick={() => {
                      setMesto({ delyanka_item_id: c.delyanka_item_id, lesokultury_uchastok_id: c.lesokultury_uchastok_id, uhody_proba_id: c.uhody_proba_id, mesto: c.mesto });
                      if (c.vid_raboty_id) setVid({ id: c.vid_raboty_id, nazvanie: c.vid_raboty });
                    }}
                    style={chip(on)}
                  >
                    📍 {c.mesto}{c.vid_raboty ? ` · ${c.vid_raboty}` : ""}
                  </button>
                );
              })}
            </div>
          )}
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <input
              id="perekl-mesto"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Найти: 71/2, № лесосеки, название, культуры…"
              style={{ flex: "1 1 220px", minWidth: 0, height: 32, border: `1px solid ${C.line}`, borderRadius: 8, padding: "0 10px", fontSize: 13 }}
            />
            {mesto && (
              <span style={{ fontSize: 13, fontWeight: 700, color: C.pine }}>
                📍 {mesto.mesto}{" "}
                <button type="button" onClick={() => setMesto(null)} aria-label="Убрать место" style={{ border: 0, background: "transparent", color: C.muted, cursor: "pointer" }}>×</button>
              </span>
            )}
          </div>
          {nayd.length > 0 && (
            <div className="flex flex-col" style={{ gap: 2, maxHeight: 200, overflowY: "auto", border: `1px solid ${C.line}`, borderRadius: 8, background: "var(--color-surface)" }}>
              {nayd.map((n, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => { setMesto(n); setQ(""); setNayd([]); }}
                  className="text-left hover:!bg-[var(--color-hover)]"
                  style={{ border: 0, background: "transparent", padding: "6px 10px", cursor: "pointer", fontSize: 13 }}
                >
                  <b>{n.mesto}</b> <span style={{ color: C.muted, fontSize: 12 }}>{n.pod}</span>
                </button>
              ))}
            </div>
          )}

          <div style={{ fontSize: 12, color: C.muted, fontFamily: MONO, textTransform: "uppercase", letterSpacing: ".06em" }}>Что делали</div>
          <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
            {den.vidy_rabot.map((v) => (
              <button key={v.id} type="button" onClick={() => setVid(vid?.id === v.id ? null : v)} style={chip(vid?.id === v.id)}>
                {v.nazvanie}
              </button>
            ))}
            <input
              id="perekl-vid"
              value={noviyVid}
              onChange={(e) => setNoviyVid(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && dobavitVid()}
              placeholder="＋ новый вид работы"
              style={{ width: 170, height: 30, border: `1px dashed ${C.line}`, borderRadius: 999, padding: "0 10px", fontSize: 12.5 }}
            />
          </div>
        </>
      )}

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        {vybrany.some((id) => lyudi.find((l) => l.sotrudnik_id === id)?.zapis_id) && (
          <Btn onClick={onSteret} title="Убрать отметку у выделенных — как будто их ещё не отмечали">🧽 Стереть отметку</Btn>
        )}
        <Btn tone="gold" onClick={() => onPrimenit({ status, mesto: NA_RABOTE.includes(status) ? mesto : null, vid: NA_RABOTE.includes(status) ? vid : null })}>
          ✅ Отметить {vybrany.length > 1 ? `всех ${vybrany.length}` : ""}
        </Btn>
        {status === "работал" && !mesto && <span style={{ fontSize: 12, color: C.muted }}>Место можно не указывать, но с ним табель полезнее.</span>}
        <span style={{ flex: 1 }} />
        {vybrany.length > 1 && (zvenoNaz === null ? (
          <Btn onClick={() => setZvenoNaz(vybrany.map((id) => korotko(lyudi.find((l) => l.sotrudnik_id === id)?.fio)).join(" + "))}>
            💾 Сделать звеном
          </Btn>
        ) : (
          <span className="flex items-center" style={{ gap: 6 }}>
            <input
              id="perekl-zveno"
              value={zvenoNaz}
              onChange={(e) => setZvenoNaz(e.target.value)}
              style={{ width: 190, height: 30, border: `1px solid ${C.line}`, borderRadius: 8, padding: "0 8px", fontSize: 13 }}
            />
            <Btn tone="pine" onClick={() => { onZveno(zvenoNaz); setZvenoNaz(null); }} disabled={!zvenoNaz.trim()}>Сохранить</Btn>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function TabelIgra() {
  const toast = useToast();
  const [data, setData] = useState(segodnya());
  const [den, setDen] = useState(null);
  const [err, setErr] = useState("");
  const [vybrany, setVybrany] = useState([]);
  const [xp, setXp] = useState(0);
  const [pop, setPop] = useState(null);
  const [zanyat, setZanyat] = useState(false);
  const [otmena, setOtmena] = useState(null); // {text, vernut: [entries], ubrat: [ids]}
  const otmenaTimer = useRef(null);
  const bylPolnyy = useRef(false);

  const load = useCallback(async (d = data) => {
    try {
      const r = await api.get("/tabel-igra/den", { data: d });
      setDen(r);
      setErr("");
      return r;
    } catch (e) {
      setErr(e.message);
      return null;
    }
  }, [data]);

  useEffect(() => {
    setDen(null);
    setVybrany([]);
    bylPolnyy.current = false;
    load(data).then((r) => {
      if (r) bylPolnyy.current = r.lyudi.length > 0 && r.lyudi.every((l) => l.zapis_id);
    });
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const lyudi = den?.lyudi || [];
  const otmecheno = lyudi.filter((l) => l.zapis_id).length;
  const vsego = lyudi.length;
  const pct = vsego ? Math.round((otmecheno / vsego) * 100) : 0;

  // Снимок «как было» у тех, кого сейчас поменяем — для кнопки «↩ Отменить».
  const snimok = (ids, text) => {
    const bylo = ids.map((id) => lyudi.find((l) => l.sotrudnik_id === id)).filter(Boolean);
    return {
      text,
      vernut: bylo.filter((l) => l.zapis_id).map((l) => ({
        sotrudnik_id: l.sotrudnik_id, status: l.status, delyanka_item_id: l.delyanka_item_id || null,
        lesokultury_uchastok_id: l.lesokultury_uchastok_id || null, uhody_proba_id: l.uhody_proba_id || null,
        vid_raboty_id: l.vid_raboty_id || null,
        kommentariy: l.kommentariy || "",
      })),
      ubrat: bylo.filter((l) => !l.zapis_id).map((l) => l.sotrudnik_id),
    };
  };
  const pokazatOtmenu = (o) => {
    clearTimeout(otmenaTimer.current);
    setOtmena(o);
    otmenaTimer.current = setTimeout(() => setOtmena(null), 15000);
  };
  const otmenit = async () => {
    const o = otmena;
    if (!o) return;
    setOtmena(null);
    setZanyat(true);
    try {
      if (o.ubrat.length) await api.post("/tabel-igra/steret", { data, sotrudnik_ids: o.ubrat });
      if (o.vernut.length) await api.post("/tabel/day", { data, entries: o.vernut });
      await load(data);
      toast.show({ tone: "success", title: "Отменено ↩", description: o.text });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не отменилось", description: e.message });
    } finally {
      setZanyat(false);
    }
  };
  const steret = async (ids, vesDen = false) => {
    const o = snimok(vesDen ? lyudi.map((l) => l.sotrudnik_id) : ids, vesDen ? "день очищен" : `стёрто: ${ids.length}`);
    setZanyat(true);
    try {
      await api.post("/tabel-igra/steret", vesDen ? { data, ves_den: true } : { data, sotrudnik_ids: ids });
      await load(data);
      setVybrany([]);
      pokazatOtmenu(o);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не стёрлось", description: e.message });
    } finally {
      setZanyat(false);
    }
  };
  const ochistitDen = () => {
    if (window.confirm(`Стереть ВСЕ отметки за ${krasivo(data)} (${otmecheno} чел.)? Можно будет отменить в течение 15 секунд.`)) steret([], true);
  };

  const sohranit = async (entries, otmenaText) => {
    if (!entries.length) return;
    const o = snimok(entries.map((e) => e.sotrudnik_id), otmenaText || `отмечено: ${entries.length}`);
    setZanyat(true);
    try {
      const novyh = entries.filter((e) => !lyudi.find((l) => l.sotrudnik_id === e.sotrudnik_id)?.zapis_id).length;
      await api.post("/tabel/day", { data, entries });
      const r = await load(data);
      pokazatOtmenu(o);
      if (novyh) {
        setXp((x) => x + novyh * XP_ZA_STROKU);
        setPop(`+${novyh * XP_ZA_STROKU} XP`);
        setTimeout(() => setPop(null), 1000);
      }
      if (r && !bylPolnyy.current && r.lyudi.length && r.lyudi.every((l) => l.zapis_id)) {
        bylPolnyy.current = true;
        toast.show({ tone: "success", title: "Отряд отмечен! 🎉", description: `Табель за ${krasivo(data)} закрыт. Серия: ${r.seriya} 🔥` });
      }
    } catch (e) {
      toast.show({ tone: "danger", title: "Табель не сохранился", description: e.message });
    } finally {
      setZanyat(false);
    }
  };

  const zapis = (l, { status, mesto, vid }) => ({
    sotrudnik_id: l.sotrudnik_id,
    status,
    delyanka_item_id: mesto?.delyanka_item_id || null,
    lesokultury_uchastok_id: mesto?.lesokultury_uchastok_id || null,
    uhody_proba_id: mesto?.uhody_proba_id || null,
    vid_raboty_id: vid?.id || null,
    kommentariy: l.kommentariy || "",
  });

  const primenit = async (m) => {
    const ent = vybrany.map((id) => lyudi.find((l) => l.sotrudnik_id === id)).filter(Boolean).map((l) => zapis(l, m));
    await sohranit(ent);
    setVybrany([]);
  };

  const pustye = lyudi.filter((l) => !l.zapis_id);
  // «Выходной» и «не работал» — разовые, их не переносим; работа,
  // больничный и отпуск обычно тянутся несколько дней.
  const PERENOSIM = ["работал", "больничный", "отпуск", "ремонт", "командировка"];
  const kakRanshe = pustye.filter((l) => l.proshloe && PERENOSIM.includes(l.proshloe.status));
  const sTelefona = pustye.filter((l) => MOBILE_TO_TABEL[l.mobile_status]);

  const kakVProshlyy = () =>
    sohranit(kakRanshe.map((l) => {
      const p = l.proshloe;
      const rab = NA_RABOTE.includes(p.status);
      return {
        sotrudnik_id: l.sotrudnik_id, status: p.status,
        delyanka_item_id: rab ? p.delyanka_item_id : null, lesokultury_uchastok_id: rab ? p.lesokultury_uchastok_id : null,
        uhody_proba_id: rab ? p.uhody_proba_id : null,
        vid_raboty_id: rab ? p.vid_raboty_id : null, kommentariy: "",
      };
    }));
  const izTelefona = () =>
    sohranit(sTelefona.map((l) => ({
      sotrudnik_id: l.sotrudnik_id, status: MOBILE_TO_TABEL[l.mobile_status],
      delyanka_item_id: null, lesokultury_uchastok_id: null, vid_raboty_id: null, kommentariy: "",
    })));

  const toggle = (id) => setVybrany((v) => (v.includes(id) ? v.filter((x) => x !== id) : [...v, id]));

  const sozdatZveno = async (nazvanie, sostav = vybrany) => {
    try {
      const n = den.zvenya.length;
      await api.post("/tabel-igra/zvenya", { nazvanie, emoji: ZVENO_EMOJI[n % ZVENO_EMOJI.length], sostav });
      await load(data);
      toast.show({ tone: "success", title: `Звено «${nazvanie}» сохранено`, description: "Теперь отмечается одним кликом" });
    } catch (e) {
      toast.show({ tone: "danger", title: "Звено не сохранилось", description: e.message });
    }
  };
  const udalitZveno = async (z) => {
    try {
      await api.delete(`/tabel-igra/zvenya/${z.id}`);
      await load(data);
    } catch (e) {
      toast.show({ tone: "danger", title: "Звено не удалилось", description: e.message });
    }
  };

  const poId = useMemo(() => Object.fromEntries(lyudi.map((l) => [l.sotrudnik_id, l])), [lyudi]);

  if (!den) {
    return <div className="p-8 text-muted text-[13px]">{err ? `Перекличка не загрузилась: ${err}` : "Строю отряд…"}</div>;
  }

  return (
    <div className="flex flex-col" style={{ padding: 18, gap: 14 }}>
      <style>{`
        @keyframes pkUp { from { opacity: 1; transform: translateY(0) } to { opacity: 0; transform: translateY(-20px) } }
        .pk-pop { animation: pkUp .95s ease-out forwards }
        @media (prefers-reduced-motion: reduce) { .pk-pop { animation: none; opacity: 0 } }
        .pk-card:focus-visible { outline: 2px solid ${C.gold}; outline-offset: 2px }
      `}</style>

      <div style={{ fontSize: 12.5, color: C.muted }}>
        <b style={{ color: C.pine }}>🎮 Перекличка</b> — игровой вид табеля. Обычный ввод: «Обычный» в переключателе сверху.
      </div>

      {/* шапка: дата, прогресс, серия */}
      <div className="flex flex-wrap items-center" style={{ gap: 10 }}>
        <Btn onClick={() => setData(sdvig(data, -1))} title="Предыдущий день">◀</Btn>
        <input
          id="perekl-data"
          type="date"
          value={data}
          onChange={(e) => e.target.value && setData(e.target.value)}
          style={{ height: 32, border: `1px solid ${C.line}`, borderRadius: 8, padding: "0 8px", fontSize: 13 }}
        />
        <Btn onClick={() => setData(sdvig(data, 1))} title="Следующий день">▶</Btn>
        {data !== segodnya() && <Btn onClick={() => setData(segodnya())}>Сегодня</Btn>}
        {otmecheno > 0 && <Btn onClick={ochistitDen} disabled={zanyat} title="Стереть все отметки за этот день">🧹 Очистить день</Btn>}
        <span style={{ fontWeight: 800, color: C.pine, fontSize: 15 }}>{krasivo(data)}</span>
        <span style={{ flex: 1 }} />
        <span
          title="Рабочих дней подряд, когда табель заполнен на всех. Выходные серию не рвут."
          style={{ background: C.goldSoft, color: C.gold, fontWeight: 800, borderRadius: 9, padding: "5px 10px", fontSize: 13 }}
        >
          🔥 {den.seriya} {den.seriya === 1 ? "день" : "дн."} полного табеля
        </span>
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 10, position: "relative" }}>
        <div style={{ flex: "1 1 240px", height: 12, borderRadius: 7, background: C.line, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${pct}%`, background: pct === 100 ? "var(--c-green-2)" : C.gold, transition: "width .4s" }} />
        </div>
        <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.muted }}>
          {otmecheno === vsego && vsego ? "Отряд отмечен ✅" : `Отмечено ${otmecheno} из ${vsego}`}
          {xp > 0 && <span style={{ color: C.gold }}> · +{xp} XP</span>}
        </span>
        {pop && <span className="pk-pop" style={{ position: "absolute", right: 0, top: -14, fontFamily: MONO, fontWeight: 800, color: C.gold }}>{pop}</span>}
      </div>

      {otmena && (
        <div className="flex items-center" style={{ gap: 10, background: C.pine, color: "#fff", borderRadius: 10, padding: "8px 12px", fontSize: 13 }}>
          <span style={{ flex: 1 }}>Готово — {otmena.text}. Ошибся?</span>
          <button type="button" onClick={otmenit} disabled={zanyat} style={{ background: "var(--color-surface)", color: C.pine, borderRadius: 8, padding: "4px 12px", fontWeight: 800 }}>↩ Отменить</button>
        </div>
      )}

      {/* быстрые комбо */}
      {pustye.length > 0 && (
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <Btn tone="gold" onClick={kakVProshlyy} disabled={!kakRanshe.length || zanyat} title="Каждому, кто ещё не отмечен, — его последняя запись: то же место, та же работа (больничный и отпуск тоже продолжаются; выходной не переносится)">
            ⚡ Как в прошлый раз ({kakRanshe.length})
          </Btn>
          {sTelefona.length > 0 && (
            <Btn onClick={izTelefona} disabled={zanyat} title="Статус из отметок в приложении">
              📱 Как отметились с телефона ({sTelefona.length})
            </Btn>
          )}
          <Btn onClick={() => setVybrany(pustye.map((l) => l.sotrudnik_id))}>Выделить неотмеченных ({pustye.length})</Btn>
        </div>
      )}

      {/* звенья */}
      <div className="flex flex-col" style={{ gap: 8 }}>
        <div style={{ fontSize: 13, color: C.muted }}>
          <b style={{ color: C.ink }}>Звенья</b> — кто обычно работает вместе. Клик — выделить всех, потом «где» и «что».
        </div>
        <div className="flex flex-wrap" style={{ gap: 8 }}>
          {den.zvenya.map((z) => {
            const chleny = z.sostav.map((id) => poId[id]).filter(Boolean);
            const gotovo = chleny.length > 0 && chleny.every((l) => l.zapis_id);
            const on = chleny.length > 0 && chleny.every((l) => vybrany.includes(l.sotrudnik_id));
            return (
              <div
                key={z.id}
                style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "7px 8px 7px 10px", borderRadius: 12,
                  border: `2px solid ${on ? C.gold : gotovo ? "var(--color-mint)" : C.line}`, background: gotovo ? C.moss : "var(--color-surface)",
                }}
              >
                <button
                  type="button"
                  onClick={() => setVybrany(on ? [] : chleny.map((l) => l.sotrudnik_id))}
                  className="flex items-center"
                  style={{ gap: 8, border: 0, background: "transparent", cursor: "pointer", padding: 0 }}
                  title={chleny.map((l) => l.fio).join(", ")}
                >
                  <span style={{ fontSize: 18 }}>{z.emoji}</span>
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: C.ink }}>{z.nazvanie}</span>
                  <span className="flex" style={{ marginLeft: 2 }}>
                    {chleny.map((l, i) => (
                      <span key={l.sotrudnik_id} style={{ marginLeft: i ? -6 : 0, border: "2px solid var(--color-surface)", borderRadius: 9 }}>
                        <Ava r={l} size={22} />
                      </span>
                    ))}
                  </span>
                  {gotovo && <span style={{ fontSize: 12, color: C.pine, fontWeight: 700 }}>✓</span>}
                </button>
                <button
                  type="button"
                  onClick={() => udalitZveno(z)}
                  title="Распустить звено"
                  aria-label={`Распустить звено ${z.nazvanie}`}
                  className="hover:!text-[var(--color-error)]"
                  style={{ border: 0, background: "transparent", color: "var(--color-disabled)", cursor: "pointer", fontSize: 14 }}
                >
                  ×
                </button>
              </div>
            );
          })}
          {den.zvenya.length === 0 && (
            <span style={{ fontSize: 12.5, color: C.muted }}>Пока нет. Выдели 2–3 человек и нажми «💾 Сделать звеном».</span>
          )}
        </div>
        {den.podskazka.length > 0 && (
          <div className="flex flex-wrap" style={{ gap: 6 }}>
            {den.podskazka.map((p) => {
              const chleny = p.sostav.map((id) => poId[id]).filter(Boolean);
              if (chleny.length < 2) return null;
              const imena = chleny.map((l) => korotko(l.fio));
              const spisok = imena.length === 2 ? imena.join(" и ") : `${imena.slice(0, -1).join(", ")} и ${imena[imena.length - 1]}`;
              return (
                <button
                  key={p.sostav.join("-")}
                  type="button"
                  onClick={() => sozdatZveno(imena.join(" + "), p.sostav)}
                  style={{ fontSize: 12.5, padding: "5px 10px", borderRadius: 999, border: `1px dashed ${C.gold}`, background: C.goldSoft, color: "#7a5600", cursor: "pointer" }}
                >
                  🤝 {spisok} работали вместе {p.dney} дн. — сделать звеном?
                </button>
              );
            })}
          </div>
        )}
      </div>

      {vybrany.length > 0 && (
        <Missiya den={den} vybrany={vybrany} lyudi={lyudi} onPrimenit={primenit} onZveno={(n) => sozdatZveno(n)} onSbros={() => setVybrany([])}
          onSteret={() => steret(vybrany.filter((id) => lyudi.find((l) => l.sotrudnik_id === id)?.zapis_id))} />
      )}

      {/* отряд */}
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 10 }}>
        {lyudi.map((l) => {
          const s = ST[l.status];
          const on = vybrany.includes(l.sotrudnik_id);
          return (
            <button
              key={l.sotrudnik_id}
              type="button"
              onClick={() => toggle(l.sotrudnik_id)}
              aria-pressed={on}
              className="pk-card text-left"
              style={{
                display: "flex", flexDirection: "column", gap: 7, padding: 11, borderRadius: 12, cursor: "pointer",
                border: on ? `2px solid ${C.gold}` : l.zapis_id ? `1px solid ${C.line}` : `1.5px dashed var(--c-line-strong)`,
                background: on ? "#fffaf0" : l.zapis_id ? "var(--color-surface)" : "#fbfaf6",
                boxShadow: on ? "0 6px 16px rgba(176,125,12,.18)" : "none",
              }}
            >
              <span className="flex items-center" style={{ gap: 9 }}>
                <Ava r={l} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate" style={{ fontWeight: 700, fontSize: 13.5, color: C.ink }}>{l.fio}</span>
                  <span className="block truncate" style={{ fontSize: 11.5, color: C.muted }}>
                    {rolEmoji(l.dolzhnost)} {l.dolzhnost || "сотрудник"}
                  </span>
                </span>
                <span
                  title="Рабочих дней в этом месяце"
                  style={{ fontFamily: MONO, fontSize: 11, color: C.muted, whiteSpace: "nowrap" }}
                >
                  🗓 {l.dney_v_mesyace}
                </span>
              </span>
              {l.zapis_id && s ? (
                <span className="flex flex-col" style={{ gap: 3 }}>
                  <span style={{ alignSelf: "flex-start", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "2px 9px", background: s.bg, color: s.fg }}>
                    {s.emoji} {s.label}
                  </span>
                  {NA_RABOTE.includes(l.status) && (l.mesto || l.vid_raboty_nazvanie) && (
                    <span style={{ fontSize: 12.5, color: C.ink }}>
                      {l.mesto && <>📍 {l.mesto}</>}
                      {l.vid_raboty_nazvanie && <span style={{ color: C.muted }}> · {l.vid_raboty_nazvanie}</span>}
                    </span>
                  )}
                </span>
              ) : (
                <span className="flex flex-col" style={{ gap: 2 }}>
                  <span style={{ fontSize: 12.5, fontWeight: 700, color: "var(--color-disabled)" }}>❔ Не отмечен</span>
                  {l.mobile_status && <span style={{ fontSize: 11.5, color: C.sky }}>📱 с телефона: {l.mobile_status}</span>}
                  {l.proshloe && (
                    <span style={{ fontSize: 11.5, color: C.muted }}>
                      в прошлый раз: {ST[l.proshloe.status]?.emoji} {NA_RABOTE.includes(l.proshloe.status) ? (l.proshloe.mesto || l.proshloe.status) : l.proshloe.status}
                      {l.proshloe.vid_raboty ? ` · ${l.proshloe.vid_raboty}` : ""}
                    </span>
                  )}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {vsego === 0 && (
        <div style={{ color: C.muted, fontSize: 13 }}>В справочнике нет активных сотрудников — добавь их на экране «Сотрудники».</div>
      )}
    </div>
  );
}
