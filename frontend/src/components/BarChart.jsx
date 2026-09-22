import React from "react";

/**
 * BarChart — новый атом (Этап 4, экран "Дашборд"): парные столбцы
 * "план/факт" по периодам. Заменяет HarvestChartWidget — кастомную
 * отрисовку QPainter из screens/dashboard/widgets.py — обычным SVG, без
 * подключения библиотеки графиков (recharts и т.п. не установлены,
 * а один график из двух серий не стоит нового пакета в зависимостях).
 *
 * series: [{ label, values: number[], color }] — все серии должны быть
 * той же длины, что и categories.
 */
export default function BarChart({ categories, series, height = 220 }) {
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const n = categories.length;
  const groupWidth = 100 / Math.max(n, 1);
  const barGapPct = groupWidth * 0.12;
  const barWidthPct = (groupWidth - barGapPct * (series.length + 1)) / series.length;

  return (
    <div style={{ height }} className="flex flex-col">
      <svg viewBox={`0 0 100 100`} preserveAspectRatio="none" className="flex-1 w-full overflow-visible">
        {categories.map((_, catIndex) => {
          const groupX = catIndex * groupWidth;
          return series.map((s, seriesIndex) => {
            const value = s.values[catIndex] ?? 0;
            const barHeight = (value / max) * 100;
            const x = groupX + barGapPct + seriesIndex * (barWidthPct + barGapPct);
            return (
              <rect
                key={`${catIndex}-${seriesIndex}`}
                x={x}
                y={100 - barHeight}
                width={barWidthPct}
                height={barHeight}
                rx={1.2}
                fill={s.color}
              >
                <title>
                  {s.label} · {categories[catIndex]}: {value.toFixed(1)}
                </title>
              </rect>
            );
          });
        })}
      </svg>
      <div className="flex mt-1.5">
        {categories.map((label, i) => (
          <div key={i} style={{ width: `${groupWidth}%` }} className="text-center text-xs text-muted">
            {label}
          </div>
        ))}
      </div>
    </div>
  );
}
