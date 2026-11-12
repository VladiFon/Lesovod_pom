import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";
import { openScreen, useScreenParam } from "../nav.js";

/**
 * «🧭 Путь делянки» — игровой вид экрана «Делянки» (этап 3, 03.11.2026).
 * Каждая делянка идёт по дороге МДО → Билет → Рубка → Вывозка → Акт →
 * Закрыта. Видно, где она стоит, сколько дней без движения и какой срок
 * горит. Закрытые за год — гонка на скорость прохождения пути.
 * Сервер: routers/put_delyanki.py (только чтение).
 */

const C = {
  pine: "var(--color-pine)", leaf: "var(--c-green-2)", moss: "var(--color-mint-soft)", line: "var(--color-border)", muted: "var(--color-muted-2)", ink: "var(--color-ink)",
  gold: "var(--c-gold)", goldSoft: "var(--c-gold-soft)", danger: "var(--color-error)", dangerSoft: "var(--c-error-soft-2)", warn: "#a15c00", warnSoft: "#fff4e0",
};
const TON = {
  bad: { bg: C.dangerSoft, border: "var(--c-error-line)", c: C.danger },
  warn: { bg: C.warnSoft, border: "#f5d9a8", c: C.warn },
  ok: { bg: "var(--color-surface)", border: C.line, c: C.pine },
  done: { bg: C.moss, border: "var(--color-mint)", c: C.pine },
};
const KUDA = {
  mdo: (id) => openScreen("plots", { tab: "spisok", d: id }),
  bilet: (id) => openScreen("plots", { tab: "spisok", d: id }),
  rubka: (id) => openScreen("raskhod", { tab: "raskhod", d: id }),
  vyvozka: () => openScreen("raskhod", { tab: "vyvozka" }),
  akt: (id) => openScreen("inspection", { tab: "spisok", d: id }),
  zakryta: (id) => openScreen("inspection", { tab: "spisok", d: id }),
};
const SHAG = {
  bilet: "Внеси номер и дату лесорубочного билета",
  rubka: "Рубят — заноси наряды",
  vyvozka: "Вывозят — ЕГАИС покажет, когда склад опустеет",
  akt: "Пора составлять акт освидетельствования",
  zakryta: "Акт есть — закрой делянку",
};

function Stanciya({ kod, emoji, title, s, tek, onGo }) {
  const done = s.done;
  const cur = tek === kod;
  const bg = done ? C.leaf : cur ? "var(--color-surface)" : "var(--c-muted-bg)";
  const border = done ? C.leaf : cur ? C.gold : C.line;
  const srok = s.srok;
  return (
    <button type="button" onClick={onGo} title={`${title}${s.data ? ` — ${s.data}` : ""}`} style={{
      display: "flex", flexDirection: "column", alignItems: "center", gap: 3, width: 92, flexShrink: 0, position: "relative", zIndex: 1,
    }}>
      <span style={{
        width: cur ? 46 : 38, height: cur ? 46 : 38, borderRadius: "50%", background: bg, border: `3px solid ${border}`,
        display: "flex", alignItems: "center", justifyContent: "center", fontSize: cur ? 22 : 17,
        filter: !done && !cur ? "grayscale(1)" : "none", opacity: !done && !cur ? 0.55 : 1,
        boxShadow: cur ? `0 0 0 5px ${C.goldSoft}` : "none",
      }}>{done ? "✓" : emoji}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color: done || cur ? C.ink : C.muted }}>{title}</span>
      <span style={{ fontSize: 11, color: C.muted, minHeight: 14, textAlign: "center", lineHeight: 1.25 }}>
        {done ? (s.data || "") : cur && s.pct != null ? `${Math.round(s.pct)}%` : ""}
        {!done && srok && (
          <span style={{ display: "block", color: srok.dney < 0 ? C.danger : srok.dney <= 14 ? C.warn : C.muted, fontWeight: srok.dney <= 14 ? 700 : 400 }}>
            {srok.dney < 0 ? `просрочен ${-srok.dney} дн.` : `до ${srok.data.slice(0, 5)}`}
          </span>
        )}
      </span>
    </button>
  );
}

function Doroga({ x, stancii }) {
  const t = TON[x.ton] || TON.ok;
  const n = stancii.length;
  const tekIdx = stancii.findIndex((s) => s.kod === x.tekushchaya);
  const proydeno = x.tekushchaya ? tekIdx : n - 1;
  return (
    <div style={{ background: t.bg, border: `1.5px solid ${t.border}`, borderRadius: 14, padding: "12px 14px" }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 8, marginBottom: 8 }}>
        <button type="button" onClick={() => KUDA.mdo(x.id)} style={{ fontWeight: 800, fontSize: 15, color: C.pine, textAlign: "left" }}>
          {x.nazvanie}
          {x.status === "черновик" && <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 700, color: C.muted }}>черновик</span>}
          {x.chuzhaya && <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 700, color: C.muted }}>сторонняя заготовка</span>}
        </button>
        <div className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 12.5 }}>
          {x.gorit && <span style={{ color: t.c, fontWeight: 700 }}>🔥 {x.gorit}</span>}
          {x.stoit != null && (
            <span title={`последнее событие ${x.posledneye}`} style={{ color: x.zastryala ? C.warn : C.muted, fontWeight: x.zastryala ? 700 : 400 }}>
              {x.zastryala ? "🐌" : "⏱"} стоит {x.stoit} дн.
            </span>
          )}
          {x.otsrochek > 0 && <span style={{ color: C.muted }}>⏳ отсрочек {x.otsrochek}</span>}
        </div>
      </div>
      <div style={{ position: "relative", overflowX: "auto" }}>
        <div className="flex" style={{ justifyContent: "space-between", position: "relative", minWidth: n * 92 }}>
          <span style={{ position: "absolute", left: 46, right: 46, top: 21, height: 4, background: C.line, borderRadius: 2 }} />
          <span style={{
            position: "absolute", left: 46, top: 21, height: 4, borderRadius: 2, background: C.leaf,
            width: `calc((100% - 92px) * ${Math.max(proydeno, 0) / (n - 1)})`,
          }} />
          {stancii.map((s) => (
            <Stanciya key={s.kod} kod={s.kod} emoji={s.emoji} title={s.title} s={x.stancii[s.kod]} tek={x.tekushchaya}
              onGo={() => KUDA[s.kod](x.id)} />
          ))}
        </div>
      </div>
      {x.tekushchaya && (
        <div style={{ fontSize: 12.5, color: C.muted, marginTop: 6 }}>
          👉 {SHAG[x.tekushchaya] || ""}
          {x.tekushchaya === "vyvozka" && x.stancii.vyvozka.lezhit != null && ` · на складе ${x.stancii.vyvozka.lezhit} м³`}
          {x.stancii.rubka.info && ` · ${x.stancii.rubka.info}`}
        </div>
      )}
    </div>
  );
}

const FILTRY = [
  ["vse", "Все в пути"],
  ["gorit", "🔥 Горят"],
  ["zastryali", "🐌 Застряли"],
];

export default function PutDelyanki() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [filtr, setFiltr] = useState("vse");
  const [stanciya, setStanciya] = useState(null);
  const [dParam] = useScreenParam("plots", "d");

  // Пришли «открыть делянку» (из Таксации, навигации) — в обычный список.
  useEffect(() => {
    if (dParam) openScreen("plots", { tab: "spisok" });
  }, [dParam]);

  const load = useCallback(async () => {
    try {
      setD(await api.get("/put-delyanki"));
    } catch (e) {
      toast.show({ tone: "danger", title: "Карта дорог не загрузилась", description: e.message });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Прокладываем дороги… 🧭</div>;

  let spisok = d.v_puti;
  if (filtr === "gorit") spisok = spisok.filter((x) => x.ton === "bad" || (x.gorit && x.ton === "warn"));
  if (filtr === "zastryali") spisok = spisok.filter((x) => x.zastryala);
  if (stanciya) spisok = spisok.filter((x) => x.tekushchaya === stanciya);

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: C.pine, color: "#fff", borderRadius: 16, padding: "16px 18px" }}>
        <div className="flex flex-wrap items-baseline justify-between" style={{ gap: 10 }}>
          <div style={{ fontWeight: 800, fontSize: 18 }}>🧭 Путь делянки</div>
          <div style={{ fontSize: 13, color: "var(--color-mint)" }}>
            В пути {d.v_puti.length} · 🔥 горят {d.goryat} · 🐌 застряли ({d.zastryala_dney}+ дн. без событий) {d.zastryali}
          </div>
        </div>
        <div className="flex" style={{ gap: 6, marginTop: 14, overflowX: "auto" }}>
          {d.stancii.map((s, i) => {
            const act = stanciya === s.kod;
            return (
              <React.Fragment key={s.kod}>
                {i > 0 && <span style={{ alignSelf: "center", color: "var(--color-mint)", fontSize: 18 }}>→</span>}
                <button type="button" onClick={() => setStanciya(act ? null : s.kod)} aria-pressed={act} style={{
                  flex: 1, minWidth: 92, borderRadius: 12, padding: "8px 6px", textAlign: "center",
                  background: act ? "var(--color-surface)" : "rgba(255,255,255,.08)", color: act ? C.pine : "#fff",
                  border: `1px solid ${act ? "var(--color-surface)" : "rgba(255,255,255,.18)"}`,
                }}>
                  <div style={{ fontSize: 22 }}>{s.emoji}</div>
                  <div style={{ fontSize: 12.5, fontWeight: 700 }}>{s.title}</div>
                  <div style={{ fontSize: 20, fontWeight: 900 }}>{s.kod === "zakryta" ? d.finish.length : s.delyanok}</div>
                </button>
              </React.Fragment>
            );
          })}
        </div>
        <div style={{ fontSize: 12, color: "var(--color-mint)", marginTop: 8 }}>
          Цифра — сколько делянок стоит на станции сейчас (у «Закрыта» — финишировали в этом году). Нажми станцию — покажу только их.
        </div>
      </div>

      <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
        {FILTRY.map(([k, l]) => (
          <button key={k} type="button" onClick={() => setFiltr(k)} aria-pressed={filtr === k} style={{
            padding: "5px 12px", borderRadius: 999, fontSize: 13, fontWeight: 700,
            background: filtr === k ? C.pine : "var(--color-surface)", color: filtr === k ? "#fff" : C.pine, border: `1px solid ${filtr === k ? C.pine : C.line}`,
          }}>{l}</button>
        ))}
        {stanciya && (
          <button type="button" onClick={() => setStanciya(null)} style={{ fontSize: 13, color: C.muted, textDecoration: "underline" }}>
            сбросить станцию
          </button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 16, alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
          {stanciya === "zakryta" ? (
            d.finish.map((x) => <Doroga key={x.id} x={x} stancii={d.stancii} />)
          ) : spisok.length === 0 ? (
            <div style={{ padding: 30, textAlign: "center", color: C.muted, border: `1px dashed ${C.line}`, borderRadius: 14 }}>
              Тут пусто — дороги свободны 🛣
            </div>
          ) : spisok.map((x) => <Doroga key={x.id} x={x} stancii={d.stancii} />)}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: C.goldSoft, border: "1px solid var(--c-gold-line)", borderRadius: 14, padding: 14 }}>
            <div style={{ fontWeight: 800, color: C.gold, marginBottom: 6 }}>🏁 Гонка {new Date().getFullYear()}</div>
            {d.finish.length === 0 ? (
              <div style={{ fontSize: 13, color: C.muted }}>В этом году ещё никто не финишировал. Первый закрытый — сразу рекорд!</div>
            ) : (
              <>
                {d.rekord && (
                  <div style={{ fontSize: 13, marginBottom: 6 }}>
                    Рекорд: <b>{d.rekord.nazvanie}</b> — путь за <b>{d.rekord.dney} дн.</b>
                    {d.srednij_put && <div style={{ color: C.muted }}>в среднем {d.srednij_put} дн.</div>}
                  </div>
                )}
                {d.finish.map((x, i) => (
                  <button key={x.id} type="button" onClick={() => KUDA.akt(x.id)} className="flex justify-between" style={{
                    width: "100%", fontSize: 13, padding: "4px 0", borderTop: i ? `1px solid var(--c-gold-line)` : "none", textAlign: "left",
                  }}>
                    <span>{["🥇", "🥈", "🥉"][i] || "▫️"} {x.nazvanie}</span>
                    <span style={{ fontWeight: 700 }}>{x.put_dney != null ? `${x.put_dney} дн.` : "—"}</span>
                  </button>
                ))}
                <div style={{ fontSize: 11.5, color: C.muted, marginTop: 6 }}>
                  Путь = от первого события (заведена / билет / наряд) до акта.
                </div>
              </>
            )}
          </div>
          <div style={{ background: "var(--color-surface)", border: `1px solid ${C.line}`, borderRadius: 14, padding: 14, fontSize: 12.5, color: C.muted, lineHeight: 1.55 }}>
            <b style={{ color: C.pine }}>Как читаются станции</b>
            <div>🪓 Рубка пройдена — площадь закрыта по нарядам или справкой заготовителя.</div>
            <div>🚛 Вывозка пройдена — склад делянки по ЕГАИС пуст.</div>
            <div>📜 Акт — есть акт освидетельствования.</div>
            <div>Кружок станции кликается — откроет нужный экран.</div>
          </div>
        </div>
      </div>
    </div>
  );
}
