import React, { useCallback, useEffect, useRef, useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { api, API_BASE_URL } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";

/**
 * pages/Documents.jsx — Этап 5 плана переноса, часть 2 (фронтенд).
 *
 * Глобальный экран "Документы" поверх /api/documents (backend доработан
 * в части 1: фильтры created_by/date_from/date_to, file_size в ответе,
 * POST /api/documents/bulk-delete, POST /api/documents/bulk-zip). В
 * отличие от списка документов внутри карточки делянки (pages/Plots.jsx,
 * Этап 4) — здесь таблица сразу по ВСЕМ делянкам, с фильтрами и панелью
 * массовых действий, как и было задумано в самом плане переноса.
 *
 * Опрос: пока в списке есть хоть один документ в статусе "в процессе"/
 * "в очереди", страница раз в 2 секунды перезапрашивает список и сверяет
 * статусы построчно — как только строка переходит в "готов", показывается
 * Toast с кнопкой "Скачать" (см. requestDownload). Отдельного task_id на
 * документ API не отдаёт, поэтому опрашивается сам список документов, а
 * не /api/tasks/{id} — с тем же результатом для пользователя.
 */

const DOC_TYPE_LABELS = {
  akt: "Акт обследования",
  listok: "Листок сигнализации",
  tehkarta: "Технологическая карта",
  akt_gotovnosti: "Акт готовности лесосеки",
  spravka: "Справка",
  akt_osvidetelstvovaniya: "Акт освидетельствования",
  blank_akt: "Бланк акта",
  raskhod_export: "Экспорт книги расхода",
  forest_map: "Карта леса",
  uhody_proba_word: "Ведомость пробы рубок ухода (Word)",
  uhody_proba_excel: "Ведомость пробы рубок ухода (Excel)",
};

function docTypeLabel(t) {
  return DOC_TYPE_LABELS[t] || t;
}

function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

const PENDING_STATUSES = new Set(["в процессе", "в очереди"]);

// Документ доступен для скачивания/просмотра/отправки и в готовом, и в
// заархивированном статусе (пункт 1.4 TODO_DOMIGRACII.md) — архивация лишь
// перекладывает файл, а не прячет его от того, кто уже знает делянку.
const DOWNLOADABLE_STATUSES = new Set(["готов", "архив"]);

async function downloadBlob(path, filename) {
  const token = localStorage.getItem("lesovod_token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE_URL}${path}`, { headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Ошибка сервера (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Расширения, которые бэкенд (mdo_parser.PDF_CONVERTIBLE_EXTENSIONS) умеет
// превращать в PDF для предпросмотра — держим тот же список на фронте,
// чтобы не показывать кнопку "Просмотр" там, где сервер всё равно ответит
// 415. .pdf сюда не входит отдельно: он поддержан всегда (сервер отдаёт
// такой файл как есть, без конвертации).
const PREVIEWABLE_EXTENSIONS = new Set([
  ".pdf", ".docx", ".doc", ".odt", ".rtf", ".xlsx", ".xls", ".ods",
]);

function isPreviewable(fileName) {
  const dot = fileName.lastIndexOf(".");
  if (dot === -1) return false;
  return PREVIEWABLE_EXTENSIONS.has(fileName.slice(dot).toLowerCase());
}

async function fetchPreviewBlob(documentId) {
  const token = localStorage.getItem("lesovod_token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE_URL}/documents/${documentId}/preview`, { headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Ошибка сервера (${res.status})`);
  }
  return res.blob();
}

async function downloadZip(ids) {
  const token = localStorage.getItem("lesovod_token");
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE_URL}/documents/bulk-zip`, {
    method: "POST",
    headers,
    body: JSON.stringify({ ids }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Ошибка сервера (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "documents.zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function Documents() {
  const toast = useToast();

  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [authors, setAuthors] = useState([]);
  const [selection, setSelection] = useState([]);
  const [deleteConfirm, setDeleteConfirm] = useState(null); // { ids } | null
  const [preview, setPreview] = useState(null); // { fileName, loading, error, url } | null

  const [filters, setFilters] = useState({
    doc_type: "",
    status: "",
    created_by: "",
    date_from: "",
    date_to: "",
  });

  const statusesRef = useRef({}); // id -> предыдущий статус, для детекта перехода

  const load = useCallback(async () => {
    const params = Object.fromEntries(
      Object.entries(filters).filter(([, v]) => v !== "")
    );
    const rows = await api.get("/documents/", params);

    // Сверяем со старыми статусами: если что-то было "в процессе"/"в очереди"
    // и стало "готов" или "ошибка" — покажем тост, не дожидаясь клика.
    for (const row of rows) {
      const prevStatus = statusesRef.current[row.id];
      if (prevStatus && PENDING_STATUSES.has(prevStatus) && row.status === "готов") {
        toast.show({
          tone: "success",
          title: `${docTypeLabel(row.doc_type)} готов`,
          description: row.file_name,
          action: {
            label: "Скачать",
            onClick: () => downloadBlob(`/documents/${row.id}/download`, row.file_name).catch(
              (e) => toast.show({ tone: "danger", title: "Не удалось скачать", description: e.message })
            ),
          },
        });
      } else if (prevStatus && PENDING_STATUSES.has(prevStatus) && row.status === "ошибка") {
        toast.show({
          tone: "danger",
          title: `${docTypeLabel(row.doc_type)}: ошибка генерации`,
          description: row.error_text || undefined,
        });
      }
    }
    statusesRef.current = Object.fromEntries(rows.map((r) => [r.id, r.status]));

    setDocs(rows);
    return rows;
  }, [filters, toast]);

  useEffect(() => {
    setLoading(true);
    load()
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить документы", description: e.message }))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  useEffect(() => {
    api.get("/documents/authors").then(setAuthors).catch(() => {});
  }, []);

  // Опрос раз в 2с, пока есть незавершённые документы (план, Этап 5).
  useEffect(() => {
    const hasPending = docs.some((d) => PENDING_STATUSES.has(d.status));
    if (!hasPending) return undefined;
    const timer = setInterval(() => {
      load().catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
  }, [docs, load]);

  const setFilter = (key) => (e) =>
    setFilters((prev) => ({ ...prev, [key]: e.target.value }));

  const handleBulkZip = async () => {
    try {
      await downloadZip(selection);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось скачать архив", description: e.message });
    }
  };

  const handleBulkDelete = async () => {
    const ids = deleteConfirm.ids;
    setDeleteConfirm(null);
    try {
      const { results } = await api.post("/documents/bulk-delete", { ids });
      const failed = results.filter((r) => !r.ok);
      setSelection([]);
      await load();
      if (failed.length) {
        toast.show({
          tone: "warning",
          title: "Удалено не всё",
          description: `${results.length - failed.length} из ${results.length} — часть документов уже не найдена.`,
        });
      } else {
        toast.show({ tone: "success", title: "Документы удалены" });
      }
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить", description: e.message });
    }
  };

  // Предпросмотр .docx/.xlsx в браузере (TODO п.1.5): конвертация в PDF —
  // на сервере (LibreOffice headless), здесь только показ готового PDF в
  // <iframe>. Открывается сразу с индикатором загрузки, т.к. первая
  // конвертация конкретного документа может занять пару секунд —
  // повторные открытия быстрее благодаря кэшу на бэкенде.
  const openPreview = async (r) => {
    setPreview({ fileName: r.file_name, loading: true, error: null, url: null });
    try {
      const blob = await fetchPreviewBlob(r.id);
      const url = URL.createObjectURL(blob);
      setPreview({ fileName: r.file_name, loading: false, error: null, url });
    } catch (e) {
      setPreview({ fileName: r.file_name, loading: false, error: e.message, url: null });
    }
  };

  const closePreview = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
    setPreview(null);
  };

  const handleSend = (r) => {
    // Пункт 1.4 TODO_DOMIGRACII.md: решение по продукту — «Отправить» не
    // лезет само в почту/Telegram, а просто скачивает файл, чтобы
    // пользователь отправил его сам уже знакомым ему способом.
    downloadBlob(`/documents/${r.id}/download`, r.file_name)
      .then(() =>
        toast.show({
          tone: "success",
          title: "Файл скачан",
          description: "Теперь его можно отправить любым удобным способом.",
        })
      )
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось скачать", description: e.message }));
  };

  const handleArchive = async (r) => {
    try {
      await api.post(`/documents/${r.id}/archive`, {});
      await load();
      toast.show({ tone: "success", title: "Документ заархивирован" });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось заархивировать", description: e.message });
    }
  };

  const handleUnarchive = async (r) => {
    try {
      await api.post(`/documents/${r.id}/unarchive`, {});
      await load();
      toast.show({ tone: "success", title: "Документ восстановлен из архива" });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось восстановить", description: e.message });
    }
  };

  const handleBulkArchive = async () => {
    try {
      const { results } = await api.post("/documents/bulk-archive", { ids: selection });
      const failed = results.filter((r) => !r.ok);
      setSelection([]);
      await load();
      if (failed.length) {
        toast.show({
          tone: "warning",
          title: "Заархивировано не всё",
          description: `${results.length - failed.length} из ${results.length} — остальные не готовы или уже в архиве.`,
        });
      } else {
        toast.show({ tone: "success", title: "Документы заархивированы" });
      }
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось заархивировать", description: e.message });
    }
  };

  const columns = [
    { key: "doc_type", header: "Тип документа", sortable: true, render: (r) => docTypeLabel(r.doc_type) },
    { key: "delyanka_id", header: "Делянка", sortable: true, render: (r) => r.delyanka_id ?? "—" },
    { key: "created_at", header: "Дата создания", sortable: true },
    { key: "created_by", header: "Автор", sortable: true, render: (r) => r.created_by || "—" },
    {
      key: "status",
      header: "Статус",
      sortable: true,
      render: (r) => <StatusBadge status={r.status} />,
    },
    { key: "file_size", header: "Размер", sortable: true, sortValue: (r) => r.file_size ?? -1, render: (r) => formatSize(r.file_size) },
    {
      key: "actions",
      header: "Действия",
      render: (r) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {DOWNLOADABLE_STATUSES.has(r.status) ? (
            <>
              {isPreviewable(r.file_name) && (
                <button
                  className="text-pine font-semibold text-sm hover:text-pine-hover"
                  onClick={() => openPreview(r)}
                >
                  Просмотр
                </button>
              )}
              <button
                className="text-pine font-semibold text-sm hover:text-pine-hover"
                onClick={() =>
                  downloadBlob(`/documents/${r.id}/download`, r.file_name).catch((e2) =>
                    toast.show({ tone: "danger", title: "Не удалось скачать", description: e2.message })
                  )
                }
              >
                Скачать
              </button>
              <button
                className="text-pine font-semibold text-sm hover:text-pine-hover"
                onClick={() => handleSend(r)}
              >
                Отправить
              </button>
            </>
          ) : (
            <span className="text-faint text-sm">недоступно</span>
          )}
          {r.status === "готов" && (
            <button
              className="text-muted font-semibold text-sm hover:text-ink"
              onClick={() => handleArchive(r)}
            >
              Архивировать
            </button>
          )}
          {r.status === "архив" && (
            <button
              className="text-muted font-semibold text-sm hover:text-ink"
              onClick={() => handleUnarchive(r)}
            >
              Восстановить
            </button>
          )}
          <button
            className="text-error font-semibold text-sm hover:opacity-80"
            onClick={() => setDeleteConfirm({ ids: [r.id] })}
          >
            Удалить
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card title="Документы" subtitle="Все документы, сгенерированные по делянкам">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">
              Тип документа
            </label>
            <select
              value={filters.doc_type}
              onChange={setFilter("doc_type")}
              className="w-full bg-surface border border-border rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none focus:bg-surface focus:border-pine"
            >
              <option value="">Все типы</option>
              {Object.entries(DOC_TYPE_LABELS).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">
              Статус
            </label>
            <select
              value={filters.status}
              onChange={setFilter("status")}
              className="w-full bg-surface border border-border rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none focus:bg-surface focus:border-pine"
            >
              <option value="">Любой</option>
              <option value="готов">Готов</option>
              <option value="в процессе">В процессе</option>
              <option value="ошибка">Ошибка</option>
              <option value="архив">Архив</option>
            </select>
          </div>
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">
              Автор
            </label>
            <select
              value={filters.created_by}
              onChange={setFilter("created_by")}
              className="w-full bg-surface border border-border rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none focus:bg-surface focus:border-pine"
            >
              <option value="">Все авторы</option>
              {authors.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </div>
          <TextField label="С даты" type="date" value={filters.date_from} onChange={setFilter("date_from")} />
          <TextField label="По дату" type="date" value={filters.date_to} onChange={setFilter("date_to")} />
        </div>
      </Card>

      {selection.length > 0 && (
        <div className="sticky top-0 z-10 bg-pine text-white rounded-md px-4 py-3 flex items-center justify-between shadow-card">
          <span className="font-ui font-bold">Выбрано: {selection.length}</span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" className="!bg-transparent !text-white !border-white hover:!bg-white/10" onClick={handleBulkZip}>
              Скачать выбранное (.zip)
            </Button>
            <Button variant="ghost" className="!bg-transparent !text-white !border-white hover:!bg-white/10" onClick={handleBulkArchive}>
              Архивировать
            </Button>
            <Button
              variant="ghost"
              className="!bg-transparent !text-white !border-white hover:!bg-white/10"
              onClick={() => setDeleteConfirm({ ids: selection })}
            >
              Удалить
            </Button>
            <Button variant="ghost" className="!bg-transparent !text-white !border-white hover:!bg-white/10" onClick={() => setSelection([])}>
              Снять выделение
            </Button>
          </div>
        </div>
      )}

      <DataTable
        columns={columns}
        rows={docs}
        loading={loading}
        selectable
        selection={selection}
        onSelectionChange={setSelection}
        getRowId={(r) => r.id}
        emptyTitle="Документов пока нет"
        emptyDescription="Создайте документ на экране делянки — он появится здесь."
      />

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4 py-8">
          <Card className="w-full max-w-4xl" title={`Просмотр: ${preview.fileName}`}>
            {preview.loading && (
              <div className="h-[70vh] flex items-center justify-center text-muted text-sm">
                Готовим предпросмотр (конвертация в PDF)…
              </div>
            )}
            {preview.error && (
              <div className="h-[70vh] flex items-center justify-center text-error text-sm text-center px-4">
                {preview.error}
              </div>
            )}
            {preview.url && (
              <iframe
                src={preview.url}
                title={preview.fileName}
                className="w-full h-[70vh] rounded-md border border-border"
              />
            )}
            <div className="flex justify-end pt-3">
              <Button variant="secondary" onClick={closePreview}>Закрыть</Button>
            </div>
          </Card>
        </div>
      )}

      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
          <Card className="max-w-sm w-full" title="Удалить документы?">
            <p className="text-muted text-sm mb-4">
              {deleteConfirm.ids.length === 1
                ? "Документ будет удалён безвозвратно."
                : `Будет удалено документов: ${deleteConfirm.ids.length}. Действие необратимо.`}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setDeleteConfirm(null)}>Отмена</Button>
              <Button variant="danger" onClick={handleBulkDelete}>Удалить</Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
