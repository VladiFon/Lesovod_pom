import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useVid } from "../vid.jsx";

// Группы и подписи — из дизайна «Вкладки - новый дизайн»: тёмно-зелёная
// узкая колонка; клик по пункту открывает (или фокусирует) вкладку.
// Шаг 4 разбора (03.11.2026): 21 пункт → 16. «С телефона» = отчёты (бывший
// ИИ-журнал) + заметки; «Табель» = ввод + присутствие; «Задачи» = план
// работ + календарь (вкладки внутри экрана, см. App.jsx).
// Шаг 4 разбора «сайт разбросан» (04.11.2026): меню по делам, а не по
// тому, откуда пришли данные. Ключи экранов прежние — ссылки и закладки
// не ломаются; уехавшие вкладки «С телефона» — алиасы в nav.js.
// Шаг 3 разбора сайта (09.11.2026): меню 25 → 16 пунктов по делам.
// «Дашборд» стал «Сегодня», появились «Отчёты»; Текущие изменения + Книга
// ЛВ/ЛР — один экран «Формы и книги»; Документы, Схема, Архив, Корзина,
// Настройки уехали в «⋯ Ещё» под именем пользователя; игровые экраны —
// своей группой, только в игровом виде. Счётчики у пунктов — из /api/zhdet.
// Ключи экранов прежние: ссылки, закладки и Ctrl+K не ломаются.
export const NAV_GROUPS = [
  { title: "сегодня", items: [["dashboard", "Сегодня"], ["telefon", "Входящие"], ["otchety", "Отчёты"]] },
  { title: "заготовка", items: [["plots", "Делянки"], ["raskhod", "Расход / ЕГАИС"], ["inspection", "Инспекция"], ["raspredelenie", "Бригады"]] },
  { title: "лес", items: [["taxation", "Выдел"], ["forestry", "Лесокультуры"], ["uhody", "Рубки ухода"], ["formy", "Формы и книги"]] },
  {
    title: "люди и техника",
    items: [["sotrudniki", "Люди"], ["tabel", "Табель"], ["zadachi", "Задачи"], ["raboty", "Журнал работ"], ["tehnika", "Техника и путевые"]],
  },
  { title: "игра", igra: true, items: [["kvesty", "🎯 Квесты"], ["gazeta", "📰 Газета"], ["reyting", "🏆 Рейтинг"], ["chellendzhi", "🔥 Челленджи"]] },
  {
    title: "ещё",
    footer: true,
    items: [["skhema", "🗺 Схема сайта"], ["documents", "📄 Документы"], ["archive", "🗄 Архив"], ["korzina", "🗑 Корзина"], ["settings", "⚙ Настройки"]],
  },
];

// Пункты меню, которые видны не всем ролям (права — из /api/auth/me).
export const NAV_PERMISSION = { korzina: "korzina.view" };

const MONO = "'JetBrains Mono', monospace";

const POLL_MS = 120000;

// Счётчики у пунктов меню: сколько ждёт разбора на этом экране (/api/zhdet).
function useSchetchiki() {
  const [s, setS] = useState({});
  useEffect(() => {
    let zhiv = true;
    const load = () => api.get("/zhdet").then((d) => {
      if (!zhiv) return;
      const out = {};
      (d?.items || []).forEach((i) => {
        const o = (out[i.screen] = out[i.screen] || { n: 0, tone: "info" });
        o.n += i.count;
        if (i.tone === "danger" || (i.tone === "warning" && o.tone === "info")) o.tone = i.tone;
      });
      setS(out);
    }).catch(() => {}); // фон — тихо, ошибку покажет сам экран
    load();
    const t = setInterval(load, POLL_MS);
    window.addEventListener("focus", load);
    return () => { zhiv = false; clearInterval(t); window.removeEventListener("focus", load); };
  }, []);
  return s;
}

const BADGE = { danger: { bg: "#ff8a80", fg: "#3a0603" }, warning: { bg: "#f2b667", fg: "#3a2400" }, info: { bg: "#bcefc5", fg: "#0f2a1d" } };

export default function Sidebar({ openKeys = [], activeKey, onNavigate, user, onLogout, permissions = [] }) {
  const [vid] = useVid();
  const schet = useSchetchiki();
  const [esche, setEsche] = useState(false);
  const escheRef = useRef(null);
  const mozhno = ([key]) => !NAV_PERMISSION[key] || permissions.includes(NAV_PERMISSION[key]);

  useEffect(() => {
    if (!esche) return undefined;
    const onDown = (e) => { if (escheRef.current && !escheRef.current.contains(e.target)) setEsche(false); };
    const onKey = (e) => e.key === "Escape" && setEsche(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [esche]);

  const punkt = ([key, label]) => {
    const isActive = key === activeKey;
    const isOpen = openKeys.includes(key);
    const c = schet[key];
    return (
      <button
        key={key}
        type="button"
        onClick={() => onNavigate?.(key)}
        aria-current={isActive ? "page" : undefined}
        className="flex items-center justify-between w-full text-left rounded-lg hover:!bg-[#235a41] hover:!text-white"
        style={{
          gap: 6,
          padding: "7px 8px",
          fontSize: 13.5,
          fontWeight: isActive ? 700 : 500,
          border: 0,
          cursor: "pointer",
          background: isActive ? "#235a41" : "transparent",
          color: isActive ? "#fff" : "#d7ecdd",
        }}
      >
        <span className="truncate">{label}</span>
        <span className="flex items-center shrink-0" style={{ gap: 5 }}>
          {c?.n > 0 && (
            <span title="Ждёт разбора" style={{ minWidth: 18, height: 17, padding: "0 5px", borderRadius: 999, fontSize: 10.5, fontWeight: 800, lineHeight: "17px", textAlign: "center", background: BADGE[c.tone].bg, color: BADGE[c.tone].fg }}>
              {c.n > 99 ? "99+" : c.n}
            </span>
          )}
          {isOpen && <span style={{ width: 6, height: 6, borderRadius: 999, background: "#bcefc5" }} />}
        </span>
      </button>
    );
  };

  const footer = NAV_GROUPS.find((g) => g.footer);
  const escheAktiven = footer.items.some(([k]) => k === activeKey);

  return (
    <nav className="w-[166px] shrink-0 h-screen flex flex-col overflow-y-auto" style={{ background: "#1a4331", color: "#eaf7ec" }}>
      <div style={{ padding: "18px 16px 14px" }}>
        <div style={{ fontWeight: 800, fontSize: 17, color: "#fff", lineHeight: 1.1 }}>Лесовод</div>
        <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: ".14em", textTransform: "uppercase", color: "#bcefc5", marginTop: 3 }}>
          рабочий стол
        </div>
      </div>

      <div className="flex flex-col flex-1" style={{ gap: 14, padding: "0 8px 16px" }}>
        {NAV_GROUPS.filter((g) => !g.footer && (!g.igra || vid === "igra")).map((group) => (
          <div key={group.title} className="flex flex-col" style={{ gap: 2 }}>
            <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: ".12em", textTransform: "uppercase", color: "#8fb79f", padding: "6px 8px 4px" }}>
              {group.title}
            </div>
            {group.items.filter(mozhno).map(punkt)}
          </div>
        ))}
      </div>

      {/* «⋯ Ещё» — редкие экраны и руководство, под именем пользователя */}
      <div ref={escheRef} className="relative" style={{ borderTop: "1px solid #235a41" }}>
        {esche && (
          <div className="absolute left-2 right-2 bottom-full mb-1 flex flex-col rounded-xl shadow-hover" style={{ background: "#12321f", border: "1px solid #2c6449", padding: 6, gap: 2, zIndex: 30 }}>
            {footer.items.filter(mozhno).map(([key, label]) => punkt([key, label]))}
            <a href="/guide/index.html" target="_blank" rel="noreferrer" className="rounded-lg hover:!bg-[#235a41] hover:!text-white"
              style={{ padding: "7px 8px", fontSize: 13.5, color: "#d7ecdd", textDecoration: "none" }}>
              📖 Руководство
            </a>
          </div>
        )}
        <div className="flex items-center justify-between" style={{ padding: "10px 10px 10px 14px", gap: 6 }}>
          <button type="button" onClick={() => setEsche(!esche)} aria-expanded={esche} title="Схема сайта, документы, архив, корзина, настройки, руководство"
            className="min-w-0 flex-1 text-left rounded-lg hover:!bg-[#235a41]" style={{ background: escheAktiven || esche ? "#235a41" : "transparent", border: 0, padding: "4px 6px", margin: "-4px -6px", cursor: "pointer" }}>
            <div className="truncate" style={{ fontSize: 12.5, fontWeight: 700, color: "#eaf7ec" }}>{user?.fio ?? "Гость"}</div>
            <div className="truncate" style={{ fontFamily: MONO, fontSize: 9.5, color: "#8fb79f" }}>{user?.role ?? ""} · ⋯ ещё</div>
          </button>
          {onLogout && (
            <button
              type="button"
              onClick={onLogout}
              title="Выйти"
              aria-label="Выйти"
              className="shrink-0 hover:!text-white"
              style={{ background: "transparent", border: 0, color: "#8fb79f", cursor: "pointer", fontSize: 14 }}
            >
              ⎋
            </button>
          )}
        </div>
      </div>
    </nav>
  );
}
