import React, { createContext, useCallback, useContext, useState } from "react";
import { createPortal } from "react-dom";

/**
 * Toast — всплывающие уведомления в правом нижнем углу. Задуман в первую
 * очередь под сценарий Этапа 5: "Акт по делянке №12 готов" + кнопка
 * "Скачать", когда опрос GET /api/tasks/{id} видит статус "готов" — но
 * годится для любых уведомлений (успех сохранения, ошибка сети и т.п.).
 *
 * Использование:
 *   const toast = useToast();
 *   toast.show({ tone: "success", title: "Акт готов", description: "...",
 *                action: { label: "Скачать", onClick: () => ... } });
 */
const ToastContext = createContext(null);

const TONES = {
  success: "border-l-green",
  danger: "border-l-error",
  warning: "border-l-oak",
  info: "border-l-pine",
};

let idCounter = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    ({ tone = "info", title, description, action, duration = 5000 }) => {
      const id = ++idCounter;
      setToasts((prev) => [...prev, { id, tone, title, description, action }]);
      if (duration) setTimeout(() => dismiss(id), duration);
      return id;
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ show, dismiss }}>
      {children}
      {createPortal(
        <div className="fixed bottom-5 right-5 z-[100] flex flex-col gap-2 w-80 max-w-[calc(100vw-2.5rem)]">
          {toasts.map((t) => (
            <div
              key={t.id}
              role="status"
              className={[
                "bg-surface border border-border border-l-4 rounded-md shadow-modal",
                "px-4 py-3 flex items-start gap-3 animate-[toast-in_180ms_ease-out]",
                TONES[t.tone],
              ].join(" ")}
            >
              <div className="flex-1 min-w-0">
                {t.title && <div className="font-ui font-bold text-ink text-base">{t.title}</div>}
                {t.description && <div className="text-muted text-sm mt-0.5">{t.description}</div>}
                {t.action && (
                  <button
                    onClick={() => {
                      t.action.onClick?.();
                      dismiss(t.id);
                    }}
                    className="text-pine font-semibold text-sm mt-1.5 hover:text-pine-hover"
                  >
                    {t.action.label}
                  </button>
                )}
              </div>
              <button
                onClick={() => dismiss(t.id)}
                aria-label="Закрыть уведомление"
                className="text-faint hover:text-muted shrink-0"
              >
                ✕
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
      <style>{`
        @keyframes toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast() must be used inside <ToastProvider>");
  return ctx;
}
