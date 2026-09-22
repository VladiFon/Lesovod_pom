import React from "react";

/**
 * EmptyState — пустое состояние (список документов/делянок/задач).
 * По принципам frontend-design: "пустой экран — это приглашение к
 * действию", поэтому description и action обязательны по смыслу, а не
 * просто "ничего не найдено".
 */
export default function EmptyState({ icon, title, description, action, className = "" }) {
  return (
    <div
      className={[
        "flex flex-col items-center justify-center text-center gap-3 py-14 px-6",
        "border border-dashed border-border rounded-lg bg-surface-alt/50",
        className,
      ].join(" ")}
    >
      <div className="h-14 w-14 rounded-full bg-hover text-pine flex items-center justify-center text-2xl">
        {icon ?? "🌲"}
      </div>
      <div>
        <div className="font-ui font-bold text-ink text-md">{title}</div>
        {description && <p className="text-muted text-base mt-1 max-w-sm">{description}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
