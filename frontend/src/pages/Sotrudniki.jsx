import React, { useEffect, useMemo, useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import Modal from "../components/Modal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";
import { api, ApiError } from "../api/client.js";

/**
 * Экран "Сотрудники" — справочник работников, полноценным разделом (был
 * блок WorkersCard внутри Settings.jsx). Тот же источник данных, что и
 * лёгкие выпадающие списки в других местах (GET /work-plan/sotrudniki,
 * GET /uhody/sotrudniki) — но здесь берём полный GET /api/auth/workers
 * (те же поля + is_active + неактивные тоже видны), т.к. только этот
 * эндпоинт даёт полноценный CRUD (создание/вкл-выкл), а не только чтение
 * активных для пикера.
 *
 * Список должностей (DOLZHNOST_OPTIONS) — 1:1 с Dolzhnost (Literal) в
 * backend/app/routers/auth.py: backend отклонит создание сотрудника с
 * должностью не из этого списка, значения нужно менять синхронно в обоих
 * местах.
 */
const DOLZHNOST_OPTIONS = [
  "Лесовод",
  "Машинист трелевочной (лесозаготовительной (Форвардер)) машины",
  "Мастер леса",
  "Тракторист на подготовке лесосек, трелевке и вывозке леса",
  "Лесоруб",
  "Вальщик леса",
  "Водитель автомобиля",
  "Помощник лесничего",
  "Лесничий",
];

function WorkerCard({ worker, onSetActive }) {
  const initial = (worker.fio || "?").trim().charAt(0).toUpperCase();
  return (
    <Card className={!worker.is_active ? "opacity-60" : ""}>
      <div className="flex items-start gap-3">
        <div className="h-11 w-11 shrink-0 rounded-full bg-mint text-pine font-bold flex items-center justify-center text-base">
          {initial}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-ui font-bold text-ink text-base truncate">{worker.fio}</div>
          <div className="text-muted text-sm truncate">{worker.dolzhnost || "Должность не указана"}</div>
        </div>
      </div>

      <div className="mt-3.5 flex flex-col gap-1.5 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-muted-2">Участок</span>
          <span className="text-ink font-medium truncate ml-2">{worker.uchastok || "—"}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-2">Логин</span>
          <span className="text-ink font-mono truncate ml-2">{worker.login}</span>
        </div>
      </div>

      <button
        onClick={() => onSetActive(worker.id, !worker.is_active)}
        className={[
          "mt-4 w-full text-xs font-semibold rounded-full px-2.5 py-1.5 border transition-colors",
          worker.is_active
            ? "border-pine text-pine bg-mint-soft hover:bg-mint"
            : "border-error text-error bg-error-soft hover:bg-error-soft/70",
        ].join(" ")}
      >
        {worker.is_active ? "Активен" : "Отключён"}
      </button>
    </Card>
  );
}

export default function Sotrudniki() {
  const toast = useToast();
  const [workers, setWorkers] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [search, setSearch] = useState("");
  const [dolzhnostFilter, setDolzhnostFilter] = useState("");

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({
    login: "",
    pin: "",
    fio: "",
    dolzhnost: DOLZHNOST_OPTIONS[0],
    uchastok: "",
  });
  const [creating, setCreating] = useState(false);

  const loadWorkers = () =>
    api
      .get("/auth/workers")
      .then(setWorkers)
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "Не удалось загрузить список сотрудников"));

  useEffect(() => {
    loadWorkers();
  }, []);

  const handleCreate = async () => {
    if (!createForm.login.trim() || !createForm.pin.trim() || !createForm.fio.trim()) {
      toast.show({ tone: "warning", title: "Заполните логин, PIN и ФИО" });
      return;
    }
    if (createForm.pin.trim().length < 4) {
      toast.show({ tone: "warning", title: "PIN слишком короткий", description: "Минимум 4 символа." });
      return;
    }
    setCreating(true);
    try {
      await api.post("/auth/workers", createForm);
      toast.show({ tone: "success", title: "Сотрудник создан", description: `Логин «${createForm.login}» — сообщите его и PIN сотруднику для входа в мобильное приложение.` });
      setCreateOpen(false);
      setCreateForm({ login: "", pin: "", fio: "", dolzhnost: DOLZHNOST_OPTIONS[0], uchastok: "" });
      loadWorkers();
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось создать сотрудника",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    } finally {
      setCreating(false);
    }
  };

  const handleSetActive = async (workerId, isActive) => {
    try {
      await api.patch(`/auth/workers/${workerId}/active`, { is_active: isActive });
      loadWorkers();
      toast.show({ tone: "info", title: isActive ? "Учётная запись включена" : "Учётная запись отключена" });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось изменить статус",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    }
  };

  const visibleWorkers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (workers ?? [])
      .filter((w) => !dolzhnostFilter || w.dolzhnost === dolzhnostFilter)
      .filter((w) => !q || (w.fio || "").toLowerCase().includes(q));
  }, [workers, search, dolzhnostFilter]);

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex items-center gap-3 flex-wrap justify-between">
          <div className="flex items-center gap-3 flex-wrap flex-1">
            <TextField
              placeholder="Поиск по ФИО…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 min-w-[220px]"
            />
            <select
              value={dolzhnostFilter}
              onChange={(e) => setDolzhnostFilter(e.target.value)}
              className="bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none min-w-[220px]"
            >
              <option value="">Все должности</option>
              {DOLZHNOST_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)}>
            + Новый сотрудник
          </Button>
        </div>
      </Card>

      {loadError && <p className="text-error text-base">{loadError}</p>}

      {workers === null ? (
        <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <div className="h-11 w-11 rounded-full bg-hover animate-pulse" />
              <div className="h-3.5 mt-3.5 rounded bg-hover animate-pulse" style={{ width: "70%" }} />
              <div className="h-3 mt-2 rounded bg-hover animate-pulse" style={{ width: "50%" }} />
            </Card>
          ))}
        </div>
      ) : visibleWorkers.length === 0 ? (
        <EmptyState
          title={workers.length === 0 ? "Сотрудников пока нет" : "Никого не нашлось"}
          description={
            workers.length === 0
              ? "Создайте первого сотрудника кнопкой выше — логин и PIN нужно будет сообщить ему для входа в мобильное приложение."
              : "Попробуйте изменить поиск или фильтр по должности."
          }
        />
      ) : (
        <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
          {visibleWorkers.map((w) => (
            <WorkerCard key={w.id} worker={w} onSetActive={handleSetActive} />
          ))}
        </div>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Новый сотрудник">
        <div className="flex flex-col gap-4">
          <TextField
            label="Логин"
            hint="Придумайте короткий логин, например по фамилии — ivanov."
            value={createForm.login}
            onChange={(e) => setCreateForm((s) => ({ ...s, login: e.target.value }))}
          />
          <TextField
            label="PIN"
            hint="Минимум 4 символа — цифры, вводится на телефоне в лесу."
            value={createForm.pin}
            onChange={(e) => setCreateForm((s) => ({ ...s, pin: e.target.value }))}
          />
          <TextField
            label="ФИО"
            value={createForm.fio}
            onChange={(e) => setCreateForm((s) => ({ ...s, fio: e.target.value }))}
          />
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">
              Должность
            </label>
            <select
              value={createForm.dolzhnost}
              onChange={(e) => setCreateForm((s) => ({ ...s, dolzhnost: e.target.value }))}
              className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none"
            >
              {DOLZHNOST_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <TextField
            label="Участок"
            value={createForm.uchastok}
            onChange={(e) => setCreateForm((s) => ({ ...s, uchastok: e.target.value }))}
          />
        </div>
        <div className="flex items-center justify-end gap-2 mt-6">
          <Button variant="secondary" onClick={() => setCreateOpen(false)}>
            Отмена
          </Button>
          <Button variant="primary" loading={creating} onClick={handleCreate}>
            Создать
          </Button>
        </div>
      </Modal>
    </div>
  );
}
