/**
 * Команды в Ctrl+K (шаг 6 разбора сайта 09.11.2026).
 *
 * Вместо «открыл Расход → выбрал делянку → выбрал выдел → нажал ＋ наряд →
 * вписал породы» — одна строка:
 *   наряд 71/2 С 12,4 Б 3,1        — форма наряда с позициями, дата и № сами
 *   наряд 71/2 С ср 12,4 Б др 3    — с сортиментом (кр, ср, мл, др)
 *   qgis 71/2  (или «показать 71/2») — приблизить карту в QGIS
 *   тема тёмная / тема светлая
 *   табель — табель за месяц; итоги — итоги сезона; печать — этот экран
 */

const SORT = { кр: "KR", круп: "KR", ср: "SR", сред: "SR", мл: "ML", мел: "ML", др: "DROVA", дров: "DROVA", хв: "HVOROST" };
const KOD_PORODY = { с: "сосна", е: "ель", б: "берез", ос: "осин", ол: "ольх", олч: "ольха черн", д: "дуб", лп: "лип", г: "граб", кл: "клён", я: "ясен" };

/** «С 12,4 Б ср 3,1» → [{p: "С", s: null, v: 12.4}, {p: "Б", s: "SR", v: 3.1}] */
export function razobratPozicii(tekst) {
  const out = [];
  let tek = null;
  for (const t of String(tekst || "").replace(/;/g, " ").split(/\s+/).filter(Boolean)) {
    const chislo = Number(t.replace(",", "."));
    const nizh = t.toLowerCase().replace(/\.$/, "");
    if (Number.isFinite(chislo) && /\d/.test(t)) {
      if (tek) { out.push({ ...tek, v: chislo }); tek = null; }
    } else if (tek && SORT[nizh]) {
      tek.s = SORT[nizh];
    } else {
      tek = { p: t, s: null };
    }
  }
  return out;
}

/** Порода из команды → порода из списка выдела («С» → «Сосна»). */
export function nayitPorodu(p, porody) {
  const n = String(p || "").toLowerCase().replace("ё", "е");
  const norm = (x) => String(x).toLowerCase().replace("ё", "е");
  return (
    porody.find((x) => norm(x) === n)
    || porody.find((x) => norm(x).startsWith(KOD_PORODY[n] || "\u0000"))
    || porody.find((x) => norm(x).startsWith(n))
    || ""
  );
}

export function opisaniePoziciy(poz) {
  const SN = { KR: "кр", SR: "ср", ML: "мл", DROVA: "др", HVOROST: "хв" };
  return poz.map((x) => `${x.p}${x.s ? ` ${SN[x.s]}` : ""} ${String(x.v).replace(".", ",")}`).join(" · ");
}

/**
 * Разобрать строку палитры. Возвращает null (обычный поиск) или
 * { tip, poisk?, ... } — poisk: что искать на сервере вместо всей строки.
 */
export function razobratKomandu(stroka) {
  const q = String(stroka || "").trim();
  let m = q.match(/^наряд\s+(\S+)\s*(.*)$/i);
  if (m) return { tip: "naryad", poisk: m[1], kvvd: m[1], pozicii: razobratPozicii(m[2]) };
  m = q.match(/^(?:qgis|кгис|показать)\s+(.+)$/i);
  if (m) return { tip: "qgis", poisk: m[1] };
  m = q.match(/^тема\s*(.*)$/i);
  if (m) return { tip: "tema", tema: /т[её]мн|ноч|dark/i.test(m[1]) ? "dark" : /светл|ден|light/i.test(m[1]) ? "light" : /авто|сист/i.test(m[1]) ? "auto" : null };
  if (/^(табель|т-13|т13)/i.test(q)) return { tip: "tabel" };
  if (/^(итоги|сезон)/i.test(q)) return { tip: "itogi" };
  if (/^(печать|распечат)/i.test(q)) return { tip: "pechat" };
  return null;
}

export const PODSKAZKA_KOMAND = [
  ["наряд 71/2 С 12,4 Б ср 3,1", "наряд с позициями"],
  ["qgis 71/2", "показать в QGIS"],
  ["табель · итоги · печать · тема тёмная", ""],
];
