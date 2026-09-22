import React, { useMemo, useState } from "react";
import EmptyState from "./EmptyState.jsx";

/**
 * DataTable — универсальная таблица (↔ QTableWidget#AILogTable/#ReportsTable
 * в styles.py: белый фон, рамка/радиус 12px, шапка на surface-alt, hover и
 * selected-строка в mint). Рассчитана в первую очередь на экран "Документы"
 * (Этап 5) — чекбоксы + массовые действия, но переиспользуема где угодно.
 *
 * columns: [{ key, header, render?(row), sortable?, width? }]
 * rows: [{ id, ...}]
 * selectable: включает столбец чекбоксов + selection/onSelectionChange
 * onRowClick(row): клик по строке (не по чекбоксу) — напр. открыть превью
 */
export default function DataTable({
  columns,
  rows,
  selectable = false,
  selection,
  onSelectionChange,
  onRowClick,
  getRowId = (row) => row.id,
  emptyTitle = "Пока пусто",
  emptyDescription = "Здесь появятся данные, когда они будут созданы.",
  emptyAction = null,
  loading = false,
}) {
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const isControlledSelection = selection !== undefined;
  const [internalSelection, setInternalSelection] = useState([]);
  const selected = isControlledSelection ? selection : internalSelection;

  const setSelected = (next) => {
    if (isControlledSelection) onSelectionChange?.(next);
    else setInternalSelection(next);
  };

  const sortedRows = useMemo(() => {
    if (!sort.key) return rows;
    const col = columns.find((c) => c.key === sort.key);
    const sorted = [...rows].sort((a, b) => {
      const av = col?.sortValue ? col.sortValue(a) : a[sort.key];
      const bv = col?.sortValue ? col.sortValue(b) : b[sort.key];
      if (av === bv) return 0;
      return av > bv ? 1 : -1;
    });
    return sort.dir === "asc" ? sorted : sorted.reverse();
  }, [rows, sort, columns]);

  const toggleSort = (key, sortable) => {
    if (!sortable) return;
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }
    );
  };

  const allChecked = rows.length > 0 && selected.length === rows.length;
  const someChecked = selected.length > 0 && !allChecked;

  const toggleAll = () => setSelected(allChecked ? [] : rows.map(getRowId));
  const toggleRow = (id) =>
    setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  if (!loading && rows.length === 0) {
    return <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />;
  }

  return (
    <div className="bg-surface border border-border rounded-md overflow-hidden">
      <table className="w-full text-base border-collapse">
        <thead>
          <tr className="bg-surface-alt border-b border-border">
            {selectable && (
              <th className="w-10 px-3 py-2.5 text-left">
                <input
                  type="checkbox"
                  checked={allChecked}
                  ref={(el) => el && (el.indeterminate = someChecked)}
                  onChange={toggleAll}
                  aria-label="Выбрать все строки"
                  className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
                />
              </th>
            )}
            {columns.map((col) => (
              <th
                key={col.key}
                style={col.width ? { width: col.width } : undefined}
                onClick={() => toggleSort(col.key, col.sortable)}
                className={[
                  "px-3 py-2.5 text-left text-sm font-semibold text-muted select-none",
                  col.sortable ? "cursor-pointer hover:text-pine" : "",
                ].join(" ")}
              >
                <span className="inline-flex items-center gap-1">
                  {col.header}
                  {col.sortable && sort.key === col.key && (
                    <span className="text-pine">{sort.dir === "asc" ? "↑" : "↓"}</span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-border">
                  {selectable && <td className="px-3 py-3" />}
                  {columns.map((col) => (
                    <td key={col.key} className="px-3 py-3">
                      <div className="h-3.5 rounded bg-hover animate-pulse" style={{ width: "70%" }} />
                    </td>
                  ))}
                </tr>
              ))
            : sortedRows.map((row) => {
                const id = getRowId(row);
                const isSelected = selected.includes(id);
                return (
                  <tr
                    key={id}
                    onClick={() => onRowClick?.(row)}
                    className={[
                      "border-b border-border last:border-b-0 transition-colors",
                      onRowClick ? "cursor-pointer" : "",
                      isSelected ? "bg-mint/40" : "hover:bg-surface-alt",
                    ].join(" ")}
                  >
                    {selectable && (
                      <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRow(id)}
                          aria-label="Выбрать строку"
                          className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
                        />
                      </td>
                    )}
                    {columns.map((col) => (
                      <td key={col.key} className="px-3 py-2.5 text-ink">
                        {col.render ? col.render(row) : row[col.key]}
                      </td>
                    ))}
                  </tr>
                );
              })}
        </tbody>
      </table>
    </div>
  );
}
