import React from "react";
import StatusBadge from "./StatusBadge.jsx";

// Один и тот же % освоения на всех экранах (большее из наряда и ЕГАИС, см.
// raskhod_v2.compute_osvoenie_batch) и одни пороги 90 / 100 / 110 %.
const LEVEL_TONE = { norma: "neutral", vnimanie: "warning", preduprezhdenie: "warning", pererub: "danger", net_limita: "neutral" };
const LEVEL_HINT = {
  norma: "в пределах лимита",
  vnimanie: "подходит к лимиту (90%+)",
  preduprezhdenie: "лимит выбран, дальше только в допуске +10%",
  pererub: "превышен допуск +10%",
  net_limita: "лимит не задан",
};

export function osvoenieTone(level) {
  return LEVEL_TONE[level] || "neutral";
}

export default function OsvoenieBadge({ pct, level, suffix = "" }) {
  if (pct == null) return <StatusBadge tone="neutral" label={`—${suffix}`} />;
  return (
    <span title={`${LEVEL_HINT[level] || ""} · считается по большему из нарядов и ЕГАИС`}>
      <StatusBadge tone={osvoenieTone(level)} label={`${pct}%${suffix}`} />
    </span>
  );
}
