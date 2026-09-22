import React, { useEffect, useMemo, useState } from "react";
import Card from "../components/Card.jsx";
import TextField from "../components/TextField.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { useToast } from "../components/Toast.jsx";
import { api } from "../api/client.js";

/**
 * Экран "Присутствие" (часть раздела "Люди") — сводка "кто сегодня
 * работал" поверх GET /api/attendance (см. app/routers/attendance.py).
 * Односторонняя лента: рабочий отмечается в мобильном приложении
 * (POST /api/bot/attendance), здесь только читают, ответа обратно нет.
 *
 * Список сотрудников для фильтра строится из уже загруженных отметок
 * (уникальные sotrudnik_id/fio), а не отдельным запросом к пикеру —
 * GET /work-plan/sotrudniki и GET /uhody/sotrudniki требуют права
 * редактирования (admin/lesovod), а этот экран, как и сам
 * GET /api/attendance, должен быть доступен любому залогиненному
 * офисному пользователю (см. обсуждение прав в app/routers/attendance.py).
 */
const STATUS_TONE = {
  "работаю": "success",
  "не работаю": "neutral",
  "больничный": "danger",
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function formatDateTime(s) {
  if (!s) return "—";
  const [date, time] = s.split(" ");
  return `${date.split("-").reverse().join(".")} ${time?.slice(0, 5) ?? ""}`;
}

export default function Attendance() {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState(todayIso());
  const [dateTo, setDateTo] = useState(todayIso());
  const [sotrudnikId, setSotrudnikId] = useState("");

  const load = () => {
    setLoading(true);
    api
      .get("/attendance/", { date_from: dateFrom || undefined, date_to: dateTo || undefined, sotrudnik_id: sotrudnikId || undefined })
      .then(setRows)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить отметки", description: e.message }))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, sotrudnikId]);

  // Список для фильтра "Сотрудник" — берём из последней НЕотфильтрованной
  // по sotrudnik_id загрузки, чтобы при переключении фильтра список имён
  // не схлопывался до одного выбранного.
  const [allSeen, setAllSeen] = useState([]);
  useEffect(() => {
    if (!sotrudnikId && rows.length) {
      const seen = new Map();
      rows.forEach((r) => seen.set(r.sotrudnik_id, r.sotrudnik_fio));
      setAllSeen(Array.from(seen, ([id, fio]) => ({ id, fio })).sort((a, b) => a.fio.localeCompare(b.fio, "ru")));
    }
  }, [rows, sotrudnikId]);

  const columns = useMemo(
    () => [
      { key: "sotrudnik_fio", header: "Сотрудник", render: (r) => (
        <div>
          <div className="font-medium text-ink">{r.sotrudnik_fio}</div>
          <div className="text-muted-2 text-xs">{r.sotrudnik_dolzhnost || "—"}</div>
        </div>
      ) },
      { key: "status", header: "Статус", render: (r) => <StatusBadge tone={STATUS_TONE[r.status] || "neutral"} label={r.status} /> },
      { key: "created_at", header: "Время отметки", render: (r) => formatDateTime(r.created_at) },
      {
        key: "coords", header: "Координаты",
        render: (r) =>
          r.lat != null && r.lon != null ? (
            <a
              href={`https://www.google.com/maps?q=${r.lat},${r.lon}`}
              target="_blank"
              rel="noreferrer"
              className="text-pine font-semibold hover:underline"
            >
              {r.lat.toFixed(5)}, {r.lon.toFixed(5)}
            </a>
          ) : (
            <span className="text-faint">—</span>
          ),
      },
    ],
    []
  );

  return (
    <div className="p-8 flex flex-col gap-6">
      <Card>
        <div className="flex items-center gap-3 flex-wrap">
          <TextField label="С даты" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <TextField label="По дату" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <div className="min-w-[220px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Сотрудник</label>
            <select
              value={sotrudnikId}
              onChange={(e) => setSotrudnikId(e.target.value)}
              className="w-full bg-surface-alt border border-transparent focus:border-pine rounded-md px-3.5 py-2.5 text-base text-ink outline-none"
            >
              <option value="">Все сотрудники</option>
              {allSeen.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.fio}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      <Card padding={false}>
        <DataTable
          columns={columns}
          rows={rows}
          loading={loading}
          emptyTitle="Отметок нет"
          emptyDescription="За выбранный период и фильтры никто не отмечался в мобильном приложении."
        />
      </Card>
    </div>
  );
}
