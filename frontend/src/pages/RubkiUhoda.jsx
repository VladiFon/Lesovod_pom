import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import {
  calculateProba,
  createProba,
  deleteKomissiyaPreset,
  deleteProba,
  generateAndDownload,
  getPorody,
  getProba,
  listKomissiyaPresets,
  listLesokulturyUchastkiForPicker,
  listProby,
  saveKomissiyaPreset,
  updateProba,
} from "../api/uhody.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Рубки ухода" (C.3 плана) — независимые пробы (не привязаны к
 * делянке, см. docstring backend/legacy/uhody.py): ведомость перечёта и
 * обмера укладок хвороста, расчёт запаса, экспорт в Word/Excel.
 *
 * Перенесено 1:1 из "плана 1.3" (screens/uhody/, десктоп) с поправкой на
 * веб: фронт не считает сам — только шлёт сырые строки укладок на
 * POST /api/uhody/calculate и показывает то, что вернул бэкенд, ровно как
 * задумано в C3_plan_rubki_uhoda.md.
 *
 * Собрано по тем же паттернам, что и остальные экраны Этапа 4-7 (не
 * своим CSS/fetch, как в первом черновике этого экрана):
 *   Поиск участка по кварталу/выделу      → api.get("/taxation/vydel", ...), как в Taxation.jsx
 *   Список слева + карточка справа        → тот же layout, что Plots.jsx
 *   Пресеты комиссии                      → PresetRow, скопирован 1:1 из Plots.jsx
 *   Генерация Word/Excel                  → POST .../documents/{kind} → pollTask() → скачивание,
 *                                            тот же паттерн, что и у остальных генераторов документов
 */

const emptyRow = () => ({ poroda: "", shirina: "", vysota: "", dlina: "" });

const emptyForm = () => ({
  lesnichestvo: "",
  nomer_lesoseki: "",
  ploshad_lesoseki: "",
  kategoriya_lesov: "",
  vozrast: "",
  sostav: "",
  polnota: "",
  vid_polzovaniya: "",
  vid_rubki: "",
  sposob_rubki: "",
  god_rubki: "",
  metod: "По пробным площадям (обмер укладок хвороста)",
  kol_ploshadok: "",
  ploshad_ploshadki: "",
  komissiya: { perechet1: "", perechet2: "", perechet3: "", doljnost: "", fio: "" },
});

/** Подписанный select — тот же класс, что использует Taxation.jsx для
 * "Лесничество" (в компонентах дизайн-кита нет отдельного Select). */
function SelectField({ label, value, onChange, options, placeholder = "—", className = "" }) {
  return (
    <div className={className}>
      {label && (
        <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
          {label}
        </label>
      )}
      <select
        value={value}
        onChange={onChange}
        className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
      >
        <option value="">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Читаемое значение (↔ Field в Taxation.jsx) — для карточки найденного
 * участка и итогов расчёта. */
function Field({ caption, value }) {
  return (
    <div>
      <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase">{caption}</div>
      <div className="text-base text-ink font-semibold mt-0.5">{value ?? "—"}</div>
    </div>
  );
}

/** PresetRow — скопирован 1:1 из pages/Plots.jsx (компонент там локальный,
 * не экспортируется из components/). Применить/сохранить/удалить пресет
 * по названию, с инлайновым полем ввода имени вместо window.prompt. */
function PresetRow({ label, options, onApply, onDelete, onSaveNew }) {
  const [selected, setSelected] = useState("");
  const [savingNew, setSavingNew] = useState(false);
  const [newName, setNewName] = useState("");
  const hasOptions = options && options.length > 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase">{label}</div>

      {hasOptions ? (
        <div className="flex items-center gap-2">
          <select
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              if (e.target.value) onApply(e.target.value);
            }}
            className="flex-1 bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
          >
            <option value="" disabled>
              Выбрать пресет…
            </option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.nazvanie}
              </option>
            ))}
          </select>
          {selected && (
            <button
              onClick={() => {
                onDelete(selected);
                setSelected("");
              }}
              title="Удалить пресет"
              className="text-error hover:text-error shrink-0 px-2"
            >
              🗑
            </button>
          )}
        </div>
      ) : (
        <div className="text-sm text-faint">Пресетов пока нет.</div>
      )}

      {savingNew ? (
        <div className="flex items-center gap-2">
          <input
            autoFocus
            placeholder="Название пресета…"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="flex-1 bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3 py-2 text-sm text-ink outline-none transition-colors"
          />
          <button
            onClick={() => {
              if (!newName.trim()) return;
              onSaveNew(newName.trim());
              setNewName("");
              setSavingNew(false);
            }}
            className="text-pine font-semibold text-sm shrink-0"
          >
            Сохранить
          </button>
          <button
            onClick={() => {
              setNewName("");
              setSavingNew(false);
            }}
            className="text-faint text-sm shrink-0"
          >
            Отмена
          </button>
        </div>
      ) : (
        <button onClick={() => setSavingNew(true)} className="text-pine font-semibold text-sm text-left">
          💾 Сохранить текущее как пресет
        </button>
      )}
    </div>
  );
}

export default function RubkiUhoda() {
  const toast = useToast();

  // --- справочники ---
  const [porody, setPorody] = useState([]);
  const [vidyRubki, setVidyRubki] = useState([]);
  const [komissiyaPresets, setKomissiyaPresets] = useState([]);

  // --- поиск участка ---
  const [searchKvartal, setSearchKvartal] = useState("");
  const [searchVydelNomer, setSearchVydelNomer] = useState("");
  const [vydelCard, setVydelCard] = useState(null);
  const [searching, setSearching] = useState(false);

  // --- список своих проб ---
  const [proby, setProby] = useState([]);
  const [probyLoading, setProbyLoading] = useState(true);
  const [probySearch, setProbySearch] = useState("");

  // --- текущая проба ---
  const [selectedId, setSelectedId] = useState(null);
  const [kvartal, setKvartal] = useState("");
  const [vydel, setVydel] = useState("");
  const [ploshadVydela, setPloshadVydela] = useState("");
  const [dataZamera, setDataZamera] = useState("");
  const [form, setForm] = useState(emptyForm());
  const [rows, setRows] = useState([emptyRow()]);
  const [calcResult, setCalcResult] = useState(null);

  const [calculating, setCalculating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exportingWord, setExportingWord] = useState(false);
  const [exportingExcel, setExportingExcel] = useState(false);

  // ---- Фаза 2 плана доработки: отметка "выполнено" + исполнители ---- //
  const [completedAt, setCompletedAt] = useState(null);
  const [ispolniteli, setIspolniteli] = useState([]);
  const [sotrudnikiList, setSotrudnikiList] = useState([]);
  const [completeModalOpen, setCompleteModalOpen] = useState(false);
  const [pickedSotrudnikIds, setPickedSotrudnikIds] = useState([]);
  const [completing, setCompleting] = useState(false);

  // ---- доработка: пробы ↔ лесные культуры ---- //
  // Участки лесных культур, на которых проведена эта проба — при отметке
  // "выполнено" на каждом автоматически заводится запись "уход выполнен"
  // (см. db.mark_uhody_proba_completed). Выбираются при сохранении пробы.
  const [lesokulturyUchastokIds, setLesokulturyUchastokIds] = useState([]);
  const [lesokulturySelectedInfo, setLesokulturySelectedInfo] = useState([]);
  const [lesokulturyOptions, setLesokulturyOptions] = useState([]);
  const [lesokulturySearch, setLesokulturySearch] = useState("");
  const [lesokulturyLoading, setLesokulturyLoading] = useState(false);

  useEffect(() => {
    setLesokulturyLoading(true);
    const t = setTimeout(() => {
      listLesokulturyUchastkiForPicker(lesokulturySearch.trim() || undefined)
        .then(setLesokulturyOptions)
        .catch(() => {})
        .finally(() => setLesokulturyLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [lesokulturySearch]);

  const toggleLesokulturyPick = (u) => {
    setLesokulturyUchastokIds((ids) =>
      ids.includes(u.id) ? ids.filter((id) => id !== u.id) : [...ids, u.id]
    );
    setLesokulturySelectedInfo((list) =>
      list.some((x) => x.id === u.id) ? list.filter((x) => x.id !== u.id) : [...list, u]
    );
  };

  useEffect(() => {
    api.get("/uhody/sotrudniki").then(setSotrudnikiList).catch(() => {});
  }, []);

  const isEditing = selectedId !== null;

  // ------------------------------------------------------------------- //
  const reloadProby = useCallback(() => {
    setProbyLoading(true);
    listProby()
      .then(setProby)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить пробы", description: e.message }))
      .finally(() => setProbyLoading(false));
  }, [toast]);

  useEffect(() => {
    getPorody()
      .then((r) => {
        setPorody(r.porody || []);
        setVidyRubki(r.vidy_rubki || []);
      })
      .catch(() => {});
    listKomissiyaPresets()
      .then(setKomissiyaPresets)
      .catch(() => {});
    reloadProby();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredProby = useMemo(() => {
    const q = probySearch.trim().toLowerCase();
    if (!q) return proby;
    return proby.filter((p) => `${p.kvartal}/${p.vydel}`.toLowerCase().includes(q));
  }, [proby, probySearch]);

  // ------------------------------------------------------------------- //
  //   Поиск участка (кв./выдел) — предзаполнение формы
  // ------------------------------------------------------------------- //
  const handleSearchVydel = async () => {
    if (!searchKvartal.trim() || !searchVydelNomer.trim()) {
      toast.show({ tone: "warning", title: "Укажите номер квартала и номер выдела" });
      return;
    }
    setSearching(true);
    try {
      const card = await api.get("/taxation/vydel", {
        kvartal: searchKvartal.trim(),
        vydel: searchVydelNomer.trim(),
      });
      setVydelCard(card);
      setKvartal(searchKvartal.trim());
      setVydel(searchVydelNomer.trim());
      setPloshadVydela(card.ploshad ?? "");
      setForm((f) => ({
        ...f,
        lesnichestvo: card.lesnichestvo || f.lesnichestvo,
        kategoriya_lesov: card.kategoriya_lesov || f.kategoriya_lesov,
        polnota: card.polnota ?? f.polnota,
        sostav: card.formula_sostava || f.sostav,
        vozrast: card.sostav?.[0]?.vozrast ?? f.vozrast,
      }));
    } catch (e) {
      setVydelCard(null);
      if (e.status === 404) {
        toast.show({ tone: "warning", title: "Участок не найден", description: "Проверьте квартал и выдел." });
      } else {
        toast.show({ tone: "danger", title: "Поиск не удался", description: e.message });
      }
    } finally {
      setSearching(false);
    }
  };

  // ------------------------------------------------------------------- //
  //   Открыть / создать новую пробу
  // ------------------------------------------------------------------- //
  const resetForm = () => {
    setSelectedId(null);
    setKvartal("");
    setVydel("");
    setPloshadVydela("");
    setDataZamera("");
    setForm(emptyForm());
    setRows([emptyRow()]);
    setCalcResult(null);
    setVydelCard(null);
    setCompletedAt(null);
    setIspolniteli([]);
    setLesokulturyUchastokIds([]);
    setLesokulturySelectedInfo([]);
  };

  const openProba = async (id) => {
    try {
      const record = await getProba(id);
      const data = record.data || {};
      setSelectedId(record.id);
      setKvartal(record.kvartal || "");
      setVydel(record.vydel || "");
      setPloshadVydela(record.ploshad_vydela ?? "");
      setDataZamera(record.data_zamera || "");
      setForm({
        lesnichestvo: data.lesnichestvo || "",
        nomer_lesoseki: data.nomer_lesoseki || "",
        ploshad_lesoseki: data.ploshad_lesoseki ?? "",
        kategoriya_lesov: data.kategoriya_lesov || "",
        vozrast: data.vozrast ?? "",
        sostav: data.sostav || "",
        polnota: data.polnota ?? "",
        vid_polzovaniya: data.vid_polzovaniya || "",
        vid_rubki: data.vid_rubki || "",
        sposob_rubki: data.sposob_rubki || "",
        god_rubki: data.god_rubki ?? "",
        metod: data.metod || "По пробным площадям (обмер укладок хвороста)",
        kol_ploshadok: data.kol_ploshadok ?? "",
        ploshad_ploshadki: data.ploshad_ploshadki ?? "",
        komissiya: {
          perechet1: data.komissiya?.perechet1 || "",
          perechet2: data.komissiya?.perechet2 || "",
          perechet3: data.komissiya?.perechet3 || "",
          doljnost: data.komissiya?.doljnost || "",
          fio: data.komissiya?.fio || "",
        },
      });
      // rows хранятся уже посчитанными — для повторного редактирования
      // нужны только сырые поля, расчётные колонки вернутся после
      // следующего "Рассчитать".
      const rawRows = (data.rows || []).map((r) => ({
        poroda: r.poroda === "—" ? "" : r.poroda || "",
        shirina: r.shirina ?? "",
        vysota: r.vysota ?? "",
        dlina: r.dlina ?? "",
      }));
      setRows(rawRows.length ? rawRows : [emptyRow()]);
      setCalcResult(null);
      setVydelCard(null);
      setCompletedAt(record.completed_at || null);
      setIspolniteli(record.ispolniteli || []);
      setLesokulturyUchastokIds(record.lesokultury_uchastok_ids || []);
      setLesokulturySelectedInfo(record.lesokultury_uchastki || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось открыть пробу", description: e.message });
    }
  };

  // ------------------------------------------------------------------- //
  //   Таблица укладок
  // ------------------------------------------------------------------- //
  const updateRow = (idx, field, value) => {
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, [field]: value } : r)));
  };
  const addRow = () => setRows((rs) => [...rs, emptyRow()]);
  const removeRow = (idx) => setRows((rs) => (rs.length > 1 ? rs.filter((_, i) => i !== idx) : rs));

  // ------------------------------------------------------------------- //
  //   Расчёт / сохранение / удаление / экспорт
  // ------------------------------------------------------------------- //
  const handleCalculate = async () => {
    setCalculating(true);
    try {
      const result = await calculateProba({
        rows,
        kol_ploshadok: form.kol_ploshadok,
        ploshad_ploshadki: form.ploshad_ploshadki,
        ploshad_lesoseki: form.ploshad_lesoseki,
      });
      setCalcResult(result);
    } catch (e) {
      setCalcResult(null);
      toast.show({ tone: "danger", title: "Не удалось рассчитать пробу", description: e.message });
    } finally {
      setCalculating(false);
    }
  };

  const handleSave = async () => {
    if (!kvartal.trim() || !vydel.trim()) {
      toast.show({ tone: "warning", title: "Укажите квартал и выдел, прежде чем сохранять пробу" });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        kvartal: kvartal.trim(),
        vydel: vydel.trim(),
        ploshad_vydela: ploshadVydela,
        data_zamera: dataZamera,
        rows,
        form,
        lesokultury_uchastok_ids: lesokulturyUchastokIds,
      };
      const saved = isEditing ? await updateProba(selectedId, payload) : await createProba(payload);
      setSelectedId(saved.id);
      setCalcResult({
        rows: saved.data.rows,
        obyom_sklad_total: saved.data.obyom_sklad_total,
        zapas_proby_total: saved.data.zapas_proby_total,
        zapas_na_1ga: saved.data.zapas_na_1ga,
        zapas_na_lesoseke: saved.data.zapas_na_lesoseke,
      });
      toast.show({ tone: "success", title: isEditing ? "Проба обновлена" : "Проба сохранена" });
      reloadProby();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить пробу", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!isEditing) return;
    if (!window.confirm("Удалить эту пробу? Действие необратимо.")) return;
    try {
      await deleteProba(selectedId);
      toast.show({ tone: "success", title: "Проба удалена" });
      resetForm();
      reloadProby();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить пробу", description: e.message });
    }
  };

  // ---- Фаза 2 плана доработки: отметка "выполнено" + исполнители ---- //
  const openCompleteModal = () => {
    setPickedSotrudnikIds(ispolniteli.map((i) => i.id));
    setCompleteModalOpen(true);
  };

  const toggleSotrudnikPick = (id) => {
    setPickedSotrudnikIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const handleConfirmComplete = async () => {
    if (pickedSotrudnikIds.length === 0) {
      toast.show({ tone: "warning", title: "Выберите хотя бы одного исполнителя" });
      return;
    }
    setCompleting(true);
    try {
      const record = await api.post(`/uhody/proby/${selectedId}/complete`, { sotrudnik_ids: pickedSotrudnikIds });
      setCompletedAt(record.completed_at);
      setIspolniteli(record.ispolniteli || []);
      setCompleteModalOpen(false);
      toast.show({ tone: "success", title: "Проба отмечена выполненной", description: "Выдел подсветится на Живой карте." });
      reloadProby();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось отметить пробу", description: e.message });
    } finally {
      setCompleting(false);
    }
  };

  const handleUncomplete = async () => {
    if (!window.confirm("Снять отметку «выполнено»? Подсветка на карте тоже пропадёт.")) return;
    try {
      const record = await api.post(`/uhody/proby/${selectedId}/uncomplete`);
      setCompletedAt(record.completed_at);
      setIspolniteli(record.ispolniteli || []);
      toast.show({ tone: "info", title: "Отметка снята" });
      reloadProby();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось снять отметку", description: e.message });
    }
  };

  const handleExport = async (kind) => {
    if (!isEditing) {
      toast.show({ tone: "warning", title: "Сначала сохраните пробу", description: "Экспорт доступен только для сохранённой пробы." });
      return;
    }
    const setBusy = kind === "word" ? setExportingWord : setExportingExcel;
    setBusy(true);
    try {
      await generateAndDownload(selectedId, kind);
      toast.show({ tone: "success", title: "Документ готов", description: "Скачивание началось." });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сформировать документ", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  // ------------------------------------------------------------------- //
  //   Комиссия / пресеты
  // ------------------------------------------------------------------- //
  const updateKomissiya = (field, value) => {
    setForm((f) => ({ ...f, komissiya: { ...f.komissiya, [field]: value } }));
  };

  const applyPreset = (presetId) => {
    const preset = komissiyaPresets.find((p) => String(p.id) === String(presetId));
    if (!preset) return;
    setForm((f) => ({
      ...f,
      komissiya: {
        perechet1: preset.perechetchik_1 || "",
        perechet2: preset.perechetchik_2 || "",
        perechet3: preset.perechetchik_3 || "",
        doljnost: preset.proveril_doljnost || "",
        fio: preset.proveril_fio || "",
      },
    }));
  };

  const saveCurrentAsPreset = async (nazvanie) => {
    try {
      await saveKomissiyaPreset({
        nazvanie,
        perechetchik_1: form.komissiya.perechet1,
        perechetchik_2: form.komissiya.perechet2,
        perechetchik_3: form.komissiya.perechet3,
        proveril_doljnost: form.komissiya.doljnost,
        proveril_fio: form.komissiya.fio,
      });
      listKomissiyaPresets().then(setKomissiyaPresets);
      toast.show({ tone: "success", title: "Пресет сохранён" });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить пресет", description: e.message });
    }
  };

  const removePreset = async (presetId) => {
    try {
      await deleteKomissiyaPreset(presetId);
      listKomissiyaPresets().then(setKomissiyaPresets);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить пресет", description: e.message });
    }
  };

  // ------------------------------------------------------------------- //
  //   Рендер
  // ------------------------------------------------------------------- //
  return (
    <div className="p-8 flex gap-6 items-start">
      {/* ---------- Левая колонка: список своих проб ---------- */}
      <Card padding={false} className="w-[360px] shrink-0 flex flex-col">
        <div className="p-5 pb-3 flex flex-col gap-3 border-b border-border">
          <Button variant="primary" onClick={resetForm}>
            + Новая проба
          </Button>
          <TextField
            placeholder="Фильтр по кварталу/выделу…"
            value={probySearch}
            onChange={(e) => setProbySearch(e.target.value)}
          />
        </div>
        <div className="flex-1 overflow-y-auto max-h-[calc(100vh-280px)] p-2">
          {probyLoading ? (
            <div className="p-5 flex justify-center">
              <div className="h-5 w-5 rounded-full border-2 border-pine border-t-transparent animate-spin" />
            </div>
          ) : filteredProby.length === 0 ? (
            <div className="p-3">
              <EmptyState icon="🪵" title="Проб пока нет" description="Заполните форму справа и нажмите «Сохранить пробу»." />
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {filteredProby.map((p) => (
                <li key={p.id}>
                  <button
                    onClick={() => openProba(p.id)}
                    className={[
                      "w-full text-left px-3 py-2.5 rounded-md transition-colors",
                      selectedId === p.id ? "bg-mint text-pine font-bold" : "hover:bg-hover",
                    ].join(" ")}
                  >
                    <div className="text-base">
                      кв. {p.kvartal} / выд. {p.vydel}
                      {p.completed_at && <span className="ml-1.5 text-pine">✓</span>}
                    </div>
                    <div className="text-xs text-muted mt-0.5 truncate">
                      {p.data_zamera || "дата не указана"}
                      {p.ploshad_proby ? ` · проба ${p.ploshad_proby} га` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      {/* ---------- Правая колонка ---------- */}
      <div className="flex-1 min-w-0 flex flex-col gap-6">
        {/* Поиск участка */}
        <Card title="Участок" subtitle="Поиск по кварталу/выделу — предзаполняет лесничество, категорию, состав и полноту">
          <div className="flex items-end gap-4 flex-wrap">
            <TextField
              label="Квартал"
              placeholder="Квартал…"
              value={searchKvartal}
              onChange={(e) => setSearchKvartal(e.target.value.replace(/[^\d]/g, ""))}
              className="w-40"
            />
            <TextField
              label="Выдел"
              placeholder="Выдел…"
              value={searchVydelNomer}
              onChange={(e) => setSearchVydelNomer(e.target.value.replace(/[^\d]/g, ""))}
              className="w-40"
            />
            <Button variant="primary" onClick={handleSearchVydel} loading={searching}>
              🔍 Найти участок
            </Button>
          </div>
          {vydelCard && (
            <div className="grid grid-cols-4 gap-4 mt-5 pt-5 border-t border-border">
              <Field caption="Лесничество" value={vydelCard.lesnichestvo} />
              <Field caption="Площадь выдела, га" value={vydelCard.ploshad} />
              <Field caption="Категория лесов" value={vydelCard.kategoriya_lesov} />
              <Field caption="Полнота" value={vydelCard.polnota} />
            </div>
          )}
        </Card>

        {/* Шапка ведомости */}
        <Card
          title={isEditing ? `Ведомость перечёта — проба №${selectedId}` : "Ведомость перечёта — новая проба"}
          subtitle="Ведомость перечёта и обмера древесины на пробных площадях"
        >
          <div className="grid grid-cols-3 gap-4">
            <TextField label="Квартал" value={kvartal} onChange={(e) => setKvartal(e.target.value)} />
            <TextField label="Выдел" value={vydel} onChange={(e) => setVydel(e.target.value)} />
            <TextField
              label="Площадь выдела, га"
              type="number"
              value={ploshadVydela}
              onChange={(e) => setPloshadVydela(e.target.value)}
            />

            <TextField
              label="Лесничество"
              className="col-span-2"
              value={form.lesnichestvo}
              onChange={(e) => setForm({ ...form, lesnichestvo: e.target.value })}
            />
            <TextField label="Дата замера" type="date" value={dataZamera} onChange={(e) => setDataZamera(e.target.value)} />

            <TextField
              label="№ лесосеки"
              value={form.nomer_lesoseki}
              onChange={(e) => setForm({ ...form, nomer_lesoseki: e.target.value })}
            />
            <TextField
              label="Площадь лесосеки, га"
              type="number"
              value={form.ploshad_lesoseki}
              onChange={(e) => setForm({ ...form, ploshad_lesoseki: e.target.value })}
            />
            <TextField
              label="Категория лесов"
              value={form.kategoriya_lesov}
              onChange={(e) => setForm({ ...form, kategoriya_lesov: e.target.value })}
            />

            <TextField
              label="Возраст"
              type="number"
              value={form.vozrast}
              onChange={(e) => setForm({ ...form, vozrast: e.target.value })}
            />
            <TextField
              label="Вид пользования"
              value={form.vid_polzovaniya}
              onChange={(e) => setForm({ ...form, vid_polzovaniya: e.target.value })}
            />
            <TextField
              label="Состав насаждения"
              value={form.sostav}
              onChange={(e) => setForm({ ...form, sostav: e.target.value })}
            />

            <TextField
              label="Полнота"
              type="number"
              step="0.1"
              value={form.polnota}
              onChange={(e) => setForm({ ...form, polnota: e.target.value })}
            />
            <TextField label="Год рубки" value={form.god_rubki} onChange={(e) => setForm({ ...form, god_rubki: e.target.value })} />
            <SelectField
              label="Вид рубки"
              value={form.vid_rubki}
              onChange={(e) => setForm({ ...form, vid_rubki: e.target.value })}
              options={vidyRubki}
            />

            <TextField
              label="Способ рубки"
              value={form.sposob_rubki}
              onChange={(e) => setForm({ ...form, sposob_rubki: e.target.value })}
            />
            <TextField
              label="Метод"
              className="col-span-2"
              value={form.metod}
              onChange={(e) => setForm({ ...form, metod: e.target.value })}
            />

            <TextField
              label="Кол-во пробных площадок"
              type="number"
              value={form.kol_ploshadok}
              onChange={(e) => setForm({ ...form, kol_ploshadok: e.target.value })}
            />
            <TextField
              label="Площадь одной площадки, га"
              type="number"
              step="0.001"
              value={form.ploshad_ploshadki}
              onChange={(e) => setForm({ ...form, ploshad_ploshadki: e.target.value })}
            />
          </div>
        </Card>

        {/* Обмер укладок хвороста */}
        <Card title="Обмер укладок хвороста" subtitle="Фронт не считает сам — расчёт делает сервер по нажатию «Рассчитать»">
          <div className="bg-surface border border-border rounded-md overflow-hidden">
            <table className="w-full text-base border-collapse">
              <thead>
                <tr className="bg-surface-alt border-b border-border">
                  <th className="px-3 py-2.5 text-left text-sm font-semibold text-muted">Порода</th>
                  <th className="px-3 py-2.5 text-left text-sm font-semibold text-muted">Ширина, м</th>
                  <th className="px-3 py-2.5 text-left text-sm font-semibold text-muted">Высота, м</th>
                  <th className="px-3 py-2.5 text-left text-sm font-semibold text-muted">Длина, м</th>
                  <th className="w-10 px-3 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={idx} className="border-b border-border last:border-b-0">
                    <td className="px-2 py-1.5">
                      <input
                        list="uhody-porody-list"
                        value={row.poroda}
                        onChange={(e) => updateRow(idx, "poroda", e.target.value)}
                        className="w-full bg-transparent px-1.5 py-1 rounded outline-none focus:bg-surface-alt"
                      />
                    </td>
                    {["shirina", "vysota", "dlina"].map((field) => (
                      <td key={field} className="px-2 py-1.5">
                        <input
                          type="number"
                          step="0.01"
                          value={row[field]}
                          onChange={(e) => updateRow(idx, field, e.target.value)}
                          className="w-full bg-transparent px-1.5 py-1 rounded outline-none focus:bg-surface-alt"
                        />
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-center">
                      <button
                        onClick={() => removeRow(idx)}
                        title="Удалить строку"
                        className="text-error hover:text-error"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <datalist id="uhody-porody-list">
            {porody.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>

          <div className="flex items-center justify-between mt-3">
            <Button variant="ghost" size="sm" onClick={addRow}>
              + Добавить укладку
            </Button>
            <Button variant="primary" onClick={handleCalculate} loading={calculating}>
              Рассчитать
            </Button>
          </div>

          {calcResult && (
            <div className="mt-5 pt-5 border-t border-border">
              <div className="bg-surface border border-border rounded-md overflow-hidden mb-4">
                <table className="w-full text-base border-collapse">
                  <thead>
                    <tr className="bg-surface-alt border-b border-border">
                      {["№", "Порода", "Ширина", "Высота", "Длина", "Объём склад.", "Коэфф.", "Запас на пробе"].map(
                        (h) => (
                          <th key={h} className="px-3 py-2.5 text-left text-sm font-semibold text-muted">
                            {h}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {calcResult.rows.map((r) => (
                      <tr key={r.nomer} className="border-b border-border last:border-b-0">
                        <td className="px-3 py-2 text-ink">{r.nomer}</td>
                        <td className="px-3 py-2 text-ink">{r.poroda}</td>
                        <td className="px-3 py-2 text-ink">{r.shirina}</td>
                        <td className="px-3 py-2 text-ink">{r.vysota}</td>
                        <td className="px-3 py-2 text-ink">{r.dlina}</td>
                        <td className="px-3 py-2 text-ink">{r.obyom_sklad}</td>
                        <td className="px-3 py-2 text-ink">{r.koeff}</td>
                        <td className="px-3 py-2 text-ink">{r.zapas}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="grid grid-cols-4 gap-4">
                <Field caption="Объём складочной массы, всего" value={calcResult.obyom_sklad_total} />
                <Field caption="Запас на пробе, м³" value={calcResult.zapas_proby_total} />
                <Field caption="Запас на 1 га, м³" value={calcResult.zapas_na_1ga} />
                {calcResult.zapas_na_lesoseke != null && (
                  <Field caption="Запас на всю лесосеку, м³" value={calcResult.zapas_na_lesoseke} />
                )}
              </div>
            </div>
          )}
        </Card>

        {/* Комиссия */}
        <Card title="Комиссия">
          <div className="grid grid-cols-3 gap-6">
            <PresetRow
              label="Пресет комиссии"
              options={komissiyaPresets}
              onApply={applyPreset}
              onDelete={removePreset}
              onSaveNew={saveCurrentAsPreset}
            />
            <div className="col-span-2 grid grid-cols-3 gap-4">
              <TextField
                label="Перечётчик 1"
                value={form.komissiya.perechet1}
                onChange={(e) => updateKomissiya("perechet1", e.target.value)}
              />
              <TextField
                label="Перечётчик 2"
                value={form.komissiya.perechet2}
                onChange={(e) => updateKomissiya("perechet2", e.target.value)}
              />
              <TextField
                label="Перечётчик 3"
                value={form.komissiya.perechet3}
                onChange={(e) => updateKomissiya("perechet3", e.target.value)}
              />
              <TextField
                label="Проверил — должность"
                value={form.komissiya.doljnost}
                onChange={(e) => updateKomissiya("doljnost", e.target.value)}
              />
              <TextField
                label="Проверил — Ф.И.О."
                className="col-span-2"
                value={form.komissiya.fio}
                onChange={(e) => updateKomissiya("fio", e.target.value)}
              />
            </div>
          </div>
        </Card>

        {/* Лесные культуры — на каких участках проведена проба */}
        <Card title="Участки лесных культур">
          <p className="text-sm text-muted mb-3">
            Выберите участки, на которых проведена эта проба — при отметке пробы выполненной на
            каждом из них автоматически появится запись «уход выполнен» в журнале мероприятий.
          </p>
          {lesokulturySelectedInfo.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {lesokulturySelectedInfo.map((u) => (
                <span
                  key={u.id}
                  className="inline-flex items-center gap-1.5 bg-mint text-pine text-sm font-medium rounded-full px-3 py-1"
                >
                  Кв. {u.kvartal || "—"} / Выд. {u.vydel || "—"}{u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}
                  <button
                    type="button"
                    onClick={() => toggleLesokulturyPick(u)}
                    className="text-pine hover:text-ink"
                    aria-label="Убрать"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}
          <TextField
            placeholder="Поиск участка: квартал, выдел, лесничество, порода"
            value={lesokulturySearch}
            onChange={(e) => setLesokulturySearch(e.target.value)}
          />
          <div className="mt-2 max-h-56 overflow-y-auto border border-border rounded-md">
            {lesokulturyLoading ? (
              <div className="p-4 flex justify-center">
                <div className="h-4 w-4 rounded-full border-2 border-pine border-t-transparent animate-spin" />
              </div>
            ) : lesokulturyOptions.length === 0 ? (
              <div className="p-4 text-sm text-muted text-center">Ничего не найдено</div>
            ) : (
              lesokulturyOptions.map((u) => (
                <label
                  key={u.id}
                  className="flex items-center gap-3 px-3 py-2 hover:bg-hover cursor-pointer border-b border-border last:border-b-0"
                >
                  <input
                    type="checkbox"
                    checked={lesokulturyUchastokIds.includes(u.id)}
                    onChange={() => toggleLesokulturyPick(u)}
                    className="w-4 h-4 accent-pine"
                  />
                  <div>
                    <div className="text-sm text-ink">Кв. {u.kvartal || "—"} / Выд. {u.vydel || "—"}</div>
                    <div className="text-xs text-muted">
                      {u.lesnichestvo || "—"}{u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}{u.god_sozdaniya ? ` · ${u.god_sozdaniya} г.` : ""}
                    </div>
                  </div>
                </label>
              ))
            )}
          </div>
        </Card>

        {/* Действия */}
        <div className="flex flex-wrap items-center gap-3 pb-6">
          <Button variant="primary" onClick={handleSave} loading={saving}>
            {isEditing ? "Сохранить изменения" : "Сохранить пробу"}
          </Button>
          <Button variant="secondary" onClick={() => handleExport("word")} loading={exportingWord} disabled={!isEditing}>
            📄 Экспорт в Word
          </Button>
          <Button variant="secondary" onClick={() => handleExport("excel")} loading={exportingExcel} disabled={!isEditing}>
            📊 Экспорт в Excel
          </Button>
          {isEditing && !completedAt && (
            <Button variant="secondary" onClick={openCompleteModal}>
              ✅ Отметить выполненной
            </Button>
          )}
          {isEditing && completedAt && (
            <Button variant="secondary" onClick={handleUncomplete}>
              ✓ Выполнено ({ispolniteli.map((i) => i.fio).join(", ")}) — снять отметку
            </Button>
          )}
          {isEditing && (
            <Button variant="danger" onClick={handleDelete}>
              Удалить пробу
            </Button>
          )}
        </div>
      </div>

      <Modal open={completeModalOpen} onClose={() => setCompleteModalOpen(false)} title="Кто выполнил работу?">
        <div className="flex flex-col gap-2 max-h-[50vh] overflow-y-auto">
          {sotrudnikiList.length === 0 ? (
            <EmptyState
              icon="👤"
              title="Справочник сотрудников пуст"
              description="Добавьте сотрудников в Настройках, во вкладке «Сотрудники (мобильное приложение)»."
            />
          ) : (
            sotrudnikiList.map((s) => (
              <label
                key={s.id}
                className="flex items-center gap-3 px-3 py-2 rounded-md hover:bg-hover cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={pickedSotrudnikIds.includes(s.id)}
                  onChange={() => toggleSotrudnikPick(s.id)}
                  className="w-4 h-4 accent-pine"
                />
                <div>
                  <div className="text-base text-ink">{s.fio}</div>
                  <div className="text-xs text-muted">{s.dolzhnost || "должность не указана"}{s.uchastok ? ` · ${s.uchastok}` : ""}</div>
                </div>
              </label>
            ))
          )}
        </div>
        <div className="flex items-center justify-end gap-2 mt-6">
          <Button variant="secondary" onClick={() => setCompleteModalOpen(false)}>
            Отмена
          </Button>
          <Button variant="primary" loading={completing} onClick={handleConfirmComplete}>
            Отметить выполненной
          </Button>
        </div>
      </Modal>
    </div>
  );
}
