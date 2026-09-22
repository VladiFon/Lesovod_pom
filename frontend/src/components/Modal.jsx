import React, { useEffect } from "react";
import { createPortal } from "react-dom";

/**
 * Modal — модальное окно (↔ QDialog#StyledInputDialog в styles.py:
 * белая карточка 16px, тень, кнопки Ok/Cancel снизу справа).
 * Закрывается по Escape и клику по подложке.
 */
export default function Modal({ open, onClose, title, footer, size = "md", children }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose?.();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const widths = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" };

  return createPortal(
    // z-[1200]: Leaflet сам use'ет z-index до 1000 для своих контролов
    // (.leaflet-top/.leaflet-bottom) внутри карты (см. LiveMap.jsx) —
    // z-50 этого модального окна было ниже, поэтому карта могла
    // перекрывать диалог поверх (заметно при открытой карточке
    // таксации во время зума/движения карты). Модалка — всегда
    // самый верхний слой интерфейса, так что берём z с явным запасом.
    <div className="fixed inset-0 z-[1200] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-pine-deep/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? "modal-title" : undefined}
        className={[
          "relative w-full bg-surface rounded-lg shadow-modal border border-border",
          "animate-[modal-in_150ms_ease-out]",
          widths[size],
        ].join(" ")}
      >
        {title && (
          <div className="px-6 pt-5 pb-3 border-b border-border">
            <h2 id="modal-title" className="font-ui font-bold text-lg text-ink">
              {title}
            </h2>
          </div>
        )}
        <div className="px-6 py-5">{children}</div>
        {footer && <div className="px-6 pb-5 pt-1 flex items-center justify-end gap-2">{footer}</div>}
      </div>
      <style>{`
        @keyframes modal-in {
          from { opacity: 0; transform: translateY(6px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>,
    document.body
  );
}
