import React from "react";

/**
 * StatCard — карточка-метрика дашборда (↔ MetricCard + CardIcon/CardValue/
 * CardTitle/CardCaption в styles.py и widgets.py::MetricCard).
 * "alert" повторяет тревожный вид критичных показателей из десктопа
 * (переруб, просроченные наряды) — акцент уходит с pine на error.
 */
export default function StatCard({ icon, title, value, caption, trend, alert = false, className = "" }) {
  return (
    <div
      className={[
        "bg-surface border rounded-lg shadow-card p-5 flex flex-col gap-3",
        alert ? "border-error/40" : "border-border",
        className,
      ].join(" ")}
    >
      <div className="flex items-center justify-between">
        {icon && (
          <span
            className={[
              "h-11 w-11 rounded-full flex items-center justify-center shrink-0",
              alert ? "bg-error-soft text-error" : "bg-hover text-pine",
            ].join(" ")}
          >
            {icon}
          </span>
        )}
        {trend && (
          <span
            className={[
              "text-xs font-semibold",
              trend.direction === "down" ? "text-error" : "text-green",
            ].join(" ")}
          >
            {trend.direction === "down" ? "↓" : "↑"} {trend.value}
          </span>
        )}
      </div>
      <div>
        <div className={["font-ui font-extrabold text-2xl", alert ? "text-error" : "text-pine-deep"].join(" ")}>
          {value}
        </div>
        <div className="text-muted text-base font-medium mt-1">{title}</div>
        {caption && <div className="text-faint text-xs mt-0.5">{caption}</div>}
      </div>
    </div>
  );
}
