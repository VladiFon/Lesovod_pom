import React from "react";

/**
 * Card — базовая панель: белая поверхность, тонкая рамка, радиус 16px.
 * Все крупные блоки экранов (карточка делянки, панель фильтров, карточка
 * метрики) собираются поверх этого компонента.
 *
 * Разбор 09.11.2026 «виджеты приятнее»: мягкая тень, заголовок с
 * необязательной иконкой в цветном кружке (icon), тонкий разделитель под
 * шапкой (divider), кликабельная карточка (onClick) приподнимается при
 * наведении.
 */
const ICON_TONE = {
  pine: "bg-mint-soft text-pine",
  oak: "bg-oak-soft text-[#8a5a00]",
  error: "bg-error-soft text-error",
  info: "bg-info-soft text-info",
};

export default function Card({
  title,
  subtitle,
  actions,
  icon = null,
  iconTone = "pine",
  divider = false,
  padding = true,
  onClick,
  className = "",
  style,
  children,
}) {
  const hasHeader = title || subtitle || actions;
  return (
    <div
      style={style}
      onClick={onClick}
      className={[
        "bg-surface border border-border rounded-lg shadow-card",
        onClick ? "cursor-pointer transition-all duration-150 hover:shadow-hover hover:-translate-y-px hover:border-[#cfd8d1]" : "",
        className,
      ].join(" ")}
    >
      {hasHeader && (
        <div className={["flex items-start justify-between gap-3 px-4 pt-3.5", divider ? "pb-3 border-b border-hover" : "pb-1"].join(" ")}>
          <div className="flex items-center gap-2.5 min-w-0">
            {icon && (
              <span className={["shrink-0 h-8 w-8 rounded-[10px] flex items-center justify-center text-[15px]", ICON_TONE[iconTone] || ICON_TONE.pine].join(" ")}>
                {icon}
              </span>
            )}
            <div className="min-w-0">
              {title && <h3 className="font-ui font-extrabold text-pine text-[14.5px] leading-tight">{title}</h3>}
              {subtitle && <p className="font-mono text-[10.5px] text-muted-2 mt-[3px]">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="shrink-0 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>{actions}</div>}
        </div>
      )}
      <div className={padding ? "px-4 py-3.5" : ""}>{children}</div>
    </div>
  );
}
