import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";

const POLL_MS = 120000;
const TONE = { danger: "#ba1a1a", warning: "#8a5a00", info: "#1a4331" };

/**
 * «Ждёт меня» — одна кнопка в шапке со списком того, что надо разобрать
 * (шаг 4 разбора 03.11.2026): отчёты и заметки с телефона, Разбор ЕГАИС,
 * сроки актов, освидетельствованные незакрытые, черновики. Каждая строка
 * открывает нужный экран (GET /api/zhdet).
 */
export default function ZhdetMenya() {
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);

  const load = useCallback(() => {
    api.get("/zhdet").then(setData).catch(() => {}); // фоновый опрос — тихо
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    window.addEventListener("focus", load);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", load);
    };
  }, [load]);

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

  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => { setOpen(!open); if (!open) load(); }}
        aria-expanded={open}
        title="Что ждёт разбора"
        className="hover:!border-[#1a4331] hover:!text-[#1a4331]"
        style={{
          height: 30, padding: "0 10px", borderRadius: 8, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
          display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap",
          border: `1px solid ${open ? "#1a4331" : "#e5e2db"}`, background: "#fff", color: "#414944",
        }}
      >
        📋 Ждёт меня
        <span
          style={{
            minWidth: 18, height: 18, padding: "0 5px", borderRadius: 999, fontSize: 11, fontWeight: 700,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            background: total ? "#ba1a1a" : "#eaf7ec", color: total ? "#fff" : "#1a4331",
          }}
        >
          {total > 99 ? "99+" : total}
        </span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 z-50 bg-white rounded-xl overflow-hidden flex flex-col"
          style={{ width: 380, maxWidth: "calc(100vw - 24px)", maxHeight: 460, border: "1px solid #e5e2db", boxShadow: "0 12px 32px rgba(26,67,49,0.16)" }}
          role="dialog"
          aria-label="Ждёт меня"
        >
          <div className="px-3.5 py-2.5 font-ui font-bold text-[13.5px] text-pine" style={{ borderBottom: "1px solid #e5e2db" }}>
            Ждёт меня
          </div>
          <div className="overflow-y-auto">
            {data === null ? (
              <div className="px-3.5 py-6 text-center text-muted text-[13px]">Загрузка…</div>
            ) : items.length === 0 ? (
              <div className="px-3.5 py-8 text-center text-muted text-[13px]">Всё разобрано 🎉</div>
            ) : (
              items.map((it) => (
                <button
                  key={it.kod}
                  type="button"
                  onClick={() => { openScreen(it.screen, it.params || {}); setOpen(false); }}
                  className="w-full text-left flex items-start gap-2.5 px-3.5 py-2.5 hover:bg-hover transition-colors"
                  style={{ borderBottom: "1px solid #f0ede6", cursor: "pointer" }}
                >
                  <span
                    className="shrink-0"
                    style={{ minWidth: 26, textAlign: "center", fontWeight: 800, fontSize: 15, color: TONE[it.tone] || TONE.info }}
                  >
                    {it.count}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold text-ink leading-[1.35]">{it.title}</span>
                    {it.hint && <span className="block text-[12px] text-muted leading-[1.35] mt-0.5 break-words">{it.hint}</span>}
                  </span>
                  <span className="shrink-0 text-muted-2 text-[13px]" aria-hidden="true">→</span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
