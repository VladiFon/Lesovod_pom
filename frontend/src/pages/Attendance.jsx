import React, { useEffect, useMemo, useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import Modal from "../components/Modal.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";
import { api } from "../api/client.js";

/**
 * Экран "Присутствие" (часть раздела "Люди") — табель на месяц поверх
 * GET /api/attendance (см. app/routers/attendance.py): строки —
 * сотрудники, столбцы — числа месяца, в ячейке — цвет последней за день
 * отметки. Клик по ячейке открывает все отметки за этот день (время,
 * статус, геометка).
 *
 * Строки табеля строятся из отметок, загруженных за месяц (как раньше
 * строился список для фильтра "Сотрудник") — GET /work-plan/sotrudniki и
 * GET /uhody/sotrudniki требуют права редактирования (admin/lesovod),
 * недоступные этому экрану (см. докстринг attendance.py), поэтому
 * сотрудник, который за весь месяц не отметился ни разу, строкой не
 * появится — это тот же компромисс, что и раньше, просто теперь виден на
 * уровне месяца, а не только текущего фильтра.
 */
const STATUS_TONE = {
  "работаю": "success",
  "не работаю": "neutral",
  "больничный": "danger",
};

const CELL_TONE = {
  "работаю": "bg-green",
  "не работаю": "bg-disabled",
  "больничный": "bg-error",
};

function pad2(n) {
  return String(n).padStart(2, "0");
}

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function daysInMonth(year, monthIndex0) {
  return new Date(year, monthIndex0 + 1, 0).getDate();
}

function shiftMonth(month, delta) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function monthLabel(month) {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1, 1);
  const label = d.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function formatTime(s) {
  const time = s?.split(" ")[1];
  return time ? time.slice(0, 5) : "—";
}

export default function Attendance() {
  const toast = useToast();
  const [month, setMonth] = useState(currentMonth());
  const [marks, setMarks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCell, setSelectedCell] = useState(null); // { emp, day }

  const [year, monthNum] = month.split("-").map(Number);
  const monthIndex0 = monthNum - 1;
  const totalDays = daysInMonth(year, monthIndex0);
  const days = useMemo(() => Array.from({ length: totalDays }, (_, i) => i + 1), [totalDays]);

  useEffect(() => {
    setLoading(true);
    api
      .get("/attendance/", { date_from: `${month}-01`, date_to: `${month}-${pad2(totalDays)}` })
      .then(setMarks)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить отметки", description: e.message }))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  const employees = useMemo(() => {
    const byId = new Map();
    for (const m of marks) {
      let emp = byId.get(m.sotrudnik_id);
      if (!emp) {
        emp = { id: m.sotrudnik_id, fio: m.sotrudnik_fio, dolzhnost: m.sotrudnik_dolzhnost, byDay: new Map() };
        byId.set(m.sotrudnik_id, emp);
      }
      const day = Number(m.created_at.slice(8, 10));
      const list = emp.byDay.get(day) || [];
      list.push(m);
      emp.byDay.set(day, list);
    }
    for (const emp of byId.values()) {
      for (const list of emp.byDay.values()) list.sort((a, b) => a.created_at.localeCompare(b.created_at));
    }
    return Array.from(byId.values()).sort((a, b) => a.fio.localeCompare(b.fio, "ru"));
  }, [marks]);

  const goMonth = (delta) => setMonth((m) => shiftMonth(m, delta));

  const selectedMarks = selectedCell ? selectedCell.emp.byDay.get(selectedCell.day) || [] : [];

  return (
    <div className="p-8 flex flex-col gap-6">
      <Card>
        <div className="flex items-center gap-3 flex-wrap">
          <Button variant="ghost" size="sm" onClick={() => goMonth(-1)} aria-label="Предыдущий месяц">
            ←
          </Button>
          <div className="min-w-[180px] text-center font-ui font-bold text-ink">{monthLabel(month)}</div>
          <Button variant="ghost" size="sm" onClick={() => goMonth(1)} aria-label="Следующий месяц">
            →
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setMonth(currentMonth())}>
            Текущий месяц
          </Button>

          <div className="ml-auto flex items-center gap-4 text-sm text-muted flex-wrap">
            {Object.entries(CELL_TONE).map(([label, tone]) => (
              <span key={label} className="inline-flex items-center gap-1.5">
                <span className={["h-2.5 w-2.5 rounded-sm", tone].join(" ")} />
                {label}
              </span>
            ))}
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm border border-border" />
              нет отметок
            </span>
          </div>
        </div>
      </Card>

      <Card padding={false}>
        {loading ? (
          <div className="p-5 text-muted text-sm">Загрузка…</div>
        ) : employees.length === 0 ? (
          <EmptyState
            title="Отметок нет"
            description="За выбранный месяц никто не отмечался в мобильном приложении."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="border-collapse text-sm w-full">
              <thead>
                <tr className="bg-surface-alt border-b border-border">
                  <th className="sticky left-0 z-10 bg-surface-alt px-3 py-2.5 text-left font-semibold text-muted min-w-[220px]">
                    Сотрудник
                  </th>
                  {days.map((day) => {
                    const dow = new Date(year, monthIndex0, day).getDay();
                    const isWeekend = dow === 0 || dow === 6;
                    return (
                      <th
                        key={day}
                        className={[
                          "px-1 py-2.5 text-center font-semibold w-9 min-w-[36px]",
                          isWeekend ? "text-oak bg-oak-soft" : "text-muted",
                        ].join(" ")}
                      >
                        {day}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => (
                  <tr key={emp.id} className="border-b border-border last:border-b-0">
                    <td className="sticky left-0 z-10 bg-surface px-3 py-2 min-w-[220px]">
                      <div className="font-medium text-ink">{emp.fio}</div>
                      <div className="text-muted-2 text-xs">{emp.dolzhnost || "—"}</div>
                    </td>
                    {days.map((day) => {
                      const dayMarks = emp.byDay.get(day);
                      const dow = new Date(year, monthIndex0, day).getDay();
                      const isWeekend = dow === 0 || dow === 6;
                      return (
                        <td
                          key={day}
                          className={["px-1 py-2 text-center", isWeekend ? "bg-oak-soft" : ""].join(" ")}
                        >
                          {dayMarks ? (
                            <button
                              onClick={() => setSelectedCell({ emp, day })}
                              title={`${dayMarks[dayMarks.length - 1].status} — нажмите для деталей`}
                              className={[
                                "relative inline-flex h-6 w-6 rounded-sm items-center justify-center",
                                "hover:ring-2 hover:ring-pine transition-shadow",
                                CELL_TONE[dayMarks[dayMarks.length - 1].status] || "bg-disabled",
                              ].join(" ")}
                            >
                              {dayMarks.length > 1 && (
                                <span className="text-[9px] font-bold text-white">{dayMarks.length}</span>
                              )}
                            </button>
                          ) : (
                            <span className="inline-block h-6 w-6 rounded-sm border border-border" />
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={!!selectedCell}
        onClose={() => setSelectedCell(null)}
        title={
          selectedCell
            ? `${selectedCell.emp.fio} — ${pad2(selectedCell.day)}.${pad2(monthNum)}.${year}`
            : ""
        }
      >
        <div className="flex flex-col gap-3">
          {selectedMarks.map((m) => (
            <div
              key={m.id}
              className="flex items-center justify-between gap-3 bg-surface-alt rounded-md px-3 py-2.5"
            >
              <div className="flex items-center gap-2.5">
                <span className="font-mono text-sm text-muted">{formatTime(m.created_at)}</span>
                <StatusBadge tone={STATUS_TONE[m.status] || "neutral"} label={m.status} />
              </div>
              {m.lat != null && m.lon != null ? (
                <a
                  href={`https://www.google.com/maps?q=${m.lat},${m.lon}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-pine font-semibold text-sm hover:underline"
                >
                  {m.lat.toFixed(5)}, {m.lon.toFixed(5)}
                </a>
              ) : (
                <span className="text-faint text-sm">без геометки</span>
              )}
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}
