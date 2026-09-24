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
 * GET /api/attendance (мобильные отметки, см. app/routers/attendance.py)
 * И GET /api/attendance/tabel (табель ручного ввода лесничего, см.
 * app/routers/tabel.py и legacy webext.list_tabel_zapisi): строки —
 * сотрудники, столбцы — дни месяца, в ячейке цветной статус за день. Клик
 * по ячейке — детали дня: и мобильные отметки (время, геометка), и — если
 * лесничий вносил вручную — место работы/вид работы/комментарий.
 *
 * Ручная запись табеля на день ПЕРЕКРЫВАЕТ мобильные отметки того же дня
 * при определении итогового статуса ячейки: это единая исправляемая запись
 * (UPSERT на сотрудника+день), а не лог отметок телефона — если лесничий
 * сам расставил день, он считается более точным источником.
 *
 * Итог за день по мобильным отметкам, когда их было несколько (лента
 * append-only: "работаю" утром, "не работаю" вечером = конец смены, а не
 * прогул), — по приоритету, а не по последней отметке: больничный > работал
 * > не работал.
 *
 * Список сотрудников строится из отметок месяца ЛИБО записей табеля:
 * отдельный справочник (GET /api/auth/workers и т.п.) требует прав
 * редактирования, а этот экран открыт и наблюдателю. Сотрудник, ни разу не
 * отметившийся и не занесённый в табель за месяц, здесь не появится.
 *
 * Даты дней берутся прямо из строки created_at ("ГГГГ-ММ-ДД ЧЧ:ММ:СС", время
 * сервера) без преобразования в Date — так день не "съезжает" из-за часового
 * пояса браузера. "Сегодня" и текущий месяц — по локальному времени.
 */
const STATUS_WORKED = "работаю";
const STATUS_OFF = "не работаю";
const STATUS_SICK = "больничный";

// Статусы ручного табеля (tabel_zapis) — те же "работал/не работал/
// больничный", что и в мобильной ленте, плюс отпуск/выходной, которых в
// мобильном приложении нет (просьба пользователя, 24.09.2026).
const TABEL_WORKED = "работал";
const TABEL_OFF = "не работал";
const TABEL_SICK = "больничный";
const TABEL_VACATION = "отпуск";
const TABEL_DAYOFF = "выходной";

// код для ячейки (цвет не единственный признак), подпись, тон чипа в деталях, классы ячейки
const DAY_KINDS = {
  worked: { code: "Р", label: "Работал", tone: "success", cell: "bg-green text-white" },
  sick: { code: "Б", label: "Больничный", tone: "danger", cell: "bg-error text-white" },
  off: { code: "Н", label: "Не работал", tone: "neutral", cell: "bg-hover text-muted border border-border" },
  vacation: { code: "О", label: "Отпуск", tone: "warning", cell: "bg-oak text-white" },
  dayoff: { code: "В", label: "Выходной", tone: "neutral", cell: "bg-surface-alt text-faint border border-border" },
};

const STATUS_TONE = { [STATUS_WORKED]: "success", [STATUS_OFF]: "neutral", [STATUS_SICK]: "danger" };

// Статус ручного табеля → тот же "код дня", что и у мобильных отметок.
const TABEL_STATUS_KIND = {
  [TABEL_WORKED]: "worked",
  [TABEL_SICK]: "sick",
  [TABEL_OFF]: "off",
  [TABEL_VACATION]: "vacation",
  [TABEL_DAYOFF]: "dayoff",
};

function tabelLocation(entry) {
  if (entry.lesokultury_uchastok_id) {
    return `кв. ${entry.lku_kvartal || "—"} / выд. ${entry.lku_vydel || "—"}${entry.lku_glavnaya_poroda ? ` · ${entry.lku_glavnaya_poroda}` : ""}`;
  }
  if (entry.delyanka_item_id) {
    return `кв. ${entry.d_kvartal || "—"} / выд. ${entry.d_vydel || "—"}`;
  }
  return null;
}

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

// Итог дня для ячейки, когда для сотрудника на этот день есть и мобильные
// отметки, и ручная запись табеля: запись табеля — приоритетнее (см.
// докстринг выше), мобильные отметки используются, только если лесничий
// день не заполнял.
function cellDayKind(day) {
  if (day.tabel) return TABEL_STATUS_KIND[day.tabel.status] || "off";
  if (day.marks) return dayKind(day.marks);
  return null;
}

const timeOf = (createdAt) => (createdAt?.split(" ")[1] ?? "").slice(0, 5);

export default function Attendance() {
  const toast = useToast();
  const [{ year, month }, setYm] = useState(currentMonth);
  const [marks, setMarks] = useState([]);
  const [tabelEntries, setTabelEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null); // { employee, iso, marks, tabel, kind }

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = todayIso();

  useEffect(() => {
    let cancelled = false; // быстрое переключение месяцев: старый ответ не должен перебить новый
    setLoading(true);
    const params = { date_from: isoDay(year, month, 1), date_to: isoDay(year, month, daysInMonth) };
    Promise.all([api.get("/attendance/", params), api.get("/attendance/tabel", params)])
      .then(([markRows, tabelRows]) => {
        if (cancelled) return;
        setMarks(markRows);
        setTabelEntries(tabelRows);
      })
      .catch((e) => !cancelled && toast.show({ tone: "danger", title: "Не удалось загрузить отметки", description: e.message }))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, month]);

  // сотрудники × дни: { id, fio, dolzhnost, days: { "ГГГГ-ММ-ДД": { marks: [...] | null, tabel: {...} | null } } }
  // — сливает мобильную ленту (attendance_marks) и ручной табель (tabel_zapis)
  // в одну сетку; запись табеля на день приоритетнее её мобильных отметок
  // (см. cellDayKind).
  const employees = useMemo(() => {
    const byId = new Map();
    const getEmp = (id, fio, dolzhnost) => {
      if (!byId.has(id)) byId.set(id, { id, fio, dolzhnost, days: {} });
      return byId.get(id);
    };
    marks.forEach((m) => {
      const emp = getEmp(m.sotrudnik_id, m.sotrudnik_fio, m.sotrudnik_dolzhnost);
      const day = m.created_at.slice(0, 10);
      (emp.days[day] ??= { marks: null, tabel: null });
      (emp.days[day].marks ??= []).push(m);
    });
    tabelEntries.forEach((t) => {
      const emp = getEmp(t.sotrudnik_id, t.sotrudnik_fio, t.sotrudnik_dolzhnost);
      (emp.days[t.data] ??= { marks: null, tabel: null });
      emp.days[t.data].tabel = t;
    });
    const list = Array.from(byId.values());
    list.forEach((e) => {
      Object.values(e.days).forEach((day) => {
        day.marks?.sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id);
      });
      const kinds = Object.values(e.days).map(cellDayKind).filter(Boolean);
      e.worked = kinds.filter((k) => k === "worked").length;
      e.sick = kinds.filter((k) => k === "sick").length;
    });
    return list.sort((a, b) => a.fio.localeCompare(b.fio, "ru"));
  }, [marks, tabelEntries]);

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
            description="В этом месяце никто не отмечался в мобильном приложении и не внесён в табель вручную."
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
                      const dayData = emp.days[day.iso];
                      const kindKey = dayData ? cellDayKind(dayData) : null;
                      const kind = kindKey ? DAY_KINDS[kindKey] : null;
                      const marksCount = dayData?.marks?.length || 0;
                      const titleSuffix = dayData?.tabel
                        ? "табель заполнен вручную"
                        : marksCount
                        ? `отметок: ${marksCount}`
                        : "";
                      return (
                        <td
                          key={day.d}
                          className={`p-[2px] text-center border-b border-border ${day.iso === today ? "bg-mint-soft" : day.weekend ? "bg-hover" : ""}`}
                        >
                          {kind ? (
                            <button
                              type="button"
                              onClick={() => setDetail({ employee: emp, iso: day.iso, marks: dayData.marks, tabel: dayData.tabel, kind: kindKey })}
                              title={`${kind.label}${titleSuffix ? ` · ${titleSuffix}` : ""}`}
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
              {detail.employee.dolzhnost || "—"} · итог дня: <b className="text-ink">{DAY_KINDS[detail.kind].label}</b>
            </p>

            {detail.tabel && (
              <div className="border border-border rounded-[10px] px-3 py-2.5 flex flex-col gap-1.5 bg-mint-soft/40">
                <div className="flex items-center gap-2">
                  <StatusBadge tone={DAY_KINDS[TABEL_STATUS_KIND[detail.tabel.status] || "off"].tone} label={detail.tabel.status} />
                  <span className="text-[11px] text-faint ml-auto">внесено вручную{detail.tabel.entered_by ? ` · ${detail.tabel.entered_by}` : ""}</span>
                </div>
                {tabelLocation(detail.tabel) && (
                  <p className="text-[12.5px] text-ink">📍 {tabelLocation(detail.tabel)}</p>
                )}
                {detail.tabel.vid_raboty_nazvanie && (
                  <p className="text-[12.5px] text-ink">🛠 {detail.tabel.vid_raboty_nazvanie}</p>
                )}
                {detail.tabel.kommentariy && (
                  <p className="text-[12.5px] text-muted">{detail.tabel.kommentariy}</p>
                )}
                {!tabelLocation(detail.tabel) && !detail.tabel.vid_raboty_nazvanie && !detail.tabel.kommentariy && (
                  <p className="text-[12.5px] text-faint">Без указания места/вида работы</p>
                )}
              </div>
            )}

            {detail.marks && detail.marks.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {detail.tabel && <div className="text-[11px] text-faint uppercase tracking-wide">Отметки в приложении</div>}
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
          </div>
        )}
      </Modal>
    </div>
  );
}
