import React from "react";

/**
 * Card — базовая панель (↔ QFrame#DossierCard / #MetricCard / #SearchPanel
 * в styles.py): белая поверхность, тонкая рамка #e5e2db, радиус 16px.
 * Все крупные блоки экранов (карточка делянки, панель фильтров, карточка
 * метрики) собираются поверх этого компонента.
 */
export default function Card({ title, subtitle, actions, padding = true, className = "", children }) {
  const hasHeader = title || subtitle || actions;
  return (
    <div
      className={[
        "bg-surface border border-border rounded-lg shadow-card",
        className,
      ].join(" ")}
    >
      {hasHeader && (
        <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-1">
          <div>
            {title && <h3 className="font-ui font-bold text-ink text-md">{title}</h3>}
            {subtitle && <p className="text-muted text-sm mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="shrink-0 flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={padding ? "p-5" : ""}>{children}</div>
    </div>
  );
}
