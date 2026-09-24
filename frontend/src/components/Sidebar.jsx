import React from "react";

// Группы и подписи — из дизайна «Вкладки - новый дизайн»: тёмно-зелёная
// узкая колонка; клик по пункту открывает (или фокусирует) вкладку.
export const NAV_GROUPS = [
  { title: "обзор", items: [["dashboard", "Дашборд"], ["calendar", "Календарь"]] },
  {
    title: "делянки",
    items: [["plots", "Делянки"], ["raskhod", "Расход / ЕГАИС"], ["inspection", "Инспекция"], ["documents", "Документы"]],
  },
  { title: "лес", items: [["taxation", "Таксация"], ["forestry", "Лесокультуры"], ["uhody", "Рубки ухода"]] },
  {
    title: "люди",
    items: [
      ["sotrudniki", "Сотрудники"],
      ["work_plan", "План работ"],
      ["tabel", "Табель — ввод"],
      ["attendance", "Присутствие"],
      ["worker_notes", "Заметки"],
    ],
  },
  { title: "прочее", items: [["ai_log", "ИИ-журнал"], ["archive", "Архив"], ["settings", "Настройки"]] },
];

const MONO = "'JetBrains Mono', monospace";

export default function Sidebar({ openKeys = [], activeKey, onNavigate, user, onLogout }) {
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
            {group.items.map(([key, label]) => {
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
        <button
          type="button"
          onClick={() => onNavigate?.("gallery")}
          className="text-left rounded-lg hover:!text-white"
          style={{ marginTop: "auto", padding: "6px 8px", fontSize: 11.5, color: "#8fb79f", background: "transparent", border: 0, cursor: "pointer" }}
        >
          ⚙ Витрина компонентов
        </button>
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
