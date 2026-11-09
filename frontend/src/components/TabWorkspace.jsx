import React, { useEffect, useMemo, useState } from "react";
import { NAV_GROUPS } from "./Sidebar.jsx";
import NotificationBell from "./NotificationBell.jsx";
import SlovarButton from "./Slovar.jsx";
import ZhdetMenya from "./ZhdetMenya.jsx";
import { useVid } from "../vid.jsx";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";

const MONO = "'JetBrains Mono', monospace";
const MAX_TABS = 8;

// Значки результатов общего поиска (/api/poisk, app/routers/poisk.py).
const TIP = {
  chelovek: { emoji: "👤", label: "человек" },
  delyanka: { emoji: "🪓", label: "делянка" },
  vydel: { emoji: "🌲", label: "выдел" },
  kultury: { emoji: "🌱", label: "культуры" },
  proba: { emoji: "✂️", label: "проба" },
};

const GROUP_OF = {};
NAV_GROUPS.forEach((g) => g.items.forEach(([k, label]) => (GROUP_OF[k] = { label, group: g.title })));

/**
 * Рабочая область с вкладками (дизайн «Вкладки - новый дизайн»):
 * полоса вкладок, до двух панелей рядом, палитра Ctrl+K.
 * Вкладки остаются смонтированными (скрытые — display:none), поэтому
 * состояние экрана не теряется при переключении.
 *
 * Состояние вкладок поднято в App (tabs/activeId/rightId) — чтобы Sidebar
 * мог открывать вкладки; здесь только отрисовка и горячие клавиши.
 */
export default function TabWorkspace({ screens, tabs, activeId, rightId, dispatch, currentUser }) {
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const [vid, setVid] = useVid();

  useEffect(() => {
    const onKey = (e) => {
      const meta = e.ctrlKey || e.metaKey;
      if (meta && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
        setQuery("");
      } else if (meta && /^[1-9]$/.test(e.key)) {
        const id = tabs[Number(e.key) - 1];
        if (id) {
          e.preventDefault();
          dispatch({ type: "focus", id });
        }
      } else if (e.key === "Escape") {
        setPalette(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tabs, dispatch]);

  // Ctrl+K — общий поиск (04.11.2026, «сайт разбросан»): экраны + люди,
  // делянки, выдел «71/2», лесные культуры, пробы рубок ухода.
  const [naydeno, setNaydeno] = useState([]);
  const [vybor, setVybor] = useState(0);
  useEffect(() => {
    const q = query.trim();
    if (!palette || q.length < 2) { setNaydeno([]); return undefined; }
    let zhiv = true;
    const t = setTimeout(() => {
      api.get("/poisk", { q }).then((r) => zhiv && setNaydeno(r.naydeno || [])).catch(() => zhiv && setNaydeno([]));
    }, 200);
    return () => { zhiv = false; clearTimeout(t); };
  }, [query, palette]);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    const ekrany = Object.keys(GROUP_OF)
      .map((k) => ({ key: k, ...GROUP_OF[k] }))
      .filter((it) => !q || it.label.toLowerCase().includes(q) || it.group.includes(q))
      .map((it) => ({ ...it, emoji: "▦", meta: it.group }));
    const nashli = naydeno.map((n, i) => ({
      key: `n${i}-${n.screen}-${JSON.stringify(n.params)}`, label: n.title, hint: n.hint,
      emoji: TIP[n.tip]?.emoji || "•", meta: TIP[n.tip]?.label || "", ssylka: n,
    }));
    return q ? [...nashli, ...ekrany] : ekrany;
  }, [query, naydeno]);
  useEffect(() => setVybor(0), [items.length, query]);

  const openFromPalette = (it) => {
    if (!it) return;
    if (it.ssylka) openScreen(it.ssylka.screen, it.ssylka.params || {});
    else dispatch({ type: "open", id: it.key });
    setPalette(false);
    setQuery("");
  };

  // «🎯 Квесты»: открыть экран квестов во второй панели рядом с текущим
  // (обычный экран остаётся рабочим); повторный клик — закрыть квесты.
  const kvestyOn = tabs.includes("kvesty");
  const toggleKvesty = () =>
    kvestyOn ? dispatch({ type: "close", id: "kvesty" }) : dispatch({ type: "openSide", id: "kvesty" });

  const toggleSplit = () =>
    dispatch({ type: "side", id: rightId ? rightId : tabs.find((t) => t !== activeId) });

  return (
    <div className="flex-1 min-w-0 h-screen flex flex-col overflow-hidden">
      {/* полоса вкладок */}
      <div className="flex items-stretch" style={{ gap: 8, background: "#f6f3ec", borderBottom: "1px solid #e5e2db", padding: "7px 10px 0", minHeight: 52 }}>
        <div className="flex items-end flex-1 min-w-0 overflow-x-auto" style={{ gap: 4 }}>
          {tabs.map((id) => {
            const active = id === activeId;
            const side = id === rightId;
            const meta = screens[id];
            return (
              <div
                key={id}
                onClick={() => dispatch({ type: "focus", id })}
                title={meta?.title ?? id}
                className="shrink-0 flex items-center cursor-pointer"
                style={{
                  gap: 7,
                  maxWidth: 230,
                  padding: "7px 9px 7px 11px",
                  borderRadius: "10px 10px 0 0",
                  border: `1px solid ${active || side ? "#e5e2db" : "transparent"}`,
                  borderBottom: 0,
                  background: active ? "#fcf9f2" : side ? "#fff" : "transparent",
                  boxShadow: active ? "inset 0 2px 0 #1a4331" : side ? "inset 0 2px 0 #bcefc5" : "none",
                  color: active ? "#1a4331" : "#414944",
                }}
              >
                <span style={{ width: 7, height: 7, borderRadius: 999, flexShrink: 0, background: active ? "#1a4331" : "#cfcbc2" }} />
                <span className="flex flex-col min-w-0">
                  <span className="truncate" style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap" }}>{meta?.title ?? id}</span>
                  <span style={{ fontFamily: MONO, fontSize: 10, color: "#565f59", whiteSpace: "nowrap" }}>{GROUP_OF[id]?.group}</span>
                </span>
                <button
                  type="button"
                  title="Открыть во второй панели"
                  onClick={(e) => { e.stopPropagation(); dispatch({ type: "side", id }); }}
                  className="shrink-0 hover:!bg-[#e5e2db] hover:!text-[#1a4331]"
                  style={{ width: 22, height: 22, border: 0, borderRadius: 6, background: "transparent", color: side ? "#1a4331" : "#8a938c", fontSize: 12, cursor: "pointer" }}
                >
                  ⇥
                </button>
                <button
                  type="button"
                  title="Закрыть вкладку"
                  onClick={(e) => { e.stopPropagation(); dispatch({ type: "close", id }); }}
                  className="shrink-0 hover:!bg-[#e5e2db] hover:!text-[#ba1a1a]"
                  style={{ width: 22, height: 22, border: 0, borderRadius: 6, background: "transparent", color: "#8a938c", fontSize: 15, cursor: "pointer" }}
                >
                  ×
                </button>
              </div>
            );
          })}
          <button
            type="button"
            title="Новая вкладка (Ctrl+K)"
            onClick={() => { setPalette(true); setQuery(""); }}
            className="shrink-0 hover:!border-[#1a4331] hover:!text-[#1a4331] hover:!bg-white"
            style={{ marginBottom: 7, height: 30, width: 30, border: "1px dashed #cfcbc2", background: "transparent", color: "#414944", borderRadius: 8, fontSize: 16, cursor: "pointer" }}
          >
            +
          </button>
        </div>
        <div className="flex items-center shrink-0" style={{ gap: 8, paddingBottom: 7 }}>
          <SlovarButton />
          <ZhdetMenya />
          {/* Вид интерфейса: обычный / игровой (у экранов с игровым вариантом) */}
          <div
            role="group"
            aria-label="Вид интерфейса"
            className="flex shrink-0"
            style={{ height: 30, border: `1px solid ${vid === "igra" ? "#b07d0c" : "#e5e2db"}`, borderRadius: 8, overflow: "hidden" }}
          >
            {[["obychnyy", "Обычный"], ["igra", "🎮 Игровой"]].map(([k, label]) => (
              <button
                key={k}
                type="button"
                aria-pressed={vid === k}
                onClick={() => setVid(k)}
                title={k === "igra" ? "Игровой вид: Штаб, Путь делянки, Карточки героев, Почта гонцов, Табель-перекличка, Огород уходов, Фронт работ, Охота на акты, Вывозка, квесты, рейтинг, челленджи, газета" : "Обычный вид всех экранов"}
                style={{
                  padding: "0 10px", border: 0, fontSize: 12.5, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
                  background: vid === k ? (k === "igra" ? "#fbf1d6" : "#eaf7ec") : "#fff",
                  color: vid === k ? (k === "igra" ? "#7a5600" : "#1a4331") : "#8a938c",
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {vid === "igra" && (
            <button
              type="button"
              onClick={toggleKvesty}
              aria-pressed={kvestyOn}
              title={kvestyOn ? "Закрыть квесты" : "Квесты дня — рядом с обычным экраном"}
              className="hover:!border-[#b07d0c]"
              style={{
                height: 30, padding: "0 10px", borderRadius: 8, fontSize: 12.5, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
                border: `1px solid ${kvestyOn ? "#b07d0c" : "#e5e2db"}`,
                background: kvestyOn ? "#fbf1d6" : "#fff",
                color: kvestyOn ? "#7a5600" : "#414944",
              }}
            >
              🎯 Квесты
            </button>
          )}
          <NotificationBell onNavigate={(id) => dispatch({ type: "open", id })} />
          <button
            type="button"
            onClick={toggleSplit}
            className="hover:!border-[#1a4331] hover:!text-[#1a4331]"
            style={{
              height: 30, padding: "0 12px", borderRadius: 8, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
              border: `1px solid ${rightId ? "#1a4331" : "#e5e2db"}`,
              background: rightId ? "#eaf7ec" : "#fff",
              color: rightId ? "#1a4331" : "#414944",
            }}
          >
            Две панели
          </button>
        </div>
      </div>

      {/* панели */}
      <div className="flex-1 min-h-0 flex flex-wrap content-start overflow-y-auto" style={{ gap: 1, background: "#e5e2db" }}>
        {tabs.map((id) => {
          const meta = screens[id];
          const role = id === activeId ? "left" : id === rightId ? "right" : null;
          const Page = meta?.Page;
          return (
            <div
              key={id}
              className="flex-col overflow-hidden"
              style={{
                display: role ? "flex" : "none",
                flex: role === "right" ? "1 1 330px" : "2 1 420px",
                minWidth: "min(100%, 330px)",
                minHeight: 0,
                height: "100%",
                maxHeight: "100%",
                background: "#fcf9f2",
                order: role === "right" ? 2 : 1,
              }}
            >
              <div className="flex items-center justify-between flex-wrap" style={{ gap: "6px 10px", padding: "12px 18px", background: "#fcf9f2", borderBottom: "1px solid #e5e2db" }}>
                <div className="min-w-0" style={{ flex: "1 1 150px" }}>
                  <div className="truncate" style={{ fontSize: 15.5, fontWeight: 800, color: "#1a4331" }}>{meta?.title ?? id}</div>
                  <div className="flex items-center min-w-0" style={{ gap: 7, marginTop: 3 }}>
                    <span className="truncate" style={{ fontFamily: MONO, fontSize: 10.5, color: "#565f59" }}>{meta?.subtitle}</span>
                    <span
                      className="shrink-0"
                      style={{
                        fontFamily: MONO, fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase", whiteSpace: "nowrap",
                        color: role === "right" ? "#565f59" : "#1a4331",
                        background: role === "right" ? "#f6f3ec" : "#eaf7ec",
                        border: `1px solid ${role === "right" ? "#e5e2db" : "#bcefc5"}`,
                        borderRadius: 999, padding: "1px 7px",
                      }}
                    >
                      {role === "right" ? "справочная панель" : "рабочая панель"}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  title={role === "right" ? "Вернуть в одну панель" : "Открыть эту вкладку во второй панели"}
                  onClick={() => (role === "right" ? dispatch({ type: "unsplit" }) : dispatch({ type: "side", id }))}
                  className="shrink-0 hover:!border-[#1a4331] hover:!text-[#1a4331]"
                  style={{ height: 28, padding: "0 10px", border: "1px solid #e5e2db", background: "#fff", color: "#414944", borderRadius: 8, fontSize: 12, whiteSpace: "nowrap", cursor: "pointer" }}
                >
                  {role === "right" ? "Закрыть" : "Рядом"}
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto">
                {Page ? <Page currentUser={currentUser} onOpenTab={(k) => dispatch({ type: "open", id: k })} /> : <div className="p-8 text-muted">Экран «{id}» не найден</div>}
              </div>
            </div>
          );
        })}
        {tabs.length === 0 && (
          <div className="flex-1 flex items-center justify-center" style={{ background: "#fcf9f2", color: "#565f59" }}>
            Нет открытых вкладок — выберите экран слева или нажмите Ctrl+K
          </div>
        )}
      </div>

      {palette && (
        <div
          onClick={() => setPalette(false)}
          className="fixed inset-0 flex items-start justify-center"
          style={{ background: "rgba(15,42,29,.28)", paddingTop: "12vh", zIndex: 40 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(520px, 92vw)", background: "#fff", border: "1px solid #e5e2db", borderRadius: 16, boxShadow: "0 12px 32px rgba(15,42,29,.18)", overflow: "hidden" }}
          >
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") openFromPalette(items[vybor] || items[0]);
                else if (e.key === "ArrowDown") { e.preventDefault(); setVybor((v) => Math.min(v + 1, items.length - 1)); }
                else if (e.key === "ArrowUp") { e.preventDefault(); setVybor((v) => Math.max(v - 1, 0)); }
              }}
              placeholder="Найти: фамилия, делянка, 71/2, проба 12 или экран…"
              style={{ width: "100%", height: 48, border: 0, borderBottom: "1px solid #e5e2db", padding: "0 16px", fontSize: 15, color: "#1c1c18", outline: "none" }}
            />
            <div className="overflow-y-auto" style={{ maxHeight: 380, padding: 6 }}>
              {items.map((it, i) => (
                <button
                  key={it.key}
                  type="button"
                  onClick={() => openFromPalette(it)}
                  onMouseEnter={() => setVybor(i)}
                  className="flex items-center justify-between w-full text-left"
                  style={{ gap: 10, background: i === vybor ? "#f1eee7" : "transparent", border: 0, borderRadius: 10, padding: it.hint ? "7px 12px" : "10px 12px", fontSize: 14, color: "#1c1c18", cursor: "pointer" }}
                >
                  <span className="flex items-center min-w-0" style={{ gap: 10 }}>
                    <span style={{ width: 20, textAlign: "center", flexShrink: 0, color: "#6b7268" }}>{it.emoji}</span>
                    <span className="min-w-0">
                      <span className="block truncate">{it.label}</span>
                      {it.hint && <span className="block truncate" style={{ fontSize: 11.5, color: "#6b7268" }}>{it.hint}</span>}
                    </span>
                  </span>
                  <span style={{ fontFamily: MONO, fontSize: 10.5, color: "#6b7268", flexShrink: 0 }}>{it.meta}</span>
                </button>
              ))}
              {!items.length && (
                <div style={{ padding: "14px 12px", fontSize: 13, color: "#6b7268" }}>Ничего не нашлось. Квартал и выдел можно писать так: 71/2 или «кв 71 выд 2».</div>
              )}
            </div>
            <div style={{ borderTop: "1px solid #e5e2db", padding: "7px 14px", fontFamily: MONO, fontSize: 10, color: "#8a8f86" }}>
              ↑↓ выбрать · Enter открыть · Esc закрыть
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Редьюсер вкладок: tabs — массив id, activeId — левая (рабочая) панель,
// rightId — необязательная вторая панель.
export function tabsReducer(state, action) {
  const { tabs, activeId, rightId } = state;
  switch (action.type) {
    case "open": {
      const next = tabs.includes(action.id) ? tabs : [...tabs, action.id].slice(-MAX_TABS);
      return { tabs: next, activeId: action.id, rightId: rightId === action.id ? null : rightId && next.includes(rightId) ? rightId : null };
    }
    case "focus":
      return { ...state, activeId: action.id, rightId: rightId === action.id ? null : rightId };
    case "close": {
      const next = tabs.filter((t) => t !== action.id);
      const newRight = rightId === action.id ? null : rightId;
      const newActive = activeId === action.id ? next.filter((t) => t !== newRight).pop() ?? next[next.length - 1] ?? null : activeId;
      return { tabs: next, activeId: newActive, rightId: newRight === newActive ? null : newRight };
    }
    case "side": {
      if (!action.id) return state;
      if (rightId === action.id) return { ...state, rightId: null };
      const newActive = activeId === action.id ? tabs.find((t) => t !== action.id) ?? activeId : activeId;
      if (newActive === action.id) return state; // единственная вкладка — сравнивать не с чем
      return { ...state, activeId: newActive, rightId: action.id };
    }
    case "openSide": {
      // Открыть вкладку сразу во второй панели (кнопка «🎯 Квесты»).
      const next = tabs.includes(action.id) ? tabs : [...tabs, action.id].slice(-MAX_TABS);
      const left = activeId && activeId !== action.id && next.includes(activeId) ? activeId : next.find((t) => t !== action.id);
      if (!left) return { tabs: next, activeId: action.id, rightId: null };
      return { tabs: next, activeId: left, rightId: action.id };
    }
    case "unsplit":
      return { ...state, rightId: null };
    default:
      return state;
  }
}
