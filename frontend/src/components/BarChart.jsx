import React from "react";

/**
 * BarChart — парные столбцы "план/факт" по периодам (дизайн «Вкладки»).
 * Обычная flex-вёрстка: каждая категория — своя колонка, столбцы внутри
 * неё ограничены по ширине и высоте, поэтому за границы графика не
 * выходят при любой ширине панели.
 *
 * series: [{ label, values: number[], color }] — той же длины, что и categories.
 */
export default function BarChart({ categories, series, height = 170 }) {
  const max = Math.max(1, ...series.flatMap((s) => s.values.map((v) => v || 0)));

  return (
    <div className="flex items-end gap-3.5 w-full overflow-hidden" style={{ height, paddingTop: 4 }}>
      {categories.map((label, i) => (
        <div key={i} className="flex-1 min-w-0 h-full flex flex-col justify-end items-center gap-1.5">
          <div className="flex-1 w-full min-h-0 flex items-end justify-center gap-1">
            {series.map((s, si) => {
              const value = s.values[i] ?? 0;
              return (
                <div
                  key={si}
                  title={`${s.label} · ${label}: ${value.toFixed(1)}`}
                  style={{
                    flex: "1 1 0",
                    maxWidth: 22,
                    height: `${Math.max(value > 0 ? 2 : 0, (value / max) * 100)}%`,
                    background: s.color,
                    borderRadius: "4px 4px 0 0",
                  }}
                />
              );
            })}
          </div>
          <span className="font-mono text-[10.5px] text-muted-2 truncate max-w-full">{label}</span>
        </div>
      ))}
    </div>
  );
}
