import React from "react";

/**
 * StatCard — карточка-метрика: значок в цветном кружке, подпись, крупное
 * число, пояснение снизу.
 *
 * Разбор 09.11.2026 «виджеты приятнее»:
 *  - icon снова рисуется (в кружке цвета tone);
 *  - tone: "pine" (обычная) | "oak" (внимание) | "error" (тревога) |
 *    "info" (входящее); alert = старый способ сказать tone="error";
 *  - onClick — карточка кликабельна: приподнимается, справа «→», ведёт
 *    на экран, где эту цифру можно разобрать;
 *  - progress (0…1+) — полоска под числом (например, освоение плана),
 *    progressMark — черта на полоске (1 = 100%).
 */
const TONES = {
  pine: { chip: "bg-mint-soft text-pine", value: "text-pine", bar: "bg-pine", ring: "border-border" },
  oak: { chip: "bg-oak-soft text-[#8a5a00]", value: "text-[#8a5a00]", bar: "bg-oak", ring: "border-[#f0d5b5]" },
  error: { chip: "bg-error-soft text-error", value: "text-error", bar: "bg-error", ring: "border-[#ebc0bc]" },
  info: { chip: "bg-info-soft text-info", value: "text-info", bar: "bg-info", ring: "border-border" },
};

export default function StatCard({
  icon,
  title,
  value,
  caption,
  trend,
  alert = false,
  tone,
  onClick,
  progress,
  progressMark,
  className = "",
}) {
  const t = TONES[tone || (alert ? "error" : "pine")] || TONES.pine;
  const Tag = onClick ? "button" : "div";
  const pct = progress == null ? null : Math.max(0, Math.min(1, progress));
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className={[
        "group text-left bg-surface border rounded-lg shadow-card flex flex-col gap-1.5 px-4 py-3.5 min-w-0 w-full",
        t.ring,
        onClick ? "cursor-pointer transition-all duration-150 hover:shadow-hover hover:-translate-y-px" : "",
        className,
      ].join(" ")}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        {icon && (
          <span className={["shrink-0 h-8 w-8 rounded-[10px] flex items-center justify-center text-[15px]", t.chip].join(" ")} aria-hidden="true">
            {icon}
          </span>
        )}
        <div className="text-[12.5px] font-semibold text-muted leading-snug flex-1 min-w-0">{title}</div>
        {onClick && (
          <span className="shrink-0 text-faint group-hover:text-pine transition-colors text-[15px]" aria-hidden="true">→</span>
        )}
      </div>
      <div className="flex items-baseline gap-2 mt-0.5">
        <span className={["font-ui font-extrabold leading-none tabular-nums tracking-tight", t.value].join(" ")} style={{ fontSize: 28 }}>
          {value}
        </span>
        {trend && (
          <span className={["text-xs font-semibold", trend.direction === "down" ? "text-error" : "text-green"].join(" ")}>
            {trend.direction === "down" ? "↓" : "↑"} {trend.value}
          </span>
        )}
      </div>
      {pct != null && (
        <div className="relative h-1.5 rounded-full bg-hover overflow-hidden mt-0.5">
          <div className={["absolute inset-y-0 left-0 rounded-full", t.bar].join(" ")} style={{ width: `${pct * 100}%` }} />
          {progressMark != null && (
            <div className="absolute inset-y-0 w-[2px] bg-[#1c1c18]/50" style={{ left: `${Math.min(1, progressMark) * 100}%` }} />
          )}
        </div>
      )}
      {caption && <div className="text-[11.5px] text-faint leading-snug">{caption}</div>}
    </Tag>
  );
}
