import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Рабочий календарь" (screens/calendar/) — Этап 12 плана.
 *
 * Backend написан заново в этом чате (app/routers/calendar.py +
 * legacy/calendar_tasks.py, скопированный без изменений из
 * lesovod_project_fixed_v5.zip — он и в desktop-версии написан без
 * зависимости от Qt специально для переиспользования, см. его докстринг).
 * Таблицы calendar_tasks/calendar_completions уже были в схеме db.py —
 * не хватало только самого модуля и роутера (см. STAGE12.md).
 *
 * Перенесено 1:1 (см. screens/calendar/screen.py):
 *   RECURRENCE_LABELS, CATEGORY_SUGGESTIONS, STATE_STYLE (цвет/иконка по статусу)
 *   Разовая/ежемесячная/ежеквартальная/раз в полгода/ежегодная/сезонная периодичность
 *   "Отметить выполненным" текущего периода / снять отметку
 *   Пауза задачи (active=false) без потери истории выполнения
 *
 * Сознательно упрощено: сама сетка QCalendarWidget с подсветкой дней —
 * не перенесена, вместо неё список задач (тот же принцип, что и остальные
 * экраны: список + статус важнее календарной сетки для рабочего сценария
 * "что нужно сделать сейчас").
 */

const RECURRENCE_LABELS = {
  once: "Разово",
  monthly: "Ежемесячно",
  quarterly: "Ежеквартально",
  semiannual: "Раз в полгода",
  annual: "Ежегодно",
  seasonal: "Сезонная (диапазон дат)",
};

const CATEGORY_SUGGESTIONS = ["Отчётность", "Проверки/инспекции", "Сезонная работа", "Кадры/охрана труда", "Хозяйственное", "Прочее"];

const STATE_STYLE = {
  overdue: { tone: "danger", label: "Просрочено" },
  due_today: { tone: "warning", label: "Сегодня" },
  due_soon: { tone: "success", label: "Скоро" },
  upcoming: { tone: "neutral", label: "Позже" },
  done: { tone: "success", label: "Выполнено" },
};

const STATE_ORDER = ["overdue", "due_today", "due_soon", "upcoming", "done"];

const MONTH_NAMES_SHORT = ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

function formatDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function defaultConfig(recurrence) {
  switch (recurrence) {
    case "once": return { date: "" };
    case "monthly": return { day: 1 };
    case "quarterly": return { months: [3, 6, 9, 12], day: 10 };
    case "semiannual": return { months: [6, 12], day: 10 };
    case "annual": return { month: 1, day: 1 };
    case "seasonal": return { start_month: 4, start_day: 1, end_month: 5, end_day: 1 };
    default: return {};
  }
}

function RecurrenceConfigFields({ recurrence, config, setConfig }) {
  const set = (key) => (e) => setConfig((c) => ({ ...c, [key]: e.target.value }));
  const setNum = (key) => (e) => setConfig((c) => ({ ...c, [key]: Number(e.target.value) }));

  if (recurrence === "once") {
    return <TextField label="Дата" type="date" value={config.date || ""} onChange={set("date")} />;
  }
  if (recurrence === "monthly") {
    return <TextField label="Число месяца" type="number" min={1} max={31} value={config.day ?? 1} onChange={setNum("day")} className="w-40" />;
  }
  if (recurrence === "quarterly" || recurrence === "semiannual") {
    const months = config.months || [];
    const toggleMonth = (m) => {
      setConfig((c) => {
        const cur = c.months || [];
        return { ...c, months: cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m].sort((a, b) => a - b) };
      });
    };
    return (
      <div className="flex flex-col gap-2">
        <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase">Месяцы</label>
        <div className="flex flex-wrap gap-1.5">
          {MONTH_NAMES_SHORT.slice(1).map((name, idx) => {
            const m = idx + 1;
            const active = months.includes(m);
            return (
              <button
                key={m}
                type="button"
                onClick={() => toggleMonth(m)}
                className={["px-2.5 py-1.5 rounded-md text-sm font-semibold border", active ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted"].join(" ")}
              >
                {name}
              </button>
            );
          })}
        </div>
        <TextField label="Число месяца" type="number" min={1} max={31} value={config.day ?? 10} onChange={setNum("day")} className="w-40" />
      </div>
    );
  }
  if (recurrence === "annual") {
    return (
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <div>
          <label className="block text-[11.5px] font-semibold text-muted mb-1">Месяц</label>
          <select value={config.month ?? 1} onChange={setNum("month")} className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none">
            {MONTH_NAMES_SHORT.slice(1).map((name, idx) => (
              <option key={idx + 1} value={idx + 1}>{name}</option>
            ))}
          </select>
        </div>
        <TextField label="Число месяца" type="number" min={1} max={31} value={config.day ?? 1} onChange={setNum("day")} />
      </div>
    );
  }
  if (recurrence === "seasonal") {
    return (
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <div>
          <label className="block text-[11.5px] font-semibold text-muted mb-1">Начало сезона, месяц</label>
          <select value={config.start_month ?? 4} onChange={setNum("start_month")} className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none">
            {MONTH_NAMES_SHORT.slice(1).map((name, idx) => (
              <option key={idx + 1} value={idx + 1}>{name}</option>
            ))}
          </select>
        </div>
        <TextField label="Начало сезона, число" type="number" min={1} max={31} value={config.start_day ?? 1} onChange={setNum("start_day")} />
        <div>
          <label className="block text-[11.5px] font-semibold text-muted mb-1">Конец сезона (срок), месяц</label>
          <select value={config.end_month ?? 5} onChange={setNum("end_month")} className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none">
            {MONTH_NAMES_SHORT.slice(1).map((name, idx) => (
              <option key={idx + 1} value={idx + 1}>{name}</option>
            ))}
          </select>
        </div>
        <TextField label="Конец сезона, число" type="number" min={1} max={31} value={config.end_day ?? 1} onChange={setNum("end_day")} />
      </div>
    );
  }
  return null;
}

function TaskModal({ open, onClose, editing, onSaved }) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [recurrence, setRecurrence] = useState("once");
  const [config, setConfig] = useState(defaultConfig("once"));
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setTitle(editing.title || "");
      setDescription(editing.description || "");
      setCategory(editing.category || "");
      setRecurrence(editing.recurrence || "once");
      try {
        setConfig(JSON.parse(editing.recurrence_config_json || "{}"));
      } catch {
        setConfig(defaultConfig(editing.recurrence || "once"));
      }
    } else {
      setTitle("");
      setDescription("");
      setCategory("");
      setRecurrence("once");
      setConfig(defaultConfig("once"));
    }
  }, [open, editing]);

  const handleRecurrenceChange = (e) => {
    const next = e.target.value;
    setRecurrence(next);
    setConfig(defaultConfig(next));
  };

  const handleSubmit = async () => {
    if (!title.trim()) {
      toast.show({ tone: "warning", title: "Укажите название задачи" });
      return;
    }
    setSubmitting(true);
    try {
      const body = { title: title.trim(), description, category, recurrence, recurrence_config: config };
      if (editing) {
        await api.patch(`/calendar/tasks/${editing.id}`, body);
        toast.show({ tone: "success", title: "Задача обновлена" });
      } else {
        await api.post("/calendar/tasks", body);
        toast.show({ tone: "success", title: "Задача добавлена" });
      }
      onClose();
      onSaved();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить задачу", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Редактировать задачу" : "Новая задача календаря"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>Сохранить</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <TextField label="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextAreaField label="Описание" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <TextField label="Категория" list="calendar-categories" value={category} onChange={(e) => setCategory(e.target.value)} />
        <datalist id="calendar-categories">
          {CATEGORY_SUGGESTIONS.map((c) => <option key={c} value={c} />)}
        </datalist>
        <div>
          <label className="block text-[11.5px] font-semibold text-muted mb-1">Периодичность</label>
          <select value={recurrence} onChange={handleRecurrenceChange} className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none">
            {Object.entries(RECURRENCE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
        </div>
        <RecurrenceConfigFields recurrence={recurrence} config={config} setConfig={setConfig} />
      </div>
    </Modal>
  );
}

function TaskRow({ task, onChanged }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const style = STATE_STYLE[task.state] || STATE_STYLE.upcoming;

  const handleToggleDone = async () => {
    setBusy(true);
    try {
      if (task.is_done) {
        await api.delete(`/calendar/tasks/${task.id}/complete/${task.period_key}`);
      } else {
        await api.post(`/calendar/tasks/${task.id}/complete`, { period_key: task.period_key });
      }
      onChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось изменить отметку", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleToggleActive = async () => {
    setBusy(true);
    try {
      await api.post(`/calendar/tasks/${task.id}/active`, undefined, { active: !task.active });
      onChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось изменить статус", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Удалить задачу «${task.title}»?`)) return;
    try {
      await api.delete(`/calendar/tasks/${task.id}`);
      onChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить задачу", description: e.message });
    }
  };

  return (
    <div className="flex items-center gap-4 py-3 border-b border-hover last:border-b-0">
      <StatusBadge tone={style.tone} label={style.label} />
      <div className="flex-1 min-w-0">
        <div className="text-base font-semibold text-ink truncate">{task.title}</div>
        <div className="text-xs text-muted mt-0.5">
          {task.category ? `${task.category} · ` : ""}{RECURRENCE_LABELS[task.recurrence] || task.recurrence}
          {task.due_date ? ` · срок ${formatDate(task.due_date)}` : ""}
          {!task.active ? " · на паузе" : ""}
        </div>
        {task.description && <div className="text-sm text-muted mt-1">{task.description}</div>}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {task.period_key && (
          <Button variant={task.is_done ? "ghost" : "secondary"} size="sm" onClick={handleToggleDone} loading={busy}>
            {task.is_done ? "Снять отметку" : "Выполнено"}
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>Изменить</Button>
        <Button variant="ghost" size="sm" onClick={handleToggleActive} loading={busy}>{task.active ? "Пауза" : "▶ Возобновить"}</Button>
        <button onClick={handleDelete} className="text-error text-sm font-semibold px-1">Удалить</button>
      </div>

      <TaskModal open={editOpen} onClose={() => setEditOpen(false)} editing={task} onSaved={onChanged} />
    </div>
  );
}

export default function CalendarScreen() {
  const toast = useToast();
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get("/calendar/tasks", { include_inactive: includeInactive });
      setTasks(data || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить календарь", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [includeInactive]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const sorted = [...tasks].sort((a, b) => STATE_ORDER.indexOf(a.state) - STATE_ORDER.indexOf(b.state) || (a.due_date || "").localeCompare(b.due_date || ""));

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(e) => setIncludeInactive(e.target.checked)}
              className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
            />
            Показывать задачи на паузе
          </label>
          <Button variant="primary" onClick={() => setCreateOpen(true)}>Новая задача</Button>
        </div>
      </Card>

      <Card>
        {loading ? (
          <div className="flex justify-center py-10">
            <div className="h-6 w-6 rounded-full border-2 border-pine border-t-transparent animate-spin" />
          </div>
        ) : sorted.length === 0 ? (
          <EmptyState icon="🗓️" title="Задач пока нет" description="Добавьте первую задачу — например, срок сдачи отчёта." />
        ) : (
          <div>
            {sorted.map((t) => (
              <TaskRow key={t.id} task={t} onChanged={load} />
            ))}
          </div>
        )}
      </Card>

      <TaskModal open={createOpen} onClose={() => setCreateOpen(false)} editing={null} onSaved={load} />
    </div>
  );
}
