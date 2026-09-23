import React, { useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import { API_BASE_URL } from "../api/client.js";

/**
 * AuthImage — картинка с эндпоинта, требующего вход (Authorization: Bearer).
 * Обычный <img src> заголовок авторизации отправить не может, поэтому файл
 * загружается fetch'ем и показывается через blob-URL (освобождается при
 * смене/размонтировании). Клик — увеличенный просмотр в модальном окне
 * (а не переход по blob-URL в новую вкладку: тип берётся с сервера, и
 * открывать такой адрес как страницу не нужно).
 *
 * path — путь относительно API_BASE_URL, например
 * "/uhody/proby/7/photo/stolb_proby". caption — подпись под миниатюрой.
 */
export default function AuthImage({ path, caption }) {
  const [state, setState] = useState({ status: "loading", url: null, error: null });
  const [zoom, setZoom] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;
    setState({ status: "loading", url: null, error: null });
    (async () => {
      try {
        const token = localStorage.getItem("lesovod_token");
        const res = await fetch(`${API_BASE_URL}${path}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) {
          const detail = await res.json().catch(() => null);
          throw new Error(detail?.detail || `Ошибка сервера (${res.status})`);
        }
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) setState({ status: "ok", url: objectUrl, error: null });
      } catch (e) {
        if (!cancelled) setState({ status: "error", url: null, error: e.message });
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  return (
    <figure className="m-0 flex flex-col gap-1.5 min-w-0">
      {state.status === "ok" ? (
        <button
          type="button"
          onClick={() => setZoom(true)}
          title="Открыть крупно"
          className="block rounded-md border border-border overflow-hidden bg-surface-alt p-0"
          style={{ cursor: "zoom-in" }}
        >
          <img src={state.url} alt={caption} className="block w-full max-h-64 object-contain" />
        </button>
      ) : (
        <div
          className="rounded-md border border-border bg-surface-alt flex items-center justify-center text-[12.5px] text-muted text-center px-3"
          style={{ height: 160 }}
          role={state.status === "error" ? "alert" : undefined}
        >
          {state.status === "loading" ? "Загрузка фото…" : state.error}
        </div>
      )}
      {caption && <figcaption className="text-[12.5px] font-semibold text-muted">{caption}</figcaption>}

      <Modal open={zoom} onClose={() => setZoom(false)} title={caption} size="lg">
        {state.url && <img src={state.url} alt={caption} className="block max-w-full max-h-[70vh] mx-auto object-contain" />}
      </Modal>
    </figure>
  );
}
