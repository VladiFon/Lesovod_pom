import { useEffect, useState } from "react";

/**
 * Светлая / тёмная тема (шаг 4 разбора сайта 09.11.2026).
 *
 * Выбор хранится в браузере (lesovod_tema): "light", "dark" или "auto" —
 * как в Windows/телефоне. Тема — атрибут data-theme у <html>; все цвета
 * сайта — переменные из design-tokens.css, которые там переопределены.
 */
const KEY = "lesovod_tema";
const EVENT = "lesovod-tema";

export function getTema() {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "auto") return v;
  } catch { /* приватный режим */ }
  return "auto";
}

function sistemnayaTemnaya() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function primenitTemu(tema = getTema()) {
  const temnaya = tema === "dark" || (tema === "auto" && sistemnayaTemnaya());
  document.documentElement.setAttribute("data-theme", temnaya ? "dark" : "light");
  return temnaya;
}

export function setTema(tema) {
  try { localStorage.setItem(KEY, tema); } catch { /* приватный режим */ }
  primenitTemu(tema);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: tema }));
}

export function useTema() {
  const [tema, setT] = useState(getTema);
  const [temnaya, setTemnaya] = useState(() => document.documentElement.getAttribute("data-theme") === "dark");
  useEffect(() => {
    const on = () => { const t = getTema(); setT(t); setTemnaya(primenitTemu(t)); };
    window.addEventListener(EVENT, on);
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener?.("change", on);
    return () => { window.removeEventListener(EVENT, on); mq?.removeEventListener?.("change", on); };
  }, []);
  return [tema, setTema, temnaya];
}
