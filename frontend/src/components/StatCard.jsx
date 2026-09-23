import React from "react";

/**
 * StatCard — карточка-метрика (дизайн «Вкладки»): подпись сверху, крупное
 * моно-число, пояснение снизу. "alert" — тревожный вид (error).
 * Проп icon оставлен для совместимости, но не рисуется.
 */
export default function StatCard({ title, value, caption, trend, alert = false, className = "" }) {
  return (
    <div
      className={[
        "bg-surface border rounded-lg flex flex-col gap-1 px-4 py-3.5 min-w-0",
        alert ? "border-error/50" : "border-border",
        className,
      ].join(" ")}
    >
      <div className="text-[12.5px] font-semibold text-muted leading-snug">{title}</div>
      <div className="flex items-baseline gap-2">
        <span
          className={["font-mono text-2xl font-bold leading-none mt-1", alert ? "text-error" : "text-pine"].join(" ")}
          style={{ fontSize: 24 }}
        >
          {value}
        </span>
        {trend && (
          <span className={["text-xs font-semibold", trend.direction === "down" ? "text-error" : "text-green"].join(" ")}>
            {trend.direction === "down" ? "↓" : "↑"} {trend.value}
          </span>
        )}
      </div>
      {caption && <div className="text-[11.5px] text-faint">{caption}</div>}
    </div>
  );
}
