import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { openScreen, useScreenParam } from "../nav.js";
import Card from "../components/Card.jsx";
import EmptyState from "../components/EmptyState.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import ChelovekLink, { openSsylka } from "../components/ChelovekLink.jsx";

/**
 * Карточка человека (Влад, 04.11.2026: «сайт разбросан — табель и журнал
 * мероприятий не вместе»). Слева — люди, справа — всё о выбранном: бригада,
 * техника, «сегодня», лента «что делал» из табеля, отчётов с телефона,
 * журнала работ, лесокультур и рубок ухода, задачи, итоги, заметки и
 * «не сходится». Только чтение — вносится всё на своих экранах, а отсюда по
 * ссылке можно туда перейти. Сервер: app/routers/chelovek.py.
 */

const DNI = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
function ruData(s) {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return s || "";
  const d = new Date(`${m[1]}-${m[2]}-${m[3]}T12:00:00`);
  return `${m[3]}.${m[2]} ${DNI[d.getDay()]}`;
}
const num = (v, d = 1) => Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: d });
function initsialy(fio) {
  const p = (fio || "").split(/\s+/).filter(Boolean);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase();
}

const TABEL_TON = { "работал": "success", "больничный": "danger", "отпуск": "info", "выходной": "neutral", "не работал": "warning", "ремонт": "warning", "командировка": "info" };
const ISTOCHNIK = { smena: "отчёт с телефона", zhurnal: "журнал выполненных работ", uhody: "рубки ухода (офис)" };

/** Строчка «где»: если сервер дал ссылку — кликабельная. */
function Gde({ text, ssylka }) {
  if (!text) return null;
  if (!ssylka) return <span className="text-muted"> · {text}</span>;
  return (
    <>
      <span className="text-muted"> · </span>
      <button type="button" onClick={() => openSsylka(ssylka)} title="Открыть"
        className="text-muted hover:text-pine hover:underline decoration-dotted underline-offset-2">{text} ↗</button>
    </>
  );
}

function Rabota({ r }) {
  return (
    <div className="leading-5" title={ISTOCHNIK[r.istochnik] || ""}>
      <span>{r.emoji} </span>
      <span className="text-ink">{r.chto}</span>
      <Gde text={r.gde} ssylka={r.ssylka} />
      {r.skolko && <span className="text-pine font-semibold"> · {r.skolko}</span>}
      {r.s_kem && <span className="text-muted"> · с {r.s_kem}</span>}
      {r.tehnika && <span className="text-muted"> · {r.tehnika}</span>}
    </div>
  );
}

function Stat({ label, value, hint }) {
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 min-w-[96px]" title={hint}>
      <div className="font-mono text-[10px] uppercase tracking-[.08em] text-muted-2">{label}</div>
      <div className="text-[18px] font-extrabold text-pine leading-6">{value}</div>
    </div>
  );
}

/** Табель-полоска: квадратик на день, цвет — статус, точка — есть работы. */
function Polosa({ dni, ot, doo }) {
  const po = useMemo(() => Object.fromEntries(dni.map((d) => [d.data, d])), [dni]);
  const days = [];
  const start = new Date(`${ot}T12:00:00`);
  const end = new Date(`${doo}T12:00:00`);
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) days.push(d.toISOString().slice(0, 10));
  const cvet = { "работал": "var(--c-green-2)", "больничный": "#b3261e", "отпуск": "#2f6f8f", "выходной": "var(--c-line-strong)", "не работал": "var(--c-gold)", "ремонт": "#9a6200", "командировка": "var(--c-info-ink)" };
  return (
    <div className="flex flex-wrap gap-[3px]">
      {days.map((d) => {
        const x = po[d];
        const st = x?.tabel?.status;
        const est = x?.raboty?.length > 0;
        return (
          <div key={d} title={`${ruData(d)}: ${st || "нет в табеле"}${est ? ` · работ: ${x.raboty.length}` : ""}`}
            className="w-[14px] h-[22px] rounded-[3px] flex items-end justify-center"
            style={{ background: st ? cvet[st] || "var(--c-line-strong)" : "#efede7", outline: est && !st ? "1.5px solid var(--c-gold)" : "none" }}>
            {est && <span className="block w-[5px] h-[5px] rounded-full mb-[3px]" style={{ background: st ? "var(--color-surface)" : "var(--c-gold)" }} />}
          </div>
        );
      })}
    </div>
  );
}

function Kartochka({ id }) {
  const [dney, setDney] = useState(31);
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!id) return;
    setD(null);
    setErr(null);
    api.get(`/chelovek/${id}`, { dney }).then(setD).catch((e) => setErr(e.message || "Не удалось загрузить"));
  }, [id, dney]);

  if (err) return <EmptyState title="Карточка не открылась" description={err} />;
  if (!d) return <div className="text-muted p-4">Загрузка…</div>;
  const s = d.summy || {};
  const seg = d.segodnya || {};
  const aktivnye = d.zadachi.filter((z) => z.status === "активна");
  const gotovye = d.zadachi.filter((z) => z.status !== "активна");
  return (
    <div className="flex flex-col gap-3">
      {/* шапка */}
      <Card>
        <div className="flex items-start gap-3">
          <div className="w-12 h-12 shrink-0 rounded-full bg-mint text-pine font-extrabold flex items-center justify-center text-[17px]">
            {initsialy(d.fio)}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-ui font-extrabold text-pine text-[18px]">{d.fio}</h2>
              {!d.aktiven && <StatusBadge tone="neutral" label="уволен / неактивен" />}
            </div>
            <div className="text-muted text-[13px]">
              {[d.dolzhnost, d.uchastok].filter(Boolean).join(" · ") || "должность не указана"}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[13px]">
              {d.brigada?.nazvanie ? (
                <span>👥 {d.brigada.nazvanie}
                  {d.brigada.brigadir_id && d.brigada.brigadir_id !== d.id && (
                    <> · бригадир <ChelovekLink id={d.brigada.brigadir_id} fio={d.brigada.brigadir_fio} /></>
                  )}
                </span>
              ) : <span className="text-muted">👥 не в бригаде</span>}
              {d.brigada?.naznacheniya?.map((n) => (
                <button key={`${n.delyanka_id}-${n.s}`} type="button" onClick={() => openSsylka({ screen: "plots", params: { d: n.delyanka_id } })}
                  className="text-pine hover:underline decoration-dotted underline-offset-2">
                  📍 {n.status === "активно" ? "сейчас" : "дальше"}: {n.delyanka} ↗
                </button>
              ))}
              {d.tehnika.map((t) => (
                <button key={t.id} type="button" onClick={() => openSsylka({ screen: "tehnika", params: { tab: "tehnika" } })}
                  className="text-pine hover:underline decoration-dotted underline-offset-2">
                  🚜 {t.nazvanie}{t.nomer ? ` (${t.nomer})` : ""}
                </button>
              ))}
            </div>
            {d.brigada?.tovarishchi?.length > 0 && (
              <div className="text-[12.5px] text-muted mt-1">
                в бригаде с ним: {d.brigada.tovarishchi.map((t, i) => (
                  <React.Fragment key={t.id}>{i > 0 && ", "}<ChelovekLink id={t.id} fio={t.fio} className="font-normal" /></React.Fragment>
                ))}
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* сегодня */}
      <Card title="Сегодня" subtitle={ruData(seg.data)}>
        <div className="flex flex-col gap-1 text-[13px]">
          <div>
            📱 {seg.otmetka
              ? seg.otmetka.segodnya
                ? <>отметился «{seg.otmetka.status}» в {String(seg.otmetka.kogda).slice(11, 16)}</>
                : <span className="text-muted">сегодня не отмечался (последний раз {ruData(seg.otmetka.kogda)} — «{seg.otmetka.status}»)</span>
              : <span className="text-muted">с телефона не отмечается</span>}
          </div>
          <div>
            📋 {seg.tabel
              ? <>в табеле: <b>{seg.tabel.status}</b>{seg.tabel.vid ? ` · ${seg.tabel.vid}` : ""}<Gde text={seg.tabel.gde} ssylka={seg.tabel.ssylka} /></>
              : <span className="text-muted">в табеле сегодня ещё нет</span>}
          </div>
          {aktivnye.filter((z) => z.data === seg.data).map((z) => (
            <div key={z.id}>🎯 задача: {z.zadacha}<Gde text={z.gde} ssylka={z.ssylka} /></div>
          ))}
          {seg.raboty.map((r, i) => <Rabota key={i} r={r} />)}
        </div>
      </Card>

      {/* итоги */}
      <Card
        title="Где был и что делал"
        subtitle={`${ruData(d.ot)} — ${ruData(d.do)} · табель, отчёты с телефона, журнал работ, лесокультуры, рубки ухода`}
        actions={
          <div className="flex gap-1 items-center">
            <button type="button" onClick={() => openScreen("raboty", { tab: "lenta", s: d.id, kv: "", vyd: "" })}
              className="mr-1 text-[12.5px] text-pine hover:underline" title="Все работы человека в «Журнале работ»">📒 в журнале →</button>
            {[[7, "Неделя"], [31, "Месяц"], [92, "3 мес."]].map(([n, t]) => (
              <button key={n} type="button" onClick={() => setDney(n)}
                className={["px-2.5 py-1 rounded-md border text-[12.5px]", dney === n ? "bg-mint text-pine border-pine font-bold" : "border-border hover:bg-hover"].join(" ")}>
                {t}
              </button>
            ))}
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Stat label="дней работал" value={s.dney_rabotal} hint="по табелю" />
            {s.dney_ne_rabotal > 0 && <Stat label="не работал" value={s.dney_ne_rabotal} hint="выходные, больничный, отпуск — по табелю" />}
            {s.otchetov > 0 && <Stat label="отчётов" value={s.otchetov} hint="отчёты за смену с телефона" />}
            {s.obyom > 0 && <Stat label="м³" value={num(s.obyom)} hint="по отчётам за смену" />}
            {s.reysov > 0 && <Stat label="рейсов" value={s.reysov} />}
            {s.ga > 0 && <Stat label="га" value={num(s.ga, 2)} />}
            {s.chasy > 0 && <Stat label="часов" value={num(s.chasy)} />}
          </div>
          <Polosa dni={d.dni} ot={d.ot} doo={d.do} />
          {d.itogo?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {d.itogo.map((x) => (
                <span key={x.chto} className="rounded-full bg-hover px-2.5 py-1 text-xs">{x.chto}: <b>{x.dney}</b></span>
              ))}
            </div>
          )}
          {d.ne_shoditsya?.length > 0 && (
            <div className="rounded-md bg-oak-soft px-3 py-2 text-[13px]">
              <div className="font-bold text-oak mb-1">⚠ Не сходится табель и отчёты</div>
              {d.ne_shoditsya.map((x) => <div key={x.data}><b>{ruData(x.data)}</b> — {x.chto}</div>)}
            </div>
          )}
          {d.dni.length === 0 ? (
            <div className="text-muted text-[13px]">За этот период о нём ничего нет — ни табеля, ни отчётов.</div>
          ) : (
            <div className="flex flex-col divide-y divide-border text-[13px]">
              {d.dni.map((x) => (
                <div key={x.data} className="py-2 flex gap-3">
                  <div className="w-[70px] shrink-0 font-semibold text-ink">{ruData(x.data)}</div>
                  <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                    {x.tabel && (
                      <div className="text-muted">
                        📋 {x.tabel.status}{x.tabel.vid ? ` · ${x.tabel.vid}` : ""}
                        <Gde text={x.tabel.gde} ssylka={x.tabel.ssylka} />
                        {x.tabel.kommentariy ? ` · ${x.tabel.kommentariy}` : ""}
                      </div>
                    )}
                    {x.raboty.map((r, i) => <Rabota key={i} r={r} />)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))" }}>
        <Card title="Задачи" subtitle="из «Плана работ» — активные и за последний месяц">
          {d.zadachi.length === 0 ? <div className="text-muted text-[13px]">Задач нет.</div> : (
            <div className="flex flex-col gap-1.5 text-[13px]">
              {[...aktivnye, ...gotovye].slice(0, 15).map((z) => (
                <div key={z.id} className="flex gap-2 items-start">
                  <span className="w-[62px] shrink-0 text-muted">{ruData(z.data)}</span>
                  <span className="flex-1 min-w-0">
                    {z.status === "активна" ? (z.prosrochena ? "⏰ " : "🎯 ") : "✅ "}{z.zadacha}
                    <Gde text={z.gde} ssylka={z.ssylka} />
                  </span>
                  {z.prosrochena && <StatusBadge tone="warning" label="просрочена" />}
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title="Заметки с телефона" subtitle="что он писал начальству">
          {d.zametki.length === 0 ? <div className="text-muted text-[13px]">Заметок нет.</div> : (
            <div className="flex flex-col gap-2 text-[13px]">
              {d.zametki.map((z) => (
                <div key={z.id}>
                  <span className="text-muted">{ruData(z.kogda)} · </span>
                  {!z.prochitana && <StatusBadge tone="warning" label="не прочитана" className="mr-1" />}
                  {z.text}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {d.ne_privyazano?.length > 0 && (
        <Card title="Может быть, это тоже он?" subtitle="записи журнала работ с похожим ФИО, которые не привязались к справочнику">
          <div className="flex flex-col gap-1 text-[13px]">
            {d.ne_privyazano.map((x) => (
              <div key={x.id}><span className="text-muted">{ruData(x.data)} · </span>«{x.fio}» — {x.chto}</div>
            ))}
            <div className="text-muted-2 text-xs mt-1">
              Исправьте ФИО в «Журнал работ → Журнал выполненных работ», и запись появится в ленте.
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

export default function Chelovek() {
  const [sParam, setSParam] = useScreenParam("sotrudniki", "s");
  const [lyudi, setLyudi] = useState(null);
  const [poisk, setPoisk] = useState("");
  const [vse, setVse] = useState(false);
  useEffect(() => {
    api.get("/chelovek", { vse }).then(setLyudi).catch(() => setLyudi([]));
  }, [vse]);
  const shown = useMemo(() => {
    const q = poisk.trim().toLowerCase();
    return (lyudi || []).filter((p) => !q || `${p.fio} ${p.dolzhnost || ""} ${p.brigada || ""}`.toLowerCase().includes(q));
  }, [lyudi, poisk]);
  const id = Number(sParam) || null;

  return (
    <div className="p-[18px] flex gap-[14px] items-start">
      <div className="w-[260px] shrink-0 flex flex-col gap-2 sticky top-[56px]">
        <input value={poisk} onChange={(e) => setPoisk(e.target.value)} placeholder="Поиск: ФИО, должность, бригада"
          className="h-9 px-3 rounded-md border border-border bg-surface text-[13px] focus:outline-none focus:border-pine" />
        <label className="flex items-center gap-2 text-[12.5px] text-muted">
          <input type="checkbox" checked={vse} onChange={(e) => setVse(e.target.checked)} /> показывать неактивных
        </label>
        <div className="flex flex-col bg-surface border border-border rounded-lg overflow-y-auto max-h-[calc(100vh-200px)]">
          {lyudi === null ? <div className="p-3 text-muted text-[13px]">Загрузка…</div>
            : shown.length === 0 ? <div className="p-3 text-muted text-[13px]">Никого не нашлось.</div>
            : shown.map((p) => (
              <button key={p.id} type="button" onClick={() => setSParam(p.id)}
                className={["text-left px-3 py-2 border-b border-border last:border-0 hover:bg-hover",
                  p.id === id ? "bg-mint" : "", p.aktiven ? "" : "opacity-60"].join(" ")}>
                <div className="flex items-center justify-between gap-2">
                  <span className={["text-[13.5px] truncate", p.id === id ? "font-bold text-pine" : "font-semibold text-ink"].join(" ")}>{p.fio}</span>
                  {p.segodnya && <StatusBadge tone={TABEL_TON[p.segodnya] || "neutral"} label={p.segodnya} />}
                </div>
                <div className="text-[11.5px] text-muted truncate">{[p.dolzhnost, p.brigada].filter(Boolean).join(" · ") || "—"}</div>
              </button>
            ))}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        {id ? <Kartochka id={id} /> : (
          <EmptyState title="Выберите человека слева"
            description="Здесь соберётся всё о нём: табель, отчёты с телефона, журнал работ, лесокультуры, рубки ухода, задачи, техника и бригада. По любому ФИО на сайте тоже можно попасть сюда." />
        )}
      </div>
    </div>
  );
}
