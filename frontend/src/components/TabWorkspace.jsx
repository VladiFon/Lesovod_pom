import { napechatat } from "./pechat.js";
import { useTema } from "../tema.js";
import { razobratKomandu, opisaniePoziciy } from "../komandy.js";
import React, { useEffect, useMemo, useState } from "react";
import { NAV_GROUPS } from "./Sidebar.jsx";
import NotificationBell from "./NotificationBell.jsx";
import SlovarButton from "./Slovar.jsx";
import ZhdetMenya from "./ZhdetMenya.jsx";
import { useVid } from "../vid.jsx";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";

const MONO = "'JetBrains Mono', monospace";
const MAX_TABS = 12;

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
const TEMA_SLED = { light: "dark", dark: "auto", auto: "light" };
const TEMA_IKON = { light: "☀️", dark: "🌙", auto: "🌓" };
const TEMA_TEKST = { light: "Светлая тема", dark: "Тёмная тема", auto: "Тема как в системе" };

export default function TabWorkspace({ screens, tabs, activeId, rightId, dispatch, currentUser }) {
  const [tema, setTema] = useTema();
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
      } else if (e.altKey && !meta && /^Digit[1-9]$/.test(e.code)) {
        // Alt+1…9 — пункты главного меню по порядку (Сегодня, Входящие, Отчёты, Делянки…)
        const glavnye = NAV_GROUPS.filter((g) => !g.footer && !g.igra).flatMap((g) => g.items.map(([k]) => k));
        const id = glavnye[Number(e.code.slice(5)) - 1];
        if (id) { e.preventDefault(); dispatch({ type: "open", id }); }
      } else if (!meta && !e.altKey && !e.shiftKey && !e.target.closest?.("input, textarea, select, [contenteditable=true]")) {
        // одиночные клавиши — по месту клавиши, раскладка не важна
        if (e.code === "KeyN") { e.preventDefault(); setPalette(true); setQuery("наряд "); }
        else if (e.code === "KeyT") { e.preventDefault(); openScreen("tabel", { tab: "mesyac" }); }
        else if (e.code === "KeyG") { e.preventDefault(); dispatch({ type: "open", id: "dashboard" }); }
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
    const k = razobratKomandu(query);
    const q = (k ? k.poisk || "" : query).trim();
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
    const k = razobratKomandu(query);
    if (k) return komandyItems(k, naydeno);
    return q ? [...nashli, ...ekrany] : ekrany;
  }, [query, naydeno]);

  // Команды Ctrl+K (шаг 6 разбора 09.11.2026) — см. komandy.js
  function komandyItems(k, nd) {
    if (k.tip === "naryad") {
      const del = nd.filter((n) => n.tip === "delyanka");
      const poz = k.pozicii.length ? opisaniePoziciy(k.pozicii) : "позиции впишете в форме";
      if (!del.length) return [{ key: "nr-none", emoji: "📝", label: `Наряд: делянка «${k.kvvd}» не найдена`, hint: "Пишите квартал/выдел: наряд 71/2 С 12,4 Б 3,1", meta: "команда" }];
      const [kv, vd] = String(k.kvvd).split(/[/\-]/);
      return del.map((n, i) => ({
        key: `nr${i}`, emoji: "📝", label: `Новый наряд · ${n.title}`, hint: poz, meta: "команда",
        run: () => openScreen("raskhod", { d: n.params.d, kv: kv || "", vd: vd || "", naryad: JSON.stringify(k.pozicii) }),
      }));
    }
    if (k.tip === "qgis") {
      return nd.filter((n) => ["delyanka", "vydel", "kultury"].includes(n.tip)).map((n, i) => ({
        key: `qg${i}`, emoji: "🗺", label: `Показать в QGIS · ${n.title}`, hint: n.hint, meta: "команда",
        run: () => api.post("/map/qgis/pokazat", n.tip === "vydel"
          ? { tip: "vydel", kvartal: n.params.kv, vydel: n.params.vyd, nazvanie: n.title }
          : { tip: n.tip === "kultury" ? "lesokultury" : "delyanka", id: Number(n.params.d || n.params.u || n.params.id) || null, nazvanie: n.title }),
      }));
    }
    if (k.tip === "tema") {
      return [["dark", "🌙 Тёмная тема"], ["light", "☀ Светлая тема"], ["auto", "◐ Как в системе"]]
        .sort((a, b) => (a[0] === k.tema ? -1 : b[0] === k.tema ? 1 : 0))
        .map(([t, label]) => ({ key: `t-${t}`, emoji: "", label, meta: "тема", run: () => setTema(t) }));
    }
    if (k.tip === "tabel") return [{ key: "tb", emoji: "📅", label: "Табель за месяц (Т-13)", hint: "сетка люди × числа, Excel, печать", meta: "команда", run: () => openScreen("tabel", { tab: "mesyac" }) }];
    if (k.tip === "itogi") return [{ key: "it", emoji: "🏁", label: "Итоги сезона", hint: "год целиком и сравнение с прошлым", meta: "команда", run: () => openScreen("otchety", { vid: "sezon" }) }];
    if (k.tip === "pechat") {
      return [{ key: "pr", emoji: "🖨", label: `Напечатать «${screens[activeId]?.title ?? activeId}»`, meta: "команда",
        run: () => { const b = document.querySelector(`[data-panel-id="${activeId}"] [data-panel-body]`); if (b) napechatat(b, { title: screens[activeId]?.title }); } }];
    }
    return [];
  }
  useEffect(() => setVybor(0), [items.length, query]);

  const openFromPalette = (it) => {
    if (!it) return;
    if (it.run) it.run();
    else if (it.ssylka) openScreen(it.ssylka.screen, it.ssylka.params || {});
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
      <div className="flex items-stretch" style={{ gap: 8, background: "var(--color-surface-alt)", borderBottom: "1px solid var(--color-border)", padding: "7px 10px 0", minHeight: 52 }}>
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
                  border: `1px solid ${active || side ? "var(--color-border)" : "transparent"}`,
                  borderBottom: 0,
                  background: active ? "var(--color-paper)" : side ? "var(--color-surface)" : "transparent",
                  boxShadow: active ? "inset 0 2px 0 var(--color-pine)" : side ? "inset 0 2px 0 var(--color-mint)" : "none",
                  color: active ? "var(--color-pine)" : "var(--color-muted)",
                }}
              >
                <span style={{ width: 7, height: 7, borderRadius: 999, flexShrink: 0, background: active ? "var(--color-pine)" : "var(--c-line-strong)" }} />
                <span className="flex flex-col min-w-0">
                  <span className="truncate" style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap" }}>{meta?.title ?? id}</span>
                  <span style={{ fontFamily: MONO, fontSize: 10, color: "var(--color-muted-2)", whiteSpace: "nowrap" }}>{GROUP_OF[id]?.group}</span>
                </span>
                <button
                  type="button"
                  title="Открыть во второй панели"
                  onClick={(e) => { e.stopPropagation(); dispatch({ type: "side", id }); }}
                  className="shrink-0 hover:!bg-[var(--color-border)] hover:!text-[var(--color-pine)]"
                  style={{ width: 22, height: 22, border: 0, borderRadius: 6, background: "transparent", color: side ? "var(--color-pine)" : "var(--color-disabled)", fontSize: 12, cursor: "pointer" }}
                >
                  ⇥
                </button>
                <button
                  type="button"
                  title="Закрыть вкладку"
                  onClick={(e) => { e.stopPropagation(); dispatch({ type: "close", id }); }}
                  className="shrink-0 hover:!bg-[var(--color-border)] hover:!text-[var(--color-error)]"
                  style={{ width: 22, height: 22, border: 0, borderRadius: 6, background: "transparent", color: "var(--color-disabled)", fontSize: 15, cursor: "pointer" }}
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
            className="shrink-0 hover:!border-[var(--color-pine)] hover:!text-[var(--color-pine)] hover:!bg-white"
            style={{ marginBottom: 7, height: 30, width: 30, border: "1px dashed var(--c-line-strong)", background: "transparent", color: "var(--color-muted)", borderRadius: 8, fontSize: 16, cursor: "pointer" }}
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
            style={{ height: 30, border: `1px solid ${vid === "igra" ? "var(--c-gold)" : "var(--color-border)"}`, borderRadius: 8, overflow: "hidden" }}
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
                  background: vid === k ? (k === "igra" ? "var(--c-gold-soft)" : "var(--color-mint-soft)") : "var(--color-surface)",
                  color: vid === k ? (k === "igra" ? "#7a5600" : "var(--color-pine)") : "var(--color-disabled)",
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
              className="hover:!border-[var(--c-gold)]"
              style={{
                height: 30, padding: "0 10px", borderRadius: 8, fontSize: 12.5, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
                border: `1px solid ${kvestyOn ? "var(--c-gold)" : "var(--color-border)"}`,
                background: kvestyOn ? "var(--c-gold-soft)" : "var(--color-surface)",
                color: kvestyOn ? "#7a5600" : "var(--color-muted)",
              }}
            >
              🎯 Квесты
            </button>
          )}
          <button
            type="button"
            onClick={() => setTema(TEMA_SLED[tema])}
            title={`${TEMA_TEKST[tema]} — нажмите: ${TEMA_TEKST[TEMA_SLED[tema]].toLowerCase()}`}
            aria-label={TEMA_TEKST[tema]}
            className="hover:!border-[var(--color-pine)]"
            style={{ height: 30, width: 32, borderRadius: 8, fontSize: 14, cursor: "pointer", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-muted)" }}
          >
            {TEMA_IKON[tema]}
          </button>
          <NotificationBell onNavigate={(id) => dispatch({ type: "open", id })} />
          <button
            type="button"
            onClick={toggleSplit}
            className="hover:!border-[var(--color-pine)] hover:!text-[var(--color-pine)]"
            style={{
              height: 30, padding: "0 12px", borderRadius: 8, fontSize: 12.5, fontWeight: 600, cursor: "pointer",
              border: `1px solid ${rightId ? "var(--color-pine)" : "var(--color-border)"}`,
              background: rightId ? "var(--color-mint-soft)" : "var(--color-surface)",
              color: rightId ? "var(--color-pine)" : "var(--color-muted)",
            }}
          >
            Две панели
          </button>
        </div>
      </div>

      {/* панели */}
      <div className="flex-1 min-h-0 flex flex-wrap content-start overflow-y-auto" style={{ gap: 1, background: "var(--color-border)" }}>
        {tabs.map((id) => {
          const meta = screens[id];
          const role = id === activeId ? "left" : id === rightId ? "right" : null;
          const Page = meta?.Page;
          return (
            <div
              key={id}
              data-panel
              data-panel-id={id}
              className="flex-col overflow-hidden"
              style={{
                display: role ? "flex" : "none",
                flex: role === "right" ? "1 1 330px" : "2 1 420px",
                minWidth: "min(100%, 330px)",
                minHeight: 0,
                height: "100%",
                maxHeight: "100%",
                background: "var(--color-paper)",
                order: role === "right" ? 2 : 1,
              }}
            >
              <div className="flex items-center justify-between flex-wrap" style={{ gap: "6px 10px", padding: "12px 18px", background: "var(--color-paper)", borderBottom: "1px solid var(--color-border)" }}>
                <div className="min-w-0" style={{ flex: "1 1 150px" }}>
                  <div className="truncate" style={{ fontSize: 15.5, fontWeight: 800, color: "var(--color-pine)" }}>{meta?.title ?? id}</div>
                  <div className="flex items-center min-w-0" style={{ gap: 7, marginTop: 3 }}>
                    <span className="truncate" style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--color-muted-2)" }}>{meta?.subtitle}</span>
                    <span
                      className="shrink-0"
                      style={{
                        fontFamily: MONO, fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase", whiteSpace: "nowrap",
                        color: role === "right" ? "var(--color-muted-2)" : "var(--color-pine)",
                        background: role === "right" ? "var(--color-surface-alt)" : "var(--color-mint-soft)",
                        border: `1px solid ${role === "right" ? "var(--color-border)" : "var(--color-mint)"}`,
                        borderRadius: 999, padding: "1px 7px",
                      }}
                    >
                      {role === "right" ? "справочная панель" : "рабочая панель"}
                    </span>
                  </div>
                </div>
                <div className="shrink-0 flex items-center" style={{ gap: 6 }}>
                <button
                  type="button"
                  title="Напечатать этот экран начисто: без меню и кнопок, на белом листе"
                  onClick={(e) => {
                    const body = e.currentTarget.closest("[data-panel]")?.querySelector("[data-panel-body]");
                    napechatat(body, { title: meta?.title ?? id, landscape: body && body.scrollWidth > 900 });
                  }}
                  className="shrink-0 hover:!border-[var(--color-pine)] hover:!text-[var(--color-pine)]"
                  style={{ height: 28, width: 32, border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-muted)", borderRadius: 8, fontSize: 13, cursor: "pointer" }}
                >
                  🖨
                </button>
                <button
                  type="button"
                  title={role === "right" ? "Вернуть в одну панель" : "Открыть эту вкладку во второй панели"}
                  onClick={() => (role === "right" ? dispatch({ type: "unsplit" }) : dispatch({ type: "side", id }))}
                  className="shrink-0 hover:!border-[var(--color-pine)] hover:!text-[var(--color-pine)]"
                  style={{ height: 28, padding: "0 10px", border: "1px solid var(--color-border)", background: "var(--color-surface)", color: "var(--color-muted)", borderRadius: 8, fontSize: 12, whiteSpace: "nowrap", cursor: "pointer" }}
                >
                  {role === "right" ? "Закрыть" : "Рядом"}
                </button>
                </div>
              </div>
              <div data-panel-body className="flex-1 min-h-0 overflow-y-auto">
                {Page ? <Page currentUser={currentUser} onOpenTab={(k) => dispatch({ type: "open", id: k })} /> : <div className="p-8 text-muted">Экран «{id}» не найден</div>}
              </div>
            </div>
          );
        })}
        {tabs.length === 0 && (
          <div className="flex-1 flex items-center justify-center" style={{ background: "var(--color-paper)", color: "var(--color-muted-2)" }}>
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
            style={{ width: "min(520px, 92vw)", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: 16, boxShadow: "0 12px 32px rgba(15,42,29,.18)", overflow: "hidden" }}
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
              placeholder="Найти или команда: наряд 71/2 С 12,4 · qgis 71/2 · табель…"
              style={{ width: "100%", height: 48, border: 0, borderBottom: "1px solid var(--color-border)", padding: "0 16px", fontSize: 15, color: "var(--color-ink)", outline: "none" }}
            />
            <div className="overflow-y-auto" style={{ maxHeight: 380, padding: 6 }}>
              {items.map((it, i) => (
                <button
                  key={it.key}
                  type="button"
                  onClick={() => openFromPalette(it)}
                  onMouseEnter={() => setVybor(i)}
                  className="flex items-center justify-between w-full text-left"
                  style={{ gap: 10, background: i === vybor ? "var(--color-hover)" : "transparent", border: 0, borderRadius: 10, padding: it.hint ? "7px 12px" : "10px 12px", fontSize: 14, color: "var(--color-ink)", cursor: "pointer" }}
                >
                  <span className="flex items-center min-w-0" style={{ gap: 10 }}>
                    <span style={{ width: 20, textAlign: "center", flexShrink: 0, color: "var(--color-faint)" }}>{it.emoji}</span>
                    <span className="min-w-0">
                      <span className="block truncate">{it.label}</span>
                      {it.hint && <span className="block truncate" style={{ fontSize: 11.5, color: "var(--color-faint)" }}>{it.hint}</span>}
                    </span>
                  </span>
                  <span style={{ fontFamily: MONO, fontSize: 10.5, color: "var(--color-faint)", flexShrink: 0 }}>{it.meta}</span>
                </button>
              ))}
              {!items.length && (
                <div style={{ padding: "14px 12px", fontSize: 13, color: "var(--color-faint)" }}>Ничего не нашлось. Квартал и выдел можно писать так: 71/2 или «кв 71 выд 2».</div>
              )}
            </div>
            <div style={{ borderTop: "1px solid var(--color-border)", padding: "7px 14px", fontFamily: MONO, fontSize: 10, color: "#8a8f86" }}>
              ↑↓ Enter Esc · N — наряд · T — табель · G — сегодня · Alt+1…9 — меню · Ctrl+1…9 — вкладки
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
