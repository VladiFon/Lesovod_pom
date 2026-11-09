/**
 * Удобный поиск по кварталу/выделу (просьба Влада 09.11.2026) — тот же
 * принцип, что backend legacy/db.py: poisk_kv_vyd.
 *   «71/2», «71 2», «кв 71 выд 2» — ровно квартал 71, выдел 2;
 *   «71» / «кв 71» — сначала квартал 71, потом остальное, где есть «71»;
 *   любой другой текст — все слова должны встретиться в полях.
 */
export function razobratKvVyd(search) {
  let q = String(search || "").trim().toLowerCase();
  if (!q) return null;
  q = q.replace(/(^|[^0-9a-zа-яё])(квартал|кв|выдел|выд|в)\.?\s*/g, "$1 ");
  const parts = q.split(/[\s/\\,;:-]+/).filter(Boolean);
  if (!parts.length || parts.length > 2 || !/^\d/.test(parts[0])) return null;
  if (!parts.every((p) => /^[0-9a-zа-яё]+$/.test(p))) return null;
  return { kv: parts[0], vd: parts.length === 2 ? parts[1] : null };
}

const norm = (v) => String(v ?? "").trim().toLowerCase();

/** items — массив; fields — функция (item) → массив строк для поиска словами. */
export function poiskKvVyd(items, search, { kv = (i) => i.kvartal, vd = (i) => i.vydel, fields } = {}) {
  const q = norm(search);
  if (!q) return items;
  const stog = (i) => (fields ? fields(i) : [kv(i), vd(i)]).map(norm).join(" ");
  const p = razobratKvVyd(search);
  if (p) {
    if (p.vd !== null) {
      const tochno = items.filter((i) => norm(kv(i)) === p.kv && norm(vd(i)) === p.vd);
      if (tochno.length) return tochno;
    } else {
      const tochno = items.filter((i) => norm(kv(i)) === p.kv);
      const ost = items.filter((i) => norm(kv(i)) !== p.kv && stog(i).includes(q));
      return [...tochno, ...ost];
    }
  }
  const words = q.replace(/[/,]/g, " ").split(/\s+/).filter(Boolean);
  return items.filter((i) => {
    const s = stog(i);
    return words.every((w) => s.includes(w));
  });
}
