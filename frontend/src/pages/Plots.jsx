import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import { pollTask } from "../hooks/useTaskPolling.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";
import ChastiForm, { chastiInfo, vydelyIz } from "../components/ChastiPoVydelam.jsx";
import KonturBlock from "../components/KonturBlock.jsx";
import { useLegendy } from "../hooks/useLegendy.js";
import { useCan } from "../auth.jsx";
import OsvoenieBadge from "../components/OsvoenieBadge.jsx";
import { openScreen, useScreenParam } from "../nav.js";

/**
 * Экран "Делянки" (screens/plots/) — Этап 5 плана.
 *
 * Backend не переписывался: делянки/документы уже были полностью готовы в
 * lesovod_backend_stage2.zip (app/routers/delyanki.py, documents.py,
 * tasks.py — прямые обёртки над delyanka.py/webext.py). Здесь только
 * фронтенд поверх них, по паттерну Этапа 4 (api/client.js, DataTable,
 * Modal, Toast + pollTask — единый опрос BackgroundTasks).
 *
 * Перенесено 1:1 (см. __init__ PlotsScreen в screens/plots/screen_core.py):
 *   Список делянок (QTreeWidget, категории)      → список слева, GET /api/delyanki/
 *   "Показывать архивные" (QCheckBox)              → тот же чекбокс, фильтр на фронте
 *   Карточка делянки + вкладки Акт/Листок/Техкарта → Card справа + вкладки, те же подписи полей
 *   4 кнопки генерации (Акт/Техкарта/Листки/       → те же 4 кнопки, POST .../documents/*,
 *     Акт готовности лесосеки)                       статус — через pollTask(task_id)
 *   "Импорт МДО" (QFileDialog)                     → модалка с <input type="file" multiple>
 *   Пресеты комиссий (загрузить)                   → выпадающие списки, заполняют поля
 *   "В архив" / "Удалить"                           → те же две кнопки, с подтверждением
 *
 * Сознательно упрощено (по аналогии с "Сознательно упрощено" в STAGE4.md):
 *   1. Абрис (screens/plots/abris.py — QWebEngineView + JS-мост, отрисовка
 *      на канве через clipper.min.js/jspdf) — НЕ перенесён. Это отдельный
 *      canvas-редактор, а не форма; per решению в этом чате — отдельный шаг.
 *   2. "Сохранить как пресет" / "Удалить пресет" — есть только применение
 *      готового пресета (выпадающий список). Создание/удаление пресетов
 *      использовалось редко (десктоп: отдельные кнопки 💾/🗑 у каждой
 *      вкладки) — можно добавить тем же паттерном, что Settings.jsx, когда
 *      понадобится.
 *   3. Drag-and-drop файлов МДО прямо на список (DropListPanel в десктопе)
 *      — заменён обычной кнопкой + выбором файлов в модалке.
 */

const DOC_TYPE_LABELS = {
  akt: "Акт обследования",
  listok: "Листок сигнализации",
  tehkarta: "Технологическая карта",
  akt_gotovnosti: "Акт готовности лесосеки",
};

const DOC_ACTIONS = [
  { key: "akt", label: "Акт обследования", icon: "📄", path: (id) => `/delyanki/${id}/documents/akt` },
  { key: "tehkarty", label: "Технологическая карта", icon: "📋", path: (id) => `/delyanki/${id}/documents/tehkarty` },
  { key: "listki", label: "Листки сигнализации", icon: "🚨", path: (id) => `/delyanki/${id}/documents/listki` },
  { key: "akt-gotovnosti", label: "Акт готовности лесосеки", icon: "✅", path: (id) => `/delyanki/${id}/documents/akt-gotovnosti` },
];

/** "Должность; ФИО" по одной строке — тот же формат, что _parse_chleny_text
 * в screens/plots/screen_forms.py, чтобы поле выглядело одинаково в
 * десктопе и в вебе. */
function parseChleny(text) {
  return (text || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.includes(";")) {
        const [dolzhnost, fio] = line.split(";", 2);
        return { dolzhnost: dolzhnost.trim(), fio: (fio || "").trim() };
      }
      return { dolzhnost: "", fio: line };
    });
}

function formatChleny(list) {
  return (list || []).map((c) => (c.dolzhnost ? `${c.dolzhnost}; ${c.fio}` : c.fio)).join("\n");
}

function fieldsFromDelyanka(d) {
  return {
    sroki_rubki: d.sroki_rubki || "",
    prichiny: d.prichiny || "",
    vrediteli: d.vrediteli || "",
    meropriyatiya: d.meropriyatiya || "",
    predsedatel_dolzhnost: d.predsedatel_dolzhnost || "",
    predsedatel_fio: d.predsedatel_fio || "",
    chleny_text: formatChleny(d.chleny),
    listok_obnaruzhil_dolzhnost: d.listok_obnaruzhil_dolzhnost || "",
    listok_obnaruzhil_fio: d.listok_obnaruzhil_fio || "",
    listok_obnaruzhil_data: d.listok_obnaruzhil_data || "",
    listok_proveril_dolzhnost: d.listok_proveril_dolzhnost || "",
    listok_proveril_fio: d.listok_proveril_fio || "",
    listok_proveril_data: d.listok_proveril_data || "",
    listok_reshenie_dolzhnost: d.listok_reshenie_dolzhnost || "",
    listok_reshenie_fio: d.listok_reshenie_fio || "",
    utverdil_dolzhnost: d.utverdil_dolzhnost || "",
    utverdil_fio: d.utverdil_fio || "",
    sostavil_dolzhnost: d.sostavil_dolzhnost || "",
    sostavil_fio: d.sostavil_fio || "",
    master_lesa_fio: d.master_lesa_fio || "",
    brigadir_fio: d.brigadir_fio || "",
    tehkarta_chleny_text: formatChleny(d.tehkarta_chleny),
  };
}

function fieldsToPayload(form) {
  const { chleny_text, tehkarta_chleny_text, ...rest } = form;
  return {
    ...rest,
    chleny: parseChleny(chleny_text),
    tehkarta_chleny: parseChleny(tehkarta_chleny_text),
  };
}

function pluralizeVydel(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return "выдел";
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return "выдела";
  return "выделов";
}

function formatDate(s) {
  if (!s) return "—";
  return s.slice(0, 10).split("-").reverse().join(".");
}

/** Дата лесорубочного билета вводится как обычный текст "ДД.ММ.ГГГГ" (как и
 * все остальные даты в этом экране/актах — см. Inspection.jsx), а не через
 * <input type="date">: бэкенд (_split_date в osvidetelstvovanie_generator.py)
 * ждёт именно такой порядок, а нативный date-пикер отдал бы ISO ГГГГ-ММ-ДД.
 * Запятая (на многих раскладках/цифровых клавиатурах её набрать проще, чем
 * точку) автоматически считается точкой — просто для удобства ввода. */
function normalizeDateInput(value) {
  return value.replace(/,/g, ".");
}

/** Абрис — отдельный canvas-редактор (public/abris_tool.html, адаптированный
 * из abris_tool.html десктоп-версии: тот же инструмент, тот же движок
 * рисования/PDF-экспорта — заменён только "мост сохранения": вместо
 * QWebChannel/pyBridge — прямой fetch на наш backend, см. комментарий в
 * самом файле). Открывается в отдельной вкладке, а не встроенным
 * компонентом — инструмент самодостаточен (свой топбар/навигация) и не
 * рассчитан на то, чтобы жить внутри React-дерева. */
function openAbrisTool(item) {
  const label = `кв${item.kvartal || "?"}_выд${item.vydel || "?"}`;
  const params = new URLSearchParams({
    item_id: String(item.id),
    api_base: API_BASE_URL,
    label,
  });
  window.open(`/abris_tool.html?${params.toString()}`, "_blank");
}

/** Выпадающий список пресета — выбор сразу заполняет поля формы и
 * сбрасывается (пресет не "выбран навсегда", просто разовая подстановка,
 * как кнопка "📥 Загрузить" в десктопе). */
function PresetRow({ label, options, onApply, onDelete, onSaveNew }) {
  const [selected, setSelected] = useState("");
  const [draftName, setDraftName] = useState(null); // null — форма скрыта, "" — открыта, пусто

  const hasOptions = options && options.length > 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase">{label}</label>
        {draftName === null && (
          <button
            type="button"
            onClick={() => setDraftName("")}
            className="text-xs font-semibold text-pine hover:underline"
          >
            + Сохранить как пресет
          </button>
        )}
      </div>

      {hasOptions ? (
        <div className="flex items-center gap-2">
          <select
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              if (e.target.value) onApply(e.target.value);
            }}
            className="flex-1 bg-surface border border-border focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
          >
            <option value="" disabled>
              Выбрать и заполнить поля…
            </option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.nazvanie}
              </option>
            ))}
          </select>
          {selected && (
            <button
              type="button"
              title="Удалить пресет"
              onClick={() => {
                onDelete(selected);
                setSelected("");
              }}
              className="shrink-0 rounded-md border border-transparent px-2.5 py-2 text-muted-2 hover:border-error hover:text-error transition-colors"
            >
              ✕
            </button>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-2">Пресетов пока нет — заполните поля ниже и сохраните.</p>
      )}

      {draftName !== null && (
        <div className="mt-2 flex items-center gap-2">
          <input
            autoFocus
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && draftName.trim()) {
                onSaveNew(draftName.trim());
                setDraftName(null);
              }
              if (e.key === "Escape") setDraftName(null);
            }}
            placeholder="Название пресета"
            className="flex-1 bg-surface border border-border focus:border-pine focus:bg-surface rounded-md px-3.5 py-2 text-sm text-ink outline-none transition-colors"
          />
          <Button
            size="sm"
            variant="primary"
            disabled={!draftName.trim()}
            onClick={() => {
              onSaveNew(draftName.trim());
              setDraftName(null);
            }}
          >
            Сохранить
          </Button>
          <button
            type="button"
            onClick={() => setDraftName(null)}
            className="px-1 text-sm text-muted-2 hover:text-ink"
          >
            Отмена
          </button>
        </div>
      )}
    </div>
  );
}

function VydelChoiceModal({ open, candidates, question, onChoose }) {
  const [manual, setManual] = useState("");

  useEffect(() => {
    if (open) setManual("");
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={() => onChoose("")}
      title="Выбор главного выдела"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onChoose("")}>
            Отмена
          </Button>
          <Button variant="primary" onClick={() => onChoose(manual.trim())} disabled={!manual.trim()}>
            Указать вручную
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-base text-ink whitespace-pre-line">
          {question ||
            "В МДО указано несколько выделов сразу — выберите, какой считать главным (для сверки с таксацией). Остальные выделы сохранятся как есть в делянке."}
        </p>
        {candidates.length > 0 && (
          <div>
            <p className="text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
              Найденные номера
            </p>
            <div className="flex flex-wrap gap-2">
              {candidates.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => onChoose(c)}
                  className="px-3.5 py-2 rounded-md bg-mint-soft text-pine font-semibold text-sm hover:bg-mint"
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}
        <TextField
          label="Или ввести номер вручную"
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="например, 15"
        />
        <p className="text-faint text-xs">
          Отмена — главным станет первое найденное число ({candidates[0] || "—"}).
        </p>
      </div>
    </Modal>
  );
}

function ImportMdoModal({ open, onClose, onImported }) {
  const toast = useToast();
  const [files, setFiles] = useState([]);
  const [mergeIntoOne, setMergeIntoOne] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Блок C.2: пока backend ждёт ответ по составному выделу, здесь лежит
  // { question, candidates, resolve } — resolve передаётся в pollTask через
  // onNeedsVydelChoice ниже и разрешает промис ответом пользователя.
  const [vydelChoice, setVydelChoice] = useState(null);

  const reset = () => {
    setFiles([]);
    setMergeIntoOne(false);
    setVydelChoice(null);
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleNeedsVydelChoice = (payload) =>
    new Promise((resolve) => {
      setVydelChoice({ ...payload, resolve });
    });

  const submitVydelChoice = (value) => {
    vydelChoice?.resolve(value);
    setVydelChoice(null);
  };

  const handleSubmit = async () => {
    if (files.length === 0) return;
    setSubmitting(true);
    try {
      const formData = new FormData();
      files.forEach((f) => formData.append("files", f));
      const { task_id } = await api.upload("/delyanki/import-mdo", formData, {
        merge_into_one: mergeIntoOne,
      });
      const result = await pollTask(task_id, {
        timeoutMs: 10 * 60 * 1000,
        onNeedsVydelChoice: handleNeedsVydelChoice,
      });
      const created = result?.delyanka_ids?.length ?? 0;
      const notFound = result?.not_found_in_taxation?.length ?? 0;
      const errors = result?.errors ?? [];
      toast.show({
        tone: errors.length ? "warning" : "success",
        title: created ? `Создано делянок: ${created}` : "Импорт завершён",
        description:
          [
            notFound ? `Не найдено в таксации: ${notFound}` : null,
            errors.length ? `Ошибок при импорте: ${errors.length}` : null,
          ]
            .filter(Boolean)
            .join(" · ") || undefined,
      });
      if (errors.length) console.warn("МДО импорт — ошибки:", errors);
      reset();
      onClose();
      onImported();
    } catch (e) {
      toast.show({ tone: "danger", title: "Импорт МДО не удался", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Modal
        open={open}
        onClose={handleClose}
        title="Импорт из МДО"
        footer={
          <>
            <Button variant="ghost" onClick={handleClose} disabled={submitting}>
              Отмена
            </Button>
            <Button variant="primary" onClick={handleSubmit} loading={submitting} disabled={files.length === 0}>
              Импортировать
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <div>
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
              Файлы МДО (.rtf)
            </label>
            <input
              type="file"
              accept=".rtf"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
              className="w-full text-base text-ink file:mr-3 file:px-3.5 file:py-2 file:rounded-md file:border-0 file:bg-mint-soft file:text-pine file:font-semibold file:cursor-pointer"
            />
            {files.length > 0 && <p className="text-faint text-xs mt-1.5">Выбрано файлов: {files.length}</p>}
          </div>
          <label className="flex items-center gap-2 text-base text-ink cursor-pointer">
            <input
              type="checkbox"
              checked={mergeIntoOne}
              onChange={(e) => setMergeIntoOne(e.target.checked)}
              className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
            />
            Объединить все файлы в одну делянку (несколько выделов)
          </label>
          <p className="text-faint text-xs">По умолчанию каждый файл МДО становится отдельной делянкой.</p>
        </div>
      </Modal>
      <VydelChoiceModal
        open={!!vydelChoice}
        candidates={vydelChoice?.candidates || []}
        question={vydelChoice?.question}
        onChoose={submitVydelChoice}
      />
    </>
  );
}

/** "Сделать активной" (Блок доработки: делянки из МДО-импорта до этого шага
 * висят статусом 'черновик' и не участвуют в расходе/освидетельствовании —
 * см. status= фильтр в GET /api/delyanki/ и /api/inspection/). Номер и дата
 * лесорубочного билета обязательны — без них backend откажет (400) — и они
 * же потом сами подставляются в Акт освидетельствования (генератор читает
 * их прямо с делянки, отдельно вводить в Inspection не нужно). */
function ActivateDelyankaModal({ open, onClose, onActivated, delyankaId, initialNomer, initialData }) {
  const toast = useToast();
  const [nomer, setNomer] = useState("");
  const [data, setData] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setNomer(initialNomer || "");
      setData(initialData || "");
    }
  }, [open, initialNomer, initialData]);

  const canSave = nomer.trim() !== "" && data.trim() !== "";

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSubmit = async () => {
    if (!canSave) return;
    setSubmitting(true);
    try {
      await api.post(`/delyanki/${delyankaId}/activate`, {
        nomer_lesorubochnogo_bileta: nomer.trim(),
        data_lesorubochnogo_bileta: data.trim(),
      });
      toast.show({ tone: "success", title: "Делянка активирована" });
      onActivated();
      onClose();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось активировать", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Сделать активной"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Отмена
          </Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting} disabled={!canSave}>
            Сохранить
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-base text-ink">
          Делянка станет активной и появится в расходе и актах освидетельствования. Укажите номер и дату
          лесорубочного билета — оба поля обязательны.
        </p>
        <TextField label="№ лесорубочного билета" value={nomer} onChange={(e) => setNomer(e.target.value)} />
        <TextField
          label="Дата лесорубочного билета"
          placeholder="ДД.ММ.ГГГГ"
          value={data}
          onChange={(e) => setData(normalizeDateInput(e.target.value))}
        />
      </div>
    </Modal>
  );
}

const STATUS_RABOT_OPTIONS = ["ожидает", "в работе", "выполнено"];

// Вид рубки выдела делянки — цвет на карте (QGIS, приложение) при окраске
// «по виду рубки». Пусто — определяется по МДО («Авто: …»).
function VidRubkiSelect({ item, vidy, onChange }) {
  const known = vidy.filter((v) => v.kod);
  const avto = known.find((v) => v.kod === item.vid_rubki_avto_kod);
  const current = known.find((v) => v.kod === item.vid_rubki_kod) || (!item.vid_rubki_kod ? avto : null);
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-block w-3 h-3 rounded-full border border-border shrink-0"
        style={{ background: current ? current.color : "#9e9e9e" }}
      />
      <select
        value={item.vid_rubki_kod || ""}
        onChange={(e) => onChange(e.target.value)}
        className="bg-surface border border-border focus:border-pine rounded-lg px-2 h-8 text-[12.5px] text-ink outline-none max-w-[220px]"
        title="Цвет лесосеки на карте при окраске по виду рубки / виду пользования"
      >
        <option value="">
          {avto ? `Авто по МДО: ${avto.kod} — ${avto.label}` : item.gruppa_avto ? `Авто: ${item.gruppa_avto}` : "Авто: не определён"}
        </option>
        {known.map((v) => (
          <option key={v.kod} value={v.kod}>{v.kod} — {v.label}</option>
        ))}
      </select>
    </div>
  );
}

// Чек-лист готовности делянки (анализ удобства 01.10.2026): карточка
// длинная, и непонятно, что уже заполнено, а что нет.
function gotovnost(delyanka, items, documents) {
  const est = (t) => documents.some((d) => d.doc_type === t);
  const vse = (f) => items.length > 0 && items.every(f);
  return [
    ["Лесорубочный билет", !!(delyanka.nomer_lesorubochnogo_bileta && delyanka.data_lesorubochnogo_bileta)],
    ["Комиссия", !!delyanka.predsedatel_fio],
    ["Контур", vse((it) => !!it.geom_geojson)],
    ["Абрис", vse((it) => !!(it.abris_image_path || it.abris_coords_json))],
    ["Акт обследования", est("akt")],
    ["Техкарта", est("tehkarta")],
    ["Акт готовности", est("akt_gotovnosti")],
    ["Сроки заготовки/вывозки", !!(delyanka.srok_okonchaniya_zagotovki && delyanka.srok_okonchaniya_vyvozki)],
  ];
}

function GotovnostChecklist({ delyanka, items, documents }) {
  const punkty = gotovnost(delyanka, items, documents);
  const gotovo = punkty.filter(([, ok]) => ok).length;
  return (
    <div className="rounded-[10px] bg-surface-alt px-3 py-2.5">
      <div className="text-[11.5px] text-muted-2 mb-1.5">
        Готовность делянки: {gotovo} из {punkty.length}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {punkty.map(([label, ok]) => (
          <span key={label} className={["text-[12.5px]", ok ? "text-pine" : "text-muted"].join(" ")}>
            {ok ? "✓" : "○"} {label}
          </span>
        ))}
      </div>
    </div>
  );
}

function PlotDetail({ delyankaId, onListChanged }) {
  const toast = useToast();
  const can = useCan();
  const [loading, setLoading] = useState(true);
  const [delyanka, setDelyanka] = useState(null);
  const [items, setItems] = useState([]);
  const [form, setForm] = useState(null);
  const [tab, setTab] = useState("akt");
  const [saving, setSaving] = useState(false);
  const [busyAction, setBusyAction] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [presets, setPresets] = useState({ komissiya: [], listok: [], tehkarta: [] });
  const [activateModalOpen, setActivateModalOpen] = useState(false);
  const [osvoenie, setOsvoenie] = useState(null);

  useEffect(() => {
    api.get(`/raskhod/delyanki/${delyankaId}/osvoenie`).then((r) => setOsvoenie(r?.itogo || null)).catch(() => setOsvoenie(null));
  }, [delyankaId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get(`/delyanki/${delyankaId}`);
      setDelyanka(res.delyanka);
      setItems(res.items || []);
      const f = fieldsFromDelyanka(res.delyanka);
      // Лесничий из «Настроек» сам подставляется туда, где обычно пишется
      // он: «Составил» техкарты и «Решение» листка (если ещё пусто).
      try {
        const l = await api.get("/settings/lesnichiy");
        if (l?.fio) {
          if (!f.sostavil_fio) Object.assign(f, { sostavil_fio: l.fio, sostavil_dolzhnost: f.sostavil_dolzhnost || l.dolzhnost || "" });
          if (!f.listok_reshenie_fio) Object.assign(f, { listok_reshenie_fio: l.fio, listok_reshenie_dolzhnost: f.listok_reshenie_dolzhnost || l.dolzhnost || "" });
        }
      } catch {
        // необязательно
      }
      setForm(f);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить делянку", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [delyankaId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Статус работ по выделу делянки — цвет на карте приложения
  // ("в работе" ставится сам по первому отчёту, "выполнено" — здесь).
  const [chastiItem, setChastiItem] = useState(null);
  const saveChasti = async (chasti) => {
    try {
      await api.put("/tekushchie-izmeneniya/chasti", { istochnik: "d", id: chastiItem.id, chasti });
      setChastiItem(null);
      toast.show({ tone: "success", title: "Площадь по выделам сохранена" });
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    }
  };

  const legendy = useLegendy();
  const updateItemVidRubki = async (item, kod) => {
    try {
      await api.patch(`/delyanki/items/${item.id}`, { vid_rubki_kod: kod });
      setItems((prev) => prev.map((it) => (it.id === item.id ? { ...it, vid_rubki_kod: kod || null } : it)));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сменить вид рубки", description: e.message });
    }
  };

  const updateItemStatus = async (item, status) => {
    try {
      await api.patch(`/delyanki/items/${item.id}`, { status_rabot: status });
      setItems((prev) => prev.map((it) => (it.id === item.id ? { ...it, status_rabot: status } : it)));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сменить статус", description: e.message });
    }
  };

  const loadDocuments = useCallback(async () => {
    setDocsLoading(true);
    try {
      const docs = await api.get("/documents/", { delyanka_id: delyankaId });
      setDocuments(docs);
    } catch (e) {
      // список документов необязателен для остальной работы экрана
    } finally {
      setDocsLoading(false);
    }
  }, [delyankaId]);

  useEffect(() => {
    load();
    loadDocuments();
  }, [load, loadDocuments]);

  // Абрис рисуется в отдельной вкладке (public/abris_tool.html — не
  // встроенный React-компонент, см. openAbrisTool ниже), поэтому об
  // успешном сохранении узнаём через BroadcastChannel, а не await/onSaved.
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel("lesovod-abris");
    channel.onmessage = () => load();
    return () => channel.close();
  }, [load]);

  const reloadPresets = useCallback(async () => {
    try {
      const [komissiya, listok, tehkarta] = await Promise.all([
        api.get("/delyanki/presets/komissiya"),
        api.get("/delyanki/presets/listok"),
        api.get("/delyanki/presets/tehkarta"),
      ]);
      setPresets({ komissiya, listok, tehkarta });
    } catch {
      // пресеты необязательны для работы экрана
    }
  }, []);

  useEffect(() => {
    reloadPresets();
  }, [reloadPresets]);

  // Сохранение/удаление пресетов (Блок 5, PLAN_DORABOTKI, п. "создание/
  // удаление пресетов") — эндпоинты POST/DELETE .../presets/... в
  // app/routers/delyanki.py уже были готовы, здесь только фронтенд поверх
  // них. Сохраняем ровно те поля формы, которые apply*Preset ниже кладёт
  // обратно — так пара "сохранить → применить" остаётся согласованной.
  const savePresetOrShowError = async (path, nazvanie, fields) => {
    try {
      await api.post(path, { nazvanie, fields });
      toast.show({ tone: "success", title: "Пресет сохранён" });
      reloadPresets();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить пресет", description: e.message });
    }
  };

  const deletePresetOrShowError = async (path) => {
    try {
      await api.delete(path);
      toast.show({ tone: "success", title: "Пресет удалён" });
      reloadPresets();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить пресет", description: e.message });
    }
  };

  const saveKomissiyaPreset = (nazvanie) =>
    savePresetOrShowError("/delyanki/presets/komissiya", nazvanie, {
      predsedatel_dolzhnost: form.predsedatel_dolzhnost || "",
      predsedatel_fio: form.predsedatel_fio || "",
      chleny: parseChleny(form.chleny_text),
    });
  // Комиссия из пресета Инспекции (общий справочник) удаляется там же,
  // где сохранена, — здесь у неё нет id.
  const deleteKomissiyaPreset = (id) =>
    id == null
      ? toast.show({ tone: "warning", title: "Этот состав сохранён в Инспекции", description: "Удалить его можно в акте освидетельствования." })
      : deletePresetOrShowError(`/delyanki/presets/komissiya/${id}`);

  const saveListokPreset = (nazvanie) =>
    savePresetOrShowError("/delyanki/presets/listok", nazvanie, {
      obnaruzhil_dolzhnost: form.listok_obnaruzhil_dolzhnost || "",
      obnaruzhil_fio: form.listok_obnaruzhil_fio || "",
      proveril_dolzhnost: form.listok_proveril_dolzhnost || "",
      proveril_fio: form.listok_proveril_fio || "",
      reshenie_dolzhnost: form.listok_reshenie_dolzhnost || "",
      reshenie_fio: form.listok_reshenie_fio || "",
    });
  const deleteListokPreset = (id) => deletePresetOrShowError(`/delyanki/presets/listok/${id}`);

  const saveTehkartaPreset = (nazvanie) =>
    savePresetOrShowError("/delyanki/presets/tehkarta", nazvanie, {
      sostavil_dolzhnost: form.sostavil_dolzhnost || "",
      sostavil_fio: form.sostavil_fio || "",
      utverdil_dolzhnost: form.utverdil_dolzhnost || "",
      utverdil_fio: form.utverdil_fio || "",
      master_lesa_fio: form.master_lesa_fio || "",
      brigadir_fio: form.brigadir_fio || "",
      tehkarta_chleny: parseChleny(form.tehkarta_chleny_text),
    });
  const deleteTehkartaPreset = (id) => deletePresetOrShowError(`/delyanki/presets/tehkarta/${id}`);

  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const applyKomissiyaPreset = (id) => {
    const preset = presets.komissiya.find((p) => String(p.id) === id);
    if (!preset) return;
    setForm((f) => ({
      ...f,
      predsedatel_dolzhnost: preset.predsedatel_dolzhnost || "",
      predsedatel_fio: preset.predsedatel_fio || "",
      chleny_text: formatChleny(preset.chleny),
    }));
  };
  const applyListokPreset = (id) => {
    const preset = presets.listok.find((p) => String(p.id) === id);
    if (!preset) return;
    setForm((f) => ({
      ...f,
      listok_obnaruzhil_dolzhnost: preset.obnaruzhil_dolzhnost || "",
      listok_obnaruzhil_fio: preset.obnaruzhil_fio || "",
      listok_proveril_dolzhnost: preset.proveril_dolzhnost || "",
      listok_proveril_fio: preset.proveril_fio || "",
      listok_reshenie_dolzhnost: preset.reshenie_dolzhnost || "",
      listok_reshenie_fio: preset.reshenie_fio || "",
    }));
  };
  const applyTehkartaPreset = (id) => {
    const preset = presets.tehkarta.find((p) => String(p.id) === id);
    if (!preset) return;
    setForm((f) => ({
      ...f,
      sostavil_dolzhnost: preset.sostavil_dolzhnost || "",
      sostavil_fio: preset.sostavil_fio || "",
      utverdil_dolzhnost: preset.utverdil_dolzhnost || "",
      utverdil_fio: preset.utverdil_fio || "",
      master_lesa_fio: preset.master_lesa_fio || "",
      brigadir_fio: preset.brigadir_fio || "",
      tehkarta_chleny_text: formatChleny(preset.tehkarta_chleny),
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.patch(`/delyanki/${delyankaId}`, fieldsToPayload(form));
      toast.show({ tone: "success", title: "Данные сохранены" });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  const runDocAction = async (action) => {
    setBusyAction(action.key);
    try {
      const { task_id } = await api.post(action.path(delyankaId));
      await pollTask(task_id, { timeoutMs: 10 * 60 * 1000 });
      toast.show({
        tone: "success",
        title: `${action.label} — готово`,
        description: "Файл появился в списке документов ниже.",
      });
      await loadDocuments();
    } catch (e) {
      toast.show({ tone: "danger", title: `${action.label} — ошибка`, description: e.message });
    } finally {
      setBusyAction(null);
    }
  };

  const handleArchive = async () => {
    setBusyAction("archive");
    try {
      await api.post(`/delyanki/${delyankaId}/archive`);
      toast.show({ tone: "success", title: "Делянка перемещена в архив" });
      onListChanged();
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось архивировать", description: e.message });
    } finally {
      setBusyAction(null);
    }
  };

  const handleDelete = async () => {
    const name = delyanka?.nazvanie || `делянку №${delyankaId}`;
    if (!window.confirm(`Удалить ${name} вместе со всеми выделами и нарядами? Она попадёт в «Корзину» (Прочее → Корзина), оттуда её можно вернуть в течение 30 дней.`)) return;
    setBusyAction("delete");
    try {
      await api.delete(`/delyanki/${delyankaId}`);
      toast.show({ tone: "success", title: "Делянка удалена", description: "Вернуть можно в «Корзине» 30 дней" });
      onListChanged(true);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить", description: e.message });
      setBusyAction(null);
    }
  };

  const handleDeleteDocument = async (doc) => {
    if (!window.confirm(`Удалить файл «${doc.file_name}»?`)) return;
    try {
      await api.delete(`/documents/${doc.id}`);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить документ", description: e.message });
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

  const TABS = [
    { key: "akt", label: "Акт" },
    { key: "listok", label: "Листок" },
    { key: "tehkarta", label: "Техкарта" },
  ];

  return (
    <Card>
      <div className="flex flex-col gap-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-ui font-extrabold text-base text-pine truncate" style={{ fontSize: 16 }}>
                {delyanka.nazvanie || `Делянка №${delyanka.id}`}
              </h2>
              <StatusBadge status={delyanka.status} />
              {osvoenie?.pct != null && <OsvoenieBadge pct={osvoenie.pct} level={osvoenie.level} suffix=" освоено" />}
            </div>
            <p className="font-mono text-[10.5px] text-muted-2 mt-[3px]">
              {items.length} {pluralizeVydel(items.length)} · создана {formatDate(delyanka.created_at)}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Перекрёстные переходы (анализ удобства 01.10.2026): та же
                делянка сразу открывается в «Расходе» и «Инспекции». */}
            <Button variant="ghost" size="sm" onClick={() => openScreen("raskhod", { d: delyanka.id })}>
              📊 Расход
            </Button>
            <Button variant="ghost" size="sm" onClick={() => openScreen("inspection", { d: delyanka.id })}>
              🔍 Инспекция
            </Button>
            {delyanka.status !== "активна" && can("delyanka.edit") && (
              <Button
                variant="primary"
                size="sm"
                disabled={busyAction !== null}
                onClick={() => setActivateModalOpen(true)}
              >
                Сделать активной
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              loading={busyAction === "archive"}
              disabled={delyanka.status === "архив" || (busyAction !== null && busyAction !== "archive")}
              onClick={handleArchive}
            >
              В архив
            </Button>
            {can("delyanka.delete") && (
              <Button
                variant="danger"
                size="sm"
                loading={busyAction === "delete"}
                disabled={busyAction !== null && busyAction !== "delete"}
                onClick={handleDelete}
              >
                Удалить
              </Button>
            )}
          </div>
        </div>

        <GotovnostChecklist delyanka={delyanka} items={items} documents={documents} />

        <Modal open={!!chastiItem} onClose={() => setChastiItem(null)} title="Площадь по выделам" size="lg">
          {chastiItem && (
            <ChastiForm info={chastiInfo(chastiItem)} onSave={saveChasti} onCancel={() => setChastiItem(null)} />
          )}
        </Modal>

        <ActivateDelyankaModal
          open={activateModalOpen}
          onClose={() => setActivateModalOpen(false)}
          onActivated={() => {
            onListChanged();
            load();
          }}
          delyankaId={delyankaId}
          initialNomer={delyanka.nomer_lesorubochnogo_bileta}
          initialData={delyanka.data_lesorubochnogo_bileta}
        />

        {items.length > 0 && (
          <div className="border border-border rounded-[10px] overflow-hidden overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-surface-alt border-b border-border text-left text-muted-2 text-[11.5px] font-medium">
                  <th className="px-3 py-2">Квартал</th>
                  <th className="px-3 py-2">Выдел</th>
                  <th className="px-3 py-2">Категория</th>
                  <th className="px-3 py-2">Площадь, га</th>
                  <th className="px-3 py-2">Состав</th>
                  <th className="px-3 py-2">Статус работ</th>
                  <th className="px-3 py-2">Вид рубки</th>
                  <th className="px-3 py-2">По выделам</th>
                  <th className="px-3 py-2">Абрис</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id} className="border-b border-border last:border-b-0">
                    <td className="px-3 py-2 text-ink">{it.kvartal || "—"}</td>
                    <td className="px-3 py-2 text-ink">{it.vydel || "—"}</td>
                    <td className="px-3 py-2 text-ink">{it.kategoriya_lesov || "—"}</td>
                    <td className="px-3 py-2 text-ink">{it.ploshad || "—"}</td>
                    <td className="px-3 py-2 text-ink">{it.sostav || "—"}</td>
                    <td className="px-3 py-2">
                      <select
                        value={it.status_rabot || "ожидает"}
                        onChange={(e) => updateItemStatus(it, e.target.value)}
                        className="bg-surface border border-border focus:border-pine rounded-lg px-2 h-8 text-[12.5px] text-ink outline-none"
                        title="Цвет выдела делянки на карте в приложении"
                      >
                        {STATUS_RABOT_OPTIONS.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
                      <VidRubkiSelect item={it} vidy={legendy.vidy_rubok} onChange={(kod) => updateItemVidRubki(it, kod)} />
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {(vydelyIz(it.vydel).length > 1 || it.chasti_json) ? (
                        <button
                          onClick={() => setChastiItem(it)}
                          title="Лесосека в нескольких выделах: площадь по каждому (для ведомостей текущих изменений)"
                          className={`text-[12px] font-semibold rounded-lg px-2.5 py-1 ${it.chasti_json ? "text-pine bg-mint-soft hover:bg-mint" : "text-oak bg-surface-alt hover:bg-hover border border-oak"}`}
                        >
                          {it.chasti_json ? "Задано" : "Разбить площадь"}
                        </button>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button
                        onClick={() => openAbrisTool(it)}
                        className="text-[12px] font-semibold text-pine bg-mint-soft hover:bg-mint rounded-lg px-2.5 py-1"
                      >
                        {it.abris_image_path ? "Открыть/перерисовать" : "Нарисовать"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {items.map((it) => (
          <KonturBlock
            // абрис при сохранении пишет и контур — после него перечитываем
            key={`${it.id}-${it.abris_image_path || ""}`}
            path={`/delyanki/items/${it.id}/kontur`}
            title={`Контур лесосеки${items.length > 1 ? ` (кв. ${it.kvartal || "?"}, выд. ${it.vydel || "?"})` : ""} — на карте лесосека будет показана им, абрис откроется с ним`}
          />
        ))}

        <div className="flex flex-wrap gap-2">
          {DOC_ACTIONS.map((action) => (
            <Button
              key={action.key}
              variant="secondary"
              icon={<span>{action.icon}</span>}
              loading={busyAction === action.key}
              disabled={busyAction !== null && busyAction !== action.key}
              onClick={() => runDocAction(action)}
            >
              {action.label}
            </Button>
          ))}
        </div>

        <div>
          <div className="flex gap-1 border-b border-border mb-4">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={[
                  "px-3.5 py-2 text-[13.5px] font-bold border-b-2 -mb-px transition-colors",
                  tab === t.key ? "border-pine text-pine" : "border-transparent text-muted hover:text-pine",
                ].join(" ")}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "akt" && (
            <div className="flex flex-col gap-4">
              <TextAreaField label="Причины рубки" rows={2} value={form.prichiny} onChange={setField("prichiny")} />
              <TextAreaField
                label="Вредители / болезни"
                rows={2}
                value={form.vrediteli}
                onChange={setField("vrediteli")}
              />
              <TextAreaField
                label="Мероприятия"
                rows={2}
                value={form.meropriyatiya}
                onChange={setField("meropriyatiya")}
              />
              <TextField label="Сроки рубки" value={form.sroki_rubki} onChange={setField("sroki_rubki")} />
              <PresetRow
                label="Пресет комиссии"
                options={presets.komissiya}
                onApply={applyKomissiyaPreset}
                onSaveNew={saveKomissiyaPreset}
                onDelete={deleteKomissiyaPreset}
              />
              <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(220px,1fr))]">
                <TextField
                  label="Председатель, должность"
                  value={form.predsedatel_dolzhnost}
                  onChange={setField("predsedatel_dolzhnost")}
                />
                <TextField label="Председатель, ФИО" value={form.predsedatel_fio} onChange={setField("predsedatel_fio")} />
              </div>
              <TextAreaField
                label="Члены комиссии"
                rows={3}
                value={form.chleny_text}
                onChange={setField("chleny_text")}
                hint="По одному на строку: Должность; ФИО"
              />
            </div>
          )}

          {tab === "listok" && (
            <div className="flex flex-col gap-4">
              <PresetRow
                label="Пресет комиссии Листка"
                options={presets.listok}
                onApply={applyListokPreset}
                onSaveNew={saveListokPreset}
                onDelete={deleteListokPreset}
              />
              <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
                <TextField
                  label="Обнаружил, должность"
                  value={form.listok_obnaruzhil_dolzhnost}
                  onChange={setField("listok_obnaruzhil_dolzhnost")}
                />
                <TextField
                  label="Обнаружил, ФИО"
                  value={form.listok_obnaruzhil_fio}
                  onChange={setField("listok_obnaruzhil_fio")}
                />
                <TextField
                  label="Обнаружил, дата"
                  placeholder="ДД.ММ.ГГГГ"
                  value={form.listok_obnaruzhil_data}
                  onChange={setField("listok_obnaruzhil_data")}
                />
              </div>
              <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
                <TextField
                  label="Проверил, должность"
                  value={form.listok_proveril_dolzhnost}
                  onChange={setField("listok_proveril_dolzhnost")}
                />
                <TextField
                  label="Проверил, ФИО"
                  value={form.listok_proveril_fio}
                  onChange={setField("listok_proveril_fio")}
                />
                <TextField
                  label="Проверил, дата"
                  placeholder="ДД.ММ.ГГГГ"
                  value={form.listok_proveril_data}
                  onChange={setField("listok_proveril_data")}
                />
              </div>
              <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(220px,1fr))]">
                <TextField
                  label="Принял решение, должность"
                  value={form.listok_reshenie_dolzhnost}
                  onChange={setField("listok_reshenie_dolzhnost")}
                />
                <TextField
                  label="Принял решение, ФИО"
                  value={form.listok_reshenie_fio}
                  onChange={setField("listok_reshenie_fio")}
                />
              </div>
            </div>
          )}

          {tab === "tehkarta" && (
            <div className="flex flex-col gap-4">
              <PresetRow
                label="Пресет комиссии Техкарты"
                options={presets.tehkarta}
                onApply={applyTehkartaPreset}
                onSaveNew={saveTehkartaPreset}
                onDelete={deleteTehkartaPreset}
              />
              <div className="grid gap-3.5 grid-cols-[repeat(auto-fill,minmax(220px,1fr))]">
                <TextField label="Утвердил, должность" value={form.utverdil_dolzhnost} onChange={setField("utverdil_dolzhnost")} />
                <TextField label="Утвердил, ФИО" value={form.utverdil_fio} onChange={setField("utverdil_fio")} />
                <TextField label="Составил, должность" value={form.sostavil_dolzhnost} onChange={setField("sostavil_dolzhnost")} />
                <TextField label="Составил, ФИО" value={form.sostavil_fio} onChange={setField("sostavil_fio")} />
                <TextField label="Мастер леса, ФИО" value={form.master_lesa_fio} onChange={setField("master_lesa_fio")} />
                <TextField label="Бригадир, ФИО" value={form.brigadir_fio} onChange={setField("brigadir_fio")} />
              </div>
              <TextAreaField
                label="Члены комиссии (Акт готовности)"
                rows={3}
                value={form.tehkarta_chleny_text}
                onChange={setField("tehkarta_chleny_text")}
                hint="По одному на строку: Должность; ФИО"
              />
            </div>
          )}
        </div>

        <div>
          <Button variant="primary" onClick={handleSave} loading={saving}>
            Сохранить данные
          </Button>
        </div>

        <div>
          <h3 className="font-mono text-[10.5px] uppercase tracking-[.1em] text-muted-2 mb-2">документы делянки</h3>
          <DataTable
            loading={docsLoading}
            columns={[
              { key: "doc_type", header: "Тип", render: (d) => DOC_TYPE_LABELS[d.doc_type] || d.doc_type },
              { key: "file_name", header: "Файл" },
              { key: "status", header: "Статус", render: (d) => <StatusBadge status={d.status} /> },
              { key: "created_at", header: "Создан" },
              {
                key: "actions",
                header: "",
                render: (d) => (
                  <div className="flex items-center gap-3">
                    {d.status === "готов" && (
                      <a
                        href={`${API_BASE_URL}/documents/${d.id}/download`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-pine font-semibold hover:text-pine-hover"
                      >
                        Скачать
                      </a>
                    )}
                    <button onClick={() => handleDeleteDocument(d)} className="text-error font-semibold hover:opacity-80">
                      Удалить
                    </button>
                  </div>
                ),
              },
            ]}
            rows={documents}
            emptyTitle="Документов ещё нет"
            emptyDescription="Сгенерируйте Акт, Техкарту, Листки или Акт готовности кнопками выше."
          />
        </div>
      </div>
    </Card>
  );
}

export default function Plots() {
  const toast = useToast();
  const [delyanki, setDelyanki] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  // Выбранная делянка — в адресе (#/plots?d=5): переживает F5, ссылку
  // можно переслать.
  const [selectedParam, setSelectedParam] = useScreenParam("plots", "d");
  const selectedId = selectedParam ? Number(selectedParam) : null;
  const setSelectedId = (id) => setSelectedParam(id ?? "");
  const [importOpen, setImportOpen] = useState(false);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.get("/delyanki/");
      setDelyanki(rows);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить делянки", description: e.message });
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadList();
  }, [loadList]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return delyanki
      .filter((d) => showArchived || d.status !== "архив")
      .filter((d) => !q || (d.nazvanie || "").toLowerCase().includes(q));
  }, [delyanki, showArchived, search]);

  const handleListChanged = (removed) => {
    if (removed) setSelectedId(null);
    loadList();
  };

  return (
    <div className="p-[18px] flex flex-wrap gap-[14px] items-start">
      <Card padding={false} className="flex flex-col" style={{ flex: "1 1 260px", maxWidth: 380 }}>
        <div className="p-3.5 flex flex-col gap-2.5 border-b border-border">
          <Button variant="primary" onClick={() => setImportOpen(true)}>
            ↑ Импорт МДО (.rtf)
          </Button>
          {/* Импорт слоя из QGIS (самостоятельный слой, не создание делянок,
              см. app/routers/map.py: /import-layer) жил на экране "Живая
              карта" (LiveMap.jsx) — экран убран из меню по решению
              пользователя (карты ведутся в самом QGIS), backend-эндпоинт
              не трогали. */}
          <TextField placeholder="Поиск: название, квартал…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
              className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
            />
            Показывать архивные
          </label>
        </div>

        <div className="flex-1 overflow-y-auto max-h-[calc(100vh-280px)] p-2.5">
          {loading ? (
            <div className="p-5 flex justify-center">
              <div className="h-5 w-5 rounded-full border-2 border-pine border-t-transparent animate-spin" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-3">
              <EmptyState
                icon="🗺️"
                title="Делянок пока нет"
                description="Импортируйте файл МДО, чтобы создать первую делянку."
              />
            </div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {filtered.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => setSelectedId(d.id)}
                    className={[
                      "w-full text-left px-3 py-2.5 rounded-[10px] border transition-colors",
                      selectedId === d.id ? "bg-mint-soft border-pine" : "border-border bg-surface hover:bg-hover",
                    ].join(" ")}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13.5px] font-semibold text-ink">{d.nazvanie || `Делянка №${d.id}`}</span>
                      <StatusBadge status={d.status} dot={false} />
                    </div>
                    <div className="font-mono text-[10.5px] text-muted-2 mt-0.5 truncate">
                      {d.n_items} {pluralizeVydel(d.n_items)}
                      {d.kategorii ? ` · ${d.kategorii}` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <div className="min-w-0" style={{ flex: "2 1 420px" }}>
        {selectedId ? (
          <PlotDetail key={selectedId} delyankaId={selectedId} onListChanged={handleListChanged} />
        ) : (
          <Card>
            <EmptyState
              icon="🗺️"
              title="Выберите делянку из списка"
              description="Или импортируйте новую из файла МДО (.rtf) — кнопка слева."
            />
          </Card>
        )}
      </div>

      <ImportMdoModal open={importOpen} onClose={() => setImportOpen(false)} onImported={loadList} />
    </div>
  );
}
