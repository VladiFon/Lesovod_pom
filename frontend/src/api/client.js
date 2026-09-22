/**
 * api/client.js — единая точка HTTP-запросов к backend (Этап 1/2,
 * FastAPI на :8000, проксируется через /api в vite.config.js на деве и
 * через Caddy в проде — см. Этап 8).
 *
 * Все страницы должны звать backend ТОЛЬКО через этот файл (требование
 * шаблона промпта Этапа 4, п.4) — единое место для: базового URL,
 * заголовка авторизации (Этап 2: `Authorization: Bearer <token>`),
 * разбора ошибок FastAPI (`{"detail": "..."}`) и таймаутов.
 */

const BASE_URL = "/api";

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function getToken() {
  return localStorage.getItem("lesovod_token");
}

async function request(path, { method = "GET", body, params, signal } = {}) {
  let url = `${BASE_URL}${path}`;
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null)
    ).toString();
    if (qs) url += `?${qs}`;
  }

  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
  } catch (networkErr) {
    // fetch кидает TypeError при обрыве сети/недоступном backend — заворачиваем
    // в понятную ошибку, чтобы страницы могли показать один и тот же Toast
    // независимо от того, сеть упала или сервер ответил 500.
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение.", 0, null);
  }

  if (response.status === 204) return null;

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : await response.text();

  if (!response.ok) {
    const detail = isJson ? payload?.detail : payload;
    throw new ApiError(
      typeof detail === "string" ? detail : `Ошибка сервера (${response.status})`,
      response.status,
      detail
    );
  }

  return payload;
}

/**
 * uploadRequest — тот же контракт (Authorization, разбор ошибок FastAPI),
 * но без Content-Type: application/json — тело формы задаёт его сам
 * (multipart/form-data + boundary). Нужен с Этапа 5 (импорт МДО:
 * POST /api/delyanki/import-mdo принимает файлы через FormData, а
 * merge_into_one — обычный query-параметр, см. params).
 */
async function uploadRequest(path, formData, { params } = {}) {
  let url = `${BASE_URL}${path}`;
  if (params) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    ).toString();
    if (qs) url += `?${qs}`;
  }

  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(url, { method: "POST", headers, body: formData });
  } catch (networkErr) {
    throw new ApiError("Не удалось связаться с сервером. Проверьте подключение.", 0, null);
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json().catch(() => null) : await response.text();

  if (!response.ok) {
    const detail = isJson ? payload?.detail : payload;
    throw new ApiError(
      typeof detail === "string" ? detail : `Ошибка сервера (${response.status})`,
      response.status,
      detail
    );
  }

  return payload;
}

export const api = {
  get: (path, params) => request(path, { method: "GET", params }),
  post: (path, body, params) => request(path, { method: "POST", body, params }),
  patch: (path, body, params) => request(path, { method: "PATCH", body, params }),
  delete: (path) => request(path, { method: "DELETE" }),
  upload: (path, formData, params) => uploadRequest(path, formData, { params }),
};

export { ApiError, BASE_URL as API_BASE_URL };
