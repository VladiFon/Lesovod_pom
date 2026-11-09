import { useEffect, useState } from "react";

// Адрес в строке браузера: #/<экран>?d=<делянка> — чтобы после F5 открывался
// тот же экран и та же делянка, а ссылку можно было переслать коллеге
// (анализ удобства 01.10.2026). Параметры каждого экрана помним и тогда,
// когда вкладка не активна, — при возврате на неё адрес восстановится.

const params = {}; // экран -> { d: "5", ... }
const EVENT = "lesovod-nav";

// Старые экраны, которые стали вкладками объединённых (шаг 4 разбора
// 03.11.2026): ссылки, закладки и колокольчик со старыми адресами
// по-прежнему работают.
export const ALIASES = {
  ai_log: { screen: "telefon", tab: "otchety" },
  worker_notes: { screen: "telefon", tab: "zametki" },
  attendance: { screen: "tabel", tab: "prisutstvie" },
  work_plan: { screen: "zadachi", tab: "plan" },
  calendar: { screen: "zadachi", tab: "kalendar" },
};

// Шаг 4 разбора «сайт разбросан» (04.11.2026): меню по делам. Вкладки,
// уехавшие с «С телефона» (теперь «Входящие» — только то, что ждёт
// проверки): техника и топливо — свой экран, отчёты за смену и журнал
// выполненных работ — в «Журнал работ». Старые адреса ведут туда же.
export const TAB_ALIASES = {
  telefon: {
    tehnika: { screen: "tehnika", tab: "tehnika" },
    toplivo: { screen: "tehnika", tab: "toplivo" },
    smena: { screen: "raboty", tab: "smena" },
    zhurnal: { screen: "raboty", tab: "zhurnal" },
  },
};

/** Старый адрес экрана → новый экран + параметры вкладки. */
export function resolveScreen(screen, p = {}) {
  const a = ALIASES[screen];
  if (a) return { screen: a.screen, params: { tab: a.tab, ...p } };
  const t = TAB_ALIASES[screen]?.[p.tab];
  if (t) return { screen: t.screen, params: { ...p, tab: t.tab } };
  return { screen, params: p };
}


export function readHash() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, q] = raw.split("?");
  return { screen: path || null, params: Object.fromEntries(new URLSearchParams(q || "")) };
}

function hashFor(screen) {
  const q = new URLSearchParams(
    Object.entries(params[screen] || {}).filter(([, v]) => v !== "" && v != null)
  ).toString();
  return `#/${screen}${q ? `?${q}` : ""}`;
}

// Записать адрес активного экрана (без новой записи в историю — Назад
// в браузере не должен перебирать каждый клик по списку делянок).
export function syncHash(screen, { push = false } = {}) {
  if (!screen) return;
  const h = hashFor(screen);
  if (window.location.hash === h) return;
  if (push) window.history.pushState(null, "", h);
  else window.history.replaceState(null, "", h);
}

// Начальные параметры из адреса при загрузке страницы.
(() => {
  const h = readHash();
  if (!h.screen) return;
  const { screen, params: p } = resolveScreen(h.screen, h.params);
  params[screen] = p;
})();

/**
 * Значение параметра экрана (например, выбранная делянка «d»), которое
 * переживает F5 и меняется по ссылке из другого экрана (openScreen).
 */
export function useScreenParam(screen, key) {
  const [value, setValue] = useState(() => params[screen]?.[key] ?? "");
  useEffect(() => {
    const onNav = (e) => {
      if (e.detail?.screen === screen && e.detail.params && key in e.detail.params) {
        setValue(e.detail.params[key] ?? "");
      }
    };
    window.addEventListener(EVENT, onNav);
    return () => window.removeEventListener(EVENT, onNav);
  }, [screen, key]);
  const set = (v) => {
    const s = v == null ? "" : String(v);
    params[screen] = { ...(params[screen] || {}), [key]: s };
    setValue(s);
    if (readHash().screen === screen) syncHash(screen);
  };
  return [value, set];
}

/** Адрес поменяли снаружи (кнопка «Назад», вставили ссылку) — подхватить. */
export function applyHash() {
  const h = readHash();
  if (!h.screen) return null;
  const { screen, params: p } = resolveScreen(h.screen, h.params);
  params[screen] = p;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { screen, params: { d: "", ...p } } }));
  return screen;
}

let opener = null;
export function setScreenOpener(fn) {
  opener = fn;
}

/** Открыть экран (вкладку) с параметрами — для перекрёстных ссылок. */
export function openScreen(screen0, p0 = {}) {
  const { screen, params: p } = resolveScreen(screen0, p0);
  params[screen] = { ...(params[screen] || {}), ...Object.fromEntries(Object.entries(p).map(([k, v]) => [k, v == null ? "" : String(v)])) };
  opener?.(screen);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { screen, params: params[screen] } }));
}
