import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";
import { openScreen } from "../nav.js";

/**
 * «🧑‍🌾 Карточки героев» — игровой вид экрана «Сотрудники» (этап 4,
 * 03.11.2026). Колода карточек как в коллекционной игре: уровень и звание,
 * класс, характеристики, навыки, места, напарник, форма, ачивки.
 * Сервер: routers/geroi.py (только чтение, очки — как в «Рейтинге»).
 */

const C = {
  pine: "#1a4331", leaf: "#3f7d4e", moss: "#eaf7ec", line: "#e5e2db", muted: "#565f59", ink: "#1c1c18",
  gold: "#b07d0c", goldSoft: "#fbf1d6",
};
const RAMKA = [ // по уровню: бронза → серебро → золото → легенда
  { ot: 1, bg: "linear-gradient(160deg, #f6ede2, #fff)", border: "#d8b994", metka: "🥉" },
  { ot: 5, bg: "linear-gradient(160deg, #eef1f4, #fff)", border: "#aeb8c2", metka: "🥈" },
  { ot: 9, bg: "linear-gradient(160deg, #fbf1d6, #fff)", border: "#e0b94a", metka: "🥇" },
  { ot: 15, bg: "linear-gradient(160deg, #e9e2fb, #fff)", border: "#9b7fe0", metka: "💎" },
];
const HAR = [
  ["sila", "💪 Сила", "м³ по нарядам за год"],
  ["vynoslivost", "🫀 Выносливость", "дней в лесу за 60 дней"],
  ["nadezhnost", "🎯 Надёжность", "% выполненных задач плана"],
  ["opyt", "🧭 Опыт", "разных мест в табеле"],
];

function ramka(lvl) {
  return [...RAMKA].reverse().find((r) => lvl >= r.ot) || RAMKA[0];
}
function initsialy(fio) {
  const p = (fio || "").split(/\s+/).filter(Boolean);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase();
}
function m3(v) {
  return `${Number(v || 0).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} м³`;
}
function ruDen(iso) {
  return iso ? new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "";
}

function Polosa({ pct, color = C.leaf, h = 6 }) {
  return (
    <span style={{ display: "block", height: h, borderRadius: h, background: "#ece9e2", overflow: "hidden" }}>
      <span style={{ display: "block", height: "100%", width: `${Math.max(0, Math.min(pct, 100))}%`, background: color, borderRadius: h }} />
    </span>
  );
}

function Karta({ g, onOpen }) {
  const r = ramka(g.uroven);
  const est = g.achivki.filter((a) => a.est);
  return (
    <button type="button" onClick={onOpen} style={{
      textAlign: "left", background: r.bg, border: `2px solid ${r.border}`, borderRadius: 16, padding: 14,
      display: "flex", flexDirection: "column", gap: 10, position: "relative", boxShadow: "0 2px 6px rgba(0,0,0,.05)",
    }}>
      <span style={{ position: "absolute", top: 10, right: 12, fontSize: 18 }} title="рамка по уровню">{r.metka}</span>
      <div className="flex items-center" style={{ gap: 12 }}>
        <span style={{
          width: 54, height: 54, borderRadius: 14, background: C.pine, color: "#fff", fontWeight: 900, fontSize: 19,
          display: "flex", alignItems: "center", justifyContent: "center", position: "relative", flexShrink: 0,
        }}>
          {initsialy(g.fio)}
          <span style={{
            position: "absolute", bottom: -7, right: -7, background: C.gold, color: "#fff", borderRadius: 10,
            fontSize: 11, fontWeight: 900, padding: "1px 6px", border: "2px solid #fff",
          }}>{g.uroven}</span>
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 800, fontSize: 15, color: C.ink }}>{g.fio}</div>
          <div style={{ fontSize: 12.5, color: C.muted }}>{g.zvanie} · {g.klass}</div>
        </div>
      </div>
      <div>
        <div className="flex justify-between" style={{ fontSize: 11, color: C.muted, marginBottom: 3 }}>
          <span>{g.ochki} очк.</span><span>до {g.uroven + 1}-го уровня {g.do - g.ochki}</span>
        </div>
        <Polosa pct={g.pct} color={C.gold} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 12px" }}>
        {HAR.map(([k, l]) => (
          <div key={k} style={{ fontSize: 11.5 }}>
            <div className="flex justify-between"><span>{l}</span><b>{g.harakteristiki[k].znach}</b></div>
            <Polosa pct={g.harakteristiki[k].pct} h={4} />
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between" style={{ fontSize: 12, color: C.muted, gap: 8 }}>
        {est.length ? (
          <span style={{ fontSize: 16, letterSpacing: 2 }} title={est.map((a) => a.title).join(", ")}>{est.map((a) => a.z).join("")}</span>
        ) : <span>🔒 ачивок пока нет</span>}
        {g.mesto_mesyaca && <span>#{g.mesto_mesyaca} в месяце</span>}
      </div>
    </button>
  );
}

function Forma({ forma }) {
  const max = Math.max(1, ...forma.map((f) => f.ochki));
  return (
    <div className="flex" style={{ gap: 4, alignItems: "flex-end", height: 60 }}>
      {forma.map((f, i) => (
        <div key={f.nedelya} title={`неделя с ${f.nedelya}: ${f.ochki} очк.`} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
          <span style={{ width: "100%", height: Math.max(2, (f.ochki / max) * 44), borderRadius: 3, background: i === forma.length - 1 ? C.gold : C.leaf }} />
          <span style={{ fontSize: 9.5, color: C.muted }}>{f.nedelya}</span>
        </div>
      ))}
    </div>
  );
}

function Blok({ title, children }) {
  return (
    <div style={{ border: `1px solid ${C.line}`, borderRadius: 12, padding: 12 }}>
      <div style={{ fontWeight: 800, fontSize: 13, color: C.pine, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13, lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

function Podrobno({ g, okno }) {
  const maxNav = Math.max(1, ...g.navyki.map((n) => n.dni));
  const trend = g.forma.length >= 2 ? g.forma[g.forma.length - 2].ochki : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="flex items-center" style={{ gap: 14, background: C.pine, color: "#fff", borderRadius: 14, padding: 14 }}>
        <span style={{ width: 64, height: 64, borderRadius: 16, background: "#fff", color: C.pine, fontWeight: 900, fontSize: 24, display: "flex", alignItems: "center", justifyContent: "center" }}>
          {initsialy(g.fio)}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: "#bcefc5" }}>{g.dolzhnost || "—"}{g.zveno ? ` · звено ${g.zveno.emoji} ${g.zveno.nazvanie}` : ""}</div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>Уровень {g.uroven} · {g.zvanie}</div>
          <div style={{ fontSize: 13 }}>{g.klass}</div>
          <div style={{ marginTop: 6 }}><Polosa pct={g.pct} color="#e0b94a" /></div>
          <div style={{ fontSize: 11.5, color: "#bcefc5", marginTop: 3 }}>{g.ochki} очк. за всё время · до следующего уровня {g.do - g.ochki}</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Blok title="📊 Характеристики (к лучшему в команде)">
          {HAR.map(([k, l, opis]) => (
            <div key={k} style={{ marginBottom: 6 }}>
              <div className="flex justify-between"><span>{l}</span><b>{g.harakteristiki[k].znach}</b></div>
              <Polosa pct={g.harakteristiki[k].pct} />
              <div style={{ fontSize: 11, color: C.muted }}>{k === "vynoslivost" ? `дней в лесу за ${okno} дней` : opis}</div>
            </div>
          ))}
        </Blok>
        <Blok title="🛠 Навыки (дней по виду работ)">
          {g.navyki.length === 0 ? <span style={{ color: C.muted }}>В табеле виды работ не отмечены</span> : g.navyki.map((n) => (
            <div key={n.vid} style={{ marginBottom: 6 }}>
              <div className="flex justify-between"><span>{n.vid}</span><b>{n.dni}</b></div>
              <Polosa pct={(n.dni / maxNav) * 100} color={C.gold} />
            </div>
          ))}
        </Blok>
        <Blok title="📈 Форма за 8 недель">
          <Forma forma={g.forma} />
          <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>
            Эта неделя: <b>{g.forma[g.forma.length - 1]?.ochki || 0}</b> очк. (прошлая {trend})
            {g.mesto_mesyaca && <> · в рейтинге месяца <b>#{g.mesto_mesyaca}</b> из {g.v_igre_mesyaca}</>}
          </div>
        </Blok>
        <Blok title="🗺 Любимые места">
          {g.mesta.length === 0 ? <span style={{ color: C.muted }}>Мест в табеле нет</span> : g.mesta.map((m) => (
            <div key={m.mesto} className="flex justify-between"><span>{m.mesto}</span><span style={{ color: C.muted }}>{m.dni} дн., посл. {ruDen(m.posledniy)}</span></div>
          ))}
          {g.seychas && <div style={{ marginTop: 6 }}>Сейчас: <b>{g.seychas.mesto || "—"}</b>{g.seychas.vid ? `, ${g.seychas.vid}` : ""} ({ruDen(g.seychas.data)})</div>}
          {g.naparnik && <div>🤝 Лучший напарник: <b>{g.naparnik.fio}</b> — вместе {g.naparnik.dney} дн.</div>}
        </Blok>
      </div>

      <Blok title={`🏅 Ачивки — открыто ${g.achivok} из ${g.achivki.length}`}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8 }}>
          {g.achivki.map((a) => (
            <div key={a.kod} title={a.opis} style={{
              border: `1px solid ${a.est ? "#e0b94a" : C.line}`, background: a.est ? C.goldSoft : "#faf9f6",
              borderRadius: 10, padding: 8, opacity: a.est ? 1 : 0.75,
            }}>
              <div style={{ fontSize: 22, filter: a.est ? "none" : "grayscale(1)" }}>{a.est ? a.z : "🔒"}</div>
              <div style={{ fontWeight: 700, fontSize: 12.5 }}>{a.title}</div>
              <div style={{ fontSize: 11, color: C.muted }}>{a.opis}</div>
              {!a.est && <div style={{ marginTop: 4 }}><Polosa pct={a.progress} h={4} /><span style={{ fontSize: 10.5, color: C.muted }}>{a.tek} / {a.nado}</span></div>}
            </div>
          ))}
        </div>
      </Blok>

      <div style={{ fontSize: 12, color: C.muted }}>
        Всего: {g.kariera.dni} дн. в лесу, {m3(g.kariera.kuby)} по нарядам, задач плана {g.kariera.zadachi}, трелёвка {m3(g.kariera.trelevka)}.
        В табеле с {g.v_tabele_s ? ruDen(g.v_tabele_s) : "—"}. Очки — как в «Рейтинге», для азарта, а не для зарплаты 😉
      </div>
    </div>
  );
}

const SORT = [
  ["ochki", "По уровню"],
  ["god", "Очки за год"],
  ["achivki", "По ачивкам"],
  ["fio", "По алфавиту"],
];

export default function Geroi() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [vybran, setVybran] = useState(null);
  const [sort, setSort] = useState("ochki");

  const load = useCallback(async () => {
    try {
      setD(await api.get("/geroi"));
    } catch (e) {
      toast.show({ tone: "danger", title: "Карточки не загрузились", description: e.message });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  if (!d) return <div style={{ padding: 24, color: C.muted }}>Тасуем колоду… 🃏</div>;
  const geroi = [...d.geroi].sort((a, b) => {
    if (sort === "fio") return a.fio.localeCompare(b.fio, "ru");
    if (sort === "god") return b.god.ochki - a.god.ochki;
    if (sort === "achivki") return b.achivok - a.achivok || b.ochki - a.ochki;
    return b.ochki - a.ochki;
  });
  const g = d.geroi.find((x) => x.id === vybran);

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: 10 }}>
        <div style={{ fontSize: 14, color: C.muted, maxWidth: 760 }}>
          <b style={{ color: C.pine }}>🧑‍🌾 Карточки героев.</b> Уровень растёт от очков за всё время (как в «Рейтинге»),
          рамка по уровню: 🥉 → 🥈 с 5-го → 🥇 с 9-го → 💎 с 15-го. Нажми карточку — откроется профиль.{" "}
          <button type="button" onClick={() => openScreen("reyting")} style={{ color: C.pine, textDecoration: "underline" }}>Рейтинг →</button>
        </div>
        <div className="flex" style={{ gap: 4, background: "#f3f1ec", padding: 3, borderRadius: 10 }}>
          {SORT.map(([k, l]) => (
            <button key={k} type="button" onClick={() => setSort(k)} aria-pressed={sort === k} style={{
              padding: "5px 12px", borderRadius: 8, fontSize: 13, fontWeight: 700,
              background: sort === k ? "#fff" : "transparent", color: sort === k ? C.pine : C.muted,
            }}>{l}</button>
          ))}
        </div>
      </div>

      {geroi.length === 0 ? (
        <div style={{ padding: 30, textAlign: "center", color: C.muted, border: `1px dashed ${C.line}`, borderRadius: 14 }}>
          В справочнике нет активных сотрудников — добавь их во вкладке «Список».
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(270px, 1fr))", gap: 14 }}>
          {geroi.map((x) => <Karta key={x.id} g={x} onOpen={() => setVybran(x.id)} />)}
        </div>
      )}

      <Modal open={!!g} onClose={() => setVybran(null)} title={g ? `🧑‍🌾 ${g.fio}` : ""} size="lg">
        {g && <Podrobno g={g} okno={d.okno_vynoslivosti} />}
      </Modal>
    </div>
  );
}
