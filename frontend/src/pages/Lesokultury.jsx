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
  "Доращивание",
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
  "lesnichestvo", "kvartal", "vydel", "vydel_staryy", "podvydel", "ploshad", "kategoriya_ploshadi",
  "tlu", "god_sozdaniya", "metod_sozdaniya", "sposob_obrabotki", "glavnaya_poroda",
  "sostav_formula", "shema_mezhdu_ryadami", "shema_v_ryadu", "gustota_posadki",
  "posadochnyy_material", "normativ_perevoda", "naznachenie_plantatsii", "primechaniya",
  "chasti_json",
];

const NUMERIC_FIELDS = new Set([
  "ploshad", "gustota_posadki", "normativ_perevoda", "shema_mezhdu_ryadami", "shema_v_ryadu",
]);

// Значения — как в графах ведомостей текущих изменений (прил. 7 к приказу №130).
const METOD_SOZDANIYA = [
  "посадка",
  "посадка механизированная",
  "посадка ручная",
  "посев механизированный",
  "посев ручной",
  "аэросев",
  "созданы ЗКС",
  "селекционным материалом",
];

const SPOSOB_OBRABOTKI = ["сплошная", "полосами", "бороздами", "площадками", "без обработки"];

const SELECT_CLASS =
  "w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none transition-colors";

function parseChasti(text) {
  try {
    const parsed = JSON.parse(text || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Части участка по таксационным выделам — для ведомостей текущих изменений
 * (прил. 4, 7, 14): культура в нескольких выделах идёт в ведомость строкой
 * на каждый выдел со своим подвыделом и площадью.
 */
function ChastiEditor({ value, onChange, vydel }) {
  const chasti = parseChasti(value);
  const save = (next) => onChange(next.length ? JSON.stringify(next) : "");
  const setPart = (i, key, v) => save(chasti.map((c, j) => (j === i ? { ...c, [key]: v } : c)));
  const vydely = String(vydel || "").split(/[,;\s]+/).filter(Boolean);
  const total = chasti.reduce((sum, c) => sum + (Number(String(c.ploshad ?? "").replace(",", ".")) || 0), 0);
  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11.5px] font-semibold text-muted">
        Части по выделам (для ведомостей текущих изменений, если участок в нескольких выделах)
      </div>
      {chasti.map((c, i) => (
        <div key={i} className="flex gap-2 items-end">
          <TextField label={i === 0 ? "Выдел" : undefined} value={c.vydel ?? ""} onChange={(e) => setPart(i, "vydel", e.target.value)} className="w-24" />
          <TextField label={i === 0 ? "Подвыдел" : undefined} value={c.podvydel ?? ""} onChange={(e) => setPart(i, "podvydel", e.target.value)} className="w-28" />
          <TextField label={i === 0 ? "Площадь, га" : undefined} value={c.ploshad ?? ""} onChange={(e) => setPart(i, "ploshad", e.target.value)} className="w-28" />
          <Button variant="ghost" size="sm" onClick={() => save(chasti.filter((_, j) => j !== i))}>Убрать</Button>
        </div>
      ))}
      <div className="flex items-center gap-3">
        <Button variant="secondary" size="sm" onClick={() => save([...chasti, { vydel: "", podvydel: "", ploshad: "" }])}>
          Добавить часть
        </Button>
        {chasti.length === 0 && vydely.length > 1 && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => save(vydely.map((v) => ({ vydel: v, podvydel: "", ploshad: "" })))}
          >
            Разбить по выделам ({vydely.join(", ")})
          </Button>
        )}
        {chasti.length > 0 && <span className="text-xs text-muted">Сумма частей: {Math.round(total * 100) / 100} га</span>}
      </div>
    </div>
  );
}

/** Выпадающий список, который не теряет значение не из списка (старые записи). */
function SelectField({ label, value, onChange, options }) {
  const all = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <div>
      <label className="block text-[11.5px] font-semibold text-muted mb-1">{label}</label>
      <select value={value} onChange={onChange} className={SELECT_CLASS}>
        <option value="">—</option>
        {all.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  );
}

function emptyUchastokForm() {
  return Object.fromEntries(UCHASTOK_FIELDS.map((k) => [k, ""]));
}

function fieldsFromUchastok(u) {
  return Object.fromEntries(UCHASTOK_FIELDS.map((k) => [k, u[k] ?? ""]));
}

/** Числовые поля отправляем как числа (или null, если пусто) — остальные как строки. */
function payloadFromForm(form) {
  const out = {};
  for (const k of UCHASTOK_FIELDS) {
    const v = form[k];
    if (NUMERIC_FIELDS.has(k)) {
      out[k] = v === "" ? null : Number(v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

function UchastokFormFields({ form, setForm }) {
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const a = Number(form.shema_mezhdu_ryadami);
  const b = Number(form.shema_v_ryadu);
  const gustotaPoShema = a > 0 && b > 0 ? Math.round(10000 / (a * b)) : null;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Лесничество" value={form.lesnichestvo} onChange={setField("lesnichestvo")} />
        <TextField label="Квартал" value={form.kvartal} onChange={setField("kvartal")} />
        <TextField label="Выдел (по действующей таксации)" value={form.vydel} onChange={setField("vydel")} />
      </div>
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Старый выдел (до таксации)" value={form.vydel_staryy} onChange={setField("vydel_staryy")} />
        <TextField label="Подвыдел" placeholder="например, 15.1" value={form.podvydel} onChange={setField("podvydel")} />
      </div>
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Площадь, га" type="number" step="0.01" value={form.ploshad} onChange={setField("ploshad")} />
        <TextField label="Категория площади" value={form.kategoriya_ploshadi} onChange={setField("kategoriya_ploshadi")} />
        <TextField label="ТЛУ" value={form.tlu} onChange={setField("tlu")} />
      </div>
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Год создания" value={form.god_sozdaniya} onChange={setField("god_sozdaniya")} />
        <SelectField label="Метод создания" value={form.metod_sozdaniya} onChange={setField("metod_sozdaniya")} options={METOD_SOZDANIYA} />
        <SelectField label="Способ обработки почвы" value={form.sposob_obrabotki} onChange={setField("sposob_obrabotki")} options={SPOSOB_OBRABOTKI} />
      </div>
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Главная порода" value={form.glavnaya_poroda} onChange={setField("glavnaya_poroda")} />
        <TextField label="Формула состава" value={form.sostav_formula} onChange={setField("sostav_formula")} />
      </div>
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Схема: между рядами, м" type="number" step="0.1" value={form.shema_mezhdu_ryadami} onChange={setField("shema_mezhdu_ryadami")} />
        <TextField label="Схема: в ряду, м" type="number" step="0.1" value={form.shema_v_ryadu} onChange={setField("shema_v_ryadu")} />
        <TextField
          label="Густота посадки, шт/га"
          type="number"
          step="1"
          value={form.gustota_posadki}
          onChange={setField("gustota_posadki")}
          hint={gustotaPoShema ? `По схеме: ${gustotaPoShema}` : undefined}
        />
      </div>
      <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <TextField label="Посадочный материал" placeholder="например, Е сн ЗКС, Б сн" value={form.posadochnyy_material} onChange={setField("posadochnyy_material")} />
        <TextField label="Норматив перевода, шт/га" type="number" step="1" value={form.normativ_perevoda} onChange={setField("normativ_perevoda")} />
        <TextField label="Назначение плантации" placeholder="только для плантаций" value={form.naznachenie_plantatsii} onChange={setField("naznachenie_plantatsii")} />
      </div>
      <ChastiEditor vydel={form.vydel} value={form.chasti_json} onChange={(v) => setForm((f) => ({ ...f, chasti_json: v }))} />
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

// Доп. поля мероприятий для ведомостей текущих изменений (приказ №130):
// «Перевод» — графы прил. 4, «Списание» — прил. 14. Уходят в dannye.
const EXTRA_FIELDS = {
  "Перевод в покрытые лесом земли": {
    group: "taksatsiya",
    title: "Таксация при переводе",
    fields: [
      { key: "nomer_kartochki", label: "№ полевой карточки" },
      { key: "ploshad", label: "Площадь перевода, га", numeric: true },
      { key: "podvydel", label: "Подвыдел" },
      { key: "sostav", label: "Состав" },
      { key: "vozrast", label: "Возраст, лет", numeric: true },
      { key: "vysota", label: "Высота, м", numeric: true },
      { key: "diametr", label: "Диаметр, см", numeric: true },
      { key: "polnota", label: "Полнота", numeric: true },
    ],
  },
  "Доращивание": {
    title: "Доращивание",
    fields: [{ key: "do_goda", label: "До какого года", numeric: true }],
  },
  "Списание": {
    title: "Списание",
    fields: [
      { key: "prichina", label: "Причина списания" },
      { key: "akt_nomer", label: "№ акта" },
      { key: "akt_data", label: "Дата акта", placeholder: "ДД.ММ.ГГГГ" },
      { key: "vid_zemel", label: "Вид земель после списания" },
    ],
  },
};

const EXTRA_LABELS = Object.fromEntries(
  Object.values(EXTRA_FIELDS).flatMap((g) => g.fields.map((f) => [f.key, f.label]))
);

function dannyeFromExtra(tip, extra) {
  const spec = EXTRA_FIELDS[tip];
  if (!spec) return undefined;
  const values = {};
  for (const f of spec.fields) {
    const v = (extra[f.key] ?? "").toString().trim();
    if (v === "") continue;
    values[f.key] = f.numeric ? Number(v.replace(",", ".")) : v;
  }
  if (Object.keys(values).length === 0) return undefined;
  return spec.group ? { [spec.group]: values } : values;
}

function AddMeropriyatieForm({ uchastokId, onAdded, onStatusChanged }) {
  const toast = useToast();
  const [tip, setTip] = useState(MEROPRIYATIE_TYPES[0]);
  const [data, setData] = useState("");
  const [prizhivaemost, setPrizhivaemost] = useState("");
  const [kolichestvo, setKolichestvo] = useState("");
  const [sostavFakt, setSostavFakt] = useState("");
  const [primechaniya, setPrimechaniya] = useState("");
  const [extra, setExtra] = useState({});
  const [submitting, setSubmitting] = useState(false);

  const isInventory = INVENTORY_TYPES.has(tip);
  const extraSpec = EXTRA_FIELDS[tip];

  const handleAdd = async () => {
    if (!data.trim()) {
      toast.show({ tone: "warning", title: "Укажите дату мероприятия" });
      return;
    }
    setSubmitting(true);
    try {
      const dannye = dannyeFromExtra(tip, extra);
      await api.post(`/lesokultury/uchastki/${uchastokId}/meropriyatiya`, dannye ? { dannye } : undefined, {
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
      setExtra({});
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
      <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
        <div>
          <label className="block text-[11.5px] font-semibold text-muted mb-1">Тип мероприятия</label>
          <select
            value={tip}
            onChange={(e) => setTip(e.target.value)}
            className={SELECT_CLASS}
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
      <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
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
      {extraSpec && (
        <div>
          <div className="text-[11.5px] font-semibold text-pine mb-1.5">{extraSpec.title}</div>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(150px,1fr))]">
            {extraSpec.fields.map((f) => (
              <TextField
                key={f.key}
                label={f.label}
                placeholder={f.placeholder}
                inputMode={f.numeric ? "decimal" : undefined}
                value={extra[f.key] ?? ""}
                onChange={(e) => setExtra((x) => ({ ...x, [f.key]: e.target.value }))}
              />
            ))}
          </div>
        </div>
      )}
      <TextAreaField label="Примечания" rows={2} value={primechaniya} onChange={(e) => setPrimechaniya(e.target.value)} />
      <div>
        <Button variant="secondary" size="sm" onClick={handleAdd} loading={submitting}>Добавить запись</Button>
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
              <h2 className="font-ui font-extrabold text-pine text-[16px]">
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
            <Button variant="danger" size="sm" onClick={handleDelete} loading={deleting}>Удалить</Button>
          </div>
        </div>

        <UchastokFormFields form={form} setForm={setForm} />

        <div>
          <Button variant="primary" onClick={handleSave} loading={saving}>Сохранить изменения</Button>
        </div>

        <div>
          <h3 className="font-ui font-extrabold text-pine text-[14px] mb-3">Журнал мероприятий</h3>
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
                { key: "primechaniya", header: "Примечания", render: (r) => (
                  <div>
                    <div>{r.primechaniya || "—"}</div>
                    {r.avtor_fio && <div className="text-xs text-muted mt-0.5">📱 {r.avtor_fio}</div>}
                    {r.dannye && <FieldCardDetails dannye={r.dannye} />}
                  </div>
                ) },
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

// Полевая карточка с телефона (инвентаризация/перевод): таблица проб и
// результаты по породам лежат в dannye — раньше на вебе видна была только
// текстовая сводка в «Примечаниях».
function DannyeValues({ values }) {
  const entries = Object.entries(values || {}).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (entries.length === 0) return null;
  return (
    <div className="text-xs text-ink mt-0.5">
      {entries.map(([k, v]) => `${EXTRA_LABELS[k] || k}: ${v}`).join(" · ")}
    </div>
  );
}

function FieldCardDetails({ dannye }) {
  const proby = dannye.proby || [];
  const rezultaty = dannye.rezultaty || [];
  const { taksatsiya, do_goda, prichina, akt_nomer, akt_data, vid_zemel } = dannye;
  const spisanie = { prichina, akt_nomer, akt_data, vid_zemel };
  const hasCard = proby.length > 0 || rezultaty.length > 0 || dannye.reshenie;
  return (
    <>
      {taksatsiya && <DannyeValues values={taksatsiya} />}
      {do_goda && <DannyeValues values={{ do_goda }} />}
      <DannyeValues values={spisanie} />
      {dannye.istochnik && <div className="text-xs text-muted mt-0.5">{dannye.istochnik}</div>}
      {hasCard && <FieldCardProby dannye={dannye} proby={proby} rezultaty={rezultaty} />}
    </>
  );
}

function FieldCardProby({ dannye, proby, rezultaty }) {
  return (
    <details className="mt-1">
      <summary className="text-xs text-pine cursor-pointer">Пробы и результаты с телефона</summary>
      <div className="mt-1.5 flex flex-col gap-2 text-xs">
        {proby.length > 0 && (
          <div>
            <div className="text-muted mb-0.5">Пробы{dannye.god ? ` · ${dannye.god}-й год` : ""}</div>
            {proby.map((p, i) => (
              <div key={i}>№{p.nomer} — {p.razmer}</div>
            ))}
          </div>
        )}
        {rezultaty.length > 0 && (
          <table className="border-collapse">
            <thead>
              <tr className="text-muted text-left">
                <th className="pr-3 font-normal">Порода</th>
                <th className="pr-3 font-normal">Высажено</th>
                <th className="pr-3 font-normal">Прижилось</th>
                <th className="font-normal">%</th>
              </tr>
            </thead>
            <tbody>
              {rezultaty.map((r, i) => (
                <tr key={i}>
                  <td className="pr-3">{r.poroda}</td>
                  <td className="pr-3">{r.vysazheno}</td>
                  <td className="pr-3">{r.prizhilos}</td>
                  <td>{r.vysazheno ? Math.round((r.prizhilos / r.vysazheno) * 1000) / 10 : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {dannye.reshenie && <div>Решение: {dannye.reshenie}</div>}
      </div>
    </details>
  );
}

// --------------------------------------------------------------------------- //
//   Разовая загрузка «Книги производства л/к» (.xls, по листу на год).
//   Сначала предпросмотр (в базу не пишет), потом «Загрузить». Повторная
//   загрузка той же книги дублей не создаёт — см. app/lesokultury_kniga.py.
// --------------------------------------------------------------------------- //
const KNIGA_FILTERS = [
  { key: "all", label: "Все", test: () => true },
  { key: "new", label: "Новые", test: (r) => r.deystvie === "новый" },
  { key: "est", label: "Уже в базе", test: (r) => r.deystvie !== "новый" },
  { key: "problem", label: "С замечаниями", test: (r) => r.problemy.length > 0 },
];

function itogKnigi(r) {
  if (r.status === "переведён") return `перевод ${r.perevod_god || ""}${r.perevod_kartochka ? `, карт. №${r.perevod_kartochka}` : ""}`;
  if (r.status === "списан") return `списание${r.spisat ? ` ${r.spisat}` : ""}`;
  if (r.dorashchivanie) return `доращивание ${r.dorashchivanie}`;
  return "растёт";
}

function KnigaImportModal({ open, onClose, onDone }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [lesnichestvo, setLesnichestvo] = useState("");
  const [godFrom, setGodFrom] = useState("2017");
  const [godTo, setGodTo] = useState(String(new Date().getFullYear()));
  const [preview, setPreview] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [skip, setSkip] = useState(() => new Set());
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const reset = () => {
    setFile(null);
    setLesnichestvo("");
    setPreview(null);
    setOverrides({});
    setSkip(new Set());
    setFilter("all");
    setResult(null);
  };

  const handleClose = () => {
    if (busy) return;
    if (result) onDone();
    reset();
    onClose();
  };

  const formData = (withSkip) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("lesnichestvo", lesnichestvo.trim());
    fd.append("god_from", godFrom || "2017");
    fd.append("god_to", godTo || "2100");
    const ov = Object.fromEntries(Object.entries(overrides).filter(([, v]) => v.trim()));
    if (Object.keys(ov).length) fd.append("overrides", JSON.stringify(ov));
    if (withSkip && skip.size) fd.append("skip", JSON.stringify([...skip]));
    return fd;
  };

  const handlePreview = async () => {
    if (!file) {
      toast.show({ tone: "warning", title: "Выберите файл книги" });
      return;
    }
    if (!lesnichestvo.trim()) {
      toast.show({ tone: "warning", title: "Укажите лесничество" });
      return;
    }
    setBusy(true);
    try {
      setPreview(await api.upload("/lesokultury/import-kniga/preview", formData(false)));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось прочитать книгу", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleApply = async () => {
    const count = preview.rows.length - skip.size;
    if (!window.confirm(`Загрузить в базу ${count} участков из книги?`)) return;
    setBusy(true);
    try {
      setResult(await api.upload("/lesokultury/import-kniga/apply", formData(true)));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const toggleSkip = (key) =>
    setSkip((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const onFile = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setPreview(null);
    if (f && !lesnichestvo.trim()) setLesnichestvo(f.name.replace(/\.[^.]+$/, ""));
  };

  const summary = preview?.summary;
  const rows = preview ? preview.rows.filter(KNIGA_FILTERS.find((f) => f.key === filter).test) : [];
  const overridesChanged = preview && Object.values(overrides).some((v) => v.trim());

  let footer;
  if (result) {
    footer = <Button variant="primary" onClick={handleClose}>Готово</Button>;
  } else if (preview) {
    footer = (
      <>
        <Button variant="ghost" onClick={handleClose} disabled={busy}>Отмена</Button>
        <Button variant="secondary" onClick={handlePreview} loading={busy && !result} disabled={!overridesChanged}>
          Проверить с исправлениями
        </Button>
        <Button variant="primary" onClick={handleApply} loading={busy}>
          Загрузить {preview.rows.length - skip.size} уч.
        </Button>
      </>
    );
  } else {
    footer = (
      <>
        <Button variant="ghost" onClick={handleClose} disabled={busy}>Отмена</Button>
        <Button variant="primary" onClick={handlePreview} loading={busy}>Проверить книгу</Button>
      </>
    );
  }

  return (
    <Modal open={open} onClose={handleClose} title="Загрузка книги производства лесных культур" size="xl" footer={footer}>
      {result ? (
        <div className="flex flex-col gap-2 text-sm">
          <p>Создано участков: <b>{result.sozdano}</b></p>
          <p>Дополнено существующих: <b>{result.obnovleno}</b> (заполнены только пустые поля)</p>
          <p>Записей в журнал мероприятий: <b>{result.zapisey_v_zhurnal}</b></p>
          {result.propushcheno > 0 && <p>Пропущено по вашему выбору: <b>{result.propushcheno}</b></p>}
          <p className="text-muted">Повторная загрузка этой же книги дублей не создаст.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(170px,1fr))] items-end">
            <div className="col-span-2">
              <label className="block text-[11.5px] font-semibold text-muted mb-1">Файл книги (.xls, .xlsx)</label>
              <input type="file" accept=".xls,.xlsx" onChange={onFile} className="text-sm" />
            </div>
            <TextField label="Лесничество" value={lesnichestvo} onChange={(e) => { setLesnichestvo(e.target.value); setPreview(null); }} />
            <TextField label="С года" type="number" value={godFrom} onChange={(e) => { setGodFrom(e.target.value); setPreview(null); }} />
            <TextField label="По год" type="number" value={godTo} onChange={(e) => { setGodTo(e.target.value); setPreview(null); }} />
          </div>

          {!preview && (
            <p className="text-sm text-muted">
              Сначала книга только проверяется: в базу ничего не пишется. Участки, которые уже есть в базе,
              находятся по кварталу, выделу (новому по таксации или старому) и году посадки; у них будут
              дописаны только пустые поля.
            </p>
          )}

          {summary && (
            <>
              <div className="text-sm flex flex-col gap-1">
                <div>
                  В книге <b>{summary.vsego}</b> уч. ({summary.ploshad} га): новых <b>{summary.novyh}</b>, уже в базе{" "}
                  <b>{summary.est_v_baze}</b>, с замечаниями <b>{summary.s_problemami}</b>.
                </div>
                <div className="text-muted">
                  По книге переведено за все годы: {summary.perevod.uchastkov} уч. / {summary.perevod.ploshad} га;
                  списано: {summary.spisanie.uchastkov} / {summary.spisanie.ploshad} га;
                  на доращивании: {summary.dorashchivanie.uchastkov} / {summary.dorashchivanie.ploshad} га.
                </div>
                {!summary.taksatsiya_proverena && (
                  <div className="text-oak">
                    Таксация этого лесничества в программе не найдена, поэтому выделы не сверены с ней.
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-1.5">
                {KNIGA_FILTERS.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={[
                      "px-3 py-1 rounded-full text-xs border",
                      filter === f.key ? "bg-mint text-pine border-pine font-bold" : "border-border text-muted hover:bg-hover",
                    ].join(" ")}
                  >
                    {f.label} ({preview.rows.filter(f.test).length})
                  </button>
                ))}
              </div>

              <div className="max-h-[50vh] overflow-auto border border-border rounded-md">
                <table className="w-full text-xs border-collapse">
                  <thead className="sticky top-0 bg-surface-alt text-muted text-left">
                    <tr>
                      <th className="p-1.5 font-semibold" title="Загружать">✓</th>
                      <th className="p-1.5 font-semibold">Лист / стр.</th>
                      <th className="p-1.5 font-semibold">Кв.</th>
                      <th className="p-1.5 font-semibold">Выдел</th>
                      <th className="p-1.5 font-semibold">Старый выд.</th>
                      <th className="p-1.5 font-semibold">Га</th>
                      <th className="p-1.5 font-semibold">Состав</th>
                      <th className="p-1.5 font-semibold">Итог по книге</th>
                      <th className="p-1.5 font-semibold">В базе</th>
                      <th className="p-1.5 font-semibold">Замечания</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.key} className={["border-t border-border", skip.has(r.key) ? "opacity-50" : ""].join(" ")}>
                        <td className="p-1.5">
                          <input type="checkbox" checked={!skip.has(r.key)} onChange={() => toggleSkip(r.key)} className="accent-pine" />
                        </td>
                        <td className="p-1.5 whitespace-nowrap">{r.list} / {r.stroka}</td>
                        <td className="p-1.5">{r.kvartal}</td>
                        <td className="p-1.5">
                          <input
                            value={overrides[r.key] ?? r.vydel ?? ""}
                            onChange={(e) => setOverrides((o) => ({ ...o, [r.key]: e.target.value }))}
                            className="w-24 bg-surface border border-border focus:border-pine rounded px-1.5 h-7 outline-none"
                            title="Можно исправить выдел; затем «Проверить с исправлениями»"
                          />
                        </td>
                        <td className="p-1.5">{r.vydel_staryy || "—"}</td>
                        <td className="p-1.5">{r.ploshad}</td>
                        <td className="p-1.5">{r.sostav || "—"}</td>
                        <td className="p-1.5 whitespace-nowrap">{itogKnigi(r)}</td>
                        <td className="p-1.5">{r.deystvie === "новый" ? "новый" : r.kak_nayden}</td>
                        <td className="p-1.5 text-oak">{r.problemy.join("; ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}

export default function Lesokultury() {
  const toast = useToast();
  const [uchastki, setUchastki] = useState([]);
  const [loading, setLoading] = useState(true);
  const [includeSpisannye, setIncludeSpisannye] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
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
    <div className="p-[18px] flex flex-wrap gap-[14px] items-start">
      <Card padding={false} className="flex flex-col" style={{ flex: "1 1 260px", maxWidth: 380 }}>
        <div className="p-5 pb-3 flex flex-col gap-3 border-b border-border">
          <Button variant="primary" onClick={() => setCreateOpen(true)}>Новый участок</Button>
          <Button variant="secondary" onClick={() => setImportOpen(true)}>Загрузить книгу л/к</Button>
          <TextField
            placeholder="Поиск: квартал, выдел, лесничество, порода, делянка"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            value={god}
            onChange={(e) => setGod(e.target.value)}
            className="w-full bg-surface border border-border focus:border-pine rounded-md px-3.5 py-2.5 text-sm text-ink outline-none transition-colors"
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

      <KnigaImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onDone={() => {
          loadList();
          api.get("/lesokultury/gody").then((rows) => setGody(rows || [])).catch(() => {});
        }}
      />
      <CreateUchastokModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(id) => { loadList(); setSelectedId(id); }} />
    </div>
  );
}
