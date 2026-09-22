import React, { useCallback, useEffect, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "ИИ-журнал" (screens/ai_log/) — Этап 13 плана, последний обычный
 * экран перед Абрисом.
 *
 * Backend написан заново в этом чате (app/routers/ai_log.py) — под этот
 * экран, как и под "Архив"/"Календарь", в lesovod_backend_stage2.zip
 * ничего не было. Логика (SQL, перенос должности из lesorub_directory
 * при одобрении) — 1:1 из screens/ai_log/screen_data.py +
 * screen_completed.py:approve_and_transfer (см. STAGE13.md).
 *
 * Перенесено 1:1:
 *   Вкладка "Требуют проверки" (raw_reports, status='на проверке')       → таблица + панель разбора справа
 *   Панель разбора: текст сообщения, фото, поля квартал/выдел/тип        → предзаполнены ботом, лесничий проверяет/правит
 *   работы/исполнитель/лесничество/описание (все уже приходят от бота)
 *   "Одобрить и перенести" → INSERT completed_works + status='обработано' → та же кнопка, тот же перенос должности по ФИО
 *   Вкладка "Выполненные работы" с фильтрами (период/исполнитель/         → таблица + фильтры, GET /completed + /completed/filters
 *   вид работы/должность), LIMIT 500
 *   Удаление записи о выполненной работе (с предупреждением про наряды)  → кнопка "Удалить" с тем же текстом предупреждения
 *
 * Новое по сравнению с desktop:
 *   Кнопка "Отклонить" для сырого отчёта (в desktop было только
 *   одобрение) — симметричное действие, POST .../reject.
 *
 * Сознательно не перенесено:
 *   "Создать наряд рубок ухода" (create_uhody_signal) — кросс-экранная
 *   связь с экраном "Рубки ухода", которого нет в списке экранов веб-версии
 *   (Sidebar) вообще — соответственно, не переносится и здесь.
 */

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
function monthAgoISO() {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 10);
}

function PhotoThumb({ path }) {
  if (!path) return null;
  const src = `${API_BASE_URL}/ai-log/photo?path=${encodeURIComponent(path)}`;
  return (
    <a href={src} target="_blank" rel="noreferrer">
      <img src={src} alt="" className="max-h-56 rounded-md border border-border object-contain" />
    </a>
  );
}

function ReviewPanel({ report, onDone }) {
  const toast = useToast();
  const [kvartal, setKvartal] = useState(report.kvartal || "");
  const [vydel, setVydel] = useState(report.vydels || "");
  const [tipRaboty, setTipRaboty] = useState(report.tip_raboty || "");
  const [ispolnitel, setIspolnitel] = useState(report.ispolnitel_fio || "");
  const [lesnichestvo, setLesnichestvo] = useState("");
  const [opisanie, setOpisanie] = useState(report.opisanie || "");
  const [submitting, setSubmitting] = useState(null);

  useEffect(() => {
    setKvartal(report.kvartal || "");
    setVydel(report.vydels || "");
    setTipRaboty(report.tip_raboty || "");
    setIspolnitel(report.ispolnitel_fio || "");
    setOpisanie(report.opisanie || "");
    setLesnichestvo("");
  }, [report]);

  const handleApprove = async () => {
    if (!(kvartal.trim() && vydel.trim() && tipRaboty.trim() && lesnichestvo.trim())) {
      toast.show({ tone: "warning", title: "Заполните квартал, выдел, тип работы и лесничество" });
      return;
    }
    setSubmitting("approve");
    try {
      await api.post(`/ai-log/raw-reports/${report.id}/approve`, {
        kvartal: kvartal.trim(), vydel: vydel.trim(), tip_raboty: tipRaboty.trim(),
        lesnichestvo: lesnichestvo.trim(), ispolnitel_fio: ispolnitel.trim(), opisanie: opisanie.trim(),
      });
      toast.show({ tone: "success", title: "Отчёт одобрен и перенесён в выполненные работы" });
      onDone();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось одобрить отчёт", description: e.message });
    } finally {
      setSubmitting(null);
    }
  };

  const handleReject = async () => {
    if (!window.confirm("Отклонить этот отчёт?")) return;
    setSubmitting("reject");
    try {
      await api.post(`/ai-log/raw-reports/${report.id}/reject`);
      toast.show({ tone: "success", title: "Отчёт отклонён" });
      onDone();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось отклонить отчёт", description: e.message });
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <Card>
      <div className="flex flex-col gap-4">
        <div>
          <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Сообщение от {report.ispolnitel_fio || "—"}</div>
          <p className="text-base text-ink bg-surface-alt rounded-md p-3">{report.raw_text || "(пустой текст сообщения)"}</p>
        </div>
        {report.photo_path && <PhotoThumb path={report.photo_path} />}
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Квартал" value={kvartal} onChange={(e) => setKvartal(e.target.value)} />
          <TextField label="Выдел" value={vydel} onChange={(e) => setVydel(e.target.value)} />
        </div>
        <TextField label="Тип работы" value={tipRaboty} onChange={(e) => setTipRaboty(e.target.value)} />
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Исполнитель" value={ispolnitel} onChange={(e) => setIspolnitel(e.target.value)} />
          <TextField label="Лесничество" value={lesnichestvo} onChange={(e) => setLesnichestvo(e.target.value)} />
        </div>
        <TextField label="Описание" value={opisanie} onChange={(e) => setOpisanie(e.target.value)} />
        <div className="flex items-center gap-2">
          <Button variant="primary" onClick={handleApprove} loading={submitting === "approve"} disabled={submitting !== null && submitting !== "approve"}>
            ✅ Одобрить и перенести
          </Button>
          <Button variant="danger" onClick={handleReject} loading={submitting === "reject"} disabled={submitting !== null && submitting !== "reject"}>
            ✕ Отклонить
          </Button>
        </div>
      </div>
    </Card>
  );
}

function RawReportsTab() {
  const toast = useToast();
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get("/ai-log/raw-reports");
      setReports(rows || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить отчёты", description: e.message });
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const handleDone = () => {
    setSelectedId(null);
    load();
  };

  const selected = reports.find((r) => r.id === selectedId) || null;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-6 items-start">
      <Card padding={false}>
        <DataTable
          loading={loading}
          columns={[
            { key: "data_soobscheniya", header: "Дата" },
            { key: "ispolnitel_fio", header: "Исполнитель", render: (r) => r.ispolnitel_fio || "—" },
            { key: "tip_raboty", header: "Тип работы", render: (r) => r.tip_raboty || "—" },
            { key: "kvartal", header: "Квартал", render: (r) => r.kvartal || "—" },
            { key: "vydels", header: "Выдел", render: (r) => r.vydels || "—" },
            { key: "raw_text", header: "Сообщение", render: (r) => (r.raw_text || "").slice(0, 60) || "—" },
          ]}
          rows={reports}
          onRowClick={(r) => setSelectedId(r.id)}
          emptyTitle="Отчётов на проверке нет"
          emptyDescription="Новые сообщения от рабочих через telegram-бота появятся здесь."
        />
      </Card>

      {selected ? (
        <ReviewPanel report={selected} onDone={handleDone} />
      ) : (
        <Card>
          <EmptyState icon="🔍" title="Выберите отчёт" description="Нажмите на строку слева, чтобы разобрать сообщение." />
        </Card>
      )}
    </div>
  );
}

function CompletedTab() {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ executors: [], types: [], dolzhnosti: [] });
  const [dateFrom, setDateFrom] = useState(monthAgoISO());
  const [dateTo, setDateTo] = useState(todayISO());
  const [executor, setExecutor] = useState("");
  const [tipRaboty, setTipRaboty] = useState("");
  const [dolzhnost, setDolzhnost] = useState("");

  useEffect(() => {
    api.get("/ai-log/completed/filters").then(setFilters).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get("/ai-log/completed", {
        date_from: dateFrom, date_to: dateTo,
        executor: executor || undefined, tip_raboty: tipRaboty || undefined, dolzhnost: dolzhnost || undefined,
      });
      setRows(data || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить журнал", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, executor, tipRaboty, dolzhnost]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = async (row) => {
    if (!window.confirm(
      "Удалить эту запись о выполненной работе?\n\nЕсли по ней уже был сделан наряд рубок ухода на другом экране, сам наряд удалён не будет — при необходимости удалите его отдельно."
    )) return;
    try {
      await api.delete(`/ai-log/completed/${row.id}`);
      setRows((prev) => prev.filter((r) => r.id !== row.id));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить запись", description: e.message });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <div className="flex items-end gap-3 flex-wrap">
          <TextField label="С" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <TextField label="По" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <div className="min-w-[180px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Исполнитель</label>
            <select value={executor} onChange={(e) => setExecutor(e.target.value)} className="w-full bg-surface-alt border border-transparent focus:border-pine rounded-md px-3.5 py-2.5 text-base text-ink outline-none">
              <option value="">Все</option>
              {filters.executors.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div className="min-w-[180px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Вид работы</label>
            <select value={tipRaboty} onChange={(e) => setTipRaboty(e.target.value)} className="w-full bg-surface-alt border border-transparent focus:border-pine rounded-md px-3.5 py-2.5 text-base text-ink outline-none">
              <option value="">Все</option>
              {filters.types.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div className="min-w-[180px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Должность</label>
            <select value={dolzhnost} onChange={(e) => setDolzhnost(e.target.value)} className="w-full bg-surface-alt border border-transparent focus:border-pine rounded-md px-3.5 py-2.5 text-base text-ink outline-none">
              <option value="">Все</option>
              {filters.dolzhnosti.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
        </div>
      </Card>

      <Card>
        <DataTable
          loading={loading}
          columns={[
            { key: "data_vypolneniya", header: "Дата" },
            { key: "ispolnitel_fio", header: "Исполнитель", render: (r) => r.ispolnitel_fio || "—" },
            { key: "dolzhnost", header: "Должность", render: (r) => r.dolzhnost || "—" },
            { key: "kvartal", header: "Квартал", render: (r) => r.kvartal || "—" },
            { key: "vydel", header: "Выдел", render: (r) => r.vydel || "—" },
            { key: "tip_raboty", header: "Вид работы", render: (r) => r.tip_raboty || "—" },
            { key: "lesnichestvo", header: "Лесничество", render: (r) => r.lesnichestvo || "—" },
            { key: "opisanie", header: "Описание", render: (r) => r.opisanie || "—" },
            {
              key: "actions", header: "",
              render: (r) => <button onClick={() => handleDelete(r)} className="text-error font-semibold hover:opacity-80">Удалить</button>,
            },
          ]}
          rows={rows}
          emptyTitle="Записей нет"
          emptyDescription="Измените период или фильтры выше."
        />
      </Card>
    </div>
  );
}

export default function AiLog() {
  const [tab, setTab] = useState("raw");

  return (
    <div className="p-8 flex flex-col gap-6">
      <div className="flex gap-1 border-b border-border">
        {[
          { key: "raw", label: "Требуют проверки" },
          { key: "completed", label: "Выполненные работы" },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={[
              "px-4 py-2 text-base font-semibold border-b-2 -mb-px transition-colors",
              tab === t.key ? "border-pine text-pine" : "border-transparent text-muted hover:text-pine",
            ].join(" ")}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "raw" ? <RawReportsTab /> : <CompletedTab />}
    </div>
  );
}
