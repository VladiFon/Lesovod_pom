import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import Modal from "../components/Modal.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "План работ" — Фаза 4 плана доработки веб-версии.
 *
 * Недостающая веб-половина уже существующей мобильной функции: таблица
 * work_plan и эндпоинты для рабочего (список своих задач + отметка
 * выполнено) были заведены заранее в app/routers/bot.py — здесь только
 * администраторский CRUD поверх них (app/routers/work_plan.py), чтобы
 * задачи можно было ставить с экрана, а не руками через /docs.
 *
 * Сознательно НЕ календарная сетка (как pages/Calendar.jsx для
 * периодических орг.задач) — список с фильтром по датам и сотруднику,
 * тот же принцип "список + статус важнее сетки", что и в остальных
 * экранах проекта.
 */
function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function addDaysIso(iso, days) {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function emptyForm() {
  return {
    sotrudnik_id: "", data: todayIso(), zadacha: "",
    targetType: "delyanka", kvartal: "", vydel: "",
    lesokulturySearch: "", lesokulturyUchastok: null,
  };
}

export default function PlanRabot() {
  const toast = useToast();

  const [dateFrom, setDateFrom] = useState(todayIso());
  const [dateTo, setDateTo] = useState(addDaysIso(todayIso(), 13));
  const [sotrudnikFilter, setSotrudnikFilter] = useState("");

  const [tasks, setTasks] = useState(null);
  const [sotrudniki, setSotrudniki] = useState([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);

  const [delyankaLookup, setDelyankaLookup] = useState(null); // { item_id, nazvanie } | null | "not_found"
  const [lookingUp, setLookingUp] = useState(false);
  const [lesokulturyOptions, setLesokulturyOptions] = useState([]);
  const [lesokulturyLoading, setLesokulturyLoading] = useState(false);

  useEffect(() => {
    api.get("/work-plan/sotrudniki").then(setSotrudniki).catch(() => {});
  }, []);

  // Поиск участков лесных культур для переключателя "Лесные культуры"
  useEffect(() => {
    if (!modalOpen || form.targetType !== "lesokultury") return;
    setLesokulturyLoading(true);
    const t = setTimeout(() => {
      api
        .get("/work-plan/lesokultury-uchastki", { search: form.lesokulturySearch.trim() || undefined })
        .then(setLesokulturyOptions)
        .catch(() => {})
        .finally(() => setLesokulturyLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [modalOpen, form.targetType, form.lesokulturySearch]);

  const loadTasks = useCallback(() => {
    setTasks(null);
    const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
    if (sotrudnikFilter) params.sotrudnik_id = sotrudnikFilter;
    api
      .get("/work-plan/", params)
      .then(setTasks)
      .catch((err) => {
        toast.show({ tone: "danger", title: "Не удалось загрузить задачи", description: err instanceof ApiError ? err.message : "Неизвестная ошибка" });
        setTasks([]);
      });
  }, [dateFrom, dateTo, sotrudnikFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const openCreateModal = () => {
    setEditingId(null);
    setForm(emptyForm());
    setDelyankaLookup(null);
    setModalOpen(true);
  };

  const openEditModal = (task) => {
    setEditingId(task.id);
    const isLesokultury = !!task.lesokultury_uchastok_id;
    setForm({
      sotrudnik_id: String(task.sotrudnik_id),
      data: task.data,
      zadacha: task.zadacha,
      targetType: isLesokultury ? "lesokultury" : "delyanka",
      kvartal: task.kvartal || "",
      vydel: task.vydel || "",
      lesokulturySearch: "",
      lesokulturyUchastok: isLesokultury
        ? {
            id: task.lesokultury_uchastok_id,
            kvartal: task.lku_kvartal,
            vydel: task.lku_vydel,
            lesnichestvo: task.lku_lesnichestvo,
            glavnaya_poroda: task.lku_glavnaya_poroda,
          }
        : null,
    });
    setDelyankaLookup(task.delyanka_item_id ? { item_id: task.delyanka_item_id } : null);
    setModalOpen(true);
  };

  const handleLookupDelyanka = async () => {
    if (!form.kvartal.trim() || !form.vydel.trim()) {
      setDelyankaLookup(null);
      return;
    }
    setLookingUp(true);
    try {
      const results = await api.get("/delyanki/by-location", { kvartal: form.kvartal.trim(), vydel: form.vydel.trim() });
      if (results.length === 0) {
        setDelyankaLookup("not_found");
      } else {
        setDelyankaLookup({ item_id: results[0].item_id, nazvanie: results[0].nazvanie });
      }
    } catch (e) {
      setDelyankaLookup("not_found");
    } finally {
      setLookingUp(false);
    }
  };

  const handleSave = async () => {
    if (!form.sotrudnik_id || !form.data || !form.zadacha.trim()) {
      toast.show({ tone: "warning", title: "Заполните сотрудника, дату и задачу" });
      return;
    }
    setSaving(true);
    const delyankaItemId =
      form.targetType === "delyanka" && delyankaLookup && delyankaLookup !== "not_found"
        ? delyankaLookup.item_id
        : null;
    const lesokulturyUchastokId =
      form.targetType === "lesokultury" && form.lesokulturyUchastok
        ? form.lesokulturyUchastok.id
        : null;
    try {
      const basePayload = {
        sotrudnik_id: Number(form.sotrudnik_id),
        data: form.data,
        zadacha: form.zadacha.trim(),
        delyanka_item_id: delyankaItemId,
        lesokultury_uchastok_id: lesokulturyUchastokId,
      };
      if (editingId) {
        await api.patch(`/work-plan/${editingId}`, basePayload);
        toast.show({ tone: "success", title: "Задача обновлена" });
      } else {
        await api.post("/work-plan/", basePayload);
        toast.show({ tone: "success", title: "Задача поставлена" });
      }
      setModalOpen(false);
      loadTasks();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить задачу", description: e instanceof ApiError ? e.message : "Неизвестная ошибка" });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (task) => {
    if (!window.confirm(`Удалить задачу «${task.zadacha}» для ${task.sotrudnik_fio}?`)) return;
    try {
      await api.delete(`/work-plan/${task.id}`);
      toast.show({ tone: "info", title: "Задача удалена" });
      loadTasks();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить задачу", description: e.message });
    }
  };

  const handleToggleStatus = async (task) => {
    const nextStatus = task.status === "активна" ? "выполнена" : "активна";
    try {
      await api.patch(`/work-plan/${task.id}`, { status: nextStatus });
      loadTasks();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось изменить статус", description: e.message });
    }
  };

  const columns = useMemo(
    () => [
      { key: "data", header: "Дата", sortable: true },
      { key: "sotrudnik_fio", header: "Сотрудник", sortable: true, render: (t) => (
        <div>
          <div className="text-ink">{t.sotrudnik_fio}</div>
          {t.sotrudnik_dolzhnost && <div className="text-xs text-muted">{t.sotrudnik_dolzhnost}</div>}
        </div>
      ) },
      { key: "zadacha", header: "Задача" },
      { key: "delyanka", header: "Место работы", render: (t) => {
        if (t.lesokultury_uchastok_id) {
          return `кв. ${t.lku_kvartal || "—"} / выд. ${t.lku_vydel || "—"}`;
        }
        return t.kvartal ? `кв. ${t.kvartal} / выд. ${t.vydel}` : "—";
      } },
      {
        key: "status",
        header: "Статус",
        render: (t) => (
          <button onClick={() => handleToggleStatus(t)}>
            <StatusBadge
              tone={t.status === "выполнена" ? "success" : "neutral"}
              label={t.status === "выполнена" ? "Выполнена" : "Активна"}
              dot={false}
            />
          </button>
        ),
      },
      {
        key: "actions",
        header: "",
        render: (t) => (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => openEditModal(t)}>Изменить</Button>
            <Button size="sm" variant="ghost" onClick={() => handleDelete(t)}>Удалить</Button>
          </div>
        ),
      },
    ],
    [] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <TextField label="С" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          <TextField label="По" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted font-medium">Сотрудник</label>
            <select
              value={sotrudnikFilter}
              onChange={(e) => setSotrudnikFilter(e.target.value)}
              className="bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none min-w-[200px]"
            >
              <option value="">Все сотрудники</option>
              {sotrudniki.map((s) => (
                <option key={s.id} value={s.id}>{s.fio}</option>
              ))}
            </select>
          </div>
          <div className="ml-auto">
            <Button variant="primary" onClick={openCreateModal}>
              + Новая задача
            </Button>
          </div>
        </div>
      </Card>

      <Card padding={false}>
        <DataTable
          columns={columns}
          rows={tasks ?? []}
          loading={tasks === null}
          emptyTitle="Задач за этот период нет"
          emptyDescription="Поставьте первую задачу кнопкой «+ Новая задача» выше, либо расширьте диапазон дат."
        />
      </Card>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editingId ? "Изменить задачу" : "Новая задача"}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted font-medium">Сотрудник</label>
            <select
              value={form.sotrudnik_id}
              onChange={(e) => setForm((f) => ({ ...f, sotrudnik_id: e.target.value }))}
              className="bg-surface border border-border focus:border-pine rounded-md px-3 py-2.5 text-base text-ink outline-none"
            >
              <option value="">Выберите сотрудника…</option>
              {sotrudniki.map((s) => (
                <option key={s.id} value={s.id}>{s.fio}{s.dolzhnost ? ` (${s.dolzhnost})` : ""}</option>
              ))}
            </select>
          </div>
          <TextField
            label="Дата"
            type="date"
            value={form.data}
            onChange={(e) => setForm((f) => ({ ...f, data: e.target.value }))}
          />
          <TextAreaField
            label="Задача"
            value={form.zadacha}
            onChange={(e) => setForm((f) => ({ ...f, zadacha: e.target.value }))}
            placeholder="например: рубка ухода на делянке, вывозка древесины…"
          />
          <div>
            <div className="text-sm text-muted font-medium mb-1.5">Место работы (необязательно)</div>
            <div className="flex gap-2 mb-3">
              <Button
                type="button"
                variant={form.targetType === "delyanka" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setForm((f) => ({ ...f, targetType: "delyanka" }))}
              >
                Делянка
              </Button>
              <Button
                type="button"
                variant={form.targetType === "lesokultury" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setForm((f) => ({ ...f, targetType: "lesokultury" }))}
              >
                Лесные культуры
              </Button>
            </div>

            {form.targetType === "delyanka" ? (
              <>
                <div className="flex items-end gap-2">
                  <TextField
                    label="Квартал"
                    value={form.kvartal}
                    onChange={(e) => setForm((f) => ({ ...f, kvartal: e.target.value }))}
                    onBlur={handleLookupDelyanka}
                  />
                  <TextField
                    label="Выдел"
                    value={form.vydel}
                    onChange={(e) => setForm((f) => ({ ...f, vydel: e.target.value }))}
                    onBlur={handleLookupDelyanka}
                  />
                  <Button variant="secondary" onClick={handleLookupDelyanka} loading={lookingUp}>
                    Найти
                  </Button>
                </div>
                {delyankaLookup === "not_found" && (
                  <p className="text-warning text-sm mt-1.5">
                    Делянка с таким кварталом/выделом не найдена — задача будет без привязки к делянке.
                  </p>
                )}
                {delyankaLookup && delyankaLookup !== "not_found" && (
                  <p className="text-pine text-sm mt-1.5">
                    Найдена: {delyankaLookup.nazvanie || `делянка №${delyankaLookup.item_id}`}
                  </p>
                )}
              </>
            ) : (
              <>
                {form.lesokulturyUchastok && (
                  <p className="text-pine text-sm mb-2">
                    Выбран: кв. {form.lesokulturyUchastok.kvartal || "—"} / выд. {form.lesokulturyUchastok.vydel || "—"}
                    {form.lesokulturyUchastok.glavnaya_poroda ? ` · ${form.lesokulturyUchastok.glavnaya_poroda}` : ""}
                    {" "}
                    <button
                      type="button"
                      className="text-muted underline"
                      onClick={() => setForm((f) => ({ ...f, lesokulturyUchastok: null }))}
                    >
                      сбросить
                    </button>
                  </p>
                )}
                <TextField
                  placeholder="Поиск участка: квартал, выдел, лесничество, порода"
                  value={form.lesokulturySearch}
                  onChange={(e) => setForm((f) => ({ ...f, lesokulturySearch: e.target.value }))}
                />
                <div className="mt-2 max-h-48 overflow-y-auto border border-border rounded-md">
                  {lesokulturyLoading ? (
                    <div className="p-3 flex justify-center">
                      <div className="h-4 w-4 rounded-full border-2 border-pine border-t-transparent animate-spin" />
                    </div>
                  ) : lesokulturyOptions.length === 0 ? (
                    <div className="p-3 text-sm text-muted text-center">Ничего не найдено</div>
                  ) : (
                    lesokulturyOptions.map((u) => (
                      <button
                        type="button"
                        key={u.id}
                        onClick={() => setForm((f) => ({ ...f, lesokulturyUchastok: u }))}
                        className={[
                          "w-full text-left px-3 py-2 border-b border-hover last:border-b-0 hover:bg-hover",
                          form.lesokulturyUchastok?.id === u.id ? "bg-mint" : "",
                        ].join(" ")}
                      >
                        <div className="text-sm text-ink">Кв. {u.kvartal || "—"} / Выд. {u.vydel || "—"}</div>
                        <div className="text-xs text-muted">
                          {u.lesnichestvo || "—"}{u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 mt-6">
          <Button variant="secondary" onClick={() => setModalOpen(false)}>
            Отмена
          </Button>
          <Button variant="primary" loading={saving} onClick={handleSave}>
            {editingId ? "Сохранить" : "Поставить задачу"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
