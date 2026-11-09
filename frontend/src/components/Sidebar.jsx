import React from "react";
import { useVid } from "../vid.jsx";

// Группы и подписи — из дизайна «Вкладки - новый дизайн»: тёмно-зелёная
// узкая колонка; клик по пункту открывает (или фокусирует) вкладку.
// Шаг 4 разбора (03.11.2026): 21 пункт → 16. «С телефона» = отчёты (бывший
// ИИ-журнал) + заметки; «Табель» = ввод + присутствие; «Задачи» = план
// работ + календарь (вкладки внутри экрана, см. App.jsx).
// Шаг 4 разбора «сайт разбросан» (04.11.2026): меню по делам, а не по
// тому, откуда пришли данные. Ключи экранов прежние — ссылки и закладки
// не ломаются; уехавшие вкладки «С телефона» — алиасы в nav.js.
export const NAV_GROUPS = [
  {
    title: "сегодня",
    items: [["dashboard", "Дашборд"], ["telefon", "📥 Входящие"], ["skhema", "🗺 Схема сайта"], ["kvesty", "🎯 Квесты"], ["gazeta", "📰 Газета"]],
  },
  {
    title: "заготовка",
    items: [["plots", "Делянки"], ["raskhod", "Расход / ЕГАИС"], ["inspection", "Инспекция"], ["documents", "Документы"], ["raspredelenie", "Бригады"]],
  },
  { title: "лес", items: [["taxation", "Выдел"], ["forestry", "Лесокультуры"], ["kniga_lvlr", "Книга ЛВ и ЛР"], ["uhody", "Рубки ухода"], ["tek_izm", "Текущие изменения"]] },
  {
    title: "люди и техника",
    items: [
      ["sotrudniki", "Люди"],
      ["tabel", "Табель"],
      ["zadachi", "Задачи"],
      ["raboty", "Журнал работ"],
      ["tehnika", "Техника и топливо"],
      ["reyting", "🏆 Рейтинг"],
      ["chellendzhi", "🔥 Челленджи"],
    ],
  },
  { title: "прочее", items: [["archive", "Архив"], ["korzina", "Корзина"], ["settings", "Настройки"]] },
];

// Пункты меню, которые видны не всем ролям (права — из /api/auth/me).
export const NAV_PERMISSION = { korzina: "korzina.view" };

const MONO = "'JetBrains Mono', monospace";

// Пункты только для игрового вида (переключатель в шапке / Настройках).
const TOLKO_IGRA = new Set(["kvesty", "reyting", "gazeta", "chellendzhi"]);

export default function Sidebar({ openKeys = [], activeKey, onNavigate, user, onLogout, permissions = [] }) {
  const [vid] = useVid();
  return (
    <nav className="w-[158px] shrink-0 h-screen flex flex-col overflow-y-auto" style={{ background: "#1a4331", color: "#eaf7ec" }}>
      <div style={{ padding: "18px 16px 14px" }}>
        <div style={{ fontWeight: 800, fontSize: 17, color: "#fff", lineHeight: 1.1 }}>Лесовод</div>
        <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: ".14em", textTransform: "uppercase", color: "#bcefc5", marginTop: 3 }}>
          рабочий стол
        </div>
      </div>

      <div className="flex flex-col flex-1" style={{ gap: 14, padding: "0 8px 16px" }}>
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="flex flex-col" style={{ gap: 2 }}>
            <div style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: ".12em", textTransform: "uppercase", color: "#8fb79f", padding: "6px 8px 4px" }}>
              {group.title}
            </div>
            {group.items.filter(([key]) => (!NAV_PERMISSION[key] || permissions.includes(NAV_PERMISSION[key])) && (vid === "igra" || !TOLKO_IGRA.has(key))).map(([key, label]) => {
              const isActive = key === activeKey;
              const isOpen = openKeys.includes(key);
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
                  {isOpen && <span style={{ width: 6, height: 6, borderRadius: 999, background: "#bcefc5", flexShrink: 0 }} />}
                </button>
              );
            })}
          </div>
        ))}
        {/* Руководство для новых сотрудников (сайт + приложение) лежит
            рядом с сайтом: frontend/public/guide/. «Витрина компонентов»
            (служебный экран разработчика) из меню убрана. */}
        <a
          href="/guide/index.html"
          target="_blank"
          rel="noreferrer"
          className="text-left rounded-lg hover:!text-white"
          style={{ marginTop: "auto", padding: "6px 8px", fontSize: 12, color: "#bcefc5", textDecoration: "none" }}
        >
          📖 Руководство
        </a>
      </div>

      <div className="flex items-center justify-between" style={{ padding: "12px 14px", borderTop: "1px solid #235a41", gap: 6 }}>
        <div className="min-w-0" style={{ fontFamily: MONO, fontSize: 10, color: "#8fb79f" }}>
          <div className="truncate">{user?.fio ?? "Гость"}</div>
          <div className="truncate">{user?.role ?? ""}</div>
        </div>
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
    </nav>
  );
}
