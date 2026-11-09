import React from "react";

/**
 * BarChart — «план/факт» по периодам.
 *
 * Разбор 09.11.2026 «виджеты приятнее»: план рисуется пунктирной
 * «рамкой-целью», факт — столбцом внутри неё, над столбцом цифра факта;
 * за столбцами тонкая сетка. Так видно сразу, добрали план или нет, а не
 * сравниваешь на глаз два столбика рядом. Если факт выше плана — столбец
 * выходит за рамку.
 *
 * series: [{ label, values: number[], color }] — той же длины, что и
 * categories. Первая серия — план (цель), вторая — факт. Для других
 * количеств серий столбцы рисуются рядом, как раньше.
 */
function fmt(v) {
  if (!v) return "";
  return v >= 100 ? String(Math.round(v)) : v.toFixed(1).replace(/\.0$/, "");
}

export default function BarChart({ categories, series, height = 190 }) {
  const max = Math.max(1, ...series.flatMap((s) => s.values.map((v) => v || 0))) * 1.12;
  const target = series.length === 2;
  const [plan, fakt] = series;

  return (
    <div className="relative w-full" style={{ height }}>
      {/* сетка */}
      <div className="absolute inset-x-0 top-0 bottom-[22px] flex flex-col justify-between pointer-events-none">
        {[0, 1, 2, 3].map((i) => <div key={i} className="border-t border-dashed border-hover" />)}
      </div>
      <div className="absolute inset-0 flex items-end gap-3.5">
        {categories.map((label, i) => {
          const pv = plan?.values[i] ?? 0;
          const fv = (target ? fakt : plan)?.values[i] ?? 0;
          const dobrali = target && pv > 0 && fv >= pv;
          return (
            <div key={i} className="flex-1 min-w-0 h-full flex flex-col justify-end items-center gap-1.5">
              {target ? (
                <div className="relative flex-1 w-full min-h-0 flex items-end justify-center">
                  {pv > 0 && (
                    <div
                      title={`${plan.label} · ${label}: ${pv.toFixed(1)}`}
                      className="absolute bottom-0 rounded-t-[7px] border-2 border-dashed"
                      style={{ height: `${(pv / max) * 100}%`, width: "min(46px, 80%)", borderColor: "#cfcbc2", borderBottom: 0 }}
                    />
                  )}
                  <div className="relative flex flex-col items-center justify-end h-full" style={{ width: "min(30px, 56%)" }}>
                    {fv > 0 && (
                      <span className={["text-[10.5px] font-bold tabular-nums mb-1", dobrali ? "text-green" : "text-muted"].join(" ")}>{fmt(fv)}</span>
                    )}
                    <div
                      title={`${fakt.label} · ${label}: ${fv.toFixed(1)}${pv ? ` из ${pv.toFixed(1)}` : ""}`}
                      className="w-full rounded-t-[6px]"
                      style={{ height: `${Math.max(fv > 0 ? 2 : 0, (fv / max) * 100)}%`, background: dobrali ? "var(--color-green)" : fakt.color }}
                    />
                  </div>
                </div>
              ) : (
                <div className="flex-1 w-full min-h-0 flex items-end justify-center gap-1">
                  {series.map((s, si) => {
                    const value = s.values[i] ?? 0;
                    return (
                      <div
                        key={si}
                        title={`${s.label} · ${label}: ${value.toFixed(1)}`}
                        style={{ flex: "1 1 0", maxWidth: 22, height: `${Math.max(value > 0 ? 2 : 0, (value / max) * 100)}%`, background: s.color, borderRadius: "5px 5px 0 0" }}
                      />
                    );
                  })}
                </div>
              )}
              <span className="font-mono text-[10.5px] text-muted-2 truncate max-w-full h-4">{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
