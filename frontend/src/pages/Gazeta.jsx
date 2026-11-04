import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";
import { openScreen } from "../nav.js";

/**
 * «📰 Лесная правда» — газета недели в игровом виде (этап 2, 03.11.2026).
 * Вёрстка сама собирается из базы (routers/gazeta.py): передовица, герои,
 * лесоповал, вывозка, инспекция, огород, почта, анонсы, анекдот. Листается
 * по неделям, печатается на А4 — повесить в конторе на стенку.
 */

const P = {
  paper: "#f8f4e9", ink: "#1f1b16", muted: "#6b6256", rule: "#2b261f", soft: "#d9d0bd",
  red: "#a3201b", pine: "#1a4331",
};
const SERIF = "Georgia, 'PT Serif', 'Times New Roman', serif";

const PRINT_CSS = `
@media print {
  @page { size: A4; margin: 10mm; }
  body.pechat-gazety * { visibility: hidden !important; }
  body.pechat-gazety .lp-gazeta, body.pechat-gazety .lp-gazeta * { visibility: visible !important; }
  body.pechat-gazety .lp-gazeta {
    position: absolute; left: 0; top: 0; width: 100%; max-width: none !important; zoom: .9;
    box-shadow: none !important; border: none !important; padding: 0 !important; background: #fff !important;
  }
  body.pechat-gazety .lp-gazeta * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body.pechat-gazety .lp-gazeta section { break-inside: avoid; }
  body.pechat-gazety .lp-net-pechati { display: none !important; }
}`;

function m3(v) {
  return `${Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} м³`;
}

function Strelka({ pct }) {
  if (pct === null || pct === undefined) return null;
  const up = pct >= 0;
  return <span style={{ color: up ? P.pine : P.red, fontWeight: 700, fontSize: 13 }}> {up ? "▲" : "▼"} {Math.abs(pct)}%</span>;
}

function Rubrika({ title, children, onGo, span }) {
  return (
    <section style={{ gridColumn: span ? "1 / -1" : undefined, borderTop: `2px solid ${P.rule}`, paddingTop: 8, minWidth: 0 }}>
      <div className="flex items-baseline justify-between" style={{ gap: 8 }}>
        <h3 style={{ fontFamily: SERIF, fontWeight: 800, fontSize: 15, textTransform: "uppercase", letterSpacing: ".06em", margin: 0 }}>{title}</h3>
        {onGo && (
          <button type="button" className="lp-net-pechati" onClick={onGo} style={{ fontSize: 12, color: P.muted, textDecoration: "underline" }}>
            подробнее
          </button>
        )}
      </div>
      <div style={{ fontFamily: SERIF, fontSize: 14, lineHeight: 1.55, marginTop: 6 }}>{children}</div>
    </section>
  );
}

function Pusto({ children }) {
  return <div style={{ color: P.muted, fontStyle: "italic" }}>{children}</div>;
}

function Stolbiki({ dni }) {
  const max = Math.max(1, ...dni.map((x) => x.obyom));
  return (
    <div className="flex" style={{ gap: 6, alignItems: "flex-end", height: 70, marginTop: 8 }}>
      {dni.map((x) => (
        <div key={x.den} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
          <span style={{ fontSize: 10, color: P.muted }}>{x.obyom ? Math.round(x.obyom) : ""}</span>
          <span style={{
            width: "100%", height: Math.max(2, (x.obyom / max) * 46),
            background: x.budushchee ? "transparent" : P.ink, border: x.budushchee ? `1px dashed ${P.soft}` : "none",
          }} />
          <span style={{ fontSize: 11 }}>{x.den}</span>
        </div>
      ))}
    </div>
  );
}

export default function Gazeta() {
  const toast = useToast();
  const [nedelya, setNedelya] = useState("");
  const [d, setD] = useState(null);

  const load = useCallback(async () => {
    try {
      setD(await api.get("/gazeta", nedelya ? { nedelya } : {}));
    } catch (e) {
      toast.show({ tone: "danger", title: "Газета не напечаталась", description: e.message });
    }
  }, [nedelya]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const pechat = () => {
    document.body.classList.add("pechat-gazety");
    const snyat = () => { document.body.classList.remove("pechat-gazety"); window.removeEventListener("afterprint", snyat); };
    window.addEventListener("afterprint", snyat);
    window.print();
    setTimeout(snyat, 1500);
  };

  if (!d) return <div style={{ padding: 24, color: P.muted, fontFamily: SERIF }}>Типография разогревается… 🗞</div>;
  const p = d.peredovica;
  const ge = d.geroi;
  const [glavnyy, ...podzag] = d.zagolovki;

  return (
    <div style={{ padding: "14px 18px 40px" }}>
      <style>{PRINT_CSS}</style>
      <div className="flex flex-wrap items-center justify-between lp-net-pechati" style={{ gap: 10, marginBottom: 12, maxWidth: 1060, marginInline: "auto" }}>
        <div className="flex items-center" style={{ gap: 6 }}>
          <button type="button" onClick={() => setNedelya(d.pred)} style={btn}>← Прошлый номер</button>
          <button type="button" onClick={() => d.sled && setNedelya(d.sled)} disabled={!d.sled} style={{ ...btn, opacity: d.sled ? 1 : 0.4 }}>
            Следующий →
          </button>
          {!d.tekushchaya && <button type="button" onClick={() => setNedelya("")} style={btn}>Свежий номер</button>}
        </div>
        <button type="button" onClick={pechat} style={{ ...btn, background: P.ink, color: P.paper }}>🖨 Распечатать на стенку</button>
      </div>

      <article className="lp-gazeta" style={{
        maxWidth: 1060, margin: "0 auto", background: P.paper, color: P.ink, padding: "22px 28px 26px",
        boxShadow: "0 2px 14px rgba(0,0,0,.12)", border: `1px solid ${P.soft}`,
      }}>
        <header style={{ textAlign: "center", borderBottom: `4px double ${P.rule}`, paddingBottom: 8 }}>
          <div className="flex justify-between" style={{ fontSize: 11, color: P.muted, fontFamily: SERIF, gap: 8 }}>
            <span>№ {d.nomer} · {d.god}</span>
            <span>Выходит по понедельникам с {d.god} года</span>
            <span>Тираж: 1 экз. · Цена: бесценно</span>
          </div>
          <div style={{ fontFamily: SERIF, fontSize: 52, fontWeight: 900, letterSpacing: ".04em", lineHeight: 1.05, margin: "6px 0 2px" }}>
            ЛЕСНАЯ ПРАВДА
          </div>
          <div style={{ fontFamily: SERIF, fontSize: 13, fontStyle: "italic" }}>
            Еженедельник лесничества · неделя {d.ot}–{d.do_vs}{d.tekushchaya && d.do !== d.do_vs ? ` (номер верстается, данные по ${d.do})` : ""}
          </div>
        </header>

        {d.prazdnik && (
          <div style={{ textAlign: "center", fontFamily: SERIF, fontWeight: 800, color: P.red, marginTop: 10, fontSize: 16 }}>🎉 {d.prazdnik}</div>
        )}

        <div style={{ margin: "14px 0 10px", textAlign: "center" }}>
          <h1 style={{ fontFamily: SERIF, fontSize: 32, fontWeight: 900, lineHeight: 1.15, margin: 0 }}>{glavnyy}</h1>
          {podzag.length > 0 && (
            <div style={{ fontFamily: SERIF, fontSize: 15, color: P.muted, marginTop: 6 }}>{podzag.join(" · ")}</div>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "16px 24px" }}>
          <Rubrika title="Передовица">
            {!p ? <Pusto>Цифры не сошлись — редакция разбирается.</Pusto> : (
              <>
                Заготовлено {d.istochnik_zagotovki === "ЕГАИС" ? "по ЕГАИС" : "по нарядам"} <b>{m3(p.kuby)}</b><Strelka pct={p.kuby_pct} />, вывезено по ЕГАИС <b>{m3(p.vyvezeno)}</b>
                <Strelka pct={p.vyvezeno_pct} />.{" "}
                В лесу отработано <b>{p.chelovekodni}</b> человеко-дн. (на прошлой неделе за те же дни {p.chelovekodni_prosh}).
                {(p.bolnichnyh > 0 || p.otpusk > 0) && <> На больничном {p.bolnichnyh} дн., в отпуске {p.otpusk} дн. — выздоравливайте и отдыхайте!</>}
                {p.progulov > 0 && <> Без уважительной {p.progulov} дн. — редакция грозит пальцем ☝️</>}
              </>
            )}
          </Rubrika>

          <Rubrika title="🏅 Герои недели" onGo={() => openScreen("reyting")}>
            {!ge || ge.top.length === 0 ? <Pusto>Героев не видно — табель пуст. Ждём подвигов!</Pusto> : (
              <>
                {ge.top.map((x, i) => (
                  <div key={x.fio}>
                    {["🥇", "🥈", "🥉"][i]} <b>{x.fio}</b> — {x.ochki} очк.
                    <span style={{ color: P.muted, fontSize: 12 }}> ({x.dni} дн., {m3(x.kuby)}{x.zadachi ? `, задач ${x.zadachi}` : ""}{x.trelevka ? `, трелёвка ${m3(x.trelevka)}` : ""})</span>
                  </div>
                ))}
                {ge.nichya.length > 1 && <div style={{ fontStyle: "italic", marginTop: 4 }}>На вершине ничья — решится на следующей неделе!</div>}
                {ge.ryvok && <div style={{ marginTop: 4 }}>🚀 Рывок недели: <b>{ge.ryvok.fio}</b>, +{ge.ryvok.rost} очк. к прошлой неделе.</div>}
                {ge.zveno && <div>⚔️ Звено недели: {ge.zveno.emoji} <b>{ge.zveno.nazvanie}</b>, в среднем {ge.zveno.srednee} очк.</div>}
              </>
            )}
          </Rubrika>

          <Rubrika title="📅 Анонсы" onGo={() => openScreen("inspection", { tab: "ohota" })}>
            {!d.tekushchaya ? <Pusto>Анонсы печатаются только в свежем номере.</Pusto>
              : !d.anonsy || d.anonsy.length === 0 ? <Pusto>Ближайшие две недели — без горящих сроков. Можно выдохнуть.</Pusto> : (
                d.anonsy.map((a, i) => (
                  <div key={i} style={{ color: a.dney <= 7 ? P.red : P.ink }}>
                    <b>{a.data}</b> — {a.text}{a.dney === 0 ? " (сегодня!)" : ""}
                  </div>
                ))
              )}
          </Rubrika>

          <Rubrika title="🪓 С лесосек" onGo={() => openScreen("raspredelenie")}>
            {!d.lesopoval ? <Pusto>Сводка не дошла.</Pusto> : d.lesopoval.delyanki.length === 0 ? <Pusto>Нарядов за неделю нет — пилы отдыхают.</Pusto> : (
              <>
                {d.lesopoval.delyanki.map((x) => <div key={x.nazvanie}>{x.nazvanie} — <b>{m3(x.obyom)}</b></div>)}
                {d.lesopoval.rekord && <div style={{ marginTop: 4 }}>Самый жаркий день: {d.lesopoval.rekord.den}, {m3(d.lesopoval.rekord.obyom)}.</div>}
                <Stolbiki dni={d.lesopoval.dni} />
              </>
            )}
          </Rubrika>

          <Rubrika title="🚛 Вывозка" onGo={() => openScreen("raskhod", { tab: "vyvozka" })}>
            {!d.vyvozka ? <Pusto>ЕГАИС молчит.</Pusto> : d.vyvozka.kuda.length === 0 ? <Pusto>Лесовозы стояли — расхода по ЕГАИС нет.</Pusto> : (
              <>
                Вывозили {d.vyvozka.dney_s_vyvozkoy} дн.{d.vyvozka.rekord && <>, больше всего — {d.vyvozka.rekord.den}: {m3(d.vyvozka.rekord.obyom)}</>}.
                <div style={{ marginTop: 4 }}>Куда ушло:</div>
                {d.vyvozka.kuda.map((x) => <div key={x.kto}>· {x.kto} — {m3(x.obyom)}</div>)}
                <div style={{ marginTop: 4 }}>Больше всех оформил: <b>{d.vyvozka.kto[0].kto}</b> ({m3(d.vyvozka.kto[0].obyom)}).</div>
              </>
            )}
          </Rubrika>

          <Rubrika title="🏹 Инспекция" onGo={() => openScreen("inspection", { tab: "ohota" })}>
            {!d.inspekciya ? <Pusto>Комиссия на выезде.</Pusto> : (
              <>
                {d.inspekciya.akty.length === 0 ? "Актов за неделю не составляли." : (
                  <>Составлены акты: {d.inspekciya.akty.map((a) => `${a.nazvanie} (${a.data})`).join(", ")}. Трофеи на стену! 🏆</>
                )}
                {d.inspekciya.rozysk_vsego > 0 && (
                  <div style={{ marginTop: 6, border: `2px solid ${P.red}`, padding: "6px 8px", color: P.red }}>
                    <b>РАЗЫСКИВАЮТСЯ</b> делянки, сбежавшие от акта: {d.inspekciya.rozysk.join(", ")}
                    {d.inspekciya.rozysk_vsego > d.inspekciya.rozysk.length ? ` и ещё ${d.inspekciya.rozysk_vsego - d.inspekciya.rozysk.length}` : ""}.
                  </div>
                )}
                {d.inspekciya.mushka > 0 && <div style={{ marginTop: 4 }}>🎯 На мушке (срок ≤ 14 дн.): {d.inspekciya.mushka}.</div>}
              </>
            )}
          </Rubrika>

          <Rubrika title="🌱 Огород уходов" onGo={() => openScreen("forestry", { tab: "ogorod" })}>
            {!d.ogorod ? <Pusto>Огородник не ответил.</Pusto> : d.ogorod.vsego === 0 ? <Pusto>На культурах тихо — уходов за неделю не записано.</Pusto> : (
              <>
                {d.ogorod.po_tipu.map((x) => <div key={x.tip}>{x.tip}: <b>{x.n}</b></div>)}
                <div style={{ color: P.muted, fontSize: 12, marginTop: 4 }}>Где: {d.ogorod.uchastki.join(", ")}{d.ogorod.vsego > d.ogorod.uchastki.length ? "…" : ""}</div>
              </>
            )}
          </Rubrika>

          <Rubrika title="📬 Почта с мест" onGo={() => openScreen("telefon", { tab: "pochta" })}>
            {!d.pochta ? <Pusto>Гонцы задержались.</Pusto> : (
              <>
                Принято отчётов о работах: <b>{d.pochta.rabot}</b>, заметок от рабочих: <b>{d.pochta.zametok}</b>.
                {d.pochta.pisatel && <div style={{ marginTop: 4 }}>✍️ Самый пишущий: <b>{d.pochta.pisatel.fio}</b> ({d.pochta.pisatel.n}).</div>}
              </>
            )}
          </Rubrika>

          <Rubrika title="😄 Анекдот недели">
            <div style={{ whiteSpace: "pre-line", fontStyle: "italic" }}>{d.anekdot}</div>
          </Rubrika>
        </div>

        <footer style={{ borderTop: `4px double ${P.rule}`, marginTop: 18, paddingTop: 6, fontSize: 11, color: P.muted, fontFamily: SERIF, textAlign: "center" }}>
          Номер собран программой «Лесовод» из ЕГАИС, нарядов, табеля, актов и журнала лесокультур. Главный редактор — робот, корректор — Влад.
          {d.oshibki && <span> Не сверстались рубрики: {Object.keys(d.oshibki).join(", ")}.</span>}
        </footer>
      </article>
    </div>
  );
}

const btn = {
  padding: "6px 12px", borderRadius: 8, fontSize: 13, fontWeight: 700, background: "#fff",
  border: "1px solid #d9d0bd", color: "#1f1b16",
};
