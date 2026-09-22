import React from "react";

/**
 * StatusBadge — цветные статус-чипы (документы, наряды, баланс ЕГАИС).
 * Тон "success" = Secondary Green (в норме/готово), "warning" = Autumn
 * Oak (в очереди/расхождение), "danger" = Error (переруб/ошибка),
 * "neutral" = серый (архив/черновик).
 */
const TONES = {
  success: "bg-mint-soft text-green border border-mint",
  warning: "bg-oak-soft text-oak border border-oak/40",
  danger: "bg-error-soft text-error border border-error/30",
  neutral: "bg-surface-alt text-muted border border-border",
  info: "bg-mint-soft text-pine border border-mint",
};

const DOT_TONES = {
  success: "bg-green",
  warning: "bg-oak",
  danger: "bg-error",
  neutral: "bg-faint",
  info: "bg-pine",
};

// Готовые пресеты под жизненный цикл документа (Этап 5), чтобы вызывать
// <StatusBadge status="готов" /> напрямую с бэкенда без маппинга на фронте.
const STATUS_PRESETS = {
  "готов": "success",
  "активна": "success",
  "в процессе": "warning",
  "в очереди": "warning",
  "ошибка": "danger",
  "архив": "neutral",
  "черновик": "neutral",
};

export default function StatusBadge({ tone, status, label, dot = true, className = "" }) {
  const resolvedTone = tone || STATUS_PRESETS[status?.toLowerCase()] || "neutral";
  const text = label ?? status ?? "";

  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold whitespace-nowrap",
        TONES[resolvedTone],
        className,
      ].join(" ")}
    >
      {dot && <span className={["h-1.5 w-1.5 rounded-full", DOT_TONES[resolvedTone]].join(" ")} />}
      {text}
    </span>
  );
}
