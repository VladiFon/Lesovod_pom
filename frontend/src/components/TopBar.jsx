import React from "react";
import Button from "./Button.jsx";

/**
 * TopBar — шапка контентной области (↔ QFrame#TopBar). Слева заголовок
 * экрана и подзаголовок, справа — строка поиска (QLineEdit#SearchInput:
 * заливка surface-alt, без рамки, рамка Pine только в фокусе), кнопка-
 * уведомление с точкой (NotificationDot) и основное действие экрана.
 */
export default function TopBar({
  title,
  subtitle,
  search,
  onSearchChange,
  searchPlaceholder = "Поиск…",
  hasNotifications = false,
  primaryAction,
}) {
  return (
    <div className="bg-paper border-b border-border px-8 py-5 flex items-center justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-ui font-extrabold text-xl text-pine truncate">{title}</h1>
        {subtitle && <p className="text-muted text-base mt-0.5 truncate">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {onSearchChange && (
          <div className="relative">
            <input
              type="search"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={searchPlaceholder}
              className="w-64 bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md pl-9 pr-3 py-2 text-base text-ink placeholder:text-faint outline-none transition-colors"
            />
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="h-4 w-4 text-faint absolute left-3 top-1/2 -translate-y-1/2"
            >
              <circle cx="11" cy="11" r="6.5" />
              <path d="m20 20-3.5-3.5" />
            </svg>
          </div>
        )}

        <button
          aria-label="Уведомления"
          className="relative h-9 w-9 rounded-md border border-border bg-surface flex items-center justify-center text-muted hover:bg-hover hover:text-pine transition-colors"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4.5 w-4.5">
            <path d="M6 9a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 13 6 9Z" />
            <path d="M10 18.5a2 2 0 0 0 4 0" />
          </svg>
          {hasNotifications && (
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-error" />
          )}
        </button>

        {primaryAction && (
          <Button variant="primary" onClick={primaryAction.onClick} icon={primaryAction.icon}>
            {primaryAction.label}
          </Button>
        )}
      </div>
    </div>
  );
}
