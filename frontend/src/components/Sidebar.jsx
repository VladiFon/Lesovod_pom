import React from "react";

// Пункты меню сгруппированы по смыслу (было — плоский список из 14
// пунктов, стало — три смысловые группы + пункты "вне групп" на своих
// исходных местах). "Живая карта" убрана из меню совсем — по решению
// пользователя карты ведутся в QGIS напрямую, экран не нужен (см.
// LiveMap.jsx — удалён, backend app/routers/map.py не трогали).
// Иконки — простые контурные SVG (без внешней библиотеки), в духе "тонких
// изолиний" из концепции дизайна.
const NAV_SECTIONS = [
  {
    title: null,
    items: [{ key: "dashboard", label: "Дашборд", icon: IconGrid }],
  },
  {
    title: "Делянки",
    items: [
      { key: "plots", label: "Делянки", icon: IconLeaf },
      { key: "raskhod", label: "Расход / ЕГАИС", icon: IconTruck },
      { key: "inspection", label: "Инспекция", icon: IconCheckShield },
      // C.3 плана — независимые пробы рубок ухода (см. App.jsx:READY_SCREENS.uhody).
      { key: "uhody", label: "Рубки ухода", icon: IconStack },
      // Этап 5 плана переноса: сквозной список документов по всем делянкам
      // (в отличие от списка внутри карточки одной делянки на "Делянках").
      { key: "documents", label: "Документы", icon: IconDoc },
    ],
  },
  {
    title: null,
    items: [{ key: "taxation", label: "Таксация", icon: IconRuler }],
  },
  {
    title: "Лесные культуры",
    items: [{ key: "forestry", label: "Лесокультуры", icon: IconSprout }],
  },
  {
    title: "Люди",
    items: [
      // Перенесено из Settings.jsx (WorkersCard) — полноценный экран
      // вместо блока внутри "Настроек", те же /api/auth/workers.
      { key: "sotrudniki", label: "Сотрудники", icon: IconUsers },
      { key: "work_plan", label: "План работ", icon: IconClipboard },
      // Односторонние ленты "рабочий -> мастер" из мобильного приложения
      // (см. app/routers/attendance.py, app/routers/notes.py).
      { key: "attendance", label: "Присутствие", icon: IconPin },
      { key: "worker_notes", label: "Заметки", icon: IconNote },
      { key: "calendar", label: "Календарь", icon: IconCalendar },
    ],
  },
  {
    title: null,
    items: [
      { key: "ai_log", label: "ИИ-журнал", icon: IconSpark },
      { key: "archive", label: "Архив", icon: IconArchive },
      { key: "settings", label: "Настройки", icon: IconGear },
    ],
  },
];

export default function Sidebar({ active, onNavigate, user, onLogout }) {
  return (
    <aside className="w-64 shrink-0 h-screen bg-paper border-r border-border flex flex-col">
      <div className="px-5 pt-6 pb-5">
        <div className="font-ui font-extrabold text-xl text-pine leading-tight">Лесовод</div>
        <div className="font-mono text-xs tracking-widest text-muted-2 uppercase mt-0.5">
          Цифровой помощник
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 flex flex-col gap-1">
        {NAV_SECTIONS.map((section, i) => (
          <div key={section.title ?? `ungrouped-${i}`} className="flex flex-col gap-1">
            {section.title && (
              <div className="px-3.5 pt-4 pb-1 text-[11px] font-bold tracking-wider text-muted-2 uppercase">
                {section.title}
              </div>
            )}
            {section.items.map((item) => {
              const isActive = active === item.key;
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  onClick={() => onNavigate?.(item.key)}
                  aria-current={isActive ? "page" : undefined}
                  className={[
                    "flex items-center gap-3 text-left px-3.5 py-2.5 rounded-md text-base font-medium transition-colors",
                    isActive
                      ? "bg-mint text-pine font-bold"
                      : "text-muted hover:bg-hover hover:text-pine",
                  ].join(" ")}
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <span className="truncate">{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="border-t border-border mx-3" />

      <div className="px-4 py-4 flex items-center gap-3">
        <div
          className="h-9 w-9 rounded-full bg-mint text-pine font-bold flex items-center justify-center text-sm shrink-0"
          aria-hidden="true"
        >
          {(user?.fio ?? "?").trim().charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-mono text-sm font-bold text-ink truncate">{user?.fio ?? "Гость"}</div>
          <div className="text-xs text-muted truncate">{user?.role ?? "не авторизован"}</div>
        </div>
        {onLogout && (
          <button
            onClick={onLogout}
            title="Выйти"
            aria-label="Выйти"
            className="h-8 w-8 shrink-0 rounded-md flex items-center justify-center text-muted hover:bg-hover hover:text-error transition-colors"
          >
            <IconLogout className="h-5 w-5" />
          </button>
        )}
      </div>
      <div className="px-4 pb-4 font-mono text-[10px] tracking-wide text-faint">
        Лесовод · веб-версия
      </div>

      {/* Этап 3, временный пункт для приёмки дизайна — не часть меню из
          Аудита (Этап 0), убрать при переходе к Этапу 4. */}
      <button
        onClick={() => onNavigate?.("gallery")}
        className={[
          "mx-3 mb-4 text-xs font-semibold rounded-md px-3 py-2 border border-dashed",
          active === "gallery"
            ? "border-pine text-pine bg-mint-soft"
            : "border-border text-faint hover:text-pine hover:border-pine",
        ].join(" ")}
      >
        ⚙ Витрина компонентов
      </button>
    </aside>
  );
}

/* ── Иконки: минималистичные, stroke-only, 24x24 viewBox ────────────── */
function iconProps(className) {
  return {
    className,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
  };
}
function IconGrid({ className }) {
  return (
    <svg {...iconProps(className)}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </svg>
  );
}
function IconLeaf({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M20 4c0 9-6 15-15 15C5 10 11 4 20 4Z" />
      <path d="M6 19c3-5 6-8 12-13" />
    </svg>
  );
}
function IconDoc({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z" />
      <path d="M14 3.5V8h4M9 13h6M9 16.5h6" />
    </svg>
  );
}
function IconRuler({ className }) {
  return (
    <svg {...iconProps(className)}>
      <rect x="3" y="8" width="18" height="8" rx="1.5" transform="rotate(-8 12 12)" />
      <path d="M7 9.5 7.6 11M11 9 11.6 10.5M15 8.5 15.6 10" />
    </svg>
  );
}
function IconStack({ className }) {
  // Штабель обмерных укладок хвороста (экран "Рубки ухода") — три
  // сложенных бруска, тот же язык, что и у остальных иконок (обводка,
  // без заливки).
  return (
    <svg {...iconProps(className)}>
      <rect x="4" y="5" width="16" height="3.2" rx="1" />
      <rect x="4" y="10.4" width="16" height="3.2" rx="1" />
      <rect x="4" y="15.8" width="16" height="3.2" rx="1" />
    </svg>
  );
}
function IconSprout({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M12 21v-9" />
      <path d="M12 12c0-4-3-6-7-6 0 4 3 6 7 6Z" />
      <path d="M12 9c0-3 2.5-5 6-5 0 3-2.5 5-6 5Z" />
    </svg>
  );
}
function IconTruck({ className }) {
  return (
    <svg {...iconProps(className)}>
      <rect x="2.5" y="7" width="11" height="9" rx="1" />
      <path d="M13.5 10h4l3 3v3h-7z" />
      <circle cx="7" cy="18" r="1.6" />
      <circle cx="16.5" cy="18" r="1.6" />
    </svg>
  );
}
function IconCheckShield({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M12 3 5 5.5v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9v-6L12 3Z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}
function IconSpark({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M12 3v5M12 16v5M4.5 12h5M14.5 12h5M6.5 6.5l3 3M14.5 14.5l3 3M17.5 6.5l-3 3M9.5 14.5l-3 3" />
    </svg>
  );
}
function IconArchive({ className }) {
  return (
    <svg {...iconProps(className)}>
      <rect x="3" y="4" width="18" height="4.5" rx="1" />
      <path d="M4.5 8.5V19a1 1 0 0 0 1 1h13a1 1 0 0 0 1-1V8.5" />
      <path d="M10 13h4" />
    </svg>
  );
}
function IconCalendar({ className }) {
  return (
    <svg {...iconProps(className)}>
      <rect x="3.5" y="5" width="17" height="16" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </svg>
  );
}
function IconClipboard({ className }) {
  // Планшет с галочками (экран "План работ") — задачи сотрудникам, в
  // отличие от IconUsers (сами сотрудники, экран "Сотрудники").
  return (
    <svg {...iconProps(className)}>
      <rect x="5" y="4.5" width="14" height="17" rx="1.5" />
      <path d="M9 3.5h6a1 1 0 0 1 1 1V6H8V4.5a1 1 0 0 1 1-1Z" />
      <path d="M8.5 12l2 2 4-4M8.5 17.5h7" />
    </svg>
  );
}
function IconPin({ className }) {
  // Геометка (экран "Присутствие") — где и когда рабочий отметился.
  return (
    <svg {...iconProps(className)}>
      <path d="M12 21s7-6.5 7-11.5A7 7 0 0 0 5 9.5C5 14.5 12 21 12 21Z" />
      <circle cx="12" cy="9.5" r="2.3" />
    </svg>
  );
}
function IconNote({ className }) {
  // Заметка (экран "Заметки") — лента текстовых сообщений от рабочих.
  return (
    <svg {...iconProps(className)}>
      <path d="M5 4.5h14a1 1 0 0 1 1 1V15l-4 5H6a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1Z" />
      <path d="M8 9h8M8 12.5h5" />
    </svg>
  );
}
function IconUsers({ className }) {
  return (
    <svg {...iconProps(className)}>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 20c0-3.3 2.5-6 5.5-6s5.5 2.7 5.5 6" />
      <circle cx="17" cy="8.5" r="2.3" />
      <path d="M15.5 14.2c2.5 0.3 4.5 2.7 4.5 5.8" />
    </svg>
  );
}
function IconGear({ className }) {
  return (
    <svg {...iconProps(className)}>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18 6l-1.6 1.6M7.6 16.4 6 18M18 18l-1.6-1.6M7.6 7.6 6 6" />
    </svg>
  );
}
function IconLogout({ className }) {
  return (
    <svg {...iconProps(className)}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  );
}
