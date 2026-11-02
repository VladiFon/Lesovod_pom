import React from "react";
import TextField from "./TextField.jsx";

/**
 * DateField — календарик (нативный <input type="date">) для дат, которые в
 * базе и в документах хранятся строкой «ДД.ММ.ГГГГ» (сроки делянки, дата
 * акта, основание…). Пикер работает в ISO ГГГГ-ММ-ДД, поэтому туда-обратно
 * конвертируем здесь, а наружу (value/onChange) — по-прежнему «ДД.ММ.ГГГГ»,
 * чтобы бэкенд и генераторы документов ничего не заметили.
 *
 * Если в базе лежит что-то, что не разбирается как дата (старый ручной
 * ввод), показываем обычное текстовое поле — чтобы не потерять значение.
 */
export function ruToIso(v) {
  const s = String(v || "").trim();
  let m = s.match(/^(\d{1,2})[.,/](\d{1,2})[.,/](\d{4})$/);
  if (m) return `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  return null;
}

export function isoToRu(v) {
  const m = String(v || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : "";
}

export default function DateField({ value, onChange, ...rest }) {
  const iso = ruToIso(value);
  if (value && !iso) {
    return (
      <TextField
        placeholder="ДД.ММ.ГГГГ"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/,/g, "."))}
        hint="Не похоже на дату — исправьте или очистите поле"
        {...rest}
      />
    );
  }
  return <TextField type="date" value={iso || ""} onChange={(e) => onChange(isoToRu(e.target.value))} {...rest} />;
}
