import { api, API_BASE_URL } from "./client.js";
import { pollTask } from "../hooks/useTaskPolling.js";

/**
 * api/uhody.js — обёртка над backend/app/routers/uhody.py (C.3 плана).
 * Как и остальные страницы, ходит в backend только через api из
 * ./client.js (единая точка HTTP, авторизация, разбор ошибок FastAPI).
 *
 * Поиск участка по кварталу/выделу не дублируется здесь — экран зовёт
 * уже существующий api.get("/taxation/vydel", { kvartal, vydel }) напрямую
 * (см. RubkiUhoda.jsx), как это делает pages/Taxation.jsx.
 *
 * Генерация документов идёт по тому же паттерну, что и на остальных
 * экранах (Plots.jsx/Documents.jsx): POST .../documents/{word|excel} ->
 * {task_id} -> pollTask() -> {document_ids: [id]} -> метаданные документа
 * (GET /documents/{id}) -> сам файл (GET /documents/{id}/download).
 */

// --- Справочники ---
export const getPorody = () => api.get("/uhody/porody");

// --- Расчёт (кнопка "Рассчитать", без сохранения) ---
export const calculateProba = (payload) => api.post("/uhody/calculate", payload);
export const calculateLesoseka = (payload) => api.post("/uhody/calculate/lesoseka", payload);

// --- CRUD проб ---
export const listProby = () => api.get("/uhody/proby");
export const getProba = (id) => api.get(`/uhody/proby/${id}`);
export const createProba = (payload) => api.post("/uhody/proby", payload);
export const updateProba = (id, payload) => api.patch(`/uhody/proby/${id}`, payload);
export const deleteProba = (id) => api.delete(`/uhody/proby/${id}`);

// --- Участки лесных культур (для мульти-select "на каких проведена проба") ---
export const listLesokulturyUchastkiForPicker = (search) =>
  api.get("/uhody/lesokultury-uchastki", search ? { search } : undefined);

// --- Пресеты комиссии ---
export const listKomissiyaPresets = () => api.get("/uhody/komissiya-presets");
export const saveKomissiyaPreset = (payload) => api.post("/uhody/komissiya-presets", payload);
export const deleteKomissiyaPreset = (id) => api.delete(`/uhody/komissiya-presets/${id}`);

// --- Генерация документов ---
// kind: "word" | "excel". Возвращает { task_id } — статус опрашивается
// через pollTask() (см. ниже generateAndDownload) в общем
// GET /api/tasks/{task_id}, ничего своего под это заводить не нужно.
const startDocumentGeneration = (probaId, kind) =>
  api.post(`/uhody/${probaId}/documents/${kind}`);

// Тот же helper, что и в pages/Documents.jsx (downloadBlob) — не
// переиспользован оттуда напрямую, т.к. там он локальный, не экспортируется.
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

// Запускает фоновую генерацию, дожидается готовности и сразу скачивает
// файл. kind: "word" | "excel".
export async function generateAndDownload(probaId, kind) {
  const { task_id: taskId } = await startDocumentGeneration(probaId, kind);
  const result = await pollTask(taskId, { intervalMs: 800, timeoutMs: 60 * 1000 });
  const documentId = result?.document_ids?.[0];
  if (!documentId) {
    throw new Error("Задача завершилась без готового документа.");
  }
  const doc = await api.get(`/documents/${documentId}`);
  await downloadBlob(`/documents/${documentId}/download`, doc.file_name);
}
