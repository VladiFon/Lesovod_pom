import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";
import { openScreen, useScreenParam } from "../nav.js";
import Lesopoval from "./Lesopoval.jsx";

/**
 * «🚛 Вывозка» — игровой вид экрана «Расход / ЕГАИС» (03.11.2026).
 * Склады делянок: что лежит (приход − расход по ЕГАИС), темп вывозки,
 * успеют ли к сроку вывозки. Табло: расход по дням, неделя к неделе,
 * рекорд, серия, кто оформил больше, куда ушло, «мусор» разбора ЕГАИС,
 * робот вечерней выгрузки. Сервер: backend/app/routers/vyvozka_igra.py.
 * Остатки и быстрый наряд — «🪓 Лесоповал» (Lesopoval.jsx); правка нарядов и ЕГАИС — вкладка «Расход».
 */

const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dangerSoft: "#fdecea", sky: "#2c5d8a", skySoft: "#e6eef7",
  wood: "#9a6a3a", woodSoft: "#f6ede2",
};
const MEDALI = ["🥇", "🥈", "🥉"];
const SHUTKI = {
  bad: ["Лес не склад — вывози!", "Короед уже точит зубы 🐛", "Лесовозы, на выход!"],
  idle: ["Штабель скучает", "Тишина на погрузке"],
  ok: ["Колёса крутятся ✨", "Так держать!"],
  pusto: [""],
};

function m3(v) {
  return v == null ? "—" : `${Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} м³`;
}
function shutka(ton, id) {
  const s = SHUTKI[ton] || [""];
  return s[id % s.length];
}

function Chip({ children, bg, color, title }) {
  return (
    <span title={title} className="inline-flex items-center" style={{
      gap: 4, padding: "5px 11px", borderRadius: 999, background: bg, color, fontWeight: 700, fontSize: 13,
    }}>{children}</span>
  );
}

function Shtabel({ na, prihod }) {
  // Штабель из брёвнышек: до 12 штук, сколько ещё лежит от прихода.
  const vsego = 12;
  const lezhit = prihod > 0 ? Math.max(na > 0 ? 1 : 0, Math.round((na / prihod) * vsego)) : 0;
  return (
    <div title={`Лежит ${m3(na)} из прихода ${m3(prihod)}`} style={{ display: "flex", flexWrap: "wrap-reverse", width: 66, gap: 2 }}>
      {Array.from({ length: vsego }).map((_, i) => (
        <span key={i} style={{
          width: 20, height: 9, borderRadius: 5, border: `1px solid ${i < lezhit ? C.wood : C.line}`,
          background: i < lezhit ? "#c99560" : "transparent",
        }} />
      ))}
    </div>
  );
}

function Sklad({ x, onLesopoval }) {
  const tone = {
    bad: { bg: C.dangerSoft, border: "#f3c2bd", color: C.danger },
    ok: { bg: C.moss, border: "#bcefc5", color: C.leaf },
    idle: { bg: "#fff", border: C.line, color: C.muted },
    pusto: { bg: "#faf9f6", border: C.line, color: C.muted },
  }[x.ton];
  return (
    <div style={{ background: "#fff", border: `1.5px solid ${x.ton === "bad" ? "#f3c2bd" : C.line}`, borderRadius: 12, padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="flex items-start" style={{ gap: 10 }}>
        <Shtabel na={x.na_sklade} prihod={x.prihod} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, color: C.ink }}>{x.nazvanie}</div>
          <div style={{ fontSize: 12, color: C.muted }}>
            {x.status === "архив" ? "закрыта · " : ""}{x.zagotovitel ? `рубит ${x.zagotovitel} · ` : ""}
            {x.srok_vyvozki ? `вывозка до ${x.srok_vyvozki}${x.dni_do != null ? ` · ${x.dni_do < 0 ? `просрочено ${-x.dni_do} дн.` : `${x.dni_do} дн.`}` : ""}` : "срок вывозки не задан"}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontWeight: 800, fontSize: 18, color: x.na_sklade > 0 ? C.wood : C.muted }}>{m3(x.na_sklade)}</div>
          <div style={{ fontSize: 11, color: C.muted }}>лежит</div>
        </div>
      </div>
      {x.pct_vyvezeno != null && (
        <div title={`Вывезено ${m3(x.raskhod)} из ${m3(x.prihod)}`}>
          <div style={{ height: 8, borderRadius: 4, background: C.line, overflow: "hidden" }}>
            <div style={{ width: `${Math.min(100, x.pct_vyvezeno)}%`, height: "100%", background: C.leaf }} />
          </div>
          <div className="flex justify-between" style={{ fontSize: 12, color: C.muted, marginTop: 3, fontFamily: "'JetBrains Mono', monospace" }}>
            <span>вывезено {x.pct_vyvezeno}%</span>
            <span>{x.temp ? `${x.temp} м³/день` : "темп —"}</span>
          </div>
        </div>
      )}
      {x.na_sklade > 0 && (x.delovaya > 0 || x.drova > 0) && (
        <div style={{ fontSize: 12, color: C.muted }}>деловая {m3(x.delovaya)} · дрова {m3(x.drova)}{x.posledniy ? ` · последний расход ${x.posledniy}` : ""}</div>
      )}
      <div style={{ padding: "6px 9px", borderRadius: 8, background: tone.bg, color: tone.color, fontSize: 13, fontWeight: 600 }}>{x.verdikt}</div>
      <div className="flex items-center justify-between" style={{ gap: 8 }}>
        <span style={{ fontSize: 12, color: C.muted, fontStyle: "italic" }}>{shutka(x.ton, x.id)}</span>
        <button type="button" onClick={() => onLesopoval(x)} style={{
          padding: "5px 11px", borderRadius: 8, fontWeight: 700, fontSize: 12, border: `1px solid ${C.wood}`, color: "#fff", background: C.wood, whiteSpace: "nowrap",
        }}>🪓 Остатки и наряд</button>
      </div>
    </div>
  );
}

function Tablo({ po_dnyam, rekord }) {
  const max = Math.max(1, ...po_dnyam.map((d) => d.obyom));
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: 12 }}>
      <div className="flex justify-between" style={{ fontSize: 13, color: C.muted, marginBottom: 8 }}>
        <b style={{ color: C.pine }}>🚛 Расход ЕГАИС по дням, 4 недели</b>
        {rekord && <span>рекорд — {m3(rekord.obyom)} ({rekord.data})</span>}
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 90 }}>
        {po_dnyam.map((d) => {
          const h = d.obyom > 0 ? Math.max(4, (d.obyom / max) * 86) : 2;
          const dt = new Date(d.data);
          return (
            <div key={d.data} title={`${dt.toLocaleDateString("ru-RU")}: ${m3(d.obyom)}`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}>
              <div style={{
                height: h, borderRadius: "3px 3px 0 0",
                background: d.obyom === 0 ? (d.vyhodnoy ? "transparent" : C.line) : rekord && d.obyom >= rekord.obyom ? C.gold : C.leaf,
              }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 3, marginTop: 3 }}>
        {po_dnyam.map((d) => {
          const dt = new Date(d.data);
          return (
            <div key={d.data} style={{ flex: 1, textAlign: "center", fontSize: 9, color: d.vyhodnoy ? "#b5b0a6" : C.muted }}>
              {dt.getDay() === 1 || po_dnyam.length < 15 ? dt.getDate() : ""}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function VyvozkaIgra() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [lesopoval, setLesopoval] = useState(null);
  const [dParam] = useScreenParam("raskhod", "d");
  const [razborParam] = useScreenParam("raskhod", "razbor");

  // Пришли по ссылке на делянку или на разбор — сразу в обычный Расход.
  useEffect(() => {
    if (dParam || razborParam) openScreen("raskhod", { tab: "raskhod" });
  }, [dParam, razborParam]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    try {
      setD(await api.get("/vyvozka-igra"));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить вывозку", description: e.message });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Заводим лесовозы… 🚛</div>;

  const bad = d.delyanki.filter((x) => x.ton === "bad").length;
  const delta = d.eta_nedelya - d.proshlaya_nedelya;
  const musor = d.razbor.korrektirovki + d.razbor.sklady + d.razbor.fls;
  const robotOk = d.robot?.text?.startsWith("✅");

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 14, color: C.muted }}>
        <b style={{ color: C.pine }}>🚛 Вывозка</b> — что лежит на складах делянок по ЕГАИС (приход − расход) и успеют ли
        вывезти к сроку. Темп — расход ЕГАИС за {d.temp_dney} дней. Склад считается за делянкой только по привязке складов,
        как в «Разборе ЕГАИС».
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <Chip bg={C.woodSoft} color={C.wood}>🪵 Лежит на складах: {m3(d.itogo_na_skladah)}</Chip>
        <Chip bg={bad ? C.dangerSoft : "#f3f1ec"} color={bad ? C.danger : C.muted}>🔥 Горит складов: {bad}</Chip>
        <Chip bg={C.moss} color={C.leaf} title={`Прошлая неделя за те же дни: ${m3(d.proshlaya_nedelya)}`}>
          🚛 Эта неделя: {m3(d.eta_nedelya)} {delta > 0.05 ? "▲" : delta < -0.05 ? "▼" : "="} {m3(Math.abs(delta))}
        </Chip>
        {d.seriya > 0 && <Chip bg={C.goldSoft} color={C.gold} title="Рабочих дней подряд с расходом в ЕГАИС">🔥 Серия: {d.seriya} раб. дн.</Chip>}
        {d.robot && (
          <Chip bg={robotOk ? C.skySoft : C.dangerSoft} color={robotOk ? C.sky : C.danger} title={d.robot.text}>
            🤖 {robotOk ? "Робот выгружал" : "Робот споткнулся"} {(() => { const t = String(d.robot.created_at || ""); return t.length >= 16 ? `${t.slice(8, 10)}.${t.slice(5, 7)} в ${t.slice(11, 16)}` : ""; })()}
          </Chip>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 16, alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Tablo po_dnyam={d.po_dnyam} rekord={d.rekord} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 12 }}>
            {d.delyanki.map((x) => <Sklad key={x.id} x={x} onLesopoval={setLesopoval} />)}
          </div>
        </div>

        <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: 12 }}>
            <div style={{ fontWeight: 800, color: C.pine, marginBottom: 6 }}>🧾 Кто оформил больше · месяц</div>
            {d.kto.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>В этом месяце расхода ещё не было</div>}
            {d.kto.map((k, i) => (
              <div key={k.kto} className="flex justify-between" style={{ fontSize: 13, padding: "4px 0", borderTop: i ? `1px solid ${C.line}` : "none" }}>
                <span>{MEDALI[i] || "▫️"} {k.kto}</span>
                <span style={{ color: C.muted }}>{m3(k.obyom)} · {k.docs} док.</span>
              </div>
            ))}
          </div>
          <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: 12 }}>
            <div style={{ fontWeight: 800, color: C.pine, marginBottom: 6 }}>📦 Куда ушло · месяц</div>
            {d.kuda.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>Пока никуда</div>}
            {d.kuda.map((k) => {
              const max = d.kuda[0].obyom || 1;
              return (
                <div key={k.kuda} style={{ fontSize: 13, padding: "3px 0" }}>
                  <div className="flex justify-between"><span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{k.kuda}</span><span style={{ color: C.muted }}>{m3(k.obyom)}</span></div>
                  <div style={{ height: 4, borderRadius: 2, background: C.line }}><div style={{ width: `${(k.obyom / max) * 100}%`, height: "100%", borderRadius: 2, background: C.sky }} /></div>
                </div>
              );
            })}
          </div>
          <div style={{ background: musor ? C.goldSoft : C.moss, border: `1px solid ${musor ? "#efd9a4" : "#bcefc5"}`, borderRadius: 12, padding: 12 }}>
            <div style={{ fontWeight: 800, color: C.pine, marginBottom: 6 }}>🧹 Мусор в ЕГАИС: {musor}</div>
            {musor === 0 ? (
              <div style={{ fontSize: 13, color: C.leaf }}>Чисто, как после санитарки 🌲</div>
            ) : (
              <>
                <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.6 }}>
                  {d.razbor.sklady > 0 && <div>склады без делянки: {d.razbor.sklady}</div>}
                  {d.razbor.korrektirovki > 0 && <div>корректировки: {d.razbor.korrektirovki}</div>}
                  {d.razbor.fls > 0 && <div>приход ФЛС: {d.razbor.fls}</div>}
                </div>
                <button type="button" onClick={() => openScreen("raskhod", { tab: "raskhod", razbor: "1" })} style={{
                  marginTop: 8, padding: "6px 12px", borderRadius: 8, fontWeight: 700, fontSize: 13, background: C.pine, color: "#fff",
                }}>Разгрести</button>
              </>
            )}
          </div>
        </aside>
      </div>
      <Lesopoval delyanka={lesopoval} onClose={() => setLesopoval(null)} onSaved={load} />
    </div>
  );
}
