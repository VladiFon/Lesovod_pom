import React from "react";
import { openScreen } from "../nav.js";
import StatusBadge from "./StatusBadge.jsx";

// Этап делянки (app/etap.py) → тон бейджа.
const ETAP_TONE = {
  chernovik: "neutral",
  v_rabote: "success",
  dorublena: "warning",
  osvid: "info",
  zakryta: "neutral",
};

/** Бейдж этапа: Черновик / В работе / Дорублена / Освидетельствована / Закрыта. */
export function EtapBadge({ etap, className = "" }) {
  if (!etap) return null;
  const title = etap.kod === "dorublena" && etap.akt_do
    ? `Площадь пройдена ${etap.ploshad_zakryta}, акт до ${etap.akt_do}`
    : undefined;
  return (
    <span title={title}>
      <StatusBadge tone={ETAP_TONE[etap.kod] || "neutral"} label={etap.label} dot className={className} />
    </span>
  );
}

const EKRANY = [
  ["plots", "📋 Карточка"],
  ["raskhod", "🧮 Расход"],
  ["inspection", "✅ Инспекция"],
  ["documents", "📄 Документы"],
];

/**
 * Ряд кнопок «Карточка · Расход · Инспекция · Документы» — перейти на
 * другой экран с той же делянкой, не ища её заново в списке (шаг 4
 * разбора 03.11.2026). current — экран, на котором стоим (его кнопку не
 * показываем).
 */
export default function DelyankaNav({ delyankaId, current, etap, storonnyaya, className = "" }) {
  if (!delyankaId) return null;
  return (
    <div className={["flex items-center gap-1.5 flex-wrap", className].join(" ")}>
      <EtapBadge etap={etap} />
      {storonnyaya && <StatusBadge tone="warning" label={`рубит ${storonnyaya.zagotovitel}`} />}
      <span className="text-muted-2 text-xs ml-1">Эта делянка в:</span>
      {EKRANY.filter(([k]) => k !== current).map(([k, label]) => (
        <button
          key={k}
          type="button"
          onClick={() => openScreen(k, { d: delyankaId })}
          className="h-7 px-2.5 rounded-md border border-border bg-surface text-[12.5px] font-semibold text-muted hover:border-pine hover:text-pine transition-colors"
        >
          {label}
        </button>
      ))}
    </div>
  );
}
