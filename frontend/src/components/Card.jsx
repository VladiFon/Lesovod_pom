import React from "react";

/**
 * Card — базовая панель (↔ QFrame#DossierCard / #MetricCard / #SearchPanel
 * в styles.py): белая поверхность, тонкая рамка #e5e2db, радиус 16px.
 * Все крупные блоки экранов (карточка делянки, панель фильтров, карточка
 * метрики) собираются поверх этого компонента.
 */
export default function Card({ title, subtitle, actions, padding = true, className = "", style, children }) {
  const hasHeader = title || subtitle || actions;
  return (
    <div style={style}
      className={[
        "bg-surface border border-border rounded-lg",
        className,
      ].join(" ")}
    >
      {hasHeader && (
        <div className="flex items-start justify-between gap-3 px-4 pt-3.5 pb-1">
          <div>
            {title && <h3 className="font-ui font-extrabold text-pine text-[14.5px]">{title}</h3>}
            {subtitle && <p className="font-mono text-[10.5px] text-muted-2 mt-[3px]">{subtitle}</p>}
          </div>
          {actions && <div className="shrink-0 flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={padding ? "px-4 py-3.5" : ""}>{children}</div>
    </div>
  );
}
