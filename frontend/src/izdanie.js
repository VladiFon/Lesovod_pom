// «Издание» сервера (backend app/izdanie.py, просьба Влада 04.11.2026):
// одна и та же программа работает у лесничества и у лесопункта, у каждого
// своя копия сервера со своей базой. Сервер говорит, кто он, — меню прячет
// экраны, которых у этого издания нет.
//
// Загружается один раз до отрисовки (main.jsx), поэтому дальше читается
// синхронно: skryt("forestry"), podpis().

let dannye = { izdanie: "lesnichestvo", nazvanie: "Лесничество", organizaciya: null, skryt_ekrany: [] };
let skrytye = new Set();

export async function zagruzitIzdanie() {
  try {
    const r = await fetch("/api/izdanie");
    if (r.ok) {
      dannye = { ...dannye, ...(await r.json()) };
      skrytye = new Set(dannye.skryt_ekrany || []);
    }
  } catch {
    // сервер недоступен — показываем всё как у лесничества; экран входа
    // всё равно скажет, что нет связи
  }
  return dannye;
}

/** Экран спрятан в этом издании? */
export function skryt(key) {
  return skrytye.has(key);
}

export function izdanie() {
  return dannye;
}

/** Подпись под «Лесовод» в меню и на экране входа. */
export function podpis(poUmolchaniyu) {
  if (dannye.izdanie === "lesnichestvo") return dannye.organizaciya || poUmolchaniyu;
  return dannye.organizaciya || dannye.nazvanie;
}
