import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Лесные культуры" (screens/lesokultury/) — Этап 8 плана.
 *
 * Backend не переписывался — app/routers/lesokultury.py уже полностью
 * оборачивает db.*_lesokultury_* (CRUD участков + журнал мероприятий).
 * Тот же паттерн, что "Делянки"/"Таксация": список слева, карточка справа.
 * В отличие от делянок, участок культур заводится вручную (не из МДО),
 * поэтому здесь есть полноценная форма создания.
 */

const MEROPRIYATIE_TYPES = [
  "Техническая приёмка",
  "Инвентаризация 1-го года",
  "Инвентаризация 3-го года",
  "Инвентаризация на перевод",
  "Внеплановая инвентаризация",
  "Агротехнический уход",
  "Химический уход",
  "Дополнение",
  "Перевод в покрытые лесом земли",
  "Списание",
];

const INVENTORY_TYPES = new Set([
  "Инвентаризация 1-го года",
  "Инвентаризация 3-го года",
  "Внеплановая инвентаризация",
  "Инвентаризация на перевод",
]);

const STATUS_TRIGGER_TYPES = {
  "Перевод в покрытые лесом земли": "переведён",
  "Списание": "списан",
};

const UCHASTOK_FIELDS = [
  "lesnichestvo", "kvartal", "vydel", "ploshad", "kategoriya_ploshadi",
  "tlu", "god_sozdaniya", "metod_sozdaniya", "glavnaya_poroda",
  "sostav_formula", "gustota_posadki", "normativ_perevoda", "primechaniya",
];

function emptyUchastokForm() {
  return Object.fromEntries(UCHASTOK_FIELDS.map((k) => [k, ""]));
}

function fieldsFromUchastok(u) {
  return Object.fromEntries(UCHASTOK_FIELDS.map((k) => [k, u[k] ?? ""]));
}

/** Числовые поля отправляем как числа (или null, если пусто) — остальные как строки. */
function payloadFromForm(form) {
  const numeric = new Set(["ploshad", "gustota_posadki", "normativ_perevoda"]);
  const out = {};
  for (const k of UCHASTOK_FIELDS) {
    const v = form[k];
    if (numeric.has(k)) {
      out[k] = v === "" ? null : Number(v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

function UchastokFormFields({ form, setForm }) {
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-4">
        <TextField label="Лесничество" value={form.lesnichestvo} onChange={setField("lesnichestvo")} />
        <TextField label="Квартал" value={form.kvartal} onChange={setField("kvartal")} />
        <TextField label="Выдел" value={form.vydel} onChange={setField("vydel")} />
      </div>
      <div className="grid grid-cols-3 gap-4">
        <TextField label="Площадь, га" type="number" step="0.01" value={form.ploshad} onChange={setField("ploshad")} />
        <TextField label="Категория площади" value={form.kategoriya_ploshadi} onChange={setField("kategoriya_ploshadi")} />
        <TextField label="ТЛУ" value={form.tlu} onChange={setField("tlu")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <TextField label="Год создания" value={form.god_sozdaniya} onChange={setField("god_sozdaniya")} />
        <TextField label="Метод создания" value={form.metod_sozdaniya} onChange={setField("metod_sozdaniya")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <TextField label="Главная порода" value={form.glavnaya_poroda} onChange={setField("glavnaya_poroda")} />
        <TextField label="Формула состава" value={form.sostav_formula} onChange={setField("sostav_formula")} />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <TextField label="Густота посадки, шт/га" type="number" step="1" value={form.gustota_posadki} onChange={setField("gustota_posadki")} />
        <TextField label="Норматив перевода, шт/га" type="number" step="1" value={form.normativ_perevoda} onChange={setField("normativ_perevoda")} />
      </div>
      <TextAreaField label="Примечания" rows={2} value={form.primechaniya} onChange={setField("primechaniya")} />
    </div>
  );
}

function CreateUchastokModal({ open, onClose, onCreated }) {
  const toast = useToast();
  const [form, setForm] = useState(emptyUchastokForm());
  const [submitting, setSubmitting] = useState(false);

  const handleClose = () => {
    if (submitting) return;
    setForm(emptyUchastokForm());
    onClose();
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const { id } = await api.post("/lesokultury/uchastki", payloadFromForm(form));
      toast.show({ tone: "success", title: "Участок создан" });
      setForm(emptyUchastokForm());
      onClose();
      onCreated(id);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось создать участок", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Новый участок лесных культур"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>Создать</Button>
        </>
      }
    >
      <UchastokFormFields form={form} setForm={setForm} />
    </Modal>
  );
}

function AddMeropriyatieForm({ uchastokId, onAdded, onStatusChanged }) {
  const toast = useToast();
  const [tip, setTip] = useState(MEROPRIYATIE_TYPES[0]);
  const [data, setData] = useState("");
  const [prizhivaemost, setPrizhivaemost] = useState("");
  const [kolichestvo, setKolichestvo] = useState("");
  const [sostavFakt, setSostavFakt] = useState("");
  const [primechaniya, setPrimechaniya] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isInventory = INVENTORY_TYPES.has(tip);

  const handleAdd = async () => {
    if (!data.trim()) {
      toast.show({ tone: "warning", title: "Укажите дату мероприятия" });
      return;
    }
    setSubmitting(true);
    try {
      await api.post(`/lesokultury/uchastki/${uchastokId}/meropriyatiya`, undefined, {
        tip,
        data: data.trim(),
        prizhivaemost_pct: isInventory && prizhivaemost !== "" ? Number(prizhivaemost) : undefined,
        kolichestvo_na_ga: isInventory && kolichestvo !== "" ? Number(kolichestvo) : undefined,
        sostav_fakt: isInventory ? sostavFakt : "",
        primechaniya,
      });
      // Как и в desktop (screens/lesokultury/screen.py:_save) — эти два типа
      // мероприятия автоматически переводят статус участка.
      if (STATUS_TRIGGER_TYPES[tip]) {
        await api.patch(`/lesokultury/uchastki/${uchastokId}`, { status: STATUS_TRIGGER_TYPES[tip] });
      }
      toast.show({ tone: "success", title: "Запись добавлена в журнал" });
      setData("");
      setPrizhivaemost("");
      setKolichestvo("");
      setSostavFakt("");
      setPrimechaniya("");
      onAdded();
      if (STATUS_TRIGGER_TYPES[tip]) onStatusChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось добавить запись", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 bg-surface-alt rounded-md p-4">
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Тип мероприятия</label>
          <select
            value={tip}
            onChange={(e) => setTip(e.target.value)}
            className="w-full bg-surface border border-transparent focus:border-pine rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
          >
            {MEROPRIYATIE_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <TextField label="Дата" placeholder="ДД.ММ.ГГГГ" value={data} onChange={(e) => setData(e.target.value)} />
        <TextField
          label="Приживаемость, %"
          type="number"
          value={prizhivaemost}
          onChange={(e) => setPrizhivaemost(e.target.value)}
          disabled={!isInventory}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="Кол-во на 1 га, шт"
          type="number"
          value={kolichestvo}
          onChange={(e) => setKolichestvo(e.target.value)}
          disabled={!isInventory}
        />
        <TextField
          label="Фактический состав"
          value={sostavFakt}
          onChange={(e) => setSostavFakt(e.target.value)}
          disabled={!isInventory}
        />
      </div>
      <TextAreaField label="Примечания" rows={2} value={primechaniya} onChange={(e) => setPrimechaniya(e.target.value)} />
      <div>
        <Button variant="secondary" size="sm" onClick={handleAdd} loading={submitting}>➕ Добавить запись</Button>
      </div>
    </div>
  );
}

function UchastokDetail({ uchastokId, onListChanged }) {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [uchastok, setUchastok] = useState(null);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [meropriyatiya, setMeropriyatiya] = useState([]);
  const [logLoading, setLogLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const u = await api.get(`/lesokultury/uchastki/${uchastokId}`);
      setUchastok(u);
      setForm(fieldsFromUchastok(u));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить участок", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [uchastokId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try {
      const rows = await api.get(`/lesokultury/uchastki/${uchastokId}/meropriyatiya`);
      setMeropriyatiya(rows || []);
    } catch (e) {
      setMeropriyatiya([]);
    } finally {
      setLogLoading(false);
    }
  }, [uchastokId]);

  useEffect(() => {
    load();
    loadLog();
  }, [load, loadLog]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.patch(`/lesokultury/uchastki/${uchastokId}`, payloadFromForm(form));
      toast.show({ tone: "success", title: "Изменения сохранены" });
      onListChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleStatusChange = async (status) => {
    setSaving(true);
    try {
      await api.patch(`/lesokultury/uchastki/${uchastokId}`, { status });
      toast.show({ tone: "success", title: status === "списан" ? "Участок списан" : "Статус обновлён" });
      onListChanged();
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось изменить статус", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Безвозвратно удалить участок вместе со всем журналом мероприятий?")) return;
    setDeleting(true);
    try {
      await api.delete(`/lesokultury/uchastki/${uchastokId}`);
      toast.show({ tone: "success", title: "Участок удалён" });
      onListChanged(true);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить", description: e.message });
      setDeleting(false);
    }
  };

  if (loading || !form) {
    return (
      <Card>
        <div className="flex items-center justify-center py-20">
          <div className="h-6 w-6 rounded-full border-2 border-pine border-t-transparent animate-spin" />
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex flex-col gap-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-ui font-extrabold text-lg text-ink">
                Кв. {uchastok.kvartal || "—"} / Выд. {uchastok.vydel || "—"}
              </h2>
              <StatusBadge status={uchastok.status} />
            </div>
            <p className="text-muted text-sm mt-0.5">{uchastok.lesnichestvo || "—"} · заведён {(uchastok.created_at || "").slice(0, 10).split("-").reverse().join(".") || "—"}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {uchastok.status !== "переведён" && (
              <Button variant="secondary" size="sm" onClick={() => handleStatusChange("переведён")} disabled={saving}>
                🌲 В покрытые лесом
              </Button>
            )}
            {uchastok.status !== "списан" && (
              <Button variant="secondary" size="sm" onClick={() => handleStatusChange("списан")} disabled={saving}>
                🗄️ Списать
              </Button>
            )}
            <Button variant="danger" size="sm" onClick={handleDelete} loading={deleting}>🗑️ Удалить</Button>
          </div>
        </div>

        <UchastokFormFields form={form} setForm={setForm} />

        <div>
          <Button variant="primary" onClick={handleSave} loading={saving}>💾 Сохранить изменения</Button>
        </div>

        <div>
          <h3 className="font-ui font-bold text-ink text-md mb-3">Журнал мероприятий</h3>
          <AddMeropriyatieForm
            uchastokId={uchastokId}
            onAdded={loadLog}
            onStatusChanged={async () => {
              await load();
              onListChanged();
            }}
          />
          <div className="mt-4">
            <DataTable
              loading={logLoading}
              columns={[
                { key: "tip", header: "Тип", render: (r) => (
                  <span>{r.tip}{r.proba_id ? <span className="ml-1.5 text-xs text-pine" title={`Заведено автоматически из пробы рубок ухода №${r.proba_id}`}>· проба №{r.proba_id}</span> : null}</span>
                ) },
                { key: "data", header: "Дата" },
                { key: "prizhivaemost_pct", header: "Приживаемость, %", render: (r) => r.prizhivaemost_pct ?? "—" },
                { key: "kolichestvo_na_ga", header: "Шт/га", render: (r) => r.kolichestvo_na_ga ?? "—" },
                { key: "sostav_fakt", header: "Состав факт.", render: (r) => r.sostav_fakt || "—" },
                { key: "primechaniya", header: "Примечания", render: (r) => r.primechaniya || "—" },
              ]}
              rows={meropriyatiya}
              emptyTitle="Журнал пуст"
              emptyDescription="Добавьте первую запись формой выше — например, техническую приёмку."
            />
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function Lesokultury() {
  const toast = useToast();
  const [uchastki, setUchastki] = useState([]);
  const [loading, setLoading] = useState(true);
  const [includeSpisannye, setIncludeSpisannye] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [gody, setGody] = useState([]);
  const [god, setGod] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.get("/lesokultury/gody").then((rows) => setGody(rows || [])).catch(() => {});
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get("/lesokultury/uchastki", {
        include_spisannye: includeSpisannye,
        god: god || undefined,
        search: search.trim() || undefined,
      });
      setUchastki(rows || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить участки", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [includeSpisannye, god, search]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // Небольшая задержка на поиск, чтобы не дёргать API на каждый символ
    const t = setTimeout(loadList, 300);
    return () => clearTimeout(t);
  }, [loadList]);

  const handleListChanged = (removed) => {
    if (removed) setSelectedId(null);
    loadList();
  };

  return (
    <div className="p-8 flex gap-6 items-start">
      <Card padding={false} className="w-[340px] shrink-0 flex flex-col">
        <div className="p-5 pb-3 flex flex-col gap-3 border-b border-border">
          <Button variant="primary" onClick={() => setCreateOpen(true)}>➕ Новый участок</Button>
          <TextField
            placeholder="Поиск: квартал, выдел, лесничество, порода, делянка"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            value={god}
            onChange={(e) => setGod(e.target.value)}
            className="w-full bg-surface border border-transparent focus:border-pine rounded-md px-3.5 py-2.5 text-sm text-ink outline-none transition-colors"
          >
            <option value="">Все годы</option>
            {gody.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={includeSpisannye}
              onChange={(e) => setIncludeSpisannye(e.target.checked)}
              className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
            />
            Показывать списанные / переведённые
          </label>
        </div>

        <div className="flex-1 overflow-y-auto max-h-[calc(100vh-260px)] p-2">
          {loading ? (
            <div className="p-5 flex justify-center">
              <div className="h-5 w-5 rounded-full border-2 border-pine border-t-transparent animate-spin" />
            </div>
          ) : uchastki.length === 0 ? (
            <div className="p-3">
              <EmptyState icon="🌱" title="Участков пока нет" description="Создайте первый участок лесных культур кнопкой выше." />
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {uchastki.map((u) => (
                <li key={u.id}>
                  <button
                    onClick={() => setSelectedId(u.id)}
                    className={[
                      "w-full text-left px-3 py-2.5 rounded-md transition-colors",
                      selectedId === u.id ? "bg-mint text-pine font-bold" : "hover:bg-hover",
                    ].join(" ")}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-base">Кв. {u.kvartal || "—"} / Выд. {u.vydel || "—"}</span>
                      <StatusBadge status={u.status} dot={false} />
                    </div>
                    <div className="text-xs text-muted mt-0.5 truncate">
                      {u.lesnichestvo || "—"}{u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}
                    </div>
                    {u.last_uhod_tip && (
                      <div className="text-xs text-pine mt-0.5 truncate" title={`${u.last_uhod_tip}${u.last_uhod_data ? ` · ${u.last_uhod_data}` : ""}`}>
                        ✅ Уход выполнен{u.last_uhod_data ? ` · ${u.last_uhod_data}` : ""}
                      </div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <div className="flex-1 min-w-0">
        {selectedId ? (
          <UchastokDetail key={selectedId} uchastokId={selectedId} onListChanged={handleListChanged} />
        ) : (
          <Card>
            <EmptyState icon="🌱" title="Выберите участок из списка" description="Или создайте новый — кнопка слева." />
          </Card>
        )}
      </div>

      <CreateUchastokModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(id) => { loadList(); setSelectedId(id); }} />
    </div>
  );
}
