import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import Card from "../components/Card.jsx";
import StatCard from "../components/StatCard.jsx";
import Button from "../components/Button.jsx";
import { openScreen, useScreenParam } from "../nav.js";
import BarChart from "../components/BarChart.jsx";
import { napechatat } from "../components/pechat.js";
import { openChelovek } from "../components/ChelovekLink.jsx";

/**
 * «Отчёты» (разбор сайта 09.11.2026, шаг 2).
 *
 * Сверху — сводка за месяц для начальства (GET /api/otchety/svodka): одна
 * страница, которую можно распечатать или показать на планёрке. Снизу —
 * все выгрузки сайта в одном месте: раньше их надо было помнить, где какая
 * кнопка лежит (Т-13 в табеле, путевые у техники, отсрочка в Инспекции…).
 */
const MESYACY = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const tekushchiy = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const sdvig = (ym, n) => { const [y, m] = ym.split("-").map(Number); const d = new Date(y, m - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const nazv = (ym) => { const [y, m] = ym.split("-").map(Number); return `${MESYACY[m - 1]} ${y}`; };
const n1 = (v) => Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 });

const LEVEL = { norma: "bg-pine", vnimanie: "bg-oak", pererub: "bg-error", net_limita: "bg-[var(--c-line-strong)]" };

function Polosa({ label, value, max, sub, cls = "bg-pine", onClick }) {
  const w = max ? Math.min(100, (value / max) * 100) : 0;
  const Tag = onClick ? "button" : "div";
  return (
    <Tag type={onClick ? "button" : undefined} onClick={onClick}
      className={["w-full text-left grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 items-baseline py-1.5", onClick ? "hover:bg-[var(--c-muted-bg)] rounded-md px-1 -mx-1" : ""].join(" ")}>
      <span className="text-[12.5px] font-semibold text-ink truncate">{label}</span>
      <span className="text-[12.5px] tabular-nums font-bold text-pine">{sub}</span>
      <span className="col-span-2 h-2 rounded-full bg-hover overflow-hidden">
        <span className={["block h-full rounded-full", cls].join(" ")} style={{ width: `${w}%` }} />
      </span>
    </Tag>
  );
}

function Stroka({ k, v, ton }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 border-b border-dashed border-border last:border-0">
      <span className="text-[12.5px] text-muted">{k}</span>
      <span className={["text-[13px] font-bold tabular-nums", ton || "text-ink"].join(" ")}>{v}</span>
    </div>
  );
}

const VYGRUZKI = [
  { ikon: "📅", t: "Табель за месяц (Т-13)", o: "Сетка «люди × числа», Excel по форме Т-13 и печать", go: () => openScreen("tabel", { tab: "mesyac" }) },
  { ikon: "📝", t: "Путевые листы", o: "Бланки по два на лист A4 и ведомость месяца по машине", go: () => openScreen("tehnika", { tab: "putevye" }) },
  { ikon: "⏳", t: "Отсрочка по делянкам", o: "Excel для заявления: делянки, у которых горит срок заготовки", go: () => openScreen("inspection") },
  { ikon: "🧾", t: "Акты и справки", o: "Акт освидетельствования, справка об объёмах — в Инспекции", go: () => openScreen("inspection") },
  { ikon: "📊", t: "Сводки ЕГАИС и расход", o: "Баланс лимитов, наряды, сводки по складам — кнопка «Сводки» в Расходе", go: () => openScreen("raskhod") },
  { ikon: "📗", t: "Книга ЛВ и ЛР", o: "Что вписать в книгу, развороты, вкладыш для печати", go: () => openScreen("kniga_lvlr") },
  { ikon: "📑", t: "Текущие изменения", o: "Ведомости для Белгослеса, прил. 1–15", go: () => openScreen("tek_izm") },
  { ikon: "⛽", t: "Топливо", o: "Заправки и расход по машинам и людям", go: () => openScreen("tehnika", { tab: "toplivo" }) },
  { ikon: "📋", t: "Журнал работ", o: "Всё, что сделано, одной лентой — с фильтрами", go: () => openScreen("raboty") },
];

function SvodkaMesyaca() {
  const [ym, setYm] = useState(tekushchiy);
  const [s, setS] = useState(null);
  const [loading, setLoading] = useState(true);
  const ref = useRef(null);

  useEffect(() => {
    let zhiv = true;
    setLoading(true);
    api.get("/otchety/svodka", { ym })
      .then((x) => zhiv && setS(x))
      .catch(() => zhiv && setS(null))
      .finally(() => zhiv && setLoading(false));
    return () => { zhiv = false; };
  }, [ym]);

  const z = s?.zagotovka;
  const dl = s?.delyanki;
  const ly = s?.lyudi;
  const th = s?.tehnika;
  const les = s?.les;
  const maxSort = Math.max(1, ...(z?.po_sortimentam || []).map((x) => x.m3));
  const maxDel = Math.max(1, ...(z?.po_delyankam || []).map((x) => x.m3));

  return (
    <div className="p-6 flex flex-col gap-5">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-surface border border-border rounded-lg shadow-card p-1">
          <button type="button" onClick={() => setYm(sdvig(ym, -1))} className="h-8 w-8 rounded-md hover:bg-hover text-muted" title="Прошлый месяц">‹</button>
          <div className="px-3 min-w-[150px] text-center font-ui font-extrabold text-pine capitalize">{nazv(ym)}</div>
          <button type="button" onClick={() => setYm(sdvig(ym, 1))} className="h-8 w-8 rounded-md hover:bg-hover text-muted" title="Следующий месяц">›</button>
        </div>
        <div className="text-[12.5px] text-muted">Сводка за месяц — для начальства и планёрки</div>
        <div className="flex-1" />
        <Button variant="primary" disabled={!s} onClick={() => napechatat(ref.current, { title: `Сводка за ${nazv(ym)}` })}>🖨 Напечатать сводку</Button>
      </div>

      {loading && !s ? <div className="text-muted">Считаю…</div> : !s ? <div className="text-muted">Сводка не загрузилась.</div> : (
        <div ref={ref} className="flex flex-col gap-4">
          <div className="grid gap-3 grid-cols-[repeat(auto-fit,minmax(200px,1fr))]">
            <StatCard icon="🪓" title="Заготовлено за месяц" value={z ? `${n1(z.m3)} м³` : "—"}
              trend={z?.izmenenie_pct != null ? { value: `${Math.abs(z.izmenenie_pct)}% к прошлому`, direction: z.izmenenie_pct < 0 ? "down" : "up" } : undefined}
              caption={z ? [`нарядов: ${z.naryadov}`, z.m3_proshlyy ? `прошлый месяц ${n1(z.m3_proshlyy)} м³` : null,
                z.m3_god_nazad ? `год назад ${n1(z.m3_god_nazad)} м³ (${z.k_godu_pct > 0 ? "+" : ""}${z.k_godu_pct}%)` : null].filter(Boolean).join(" · ") : ""}
              onClick={() => openScreen("raskhod")} />
            <StatCard icon="🌲" title="Делянки в работе" value={dl?.aktivnyh ?? "—"}
              tone={dl?.prosrocheno ? "error" : dl?.do_30_dney ? "oak" : "pine"}
              caption={dl ? (dl.prosrocheno || dl.do_30_dney ? `срок прошёл: ${dl.prosrocheno} · ≤30 дней: ${dl.do_30_dney}` : "сроки в порядке") : ""}
              onClick={() => openScreen("inspection")} />
            <StatCard icon="👷" title="Явки людей" value={ly ? ly.yavki : "—"} tone="info"
              caption={ly ? `${ly.chasov} ч · ${ly.lyudey} чел. · больничных ${ly.bolnichnyy} дн.` : ""}
              onClick={() => openScreen("tabel", { tab: "mesyac" })} />
            <StatCard icon="⛽" title="Топливо по путевым" value={th ? `${n1(th.toplivo_vsego)} л` : "—"} tone="oak"
              caption={th ? `по норме израсходовано ${n1(th.rashod_vsego)} л · машин ${th.mashiny.length}` : ""}
              onClick={() => openScreen("tehnika", { tab: "putevye" })} />
          </div>

          <div className="grid gap-4 grid-cols-[repeat(auto-fit,minmax(320px,1fr))]">
            <Card title="Заготовка по сортиментам" icon="🪵" subtitle="по нарядам за месяц" className="break-inside-avoid">
              {z?.po_sortimentam?.length ? z.po_sortimentam.map((x) => (
                <Polosa key={x.kod} label={x.nazvanie} value={x.m3} max={maxSort} sub={`${n1(x.m3)} м³`} />
              )) : <div className="text-[12.5px] text-faint py-2">В этом месяце нарядов нет.</div>}
              {z?.po_delyankam?.length > 0 && (
                <>
                  <div className="text-[11px] uppercase tracking-wide text-faint font-semibold mt-3 mb-1">Больше всего — на делянках</div>
                  {z.po_delyankam.map((x) => (
                    <Polosa key={x.id} label={x.nazvanie} value={x.m3} max={maxDel} sub={`${n1(x.m3)} м³`} cls="bg-[#7fb48e]" onClick={() => openScreen("plots", { d: x.id })} />
                  ))}
                </>
              )}
            </Card>

            <Card title="Освоение активных делянок" icon="📈" subtitle="сколько вырублено от лимита и сколько осталось до срока" className="break-inside-avoid">
              {dl?.spisok?.length ? dl.spisok.map((p) => (
                <Polosa key={p.id} label={<>{p.nazvanie}{p.dney != null && <span className={["ml-2 text-[11px] font-semibold", p.dney < 0 ? "text-error" : p.dney <= 30 ? "text-[var(--c-oak-ink)]" : "text-faint"].join(" ")}>{p.dney < 0 ? `срок прошёл ${-p.dney} дн. назад` : `${p.dney} дн. до срока`}</span>}</>}
                  value={p.pct || 0} max={100} sub={p.pct != null ? `${Math.round(p.pct)}% · ${p.fakt_fmt}/${p.limit_fmt}` : "нет лимита"} cls={LEVEL[p.level] || "bg-pine"}
                  onClick={() => openScreen("plots", { d: p.id })} />
              )) : <div className="text-[12.5px] text-faint py-2">Активных делянок нет.</div>}
            </Card>

            <Card title="Люди" icon="👷" subtitle="по табелю за месяц" className="break-inside-avoid">
              {ly ? (
                <>
                  <Stroka k="Сотрудников в табеле" v={ly.lyudey} />
                  <Stroka k="Рабочих дней по календарю" v={ly.rabochih_dney} />
                  <Stroka k="Явок (дней), всего" v={ly.yavki} ton="text-pine" />
                  <Stroka k="Отработано часов" v={ly.chasov} />
                  <Stroka k="Больничных дней" v={ly.bolnichnyy} ton={ly.bolnichnyy ? "text-[var(--c-error-ink)]" : undefined} />
                  <Stroka k="Дней отпуска" v={ly.otpusk} />
                  <Stroka k="Неявок" v={ly.nn} ton={ly.nn ? "text-error" : undefined} />
                  {ly.pusto > 0 && <Stroka k="⚠ Не заполнено прошедших будней" v={ly.pusto} ton="text-[var(--c-oak-ink)]" />}
                </>
              ) : <div className="text-[12.5px] text-faint py-2">Табель недоступен.</div>}
            </Card>

            <Card title="Техника" icon="🚜" subtitle="по путевым листам за месяц" className="break-inside-avoid">
              {th?.mashiny?.length ? (
                <table className="w-full text-[12.5px]" data-no-export>
                  <thead><tr className="text-faint text-[11px] text-right"><th className="text-left font-semibold py-1">Машина</th><th className="font-semibold">Пробег</th><th className="font-semibold">Заправка, л</th><th className="font-semibold">Расход, л</th></tr></thead>
                  <tbody>
                    {th.mashiny.map((m) => (
                      <tr key={m.id} className="border-t border-border text-right tabular-nums">
                        <td className="text-left py-1.5 font-semibold">{m.nazvanie} <span className="text-faint font-normal">{m.nomer}</span></td>
                        <td>{n1(m.probeg)} {m.edinica}</td><td>{n1(m.zapravka)}</td><td>{n1(m.rashod)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <div className="text-[12.5px] text-faint py-2">Путевых листов за месяц нет.</div>}
            </Card>

            <Card title="Лес" icon="🌱" subtitle="лесокультуры и рубки ухода за месяц" className="break-inside-avoid">
              {les ? (
                <>
                  {les.meropriyatiya.map((x) => <Stroka key={x.tip} k={x.tip} v={`${x.kol} раз`} />)}
                  <Stroka k="Рубки ухода выполнено" v={`${n1(les.uhody_ga)} га`} ton="text-pine" />
                  {!les.meropriyatiya.length && !les.uhody_ga && <div className="text-[12.5px] text-faint py-1">В этом месяце записей нет.</div>}
                </>
              ) : <div className="text-[12.5px] text-faint py-2">—</div>}
            </Card>

            <Card title="Отчёты смены с телефона" icon="📱" subtitle="что рабочие прислали за месяц" className="break-inside-avoid">
              {s.smeny?.length ? s.smeny.map((x) => (
                <Stroka key={x.vid} k={x.vid} v={[`${x.otchetov} отч.`, x.m3 ? `${n1(x.m3)} м³` : null, x.ga ? `${n1(x.ga)} га` : null].filter(Boolean).join(" · ")} />
              )) : <div className="text-[12.5px] text-faint py-2">Отчётов за месяц нет.</div>}
            </Card>
          </div>
          <div className="hidden print:flex justify-between mt-6 text-[11px]">
            <span>Составил: ____________________</span><span>Дата: ____________</span>
          </div>
        </div>
      )}

      <div className="mt-2">
        <div className="text-[11px] uppercase tracking-[.08em] text-faint font-semibold mb-2">Все выгрузки и печать — в одном месте</div>
        <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(250px,1fr))]">
          {VYGRUZKI.map((v) => (
            <Card key={v.t} onClick={v.go} title={v.t} icon={v.ikon} iconTone="info">
              <div className="text-[12px] text-muted leading-snug">{v.o}</div>
            </Card>
          ))}
          <Card title="Любая таблица → Excel" icon="↓" iconTone="pine">
            <div className="text-[12px] text-muted leading-snug">Наведите мышь на таблицу на любом экране — справа сверху появится «↓ Excel». А 🖨 в шапке вкладки печатает экран начисто.</div>
          </Card>
        </div>
      </div>
    </div>
  );
}

// «🏁 Итоги сезона» (шаг 6 разбора 09.11.2026): год целиком, по месяцам —
// пунктирная рамка = прошлый год, столбец = этот; герои сезона, техника, лес.
function ItogiSezona() {
  const [god, setGod] = useState(new Date().getFullYear());
  const [s, setS] = useState(null);
  const ref = useRef(null);
  useEffect(() => {
    let zhiv = true;
    setS(null);
    api.get("/otchety/itogi", { god }).then((x) => zhiv && setS(x)).catch(() => zhiv && setS(false));
    return () => { zhiv = false; };
  }, [god]);
  const z = s?.zagotovka;
  const ly = s?.lyudi;
  const th = s?.tehnika;
  const les = s?.les;
  const maxDel = Math.max(1, ...(z?.po_delyankam || []).map((x) => x.m3));
  const maxYav = Math.max(1, ...(ly?.geroi || []).map((x) => x.yavki));
  const MEDALI = ["🥇", "🥈", "🥉"];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-surface border border-border rounded-lg shadow-card p-1">
          <button type="button" onClick={() => setGod(god - 1)} className="h-8 w-8 rounded-md hover:bg-hover text-muted" title="Прошлый год">‹</button>
          <div className="px-3 min-w-[120px] text-center font-ui font-extrabold text-pine">Сезон {god}</div>
          <button type="button" onClick={() => setGod(god + 1)} className="h-8 w-8 rounded-md hover:bg-hover text-muted" title="Следующий год">›</button>
        </div>
        <div className="text-[12.5px] text-muted">Год целиком и сравнение с {god - 1}-м</div>
        <div className="flex-1" />
        <Button variant="primary" disabled={!s} onClick={() => napechatat(ref.current, { title: `Итоги сезона ${god}` })}>🖨 Напечатать итоги</Button>
      </div>
      {s === null ? <div className="text-muted">Считаю сезон…</div> : s === false ? <div className="text-muted">Итоги не загрузились.</div> : (
        <div ref={ref} className="flex flex-col gap-4">
          <div className="grid gap-3 grid-cols-[repeat(auto-fit,minmax(200px,1fr))]">
            <StatCard icon="🪓" title={`Заготовлено за ${god}`} value={z ? `${n1(z.m3)} м³` : "—"}
              trend={z?.izmenenie_pct != null ? { value: `${Math.abs(z.izmenenie_pct)}% к ${god - 1}`, direction: z.izmenenie_pct < 0 ? "down" : "up" } : undefined}
              caption={z ? [`нарядов ${z.naryadov} · делянок ${z.delyanok}`, z.m3_proshlyy ? `в ${god - 1}: ${n1(z.m3_proshlyy)} м³` : null, z.luchshiy_mesyac ? `лучший месяц — ${z.luchshiy_mesyac}` : null].filter(Boolean).join(" · ") : ""} />
            <StatCard icon="👷" tone="info" title="Явки за сезон" value={ly ? ly.yavki : "—"}
              caption={ly ? `${ly.chasov} ч · ${ly.lyudey} чел. · больничных ${ly.bolnichnyy} дн.` : ""} />
            <StatCard icon="⛽" tone="oak" title="Топливо по путевым" value={th ? `${n1(th.zapravka)} л` : "—"}
              caption={th ? `пробег ${n1(th.probeg)} · по норме ${n1(th.rashod)} л · листов ${th.listov}` : ""} />
            <StatCard icon="🌱" title="Рубки ухода" value={les ? `${n1(les.uhody_ga)} га` : "—"}
              caption={les ? `мероприятий в культурах: ${les.meropriyatiya.reduce((a, x) => a + x.kol, 0)}` : ""} />
          </div>
          {z && (
            <Card title="Заготовка по месяцам" icon="📊" subtitle={`столбец — ${god}, пунктирная рамка — ${god - 1}; зелёный — обогнали прошлый год`} className="break-inside-avoid">
              <BarChart categories={z.mesyacy} series={[
                { label: `${god - 1}, м³`, values: z.po_mesyacam_proshlyy, color: "var(--color-border)" },
                { label: `${god}, м³`, values: z.po_mesyacam, color: "var(--color-pine)" },
              ]} />
            </Card>
          )}
          <div className="grid gap-4 grid-cols-[repeat(auto-fit,minmax(320px,1fr))]">
            <Card title="Делянки сезона" icon="🌲" subtitle="больше всего нарубили" className="break-inside-avoid">
              {z?.po_delyankam?.length ? z.po_delyankam.map((x) => (
                <Polosa key={x.id} label={x.nazvanie} value={x.m3} max={maxDel} sub={`${n1(x.m3)} м³`} onClick={() => openScreen("plots", { d: x.id })} />
              )) : <div className="text-[12.5px] text-faint py-2">Нарядов за год нет.</div>}
            </Card>
            <Card title="Герои сезона" icon="🏅" subtitle="больше всего явок по табелю" className="break-inside-avoid">
              {ly?.geroi?.length ? ly.geroi.map((x, i) => (
                <Polosa key={x.id} label={`${MEDALI[i] || "  "} ${x.fio}`} value={x.yavki} max={maxYav} sub={`${x.yavki} дн.`} cls="bg-info"
                  onClick={() => openChelovek(x.id)} />
              )) : <div className="text-[12.5px] text-faint py-2">Табель за год пуст.</div>}
            </Card>
            <Card title="Лес за сезон" icon="🌱" subtitle="мероприятия в культурах и рубки ухода" className="break-inside-avoid">
              {les ? (
                <>
                  {les.meropriyatiya.map((x) => <Stroka key={x.tip} k={x.tip} v={`${x.kol} раз`} />)}
                  <Stroka k="Рубки ухода выполнено" v={`${n1(les.uhody_ga)} га`} ton="text-pine" />
                </>
              ) : <div className="text-[12.5px] text-faint py-2">—</div>}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Otchety() {
  const [vid, setVid] = useScreenParam("otchety", "vid");
  const sezon = vid === "sezon";
  return (
    <div>
      <div className="px-6 pt-5 -mb-2 flex gap-1.5">
        {[["", "📅 Месяц — для начальства"], ["sezon", "🏁 Итоги сезона"]].map(([k, label]) => (
          <button key={k} type="button" onClick={() => setVid(k)}
            className={["h-8 px-3 rounded-full text-[12.5px] font-semibold border transition-colors",
              (k === "sezon") === sezon ? "bg-pine text-white border-pine" : "bg-surface text-muted border-border hover:border-pine"].join(" ")}>
            {label}
          </button>
        ))}
      </div>
      {sezon ? <div className="p-6"><ItogiSezona /></div> : <SvodkaMesyaca />}
    </div>
  );
}
