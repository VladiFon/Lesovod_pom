import React, { useState } from "react";
import { useScreenParam } from "../nav.js";

/**
 * Один пункт меню — несколько экранов вкладками (шаг 4 разбора 03.11.2026:
 * меню с 21 пункта сжато до 16). Активная вкладка — в адресе (#/telefon?tab=zametki),
 * чтобы ссылка из «Ждёт меня», дашборда или колокольчика открывала нужную.
 * Открытые вкладки остаются смонтированными (скрыты), чтобы не терять
 * введённое при переключении.
 */
export function makeMergedScreen(screenKey, tabs) {
  return function MergedScreen(props) {
    const [tabParam, setTabParam] = useScreenParam(screenKey, "tab");
    const active = tabs.some((t) => t.key === tabParam) ? tabParam : tabs[0].key;
    const [visited, setVisited] = useState(() => new Set([active]));
    if (!visited.has(active)) setVisited(new Set([...visited, active]));
    return (
      <div className="flex flex-col min-h-full">
        <div className="flex gap-1 border-b border-border px-[18px] pt-3 bg-paper sticky top-0 z-10">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTabParam(t.key)}
              className={[
                "px-4 py-2 text-base font-semibold border-b-2 -mb-px transition-colors whitespace-nowrap",
                active === t.key ? "border-pine text-pine" : "border-transparent text-muted hover:text-pine",
              ].join(" ")}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tabs.map((t) => {
          if (!visited.has(t.key)) return null;
          const Page = t.Page;
          return (
            <div key={t.key} style={{ display: t.key === active ? "block" : "none" }}>
              <Page {...props} />
            </div>
          );
        })}
      </div>
    );
  };
}
