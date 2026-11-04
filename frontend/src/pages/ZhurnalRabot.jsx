import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { useScreenParam } from "../nav.js";
import Card from "../components/Card.jsx";
import EmptyState from "../components/EmptyState.jsx";
import DateField, { ruToIso, isoToRu } from "../components/DateField.jsx";
import { ChelovekList, VydelLink, openSsylka } from "../components/ChelovekLink.jsx";

/**
 * Журнал работ (шаг 3 разбора «сайт разбросан», 04.11.2026). Всё, что
 * сделано в лесхозе, одной лентой: отчёты за смену с телефона, журнал
 * лесокультур, журнал выполненных работ, «Выполнение» рубок ухода и табель
 * (табель — только про тех, о ком в этот день больше ничего не записано).
 * Фильтры «кто / где / что / когда». Только чтение — правка на своих
 * экранах, туда ведёт «открыть →». Сервер: app/zhurnal_rabot.py.
 */

const DNI = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MES = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
function zagolovokDnya(iso) {
  const d = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  const seg = new Date(); seg.setHours(12, 0, 0, 0);
  const raz = Math.round((seg - d) / 864e5);
  const pref = raz === 0 ? "Сегодня, " : raz === 1 ? "Вчера, " : "";
  return `${pref}${d.getDate()} ${MES[d.getMonth()]}, ${DNI[d.getDay()]}`;
}
const isoDaysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };

const ISTOCHNIK_STYLE = {
  smena: { label: "📱 смена", cls: "bg-mint-soft text-pine" },
  lk: { label: "🌱 культуры", cls: "bg-mint-soft text-green" },
  zhurnal: { label: "✅ журнал", cls: "bg-hover text-muted" },
  uhody: { label: "✂️ рубки ухода", cls: "bg-oak-soft text-oak" },
  tabel: { label: "📋 табель", cls: "bg-hover text-muted" },
};

const PERIODY = [
  { k: "7", label: "Неделя" },
  { k: "31", label: "Месяц" },
  { k: "92", label: "3 мес." },
  { k: "366", label: "Год" },
];

export default function ZhurnalRabot() {
  const [s, setS] = useScreenParam("raboty", "s");
  const [kv, setKv] = useScreenParam("raboty", "kv");
  const [vyd, setVyd] = useScreenParam("raboty", "vyd");
  const [period, setPeriod] = useState("31");
  const [ot, setOt] = useState(isoDaysAgo(30));
  const [doD, setDoD] = useState(isoDaysAgo(0));
  const [q, setQ] = useState("");
  const [qDeb, setQDeb] = useState("");
  const [vyklyucheny, setVyklyucheny] = useState([]);
  const [lyudi, setLyudi] = useState([]);
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => { api.get("/chelovek", { vse: true }).then(setLyudi).catch(() => setLyudi([])); }, []);
  useEffect(() => { const t = setTimeout(() => setQDeb(q), 250); return () => clearTimeout(t); }, [q]);

  const vybratPeriod = (k) => {
    setPeriod(k);
    setOt(isoDaysAgo(Number(k) - 1));
    setDoD(isoDaysAgo(0));
  };

  useEffect(() => {
    setErr("");
    api.get("/zhurnal-rabot", { ot, do: doD, q: qDeb || undefined, s: s || undefined, kv: kv || undefined, vyd: vyd || undefined, limit: 1500 })
      .then(setD)
      .catch((e) => setErr(e.message || "Не удалось загрузить журнал"));
  }, [ot, doD, qDeb, s, kv, vyd]);

  const stroki = useMemo(() => (d?.stroki || []).filter((x) => !vyklyucheny.includes(x.istochnik)), [d, vyklyucheny]);
  const poDnyam = useMemo(() => {
    const m = new Map();
    stroki.forEach((x) => { if (!m.has(x.data)) m.set(x.data, []); m.get(x.data).push(x); });
    return [...m.entries()];
  }, [stroki]);

  const chelovek = lyudi.find((p) => String(p.id) === String(s));
  const pereklyuchit = (k) => setVyklyucheny((v) => (v.includes(k) ? v.filter((x) => x !== k) : [...v, k]));
  const estFiltr = s || kv || vyd || q;

  return (
    <div className="p-5 flex flex-col gap-4 max-w-[1180px]">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1 min-w-[220px] flex-1">
            <span className="text-[11px] font-mono text-muted-2 uppercase tracking-wider">что / где / кто — словами</span>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="валка, Сосновая, Петров, инвентаризация…"
              className="h-9 px-3 rounded-lg border border-border bg-surface text-[13.5px] outline-none focus:border-pine" />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-muted-2 uppercase tracking-wider">кто</span>
            <select value={s || ""} onChange={(e) => setS(e.target.value)} className="h-9 px-2 rounded-lg border border-border bg-surface text-[13.5px] max-w-[220px]">
              <option value="">все люди</option>
              {lyudi.map((p) => <option key={p.id} value={p.id}>{p.fio}{p.aktiven ? "" : " (неакт.)"}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-muted-2 uppercase tracking-wider">квартал / выдел</span>
            <div className="flex gap-1.5">
              <input value={kv} onChange={(e) => setKv(e.target.value.trim())} placeholder="кв" className="h-9 w-16 px-2 rounded-lg border border-border bg-surface text-[13.5px]" />
              <input value={vyd} onChange={(e) => setVyd(e.target.value.trim())} placeholder="выд" className="h-9 w-16 px-2 rounded-lg border border-border bg-surface text-[13.5px]" />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-muted-2 uppercase tracking-wider">когда</span>
            <div className="flex gap-1">
              {PERIODY.map((p) => (
                <button key={p.k} type="button" onClick={() => vybratPeriod(p.k)}
                  className={["h-9 px-3 rounded-lg text-[13px] border", period === p.k ? "bg-pine text-white border-pine" : "bg-surface border-border text-muted hover:border-pine"].join(" ")}>
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-end gap-1.5">
            <div className="w-[150px]"><DateField value={isoToRu(ot)} onChange={(v) => { setPeriod(""); setOt(ruToIso(v) || ot); }} /></div>
            <span className="pb-2 text-muted">—</span>
            <div className="w-[150px]"><DateField value={isoToRu(doD)} onChange={(v) => { setPeriod(""); setDoD(ruToIso(v) || doD); }} /></div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 mt-3">
          {Object.entries(ISTOCHNIK_STYLE).map(([k, st]) => {
            const n = d?.po_istochnikam?.[k] || 0;
            const off = vyklyucheny.includes(k);
            return (
              <button key={k} type="button" onClick={() => pereklyuchit(k)}
                title={d?.istochniki?.[k]}
                className={["px-2.5 py-1 rounded-full text-[12px] font-semibold border", off ? "border-border text-muted-2 line-through bg-surface" : `border-transparent ${st.cls}`].join(" ")}>
                {st.label} · {n}
              </button>
            );
          })}
          {estFiltr && (
            <button type="button" onClick={() => { setS(""); setKv(""); setVyd(""); setQ(""); }} className="text-[12px] text-pine hover:underline ml-1">
              ✕ сбросить фильтры
            </button>
          )}
          <span className="ml-auto text-[12px] text-muted-2 font-mono">
            {d ? `${stroki.length} записей · ${d.lyudey} чел.` : "…"}
          </span>
        </div>
        {chelovek && (
          <p className="mt-2 text-[12.5px] text-muted">
            Показаны работы, где участвовал <b className="text-ink">{chelovek.fio}</b> — сам или напарником.
          </p>
        )}
      </Card>

      {err && <Card><p className="text-error text-sm">{err}</p></Card>}
      {d && !stroki.length && (
        <EmptyState title="За этот период ничего не нашлось" description="Попробуйте период побольше или уберите фильтры." />
      )}

      {poDnyam.map(([data, spisok]) => (
        <div key={data} className="flex flex-col gap-1.5">
          <div className="flex items-baseline gap-2 px-1">
            <h3 className="font-extrabold text-pine text-[14px]">{zagolovokDnya(data)}</h3>
            <span className="font-mono text-[10.5px] text-muted-2">{spisok.length} зап.</span>
          </div>
          <div className="bg-surface border border-border rounded-lg divide-y divide-border">
            {spisok.map((x) => {
              const st = ISTOCHNIK_STYLE[x.istochnik] || {};
              return (
                <div key={x.kluch} className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1.1fr)_minmax(0,1.2fr)_auto] gap-3 items-start px-4 py-2.5 text-[13.5px] max-md:grid-cols-1 max-md:gap-1">
                  <div className="min-w-0">
                    <div className="font-semibold text-ink">{x.emoji} {x.chto}</div>
                    {(x.skolko || x.opisanie) && (
                      <div className="text-[12px] text-muted mt-0.5 truncate" title={x.opisanie || ""}>
                        {[x.skolko, x.opisanie].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 text-[13px]">
                    {x.kvartal && x.vydel ? (
                      <>
                        <VydelLink kvartal={x.kvartal} vydel={x.vydel} lesnichestvo={x.lesnichestvo}>{x.gde || `кв.${x.kvartal} выд.${x.vydel}`}</VydelLink>
                      </>
                    ) : (
                      <span className="text-muted">{x.gde || "—"}</span>
                    )}
                  </div>
                  <div className="min-w-0 text-[13px]"><ChelovekList people={x.lyudi} /></div>
                  <div className="flex items-center gap-2 justify-end max-md:justify-start">
                    <span className={["px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap", st.cls].join(" ")}>{st.label}</span>
                    {x.ssylka && (
                      <button type="button" onClick={() => openSsylka(x.ssylka)} className="text-[12.5px] text-pine hover:underline whitespace-nowrap">
                        открыть →
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      {d?.obrezano && <p className="text-[12px] text-muted-2 text-center">Показаны первые {d.stroki.length} — сузьте период или фильтр.</p>}
    </div>
  );
}
