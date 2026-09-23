import React, { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "./Toast.jsx";
import { api } from "../api/client.js";

/**
 * NotificationBell — колокольчик уведомлений с красным счётчиком и
 * выпадающим списком (GET/PATCH /api/notifications, см.
 * backend/app/routers/notifications.py). "Прочитано" у каждого своё:
 * когда уведомление открыл кто-то другой, здесь оно остаётся
 * непрочитанным — сервер ведёт отметки по читателю.
 *
 * Счётчик берётся отдельным дешёвым запросом /unread-count (опрос раз в
 * минуту и при возврате на вкладку браузера), а не считается по списку:
 * список ограничен последними записями, счётчик должен быть точным.
 *
 * onNavigate(screenKey) — открыть экран, к которому относится уведомление
 * (заметка → "Заметки", проба → "Рубки ухода"); у остальных типов (поломка,
 * трелёвка) веб-экрана нет — клик только отмечает прочитанным.
 */
const POLL_MS = 60_000;

const EVENT_META = {
  breakdown: { icon: "⚠️", label: "Поломка", screen: null },
  note: { icon: "📝", label: "Заметка", screen: "worker_notes" },
  proba: { icon: "🌲", label: "Проба ухода", screen: "uhody" },
  trelevka: { icon: "🚜", label: "Трелёвка", screen: null },
};

function formatDateTime(s) {
  if (!s) return "";
  const [date, time] = s.split(" ");
  return `${date.split("-").reverse().join(".")} ${time?.slice(0, 5) ?? ""}`;
}

export default function NotificationBell({ onNavigate }) {
  const toast = useToast();
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState(null);

  const refreshCount = useCallback(() => {
    api
      .get("/notifications/unread-count")
      .then((r) => setUnread(r.unread))
      .catch(() => {}); // фоновый опрос — тихо, тост на каждый сбой сети раздражал бы
  }, []);

  const loadList = useCallback(() => {
    api
      .get("/notifications/", { limit: 30 })
      .then(setItems)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить уведомления", description: e.message }));
  }, [toast]);

  useEffect(() => {
    refreshCount();
    const timer = setInterval(refreshCount, POLL_MS);
    const onFocus = () => refreshCount();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [refreshCount]);

  // закрытие по клику вне панели и по Escape
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      setItems(null);
      loadList();
      refreshCount();
    }
  };

  const markRead = async (item) => {
    if (item.is_read) return;
    setItems((prev) => prev.map((n) => (n.id === item.id ? { ...n, is_read: true } : n)));
    setUnread((u) => Math.max(0, u - 1));
    try {
      await api.patch(`/notifications/${item.id}`, { is_read: true });
    } catch (e) {
      setItems((prev) => prev.map((n) => (n.id === item.id ? { ...n, is_read: false } : n)));
      refreshCount();
      toast.show({ tone: "danger", title: "Не удалось отметить прочитанным", description: e.message });
    }
  };

  const handleClick = (item) => {
    markRead(item);
    const screen = EVENT_META[item.event_type]?.screen;
    if (screen && onNavigate) {
      onNavigate(screen);
      setOpen(false);
    }
  };

  const markAll = async () => {
    try {
      await api.post("/notifications/read-all");
      setItems((prev) => (prev ? prev.map((n) => ({ ...n, is_read: true })) : prev));
      setUnread(0);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось отметить всё прочитанным", description: e.message });
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-label={unread > 0 ? `Уведомления, непрочитанных: ${unread}` : "Уведомления"}
        aria-expanded={open}
        title="Уведомления"
        onClick={toggle}
        className="relative h-[30px] w-[30px] rounded-lg border bg-white flex items-center justify-center text-[#414944] hover:!border-[#1a4331] hover:!text-[#1a4331] transition-colors"
        style={{ borderColor: open ? "#1a4331" : "#e5e2db", cursor: "pointer" }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-[17px] w-[17px]">
          <path d="M6 9a6 6 0 0 1 12 0c0 4 1.5 5.5 1.5 5.5H4.5S6 13 6 9Z" />
          <path d="M10 18.5a2 2 0 0 0 4 0" />
        </svg>
        {unread > 0 && (
          <span
            className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 rounded-full bg-error text-white flex items-center justify-center"
            style={{ fontSize: 10, fontWeight: 700, lineHeight: 1 }}
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 z-50 bg-white rounded-xl overflow-hidden flex flex-col"
          style={{ width: 360, maxWidth: "calc(100vw - 24px)", maxHeight: 440, border: "1px solid #e5e2db", boxShadow: "0 12px 32px rgba(26,67,49,0.16)" }}
          role="dialog"
          aria-label="Уведомления"
        >
          <div className="flex items-center justify-between px-3.5 py-2.5" style={{ borderBottom: "1px solid #e5e2db" }}>
            <span className="font-ui font-bold text-[13.5px] text-pine">Уведомления</span>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAll}
                className="text-[12px] font-semibold text-pine hover:underline"
                style={{ cursor: "pointer" }}
              >
                Прочитать все
              </button>
            )}
          </div>

          <div className="overflow-y-auto">
            {items === null ? (
              <div className="px-3.5 py-6 text-center text-muted text-[13px]">Загрузка…</div>
            ) : items.length === 0 ? (
              <div className="px-3.5 py-8 text-center text-muted text-[13px]">Уведомлений пока нет</div>
            ) : (
              items.map((n) => {
                const meta = EVENT_META[n.event_type] ?? { icon: "🔔", label: n.event_type };
                return (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => handleClick(n)}
                    className="w-full text-left flex gap-2.5 px-3.5 py-2.5 hover:bg-hover transition-colors"
                    style={{ borderBottom: "1px solid #f0ede6", background: n.is_read ? "transparent" : "#f3faf4", cursor: "pointer" }}
                  >
                    <span className="text-[16px] leading-5 shrink-0" aria-hidden="true">{meta.icon}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="text-[11.5px] font-semibold text-muted">{meta.label}</span>
                        <span className="text-[11px] text-muted-2">{formatDateTime(n.created_at)}</span>
                        {!n.is_read && <span className="h-2 w-2 rounded-full bg-pine shrink-0 ml-auto" aria-label="не прочитано" />}
                      </span>
                      <span className="block text-[13px] text-ink leading-[1.4] mt-0.5 break-words">{n.text}</span>
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
