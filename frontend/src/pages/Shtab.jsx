import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";
import { openScreen } from "../nav.js";

/**
 * «🏰 Штаб» — игровой вид Дашборда (03.11.2026). Карта мира: игрок
 * (уровень, XP, серия), квесты дня и шесть «локаций» — Перекличка, Фронт
 * работ, Вывозка, Охота на акты, Огород уходов, Квесты. Каждая локация —
 * свой экран в игровом виде, клик ведёт туда. Сервер: routers/shtab.py.
 */

const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6", danger: "#ba1a1a", dangerSoft: "#fdecea", sky: "#2c5d8a", skySoft: "#e6eef7",
  wood: "#9a6a3a", woodSoft: "#f6ede2",
};
const VID = { boss: { t: "БОСС", c: C.danger, bg: C.dangerSoft }, main: { t: "основной", c: C.gold, bg: C.goldSoft }, side: { t: "побочный", c: C.sky, bg: C.skySoft } };

function m3(v) {
  return `${Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} м³`;
}
function ruDen(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "long" });
}

function Lokaciya({ emoji, title, trevoga, ok, children, onGo, knopka }) {
  const ton = trevoga ? { bg: C.dangerSoft, border: "#f3c2bd" } : ok ? { bg: C.moss, border: "#bcefc5" } : { bg: "#fff", border: C.line };
  return (
    <button type="button" onClick={onGo} style={{
      textAlign: "left", background: ton.bg, border: `1.5px solid ${ton.border}`, borderRadius: 14, padding: 14,
      display: "flex", flexDirection: "column", gap: 6, position: "relative", minHeight: 150, cursor: "pointer",
    }}>
      {trevoga > 0 && (
        <span style={{
          position: "absolute", top: 10, right: 10, minWidth: 24, height: 24, borderRadius: 12, padding: "0 7px",
          background: C.danger, color: "#fff", fontWeight: 800, fontSize: 13, display: "flex", alignItems: "center", justifyContent: "center",
        }}>{trevoga}</span>
      )}
      <div className="flex items-center" style={{ gap: 10 }}>
        <span style={{ fontSize: 34, lineHeight: 1 }}>{emoji}</span>
        <span style={{ fontWeight: 800, fontSize: 16, color: C.pine }}>{title}</span>
      </div>
      <div style={{ fontSize: 13, color: C.ink, lineHeight: 1.5, flex: 1 }}>{children}</div>
      <span style={{ fontSize: 12, fontWeight: 700, color: C.pine }}>{knopka} →</span>
    </button>
  );
}

function Nedostupno() {
  return <span style={{ color: C.muted }}>Не удалось посчитать — открой экран</span>;
}

export default function Shtab() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const load = useCallback(async () => {
    try {
      setD(await api.get("/shtab"));
    } catch (e) {
      toast.show({ tone: "danger", title: "Штаб не отвечает", description: e.message });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Трубим сбор в штабе… 📯</div>;
  const { igrok: ig, pereklichka: pk, front: fr, ohota: oh, vyvozka: vy, ogorod: og } = d;
  const u = ig?.uroven;
  const pctUr = u ? Math.round((u.xp_v_urovne / u.nado) * 100) : 0;
  const trevog = (fr?.gorit || 0) + (oh?.ushla || 0) + (vy?.gorit || 0);

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      {ig && (
        <div style={{
          display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.2fr)", gap: 16,
          background: `linear-gradient(120deg, ${C.pine}, #2d5e45)`, color: "#fff", borderRadius: 16, padding: 18,
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 13, opacity: 0.8 }}>{ruDen(d.segodnya)} · {ig.shutka}</div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>Уровень {u.n} · {u.zvanie}</div>
            <div style={{ height: 10, borderRadius: 5, background: "rgba(255,255,255,.2)", overflow: "hidden" }}>
              <div style={{ width: `${pctUr}%`, height: "100%", background: "#f3c94a" }} />
            </div>
            <div className="flex flex-wrap" style={{ gap: 14, fontSize: 13 }}>
              <span>{u.xp_v_urovne} / {u.nado} XP до следующего</span>
              <span>⚡ сегодня +{ig.segodnya_xp}</span>
              <span>🔥 серия {ig.seriya} дн.</span>
            </div>
            <div style={{ fontSize: 14, marginTop: 4 }}>
              {trevog > 0 ? `🚨 Тревог на карте: ${trevog}. Начни с красных локаций.` : "🌲 На карте спокойно — можно и чай попить."}
            </div>
          </div>
          <div style={{ background: "rgba(255,255,255,.08)", borderRadius: 12, padding: 12 }}>
            <div className="flex justify-between" style={{ fontWeight: 800, marginBottom: 6 }}>
              <span>🎯 Квесты дня · {ig.kvestov_otkryto}</span>
              <span style={{ fontWeight: 400, fontSize: 13, opacity: 0.8 }}>сделано {ig.kvestov_sdelano}{ig.svoi_otkryto ? ` · своих ${ig.svoi_otkryto}` : ""}</span>
            </div>
            {ig.kvesty.length === 0 && <div style={{ fontSize: 13, opacity: 0.85 }}>Все квесты зачищены. Легенда! 🏆</div>}
            {ig.kvesty.map((q) => {
              const v = VID[q.vid] || VID.side;
              return (
                <button key={q.id} type="button" onClick={() => openScreen(q.screen, q.params || {})} style={{
                  display: "flex", width: "100%", alignItems: "center", gap: 8, textAlign: "left", padding: "6px 8px", borderRadius: 8,
                  background: "rgba(255,255,255,.95)", color: C.ink, marginBottom: 5,
                }}>
                  <span style={{ fontSize: 10, fontWeight: 800, padding: "2px 6px", borderRadius: 4, background: v.bg, color: v.c, textTransform: "uppercase" }}>{v.t}</span>
                  <span style={{ flex: 1, fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{q.title}</span>
                  <span style={{ fontSize: 12, color: C.gold, fontWeight: 800 }}>+{q.xp}</span>
                </button>
              );
            })}
            {ig.kvestov_otkryto > ig.kvesty.length && (
              <button type="button" onClick={() => openScreen("kvesty")} style={{ fontSize: 13, color: "#fff", opacity: 0.85 }}>
                и ещё {ig.kvestov_otkryto - ig.kvesty.length} → все квесты
              </button>
            )}
          </div>
        </div>
      )}

      <div style={{ fontWeight: 800, color: C.pine, fontSize: 16 }}>🗺 Карта мира</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
        <Lokaciya emoji="📋" title="Перекличка" knopka="Отметить табель"
          trevoga={pk && !pk.vyhodnoy && pk.otmecheno < pk.vsego && new Date().getHours() >= 15 ? pk.vsego - pk.otmecheno : 0}
          ok={pk && pk.vsego > 0 && pk.otmecheno >= pk.vsego}
          onGo={() => openScreen("tabel", { tab: "vvod" })}>
          {!pk ? <Nedostupno /> : pk.vyhodnoy && pk.otmecheno === 0 ? "Выходной — табель отдыхает 😴" : (
            <>Сегодня отмечено <b>{pk.otmecheno} из {pk.vsego}</b>, работали {pk.rabotali}.
              {pk.otmecheno < pk.vsego ? " Кого-то не хватает 👀" : " Все на месте ✅"}</>
          )}
        </Lokaciya>

        <Lokaciya emoji="🗺" title="Фронт работ" knopka="Расставить людей" trevoga={fr?.gorit || 0}
          ok={fr && !fr.gorit && fr.v_plane >= fr.lyudey && fr.lyudey > 0} onGo={() => openScreen("raspredelenie")}>
          {!fr ? <Nedostupno /> : (
            <>На {ruDen(fr.data)} в плане <b>{fr.v_plane} из {fr.lyudey}</b> человек, делянок {fr.delyanok}.
              {fr.gorit > 0 && <div style={{ color: C.danger, fontWeight: 600 }}>🔥 Горит: {fr.gorit_imena.join(", ")}</div>}</>
          )}
        </Lokaciya>

        <Lokaciya emoji="🚛" title="Вывозка" knopka="К складам" trevoga={vy?.gorit || 0} ok={vy && !vy.gorit}
          onGo={() => openScreen("raskhod", { tab: "vyvozka" })}>
          {!vy ? <Nedostupno /> : (
            <>Лежит на складах <b>{m3(vy.na_skladah)}</b>, за неделю вывезли {m3(vy.eta_nedelya)}
              {vy.eta_nedelya >= vy.proshlaya_nedelya ? " ▲" : " ▼"}.
              {vy.gorit > 0 && <div style={{ color: C.danger, fontWeight: 600 }}>🔥 {vy.gorit_imena.join(", ")}</div>}
              {vy.musor > 0 && <div style={{ color: C.gold }}>🧹 Мусор в ЕГАИС: {vy.musor}</div>}
              {vy.robot && <div style={{ color: C.muted, fontSize: 12 }}>🤖 {vy.robot.text}</div>}</>
          )}
        </Lokaciya>

        <Lokaciya emoji="🏹" title="Охота на акты" knopka="На охоту" trevoga={oh?.ushla || 0}
          ok={oh && !oh.ushla && !oh.mushka} onGo={() => openScreen("inspection", { tab: "ohota" })}>
          {!oh ? <Nedostupno /> : (
            <>🐗 ушли <b>{oh.ushla}</b> · 🎯 на мушке <b>{oh.mushka}</b> · 🔒 в капкане {oh.kapkan}
              <div>🏆 трофеев за год: {oh.trofei}</div>
              {oh.ushla > 0 && <div style={{ color: C.danger, fontWeight: 600 }}>Просрочен акт: {oh.ushla_imena.join(", ")}</div>}</>
          )}
        </Lokaciya>

        <Lokaciya emoji="🌱" title="Огород уходов" knopka="В огород" ok={og && !og.uchastkov_uhod && !og.uchastkov_osvetlenie}
          onGo={() => openScreen("forestry", { tab: "ogorod" })}>
          {!og ? <Nedostupno /> : (
            <>Сезон {og.sezon}: уходов сделано <b>{og.uhodov_sdelano} из {og.uhodov_nado}</b>.
              <div>🔥 жаждут ухода: {og.uchastkov_uhod} ({og.ga_uhod} га)</div>
              <div>🪓 ждут осветления: {og.uchastkov_osvetlenie} ({og.ga_osvetlenie} га)</div></>
          )}
        </Lokaciya>

        <Lokaciya emoji="🎯" title="Квесты" knopka="Все квесты и ачивки" ok={ig && ig.kvestov_otkryto === 0}
          onGo={() => openScreen("kvesty")}>
          {!ig ? <Nedostupno /> : (
            <>Открыто {ig.kvestov_otkryto}, сделано сегодня {ig.kvestov_sdelano}. Всего опыта <b>{ig.xp.toLocaleString("ru-RU")} XP</b>.
              <div className="flex" style={{ gap: 3, marginTop: 6, alignItems: "flex-end", height: 28 }}>
                {(ig.nedelya || []).map((x) => {
                  const max = Math.max(1, ...ig.nedelya.map((y) => y.xp));
                  return <span key={x.den} title={`${x.den}: ${x.xp} XP`} style={{ flex: 1, height: Math.max(3, (x.xp / max) * 28), borderRadius: 2, background: x.zachten ? C.gold : C.line }} />;
                })}
              </div></>
          )}
        </Lokaciya>
      </div>
      <div style={{ fontSize: 12, color: C.muted }}>
        Обычный дашборд — на вкладке «Обзор». Цифры локаций считаются так же, как на их экранах.
      </div>
    </div>
  );
}
