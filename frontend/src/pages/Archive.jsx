import React, { useCallback, useEffect, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Архив документов" (screens/archive/) — Этап 11 плана.
 *
 * Backend написан заново в этом чате (app/routers/archive.py) — единственный
 * из перенесённых экранов, под который в lesovod_backend_stage2.zip не было
 * готового роутера (см. STAGE11.md).
 *
 * Перенесено 1:1 (см. докстринг screens/archive/screen_logic.py, Этап F
 * desktop-версии — экран уже был переделан из ИИ-распознавателя в ручной
 * архиватор ДО переноса в веб, поэтому здесь нет и не должно быть попытки
 * автозаполнения полей по файлу):
 *   Выбор файла (DropZone) + заполнение полей вручную (title/тип/дата/теги)
 *   Список DOC_TYPES ("Приказы"/"Списки делянок"/"Прочее")
 *   Поиск по названию/тегам/типу через SQL LIKE (не in-memory фильтр)
 *   Иконки по расширению файла в списке (_PREVIEW_ICONS)
 */

const PREVIEW_ICONS = {
  ".pdf": "📕", ".doc": "📘", ".docx": "📘", ".rtf": "📘", ".odt": "📘",
  ".xls": "📗", ".xlsx": "📗", ".csv": "📗", ".ods": "📗",
  ".ppt": "📙", ".pptx": "📙", ".txt": "📄",
  ".jpg": "🖼️", ".jpeg": "🖼️", ".png": "🖼️",
};

function iconFor(filePath) {
  const ext = (filePath || "").slice(((filePath || "").lastIndexOf(".")) ).toLowerCase();
  return PREVIEW_ICONS[ext] || "📎";
}

function UploadModal({ open, onClose, docTypes, onUploaded }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState(docTypes[0] || "");
  const [docDate, setDocDate] = useState("");
  const [tags, setTags] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleFileChange = (e) => {
    const f = e.target.files?.[0] || null;
    setFile(f);
    if (f && !title.trim()) {
      setTitle(f.name.replace(/\.[^.]+$/, ""));
    }
  };

  const reset = () => {
    setFile(null);
    setTitle("");
    setDocType(docTypes[0] || "");
    setDocDate("");
    setTags("");
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!file || !title.trim()) {
      toast.show({ tone: "warning", title: "Укажите файл и название документа" });
      return;
    }
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      await api.upload("/archive/documents", formData, {
        title: title.trim(),
        doc_type: docType,
        doc_date: docDate,
        tags,
      });
      toast.show({ tone: "success", title: "Документ сохранён в архив" });
      reset();
      onClose();
      onUploaded();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить документ", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Добавить документ в архив"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>Сохранить в архив</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div>
          <label className="block text-[11.5px] font-semibold text-muted mb-1">Файл</label>
          <input
            type="file"
            onChange={handleFileChange}
            className="w-full text-base text-ink file:mr-3 file:px-3.5 file:py-2 file:rounded-md file:border-0 file:bg-mint-soft file:text-pine file:font-semibold file:cursor-pointer"
          />
          {file && <p className="text-faint text-xs mt-1.5">Выбран файл: {file.name}</p>}
        </div>
        <TextField label="Название документа" value={title} onChange={(e) => setTitle(e.target.value)} />
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">Тип документа</label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none"
            >
              {docTypes.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <TextField label="Дата документа" placeholder="ДД.ММ.ГГГГ" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
        </div>
        <TextField label="Ключевые слова / теги" placeholder="через запятую" value={tags} onChange={(e) => setTags(e.target.value)} />
      </div>
    </Modal>
  );
}

export default function Archive() {
  const toast = useToast();
  const [docTypes, setDocTypes] = useState([]);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);

  useEffect(() => {
    api.get("/archive/doc-types").then(setDocTypes).catch(() => setDocTypes(["Приказы", "Списки делянок", "Прочее"]));
  }, []);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get("/archive/documents", { query, doc_type: typeFilter });
      setRows(data || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить архив", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [query, typeFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(search, 250);
    return () => clearTimeout(t);
  }, [search]);

  const handleDelete = async (doc) => {
    if (!window.confirm(`Удалить «${doc.title}» из архива?`)) return;
    try {
      await api.delete(`/archive/documents/${doc.id}`);
      setRows((prev) => prev.filter((d) => d.id !== doc.id));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить документ", description: e.message });
    }
  };

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex items-end gap-4 flex-wrap">
          <TextField
            label="Поиск"
            placeholder="По названию, тегам или типу…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1 min-w-[240px]"
          />
          <div className="min-w-[200px]">
            <label className="block text-[11.5px] font-semibold text-muted mb-1">Тип документа</label>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="w-full bg-surface border border-border focus:border-pine focus:bg-surface rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none transition-colors"
            >
              <option value="">Все типы</option>
              {docTypes.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <Button variant="primary" onClick={() => setUploadOpen(true)}>Добавить документ</Button>
        </div>
      </Card>

      <Card>
        <DataTable
          loading={loading}
          columns={[
            { key: "icon", header: "", render: (r) => <span className="text-lg">{iconFor(r.file_path)}</span>, width: "40px" },
            { key: "title", header: "Название" },
            { key: "doc_type", header: "Тип", render: (r) => r.doc_type || "—" },
            { key: "doc_date", header: "Дата документа", render: (r) => r.doc_date || "—" },
            { key: "tags", header: "Теги", render: (r) => r.tags || "—" },
            { key: "added_at", header: "Добавлен" },
            {
              key: "actions", header: "",
              render: (r) => (
                <div className="flex items-center gap-3">
                  <a
                    href={`${API_BASE_URL}/archive/documents/${r.id}/download`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-pine font-semibold hover:text-pine-hover"
                  >
                    Скачать
                  </a>
                  <button onClick={() => handleDelete(r)} className="text-error font-semibold hover:opacity-80">Удалить</button>
                </div>
              ),
            },
          ]}
          rows={rows}
          emptyTitle="В архиве пока пусто"
          emptyDescription="Добавьте первый документ (скан приказа, список делянок и т.п.) кнопкой выше."
        />
      </Card>

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} docTypes={docTypes} onUploaded={search} />
    </div>
  );
}
