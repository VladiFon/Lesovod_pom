import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useCan } from "../auth.jsx";
import { useToast } from "../components/Toast.jsx";
import ZadachaModal from "../components/ZadachaModal.jsx";
import { LesnichestvoSelect, PhotoThumb, ReportPlace } from "./AiLog.jsx";

/**
 * «📬 Почта гонцов» — игровой вид экрана «С телефона» (03.11.2026).
 * Отчёты на проверку и непрочитанные заметки рабочих — одной колодой,
 * по карточке за раз, с горячими клавишами и комбо. Пишет теми же
 * запросами, что обычные вкладки:
 *   отчёт: POST /ai-log/raw-reports/{id}/approve | /reject
 *   заметка: PATCH /notes/{id} {is_read}, POST /notes/{id}/reply, задача — ZadachaModal.
 * «Вернуть» (отклонить) уходит на сервер через 5 секунд — успеешь отменить.
 */

const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dangerSoft: "#fdecea", sky: "#2c5d8a", skySoft: "#e6eef7",
};
const KOMBO_SEK = 90;
const OTMENA_SEK = 5;
const SHUTKI = [
  "Гонец скакал три дня — не томи его 🐎",
  "Свиток с печатью. Вскрывай!",
  "Голубь принёс весточку 🕊",
  "Срочно, из самой чащи!",
  "Пишут с делянки — значит, работают",
];
const PUSTO = ["Почта пуста — гонцы отдыхают 📭", "Ни одного свитка. Можно и чаю ☕", "Всё разобрано. Ты — гроза бюрократии 🏆"];

function e_v_modalke() {
  return !!document.querySelector("[role='dialog']");
}

function inicialy(fio) {
  const p = (fio || "").split(/\s+/);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase() || "?";
}
function kogda(s) {
  if (!s) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/.exec(s);
  return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}` : s;
}
function isoOtcheta(s) {
  const t = String(s || "").trim();
  const ru = /^(\d{2})\.(\d{2})\.(\d{4})/.exec(t);
  if (ru) return `${ru[3]}-${ru[2]}-${ru[1]}`;
  const iso = /^(\d{4}-\d{2}-\d{2})/.exec(t);
  return iso ? iso[1] : "";
}

function Pole({ label, value, onChange, nado, id }) {
  return (
    <label htmlFor={id} style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, color: nado && !value.trim() ? C.danger : C.muted, fontWeight: 600 }}>
      {label}{nado && !value.trim() ? " — заполни" : ""}
      <input id={id} value={value} onChange={(e) => onChange(e.target.value)} style={{
        padding: "6px 9px", borderRadius: 8, fontSize: 14, color: C.ink,
        border: `1.5px solid ${nado && !value.trim() ? "#f3c2bd" : C.line}`, background: "#fff",
      }} />
    </label>
  );
}

function Otchet({ r, onPrinyat, onVernut, onPotom, busy, mozhno, aktivno }) {
  const [f, setF] = useState({});
  useEffect(() => {
    setF({
      kvartal: r.kvartal || "", vydel: r.vydels || "", tip: r.tip_raboty || "", ispolnitel: r.ispolnitel_fio || "",
      lesnichestvo: r.lesnichestvo || "", opisanie: r.opisanie || "", data: isoOtcheta(r.data_soobscheniya),
    });
  }, [r.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const gotov = ["kvartal", "vydel", "tip", "lesnichestvo"].every((k) => (f[k] || "").trim());
  const prinyat = () => gotov && onPrinyat(f);
  useEffect(() => {
    const h = (e) => {
      if (!aktivno() || busy) return;
      const vPole = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
      if (e.key === "Enter" && (e.ctrlKey || !vPole)) { e.preventDefault(); prinyat(); }
      if (vPole) return;
      const k = e.key.toLowerCase();
      if (k === "a" || k === "ф") prinyat();
      if (k === "r" || k === "к") onVernut();
      if (k === "s" || k === "ы" || e.key === "ArrowRight") onPotom();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  if (f.kvartal === undefined) return null;
  return (
    <>
      <div style={{ fontSize: 17, lineHeight: 1.5, color: C.ink, background: "#fffdf7", border: `1px solid #efe4c8`, borderRadius: 12, padding: "12px 14px", whiteSpace: "pre-line" }}>
        {r.raw_text || "(гонец молчит — пустое сообщение)"}
      </div>
      {r.photo_path && <div style={{ maxWidth: 420 }}><PhotoThumb path={r.photo_path} /></div>}
      <ReportPlace report={r} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10 }}>
        <Pole id="p-kv" label="Квартал" value={f.kvartal} onChange={set("kvartal")} nado />
        <Pole id="p-vyd" label="Выдел" value={f.vydel} onChange={set("vydel")} nado />
        <Pole id="p-tip" label="Тип работы" value={f.tip} onChange={set("tip")} nado />
        <Pole id="p-isp" label="Исполнитель" value={f.ispolnitel} onChange={set("ispolnitel")} />
        <div style={{ fontSize: 12 }}><LesnichestvoSelect value={f.lesnichestvo} onChange={set("lesnichestvo")} /></div>
        <label htmlFor="p-data" style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, color: C.muted, fontWeight: 600 }}>
          Дата работы
          <input id="p-data" type="date" value={f.data} onChange={(e) => set("data")(e.target.value)} style={{ padding: "5px 9px", borderRadius: 8, border: `1.5px solid ${C.line}`, background: "#fff" }} />
        </label>
      </div>
      <Pole id="p-op" label="Описание" value={f.opisanie} onChange={set("opisanie")} />
      {mozhno ? (
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <button type="button" disabled={!gotov || busy} onClick={prinyat} style={{
            padding: "10px 18px", borderRadius: 10, fontWeight: 800, fontSize: 15, background: gotov ? C.leaf : "#b9c4bc", color: "#fff",
          }}>✅ Принять <span style={{ opacity: 0.7, fontWeight: 600, fontSize: 12 }}>A / Enter</span></button>
          <button type="button" disabled={busy} onClick={onVernut} style={{
            padding: "10px 16px", borderRadius: 10, fontWeight: 800, fontSize: 15, background: "#fff", color: C.danger, border: `1.5px solid #f3c2bd`,
          }}>↩ Вернуть <span style={{ opacity: 0.7, fontWeight: 600, fontSize: 12 }}>R</span></button>
          <button type="button" onClick={onPotom} style={{ padding: "10px 14px", borderRadius: 10, fontWeight: 700, color: C.muted }}>
            ⏭ Потом <span style={{ opacity: 0.7, fontSize: 12 }}>S / →</span>
          </button>
        </div>
      ) : <div style={{ fontSize: 13, color: C.muted }}>Принимать отчёты может тот, у кого есть право правки делянок.</div>}
    </>
  );
}

function Zametka({ n, onProchitano, onOtvet, onZadacha, onPotom, busy, aktivno }) {
  const [otvet, setOtvet] = useState(null);
  useEffect(() => { setOtvet(null); }, [n.id]);
  useEffect(() => {
    const h = (e) => {
      if (!aktivno() || busy) return;
      const vPole = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
      if (vPole) {
        if (e.key === "Enter" && e.ctrlKey && otvet?.trim()) onOtvet(otvet);
        return;
      }
      const k = e.key.toLowerCase();
      if (e.key === "Enter" || k === "a" || k === "ф") { e.preventDefault(); onProchitano(); }
      if (k === "o" || k === "щ") { e.preventDefault(); setOtvet(""); }
      if (k === "t" || k === "е") { e.preventDefault(); onZadacha(); }
      if (k === "s" || k === "ы" || e.key === "ArrowRight") onPotom();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  return (
    <>
      <div style={{ fontSize: 17, lineHeight: 1.5, color: C.ink, background: C.skySoft, borderRadius: 12, padding: "12px 14px", whiteSpace: "pre-line" }}>{n.text}</div>
      {otvet !== null && (
        <div className="flex items-start" style={{ gap: 8 }}>
          <textarea autoFocus value={otvet} onChange={(e) => setOtvet(e.target.value)} rows={2} placeholder="Ответ увидит рабочий в приложении · Ctrl+Enter — отправить"
            style={{ flex: 1, padding: "8px 10px", borderRadius: 10, border: `1.5px solid ${C.line}`, fontSize: 14 }} />
          <button type="button" disabled={!otvet.trim() || busy} onClick={() => onOtvet(otvet)} style={{ padding: "9px 14px", borderRadius: 10, background: C.sky, color: "#fff", fontWeight: 800 }}>Отправить</button>
        </div>
      )}
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <button type="button" disabled={busy} onClick={onProchitano} style={{ padding: "10px 18px", borderRadius: 10, fontWeight: 800, fontSize: 15, background: C.leaf, color: "#fff" }}>
          👁 Прочитано <span style={{ opacity: 0.7, fontWeight: 600, fontSize: 12 }}>A / Enter</span>
        </button>
        {otvet === null && !n.otvet && (
          <button type="button" onClick={() => setOtvet("")} style={{ padding: "10px 14px", borderRadius: 10, fontWeight: 800, background: "#fff", color: C.sky, border: `1.5px solid ${C.sky}` }}>
            💬 Ответить <span style={{ opacity: 0.7, fontSize: 12 }}>O</span>
          </button>
        )}
        <button type="button" onClick={onZadacha} style={{ padding: "10px 14px", borderRadius: 10, fontWeight: 800, background: "#fff", color: C.pine, border: `1.5px solid ${C.pine}` }}>
          📌 В задачу <span style={{ opacity: 0.7, fontSize: 12 }}>T</span>
        </button>
        <button type="button" onClick={onPotom} style={{ padding: "10px 14px", borderRadius: 10, fontWeight: 700, color: C.muted }}>⏭ Потом <span style={{ opacity: 0.7, fontSize: 12 }}>S</span></button>
      </div>
    </>
  );
}

export default function Pochta() {
  const toast = useToast();
  const can = useCan();
  const [koloda, setKoloda] = useState(null);
  const [busy, setBusy] = useState(false);
  const [stat, setStat] = useState({ prinyato: 0, vozvrat: 0, prochitano: 0, otvetov: 0, kombo: 0, luchshee: 0, posl: 0 });
  const [otmena, setOtmena] = useState(null); // {id, fio, ostalos}
  const [zadacha, setZadacha] = useState(null);
  const [vspyshka, setVspyshka] = useState(null);
  const tajmer = useRef(null);
  const koren = useRef(null);
  // Горячие клавиши — только когда «Почта» на экране (вкладка не скрыта) и не открыто окно задачи.
  const aktivno = () => !!koren.current && koren.current.offsetParent !== null && !zadacha && !e_v_modalke();

  const load = useCallback(async () => {
    try {
      const [otchety, zametki] = await Promise.all([
        api.get("/ai-log/raw-reports").catch(() => []),
        api.get("/notes/").catch(() => []),
      ]);
      setKoloda([
        ...(otchety || []).map((r) => ({ tip: "otchet", key: `o${r.id}`, fio: r.ispolnitel_fio, kogda: r.data_soobscheniya, r })),
        ...(zametki || []).filter((n) => !n.is_read).map((n) => ({ tip: "zametka", key: `z${n.id}`, fio: n.sotrudnik_fio, dolzhnost: n.sotrudnik_dolzhnost, kogda: kogda(n.created_at), n })),
      ]);
    } catch (e) {
      toast.show({ tone: "danger", title: "Почта не открылась", description: e.message });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const ochko = (pole, xpText) => {
    const now = Date.now();
    setStat((s) => {
      const kombo = now - s.posl < KOMBO_SEK * 1000 ? s.kombo + 1 : 1;
      return { ...s, [pole]: s[pole] + 1, kombo, luchshee: Math.max(s.luchshee, kombo), posl: now };
    });
    setVspyshka({ t: xpText, k: now });
  };
  const ubrat = (key) => setKoloda((k) => k.filter((x) => x.key !== key));
  const potom = () => setKoloda((k) => (k.length > 1 ? [...k.slice(1), k[0]] : k));

  const prinyat = async (item, f) => {
    setBusy(true);
    try {
      await api.post(`/ai-log/raw-reports/${item.r.id}/approve`, {
        kvartal: f.kvartal.trim(), vydel: f.vydel.trim(), tip_raboty: f.tip.trim(), lesnichestvo: f.lesnichestvo.trim(),
        ispolnitel_fio: f.ispolnitel.trim(), opisanie: f.opisanie.trim(), data_vypolneniya: f.data || null,
      });
      ubrat(item.key);
      ochko("prinyato", "✅ Принято в журнал");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось принять", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const vypolnitVozvrat = useCallback(async (id) => {
    try {
      await api.post(`/ai-log/raw-reports/${id}/reject`);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось вернуть отчёт", description: e.message });
      load();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const vernut = (item) => {
    if (otmena) { clearInterval(tajmer.current); vypolnitVozvrat(otmena.id); }
    ubrat(item.key);
    ochko("vozvrat", "↩ Возвращено");
    setOtmena({ id: item.r.id, item, ostalos: OTMENA_SEK });
    tajmer.current = setInterval(() => {
      setOtmena((o) => {
        if (!o) return o;
        if (o.ostalos <= 1) { clearInterval(tajmer.current); vypolnitVozvrat(o.id); return null; }
        return { ...o, ostalos: o.ostalos - 1 };
      });
    }, 1000);
  };
  const otmenit = () => {
    clearInterval(tajmer.current);
    setKoloda((k) => [otmena.item, ...k]);
    setStat((s) => ({ ...s, vozvrat: Math.max(0, s.vozvrat - 1), kombo: Math.max(0, s.kombo - 1) }));
    setVspyshka(null);
    setOtmena(null);
  };
  useEffect(() => () => clearInterval(tajmer.current), []);

  const prochitano = async (item) => {
    setBusy(true);
    try {
      await api.patch(`/notes/${item.n.id}`, { is_read: true });
      ubrat(item.key);
      ochko("prochitano", "👁 Прочитано");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось отметить", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const otvetit = async (item, text) => {
    setBusy(true);
    try {
      await api.post(`/notes/${item.n.id}/reply`, { text });
      await api.patch(`/notes/${item.n.id}`, { is_read: true }).catch(() => {});
      ubrat(item.key);
      setStat((s) => ({ ...s, otvetov: s.otvetov + 1 }));
      ochko("prochitano", "💬 Ответ улетел");
    } catch (e) {
      toast.show({ tone: "danger", title: "Ответ не отправился", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const vsego = useMemo(() => (koloda || []).length, [koloda]);
  if (koloda == null) return <div style={{ padding: 24, color: C.muted }}>Гонцы спешат… 🐎</div>;
  const tek = koloda[0];
  const razobrano = stat.prinyato + stat.vozvrat + stat.prochitano;
  const nOtch = koloda.filter((x) => x.tip === "otchet").length;
  const nZam = koloda.length - nOtch;

  return (
    <div ref={koren} style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 14, maxWidth: 980 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 10 }}>
        <div style={{ fontSize: 14, color: C.muted }}>
          <b style={{ color: C.pine }}>📬 Почта гонцов</b> — отчёты и заметки с телефонов по одной карточке. Клавиши: A принять/прочитано,
          R вернуть, O ответить, T в задачу, S потом. Разбирай подряд — растёт комбо.
        </div>
        <div className="flex items-center" style={{ gap: 8 }}>
          <span style={{ padding: "5px 11px", borderRadius: 999, background: C.goldSoft, color: C.gold, fontWeight: 800, fontSize: 13 }}>📜 отчётов {nOtch}</span>
          <span style={{ padding: "5px 11px", borderRadius: 999, background: C.skySoft, color: C.sky, fontWeight: 800, fontSize: 13 }}>✉️ заметок {nZam}</span>
          {stat.kombo >= 2 && (
            <span style={{ padding: "5px 11px", borderRadius: 999, background: C.dangerSoft, color: C.danger, fontWeight: 900, fontSize: 13 }}>🔥 комбо ×{stat.kombo}</span>
          )}
        </div>
      </div>

      {razobrano + vsego > 0 && (
        <div title={`Разобрано ${razobrano}, осталось ${vsego}`}>
          <div style={{ height: 10, borderRadius: 5, background: C.line, overflow: "hidden" }}>
            <div style={{ width: `${(razobrano / (razobrano + vsego)) * 100}%`, height: "100%", background: C.leaf, transition: "width .3s" }} />
          </div>
          <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>разобрано {razobrano} · осталось {vsego}</div>
        </div>
      )}

      {otmena && (
        <div className="flex items-center justify-between" style={{ padding: "8px 12px", borderRadius: 10, background: C.dangerSoft, color: C.danger, fontSize: 14 }}>
          <span>↩ Отчёт от {otmena.item.fio || "—"} будет возвращён через {otmena.ostalos} с</span>
          <button type="button" onClick={otmenit} style={{ fontWeight: 800, color: C.danger, textDecoration: "underline" }}>Отменить</button>
        </div>
      )}

      {!tek ? (
        <div style={{ padding: 40, textAlign: "center", borderRadius: 16, background: C.moss, border: "1px solid #bcefc5" }}>
          <div style={{ fontSize: 48 }}>📭</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: C.pine, marginTop: 6 }}>{PUSTO[razobrano % PUSTO.length]}</div>
          {razobrano > 0 && (
            <div style={{ fontSize: 14, color: C.ink, marginTop: 10 }}>
              За заход: принято {stat.prinyato}, возвращено {stat.vozvrat}, прочитано {stat.prochitano}{stat.otvetov ? ` (ответов ${stat.otvetov})` : ""} · лучшее комбо ×{stat.luchshee}
            </div>
          )}
          <div style={{ fontSize: 13, color: C.muted, marginTop: 6 }}>Квест «Отчёты с телефона» в «🎯 Квестах» засчитается, когда очередь опустеет.</div>
        </div>
      ) : (
        <div style={{ position: "relative" }}>
          {koloda.length > 2 && <div style={{ position: "absolute", inset: "10px -10px -10px 10px", borderRadius: 16, background: "#efece4", border: `1px solid ${C.line}` }} />}
          {koloda.length > 1 && <div style={{ position: "absolute", inset: "5px -5px -5px 5px", borderRadius: 16, background: "#f6f4ee", border: `1px solid ${C.line}` }} />}
          <div key={tek.key} style={{
            position: "relative", background: "#fff", borderRadius: 16, border: `1.5px solid ${tek.tip === "otchet" ? "#efd9a4" : "#c8d9ec"}`,
            padding: 18, display: "flex", flexDirection: "column", gap: 12, boxShadow: "0 6px 20px rgba(26,67,49,.08)",
          }}>
            <div className="flex items-center" style={{ gap: 12 }}>
              <span style={{
                width: 46, height: 46, borderRadius: 23, background: tek.tip === "otchet" ? C.gold : C.sky, color: "#fff",
                display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800,
              }}>{inicialy(tek.fio)}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 800, fontSize: 16 }}>{tek.fio || "Неизвестный гонец"} {tek.dolzhnost ? <span style={{ fontWeight: 400, color: C.muted, fontSize: 13 }}>· {tek.dolzhnost}</span> : null}</div>
                <div style={{ fontSize: 12, color: C.muted }}>
                  {tek.tip === "otchet" ? "📜 отчёт о работе" : "✉️ заметка"} · {tek.kogda || "—"} · {SHUTKI[(tek.r?.id || tek.n?.id || 0) % SHUTKI.length]}
                </div>
              </div>
              {vspyshka && Date.now() - vspyshka.k < 1500 && (
                <span key={vspyshka.k} style={{ color: C.leaf, fontWeight: 800, fontSize: 13 }}>{vspyshka.t}</span>
              )}
            </div>
            {tek.tip === "otchet" ? (
              <Otchet r={tek.r} busy={busy} aktivno={aktivno} mozhno={can("delyanka.edit")} onPrinyat={(f) => prinyat(tek, f)} onVernut={() => vernut(tek)} onPotom={potom} />
            ) : (
              <Zametka n={tek.n} busy={busy} aktivno={aktivno} onProchitano={() => prochitano(tek)} onOtvet={(t) => otvetit(tek, t)}
                onZadacha={() => setZadacha({ sotrudnik_id: tek.n.sotrudnik_id, zadacha: tek.n.text })} onPotom={potom} />
            )}
          </div>
        </div>
      )}

      {koloda.length > 1 && (
        <div style={{ fontSize: 13, color: C.muted }}>
          Дальше в колоде: {koloda.slice(1, 6).map((x) => `${x.tip === "otchet" ? "📜" : "✉️"} ${x.fio || "—"}`).join(" · ")}{koloda.length > 6 ? ` и ещё ${koloda.length - 6}` : ""}
        </div>
      )}
      <ZadachaModal open={!!zadacha} initial={zadacha} onClose={() => setZadacha(null)} />
    </div>
  );
}
