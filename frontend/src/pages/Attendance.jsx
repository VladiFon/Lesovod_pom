import React, { useEffect, useMemo, useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { useToast } from "../components/Toast.jsx";
import { api } from "../api/client.js";

/**
 * Экран "Присутствие" (часть раздела "Люди") — табель за месяц поверх
 * GET /api/attendance (см. app/routers/attendance.py): строки — сотрудники,
 * столбцы — дни месяца, в ячейке цветной статус за день. Клик по ячейке —
 * все отметки этого дня (время, геометка). Односторонняя лента: рабочий
 * отмечается в мобильном приложении (POST /api/bot/attendance), здесь
 * только читают.
 *
 * Итог за день, когда отметок было несколько (лента append-only: "работаю"
 * утром, "не работаю" вечером = конец смены, а не прогул), — по приоритету,
 * а не по последней отметке: больничный > работал > не работал.
 *
 * Список сотрудников строится из отметок месяца: отдельный справочник
 * (GET /api/auth/workers и т.п.) требует прав редактирования, а этот экран
 * открыт и наблюдателю. Сотрудник, ни разу не отметившийся за месяц, в
 * табеле не появится.
 *
 * Даты дней берутся прямо из строки created_at ("ГГГГ-ММ-ДД ЧЧ:ММ:СС", время
 * сервера) без преобразования в Date — так день не "съезжает" из-за часового
 * пояса браузера. "Сегодня" и текущий месяц — по локальному времени.
 */
const STATUS_WORKED = "работаю";
const STATUS_OFF = "не работаю";
const STATUS_SICK = "больничный";

// код для ячейки (цвет не единственный признак), подпись, тон чипа в деталях, классы ячейки
const DAY_KINDS = {
  worked: { code: "Р", label: "Работал", tone: "success", cell: "bg-green text-white" },
  sick: { code: "Б", label: "Больничный", tone: "danger", cell: "bg-error text-white" },
  off: { code: "Н", label: "Не работал", tone: "neutral", cell: "bg-hover text-muted border border-border" },
};

const STATUS_TONE = { [STATUS_WORKED]: "success", [STATUS_OFF]: "neutral", [STATUS_SICK]: "danger" };

const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const WEEKDAYS = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

const pad = (n) => String(n).padStart(2, "0");
const isoDay = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;

function currentMonth() {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() };
}

function todayIso() {
  const now = new Date();
  return isoDay(now.getFullYear(), now.getMonth(), now.getDate());
}

function dayKind(marks) {
  if (marks.some((m) => m.status === STATUS_SICK)) return "sick";
  if (marks.some((m) => m.status === STATUS_WORKED)) return "worked";
  return "off";
}

const timeOf = (createdAt) => (createdAt?.split(" ")[1] ?? "").slice(0, 5);

export default function Attendance() {
  const toast = useToast();
  const [{ year, month }, setYm] = useState(currentMonth);
  const [marks, setMarks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null); // { employee, iso, marks }

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = todayIso();

  useEffect(() => {
    let cancelled = false; // быстрое переключение месяцев: старый ответ не должен перебить новый
    setLoading(true);
    api
      .get("/attendance/", { date_from: isoDay(year, month, 1), date_to: isoDay(year, month, daysInMonth) })
      .then((rows) => !cancelled && setMarks(rows))
      .catch((e) => !cancelled && toast.show({ tone: "danger", title: "Не удалось загрузить отметки", description: e.message }))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, month]);

  // сотрудники × дни: { id, fio, dolzhnost, days: { "ГГГГ-ММ-ДД": [отметки по времени] } }
  const employees = useMemo(() => {
    const byId = new Map();
    marks.forEach((m) => {
      if (!byId.has(m.sotrudnik_id)) {
        byId.set(m.sotrudnik_id, { id: m.sotrudnik_id, fio: m.sotrudnik_fio, dolzhnost: m.sotrudnik_dolzhnost, days: {} });
      }
      const day = m.created_at.slice(0, 10);
      (byId.get(m.sotrudnik_id).days[day] ??= []).push(m);
    });
    const list = Array.from(byId.values());
    list.forEach((e) => {
      Object.values(e.days).forEach((arr) => arr.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id));
      const kinds = Object.values(e.days).map(dayKind);
      e.worked = kinds.filter((k) => k === "worked").length;
      e.sick = kinds.filter((k) => k === "sick").length;
    });
    return list.sort((a, b) => a.fio.localeCompare(b.fio, "ru"));
  }, [marks]);

  const days = useMemo(
    () =>
      Array.from({ length: daysInMonth }, (_, i) => {
        const d = i + 1;
        const dow = new Date(year, month, d).getDay();
        return { d, iso: isoDay(year, month, d), weekday: WEEKDAYS[dow], weekend: dow === 0 || dow === 6 };
      }),
    [year, month, daysInMonth]
  );

  const shiftMonth = (delta) => {
    const dt = new Date(year, month + delta, 1);
    setYm({ year: dt.getFullYear(), month: dt.getMonth() });
  };

  const onMonthInput = (value) => {
    const m = /^(\d{4})-(\d{2})$/.exec(value);
    if (m) setYm({ year: Number(m[1]), month: Number(m[2]) - 1 });
  };

  const isCurrent = currentMonth().year === year && currentMonth().month === month;
  const detailDate = detail ? `${Number(detail.iso.slice(8))} ${MONTHS_GEN[Number(detail.iso.slice(5, 7)) - 1]} ${detail.iso.slice(0, 4)}` : "";

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5">
            <Button variant="secondary" size="sm" onClick={() => shiftMonth(-1)} aria-label="Предыдущий месяц">
              ‹
            </Button>
            <input
              type="month"
              value={`${year}-${pad(month + 1)}`}
              onChange={(e) => onMonthInput(e.target.value)}
              aria-label="Месяц"
              className="bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none"
            />
            <Button variant="secondary" size="sm" onClick={() => shiftMonth(1)} aria-label="Следующий месяц">
              ›
            </Button>
            {!isCurrent && (
              <Button variant="secondary" size="sm" onClick={() => setYm(currentMonth())}>
                Текущий месяц
              </Button>
            )}
          </div>
          <span className="font-ui font-bold text-[15px] text-ink capitalize">
            {MONTHS[month]} {year}
          </span>
          <div className="flex items-center gap-3 ml-auto text-[12px] text-muted">
            {Object.values(DAY_KINDS).map((k) => (
              <span key={k.code} className="flex items-center gap-1.5">
                <span className={`inline-flex h-5 w-5 items-center justify-center rounded text-[10.5px] font-bold ${k.cell}`}>{k.code}</span>
                {k.label}
              </span>
            ))}
          </div>
        </div>
      </Card>

      <Card padding={false}>
        {!loading && employees.length === 0 ? (
          <EmptyState
            icon="🗓️"
            title="Отметок за месяц нет"
            description="В этом месяце никто не отмечался в мобильном приложении."
          />
        ) : (
          <div className={`overflow-x-auto transition-opacity ${loading ? "opacity-50" : ""}`} aria-busy={loading}>
            <table className="border-separate border-spacing-0 text-[12px]">
              <thead>
                <tr>
                  <th className="sticky left-0 z-10 bg-surface-alt text-left px-3 py-2 min-w-[190px] text-muted font-semibold border-b border-border">
                    Сотрудник
                  </th>
                  {days.map((day) => (
                    <th
                      key={day.d}
                      className={`px-0 py-1 min-w-[30px] text-center font-semibold border-b border-border ${
                        day.iso === today ? "bg-mint-soft text-pine" : day.weekend ? "bg-hover text-faint" : "bg-surface-alt text-muted"
                      }`}
                    >
                      <div className="text-[12px] leading-4">{day.d}</div>
                      <div className="text-[9.5px] leading-3 font-normal">{day.weekday}</div>
                    </th>
                  ))}
                  <th className="px-2 py-2 text-center text-muted font-semibold bg-surface-alt border-b border-l border-border" title="Дней работал">
                    Р
                  </th>
                  <th className="px-2 py-2 text-center text-muted font-semibold bg-surface-alt border-b border-border" title="Дней на больничном">
                    Б
                  </th>
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => (
                  <tr key={emp.id} className="group">
                    <td className="sticky left-0 z-10 bg-surface px-3 py-1.5 border-b border-border group-hover:bg-hover">
                      <div className="font-medium text-ink text-[13px] leading-4">{emp.fio}</div>
                      <div className="text-muted-2 text-[11px]">{emp.dolzhnost || "—"}</div>
                    </td>
                    {days.map((day) => {
                      const dayMarks = emp.days[day.iso];
                      const kind = dayMarks ? DAY_KINDS[dayKind(dayMarks)] : null;
                      return (
                        <td
                          key={day.d}
                          className={`p-[2px] text-center border-b border-border ${day.iso === today ? "bg-mint-soft" : day.weekend ? "bg-hover" : ""}`}
                        >
                          {kind ? (
                            <button
                              type="button"
                              onClick={() => setDetail({ employee: emp, iso: day.iso, marks: dayMarks })}
                              title={`${kind.label} · отметок: ${dayMarks.length}`}
                              aria-label={`${emp.fio}, ${day.d} ${MONTHS_GEN[month]}: ${kind.label}`}
                              className={`h-[26px] w-[26px] rounded text-[11px] font-bold hover:ring-2 hover:ring-pine focus-visible:ring-2 focus-visible:ring-pine outline-none ${kind.cell}`}
                              style={{ cursor: "pointer" }}
                            >
                              {kind.code}
                            </button>
                          ) : (
                            <span className="inline-block h-[26px] w-[26px]" aria-hidden="true" />
                          )}
                        </td>
                      );
                    })}
                    <td className="px-2 text-center font-semibold text-green border-b border-l border-border">{emp.worked || "—"}</td>
                    <td className="px-2 text-center font-semibold text-error border-b border-border">{emp.sick || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        title={detail ? `${detail.employee.fio} — ${detailDate}` : ""}
        size="sm"
        footer={
          <Button variant="secondary" onClick={() => setDetail(null)}>
            Закрыть
          </Button>
        }
      >
        {detail && (
          <div className="flex flex-col gap-3">
            <p className="text-muted text-[12.5px]">
              {detail.employee.dolzhnost || "—"} · итог дня: <b className="text-ink">{DAY_KINDS[dayKind(detail.marks)].label}</b>
            </p>
            <ul className="flex flex-col gap-2">
              {detail.marks.map((m) => (
                <li key={m.id} className="flex items-center gap-3 border border-border rounded-[10px] px-3 py-2">
                  <span className="font-mono text-[13px] text-ink w-11 shrink-0">{timeOf(m.created_at)}</span>
                  <StatusBadge tone={STATUS_TONE[m.status] || "neutral"} label={m.status} />
                  <span className="ml-auto text-[12.5px]">
                    {m.lat != null && m.lon != null ? (
                      <a
                        href={`https://www.google.com/maps?q=${m.lat},${m.lon}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-pine font-semibold hover:underline"
                      >
                        📍 {m.lat.toFixed(5)}, {m.lon.toFixed(5)}
                      </a>
                    ) : (
                      <span className="text-faint">без геометки</span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Modal>
    </div>
  );
}
