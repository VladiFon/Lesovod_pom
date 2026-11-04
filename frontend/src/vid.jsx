import React, { useEffect, useState } from "react";

// Вид интерфейса «обычный / игровой» (просьба Влада 03.11.2026): старые
// экраны не пропадают — переключатель в шапке и в Настройках меняет вид
// тех экранов, у которых есть игровой вариант (сейчас: Табель →
// «Перекличка»). Выбор помнится в этом браузере.

const KEY = "lesovod_vid";
const EVENT = "lesovod-vid";

function read() {
  try {
    return localStorage.getItem(KEY) === "igra" ? "igra" : "obychnyy";
  } catch {
    return "obychnyy";
  }
}

export function setVid(v) {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    /* хранилище недоступно — вид не запомнится, но переключится */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: v }));
}

/** [vid, setVid]: vid — "obychnyy" | "igra". */
export function useVid() {
  const [vid, set] = useState(read);
  useEffect(() => {
    const on = (e) => set(e.detail);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return [vid, setVid];
}

/** Экран, который в игровом виде показывает свой игровой вариант. */
export function poVidu(Obychnyy, Igrovoy) {
  return function PoVidu(props) {
    const [vid] = useVid();
    return vid === "igra" ? <Igrovoy {...props} /> : <Obychnyy {...props} />;
  };
}
