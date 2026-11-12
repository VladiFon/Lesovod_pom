import React, { useEffect, useRef, useState } from "react";

/**
 * «↓ Excel» у любой таблицы сайта (разбор 09.11.2026, шаг 1).
 *
 * Монтируется один раз в App. Когда мышь над таблицей (<table>) с хотя бы
 * одной строкой данных, в её правом верхнем углу появляется кнопка — она
 * сохраняет ровно то, что сейчас видно в таблице (с учётом фильтров и
 * сортировки), в файл, который Excel открывает сразу: CSV с «;» и BOM,
 * как любит русский Excel. Скрытые строки/столбцы и кнопки внутри ячеек
 * не попадают. Таблица может отказаться: data-no-export.
 */
function cellText(cell) {
  const clone = cell.cloneNode(true);
  clone.querySelectorAll("button, input[type=checkbox], svg, [data-no-export]").forEach((el) => el.remove());
  clone.querySelectorAll("input, select, textarea").forEach((el) => {
    const v = el.tagName === "SELECT" ? el.options[el.selectedIndex]?.text ?? "" : el.value;
    el.replaceWith(document.createTextNode(v));
  });
  return (clone.innerText ?? clone.textContent ?? "").replace(/\s+/g, " ").trim();
}

function visible(el) {
  return el.offsetParent !== null || el.getClientRects().length > 0;
}

export function tableToRows(table) {
  const rows = [];
  table.querySelectorAll("tr").forEach((tr) => {
    if (!visible(tr)) return;
    const cells = [...tr.children].filter((c) => (c.tagName === "TD" || c.tagName === "TH") && visible(c));
    const row = [];
    cells.forEach((c) => {
      row.push(cellText(c));
      for (let i = 1; i < (c.colSpan || 1); i++) row.push("");
    });
    if (row.some((v) => v !== "")) rows.push(row);
  });
  return rows;
}

function toCsv(rows) {
  const esc = (v) => {
    // числа «12.5» → «12,5», чтобы Excel понял их как числа
    let s = /^-?\d+\.\d+$/.test(v) ? v.replace(".", ",") : v;
    if (/[";\n]/.test(s)) s = `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  return "﻿" + rows.map((r) => r.map(esc).join(";")).join("\r\n");
}

function fileName(table) {
  // название экрана той панели, где таблица (их может быть две рядом)
  let el = table.parentElement;
  while (el && !el.querySelector("[data-screen-title]")) el = el.parentElement;
  const title = (el?.querySelector("[data-screen-title]")?.textContent || document.title || "tablica").trim();
  const d = new Date();
  const dd = `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
  return `${title.replace(/[\\/:*?"<>|]+/g, " ").slice(0, 60)} ${dd}.csv`;
}

export function downloadTable(table) {
  const rows = tableToRows(table);
  if (rows.length < 2) return false;
  const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = fileName(table);
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  return true;
}

export default function TableExport() {
  const [target, setTarget] = useState(null); // { table, top, left }
  const hideTimer = useRef(null);
  const btnRef = useRef(null);

  useEffect(() => {
    const place = (table) => {
      const r = table.getBoundingClientRect();
      if (r.height < 40 || r.width < 160) return null;
      return { table, top: Math.max(r.top, 56) + 4, left: r.right - 4 };
    };
    const onOver = (e) => {
      if (btnRef.current && btnRef.current.contains(e.target)) { clearTimeout(hideTimer.current); return; }
      const table = e.target.closest?.("table");
      if (table && !table.closest("[data-no-export]") && !table.hasAttribute("data-no-export") && table.querySelector("tbody tr td")) {
        clearTimeout(hideTimer.current);
        const p = place(table);
        if (p) setTarget(p);
      } else {
        clearTimeout(hideTimer.current);
        hideTimer.current = setTimeout(() => setTarget(null), 400);
      }
    };
    const onScroll = () => setTarget(null);
    document.addEventListener("mouseover", onOver);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mouseover", onOver);
      window.removeEventListener("scroll", onScroll, true);
      clearTimeout(hideTimer.current);
    };
  }, []);

  if (!target) return null;
  return (
    <button
      ref={btnRef}
      type="button"
      onClick={() => downloadTable(target.table)}
      title="Сохранить эту таблицу так, как она сейчас видна (с фильтрами), — откроется в Excel"
      className="fixed z-[60] -translate-x-full h-7 px-2.5 rounded-[8px] border border-border bg-white/95 text-pine text-[12px] font-semibold shadow-hover hover:bg-mint-soft hover:border-pine transition-colors"
      style={{ top: target.top, left: target.left }}
    >
      ↓ Excel
    </button>
  );
}
