import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Сводки экрана «Расход / ЕГАИС» (30.09.2026):
 *   - Расход ЕГАИС: кто оформил, объём, кому, продукция, с какой делянки;
 *   - Приход ЕГАИС: сколько, какой продукции, с какой делянки;
 *   - Приход по нарядам: то же по нарядам-заданиям приложения.
 * Итоги везде делятся на деловую древесину, дрова и общий итог.
 *
 * Сервер (GET /raskhod/svodka/egais|naryady, см. app/svodka_raskhod.py)
 * отдаёт строки «документ × продукция» за период; остальные фильтры и
 * группировка — здесь, на клиенте. Excel строится сервером из того, что
 * показано на экране (POST /raskhod/svodka/excel).
 */

const TABS = [
  { key: "raskhod", label: "Расход ЕГАИС" },
  { key: "prihod", label: "Приход ЕГАИС" },
  { key: "naryady", label: "Приход по нарядам" },
];

const GROUPS = [
  { key: "delovaya", label: "Деловая древесина", totalLabel: "Итого деловая" },
  { key: "drova", label: "Дрова", totalLabel: "Итого дрова" },
  { key: "hvorost", label: "Хворост", totalLabel: "Итого хворост" },
];

const NEPRIVYAZAN = "__none__";

function delyankaText(r) {
  if (r.vydel_label) return r.vydel_label;
  return `склад не привязан: ${r.sklad || "—"}`;
}

// Колонки подробного режима и ключи группировки по вкладкам.
const DETAIL_COLUMNS = {
  raskhod: [
    { key: "data", label: "Дата", width: 11 },
    { key: "nomer", label: "№ документа", width: 24 },
    { key: "tip_short", label: "Тип", width: 14 },
    { key: "sotrudnik", label: "Кто оформил", width: 18 },
    { key: "poluchatel", label: "Кому", width: 26 },
    { key: "osnovanie", label: "Основание", width: 24 },
    { key: "delyanka_text", label: "Делянка", width: 36 },
    { key: "produkciya", label: "Продукция", width: 34 },
    { key: "obyom", label: "Объём, м³", width: 11 },
  ],
  prihod: [
    { key: "data", label: "Дата", width: 11 },
    { key: "nomer", label: "№ документа", width: 24 },
    { key: "sotrudnik", label: "Кто оформил", width: 18 },
    { key: "delyanka_text", label: "Делянка", width: 40 },
    { key: "produkciya", label: "Продукция", width: 36 },
    { key: "obyom", label: "Объём, м³", width: 11 },
  ],
  naryady: [
    { key: "data", label: "Дата", width: 11 },
    { key: "nomer", label: "№ наряда", width: 12 },
    { key: "delyanka_text", label: "Делянка", width: 40 },
    { key: "produkciya", label: "Продукция", width: 26 },
    { key: "obyom", label: "Объём, м³", width: 11 },
  ],
};

const GROUP_BY = {
  raskhod: [
    { key: "", label: "Подробно (по документам)" },
    { key: "delyanka_text", label: "По делянкам", head: "Делянка" },
    { key: "poluchatel", label: "По получателям", head: "Кому (получатель)" },
    { key: "sotrudnik", label: "По сотрудникам", head: "Кто оформил" },
    { key: "produkciya", label: "По продукции", head: "Продукция" },
    { key: "poroda", label: "По породам", head: "Порода" },
  ],
  prihod: [
    { key: "", label: "Подробно (по документам)" },
    { key: "delyanka_text", label: "По делянкам", head: "Делянка" },
    { key: "sotrudnik", label: "По сотрудникам", head: "Кто оформил" },
    { key: "produkciya", label: "По продукции", head: "Продукция" },
    { key: "poroda", label: "По породам", head: "Порода" },
  ],
  naryady: [
    { key: "", label: "Подробно (по нарядам)" },
    { key: "delyanka_text", label: "По делянкам", head: "Делянка" },
    { key: "produkciya", label: "По продукции", head: "Продукция" },
    { key: "poroda", label: "По породам", head: "Порода" },
  ],
};

const fmt3 = (v) => (v ?? 0).toLocaleString("ru-RU", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const MONO = { fontFamily: "'JetBrains Mono', monospace" };
const SELECT_CLS =
  "w-full bg-surface border border-border focus:border-pine rounded-md px-2.5 py-2 text-sm text-ink outline-none";

function uniqSorted(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
}

function Field({ label, children, className = "" }) {
  return (
    <div className={className}>
      <label className="block text-[11px] font-semibold tracking-wide text-muted-2 uppercase mb-1">{label}</label>
      {children}
    </div>
  );
}

// Выпадающий список с галочками — можно выбрать несколько значений.
// value — массив выбранных значений; пустой массив = «Все».
function MultiSelect({ value, onChange, options, allLabel = "Все" }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef(null);
  const opts = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const selected = new Set(value);
  const toggle = (v) => onChange(selected.has(v) ? value.filter((x) => x !== v) : [...value, v]);
  const shown = q.trim() ? opts.filter((o) => o.label.toLowerCase().includes(q.trim().toLowerCase())) : opts;
  const caption = !value.length
    ? allLabel
    : value.length === 1
      ? opts.find((o) => o.value === value[0])?.label || value[0]
      : `Выбрано: ${value.length}`;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={[SELECT_CLS, "text-left truncate pr-7", value.length ? "border-pine font-semibold" : ""].join(" ")}
        title={value.length > 1 ? value.map((v) => opts.find((o) => o.value === v)?.label || v).join("; ") : undefined}
      >
        {caption}
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted text-xs">▾</span>
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full min-w-[240px] bg-surface border border-border rounded-md shadow-modal p-2">
          {opts.length > 8 && (
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Найти…"
              className={SELECT_CLS + " mb-1.5"}
            />
          )}
          <div className="flex items-center justify-between text-xs mb-1 px-1">
            <button type="button" className="underline text-muted" onClick={() => onChange([...new Set([...value, ...shown.map((o) => o.value)])])}>
              выбрать {q.trim() ? "найденные" : "все"}
            </button>
            <button type="button" className="underline text-muted" onClick={() => onChange([])}>очистить</button>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {shown.map((o) => (
              <label key={o.value} className="flex items-start gap-2 px-1 py-1 rounded hover:bg-hover cursor-pointer text-sm text-ink">
                <input type="checkbox" className="mt-0.5" checked={selected.has(o.value)} onChange={() => toggle(o.value)} />
                <span>{o.label}</span>
              </label>
            ))}
            {!shown.length && <div className="text-xs text-muted px-1 py-2">Ничего не найдено</div>}
          </div>
        </div>
      )}
    </div>
  );
}

async function downloadExcel(payload, filename) {
  const token = localStorage.getItem("lesovod_token");
  const res = await fetch(`${API_BASE_URL}/raskhod/svodka/excel`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Ошибка сервера (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const EMPTY_FILTERS = { delyanka: [], sotrudnik: [], poluchatel: [], poroda: [], vid: [], tip: [], q: "" };
const hasFilters = (f) => Object.values(f).some((v) => (Array.isArray(v) ? v.length > 0 : Boolean(v)));

export default function SvodkiModal({ open, onClose, initialTab = "raskhod", delyankaId }) {
  const toast = useToast();
  const [tab, setTab] = useState(initialTab);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [groupBy, setGroupBy] = useState("");
  const [exporting, setExporting] = useState(false);
  // «Скрыть непривязанные склады» — запоминается в браузере.
  const [hideUnlinked, setHideUnlinked] = useState(() => {
    try { return localStorage.getItem("svodki_hide_unlinked") === "1"; } catch { return false; }
  });
  const toggleHideUnlinked = (v) => {
    setHideUnlinked(v);
    try { localStorage.setItem("svodki_hide_unlinked", v ? "1" : "0"); } catch { /* нет хранилища */ }
  };

  useEffect(() => {
    if (!open) return;
    setTab(initialTab);
  }, [open, initialTab]);

  // Делянку, выбранную на основном экране, подставляем в фильтр по умолчанию.
  useEffect(() => {
    if (!open) return;
    setFilters({ ...EMPTY_FILTERS, delyanka: delyankaId ? [String(delyankaId)] : [] });
    setGroupBy("");
  }, [open, tab, delyankaId]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    const params = { date_from: dateFrom || undefined, date_to: dateTo || undefined };
    const req = tab === "naryady"
      ? api.get("/raskhod/svodka/naryady", params)
      : api.get("/raskhod/svodka/egais", { ...params, napravlenie: tab });
    req
      .then((res) => {
        setRows((res.rows || []).map((r) => ({
          ...r,
          delyanka_text: delyankaText(r),
          tip_short: (r.tip || "").replace("Расход при внутреннем перемещении", "Перемещение").replace("Расход при реализации потребителю", "Реализация"),
        })));
        setMeta(res);
      })
      .catch((e) => {
        setRows([]);
        toast.show({ tone: "danger", title: "Не удалось загрузить сводку", description: e.message });
      })
      .finally(() => setLoading(false));
  }, [open, tab, dateFrom, dateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  const options = useMemo(() => {
    const del = new Map();
    let hasNone = false;
    rows.forEach((r) => {
      if (r.delyanka_id) del.set(String(r.delyanka_id), r.delyanka);
      else hasNone = true;
    });
    const delyanki = [...del.entries()]
      .map(([value, label]) => ({ value, label }))
      .sort((a, b) => a.label.localeCompare(b.label, "ru", { numeric: true }));
    if (hasNone && !hideUnlinked) delyanki.push({ value: NEPRIVYAZAN, label: "— склад не привязан к делянке" });
    return {
      delyanki,
      sotrudniki: uniqSorted(rows.map((r) => r.sotrudnik)),
      poluchateli: uniqSorted(rows.map((r) => r.poluchatel)),
      porody: uniqSorted(rows.map((r) => r.poroda)),
      tipy: uniqSorted(rows.map((r) => r.tip)),
    };
  }, [rows, hideUnlinked]);

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return rows.filter((r) => {
      if (hideUnlinked && !r.delyanka_id) return false;
      const inList = (list, v) => !list.length || list.includes(v);
      if (!inList(filters.delyanka, r.delyanka_id ? String(r.delyanka_id) : NEPRIVYAZAN)) return false;
      if (!inList(filters.sotrudnik, r.sotrudnik)) return false;
      if (!inList(filters.poluchatel, r.poluchatel)) return false;
      if (!inList(filters.poroda, r.poroda)) return false;
      if (!inList(filters.vid, r.group)) return false;
      if (!inList(filters.tip, r.tip)) return false;
      if (q) {
        const hay = [r.nomer, r.produkciya, r.osnovanie, r.poluchatel, r.sotrudnik, r.delyanka_text, r.primechanie]
          .join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, filters, hideUnlinked]);

  const unlinkedCount = useMemo(() => rows.filter((r) => !r.delyanka_id).length, [rows]);

  const groupOpt = GROUP_BY[tab].find((g) => g.key === groupBy);
  const groupLabel = groupOpt?.label || "";
  const columns = groupBy
    ? [
        { key: "name", label: groupOpt?.head || "", width: 48 },
        { key: "count", label: "Строк", width: 8 },
        { key: "obyom", label: "Объём, м³", width: 12 },
      ]
    : DETAIL_COLUMNS[tab];

  const sections = useMemo(() => {
    const out = [];
    GROUPS.forEach((g) => {
      const part = filtered.filter((r) => r.group === g.key);
      if (!part.length) return;
      const total = part.reduce((s, r) => s + (r.obyom || 0), 0);
      let list = part;
      if (groupBy) {
        const m = new Map();
        part.forEach((r) => {
          const name = r[groupBy] || "—";
          const cur = m.get(name) || { name, count: 0, obyom: 0 };
          cur.count += 1;
          cur.obyom += r.obyom || 0;
          m.set(name, cur);
        });
        list = [...m.values()].sort((a, b) => b.obyom - a.obyom);
      }
      out.push({ ...g, rows: list, total });
    });
    return out;
  }, [filtered, groupBy]);

  const grandTotal = sections.reduce((s, g) => s + g.total, 0);
  const setF = (k) => (v) => setFilters((f) => ({ ...f, [k]: v }));
  const tabLabel = TABS.find((t) => t.key === tab)?.label;

  const handleExcel = async () => {
    setExporting(true);
    try {
      const fparts = [];
      if (dateFrom || dateTo) fparts.push(`период ${dateFrom || "…"} — ${dateTo || "…"}`);
      const list = (arr, label = (v) => v) => arr.map(label).join(", ");
      if (filters.delyanka.length) fparts.push(`делянка: ${list(filters.delyanka, (v) => options.delyanki.find((d) => d.value === v)?.label || v)}`);
      if (filters.sotrudnik.length) fparts.push(`сотрудник: ${list(filters.sotrudnik)}`);
      if (filters.poluchatel.length) fparts.push(`получатель: ${list(filters.poluchatel)}`);
      if (filters.poroda.length) fparts.push(`порода: ${list(filters.poroda)}`);
      if (filters.vid.length) fparts.push(list(filters.vid, (v) => GROUPS.find((g) => g.key === v)?.label || v));
      if (filters.tip.length) fparts.push(list(filters.tip));
      if (filters.q) fparts.push(`поиск: ${filters.q}`);
      if (hideUnlinked && unlinkedCount) fparts.push("без непривязанных складов");
      if (groupBy) fparts.push(groupLabel.toLowerCase());
      const round3 = (v) => Math.round((v || 0) * 1000) / 1000;
      await downloadExcel({
        title: `Сводка: ${tabLabel}`,
        subtitle: fparts.join("; "),
        columns,
        sections: [
          ...sections.map((s) => ({
            title: s.label,
            rows: s.rows.map((r) => ({ ...r, obyom: round3(r.obyom) })),
            total_label: s.totalLabel,
            total: round3(s.total),
          })),
          { title: "", rows: [], total_label: "ВСЕГО", total: round3(grandTotal) },
        ],
      }, `svodka-${tab}.xlsx`);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось выгрузить Excel", description: e.message });
    } finally {
      setExporting(false);
    }
  };

  const isEgais = tab !== "naryady";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Сводки: расход и приход"
      size="xl"
      footer={
        <>
          <Button variant="secondary" onClick={handleExcel} disabled={exporting || loading || !filtered.length}>
            {exporting ? "Готовлю Excel…" : "📥 Excel"}
          </Button>
          <Button variant="ghost" onClick={onClose}>Закрыть</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 max-h-[78vh] overflow-y-auto">
        <div className="flex items-center gap-2 flex-wrap">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={["px-3 py-1.5 rounded-md text-sm font-semibold transition-colors border",
                tab === t.key ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover"].join(" ")}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 items-end">
          <Field label="Период с">
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={SELECT_CLS} />
          </Field>
          <Field label="по">
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={SELECT_CLS} />
          </Field>
          <Field label="Делянка" className="col-span-2">
            <MultiSelect value={filters.delyanka} onChange={setF("delyanka")} options={options.delyanki} allLabel="Все делянки" />
          </Field>
          <Field label="Вид">
            <MultiSelect value={filters.vid} onChange={setF("vid")} options={GROUPS.filter((g) => tab === "naryady" || g.key !== "hvorost").map((g) => ({ value: g.key, label: g.label }))} />
          </Field>
          <Field label="Порода">
            <MultiSelect value={filters.poroda} onChange={setF("poroda")} options={options.porody} />
          </Field>
          {isEgais && (
            <Field label="Кто оформил">
              <MultiSelect value={filters.sotrudnik} onChange={setF("sotrudnik")} options={options.sotrudniki} />
            </Field>
          )}
          {tab === "raskhod" && (
            <>
              <Field label="Кому" className="col-span-2">
                <MultiSelect value={filters.poluchatel} onChange={setF("poluchatel")} options={options.poluchateli} />
              </Field>
              <Field label="Тип расхода">
                <MultiSelect value={filters.tip} onChange={setF("tip")} options={options.tipy} />
              </Field>
            </>
          )}
          <Field label="Поиск" className={tab === "raskhod" ? "" : "col-span-2"}>
            <input
              value={filters.q}
              onChange={(e) => setF("q")(e.target.value)}
              placeholder={isEgais ? "№ документа, договор, продукция…" : "№ наряда, продукция…"}
              className={SELECT_CLS}
            />
          </Field>
          <Field label="Показать" className="col-span-2">
            <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)} className={SELECT_CLS}>
              {GROUP_BY[tab].map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
            </select>
          </Field>
        </div>

        <div className="flex items-center gap-2 flex-wrap text-sm">
          {GROUPS.map((g) => {
            const s = sections.find((x) => x.key === g.key);
            if (g.key === "hvorost" && !s) return null;
            return (
              <span key={g.key} className="px-3 py-1.5 rounded-md border border-border bg-surface-alt">
                {g.label}: <b style={MONO}>{fmt3(s?.total || 0)}</b> м³
              </span>
            );
          })}
          <span className="px-3 py-1.5 rounded-md border border-pine bg-pine text-white">
            Итого: <b style={MONO}>{fmt3(grandTotal)}</b> м³
          </span>
          {unlinkedCount > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-muted ml-1 cursor-pointer select-none">
              <input type="checkbox" checked={hideUnlinked} onChange={(e) => toggleHideUnlinked(e.target.checked)} />
              Скрыть непривязанные склады ({unlinkedCount} стр.)
            </label>
          )}
          {hasFilters(filters) && (
            <button className="text-xs text-muted underline ml-1" onClick={() => setFilters(EMPTY_FILTERS)}>
              сбросить фильтры
            </button>
          )}
          {tab === "prihod" && meta?.skipped_povtor > 0 && (
            <span className="text-xs text-muted">
              Не считается повторный приход на склад-получатель при внутреннем перемещении ({meta.skipped_povtor} стр.).
            </span>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 rounded-full border-2 border-pine border-t-transparent animate-spin" />
          </div>
        ) : !filtered.length ? (
          <EmptyState
            icon="📊"
            title="Нет данных"
            description={rows.length ? "Под выбранные фильтры ничего не попало." : isEgais ? "Загрузите выгрузку ЕГАИС (кнопка «Импорт ЕГАИС»)." : "Нарядов за период нет."}
          />
        ) : (
          <div className="border border-border rounded-md overflow-auto max-h-[48vh]">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 z-10">
                <tr className="bg-surface-alt border-b border-border text-left text-muted font-semibold">
                  {columns.map((c) => (
                    <th key={c.key} className={["px-3 py-2 whitespace-nowrap", c.key === "obyom" || c.key === "count" ? "text-right" : ""].join(" ")}>{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sections.map((s) => (
                  <React.Fragment key={s.key}>
                    <tr className="bg-surface-alt/60 border-b border-border">
                      <td colSpan={columns.length} className="px-3 py-1.5 font-bold text-pine">{s.label}</td>
                    </tr>
                    {s.rows.map((r, i) => (
                      <tr key={i} className="border-b border-border align-top">
                        {columns.map((c) => (
                          <td
                            key={c.key}
                            className={[
                              "px-3 py-1.5",
                              c.key === "obyom" || c.key === "count" ? "text-right whitespace-nowrap" : "",
                              c.key === "data" || c.key === "nomer" ? "whitespace-nowrap text-xs" : "",
                              c.key === "delyanka_text" && !r.delyanka_id && !groupBy ? "text-amber-700" : "text-ink",
                            ].join(" ")}
                            style={c.key === "obyom" || c.key === "data" || c.key === "nomer" ? MONO : undefined}
                          >
                            {c.key === "obyom" ? fmt3(r.obyom) : r[c.key] || "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr className="border-b border-border bg-surface-alt font-semibold">
                      <td colSpan={columns.length - 1} className="px-3 py-1.5 text-right">{s.totalLabel}</td>
                      <td className="px-3 py-1.5 text-right" style={MONO}>{fmt3(s.total)}</td>
                    </tr>
                  </React.Fragment>
                ))}
                <tr className="bg-pine text-white font-bold">
                  <td colSpan={columns.length - 1} className="px-3 py-2 text-right">ВСЕГО</td>
                  <td className="px-3 py-2 text-right" style={MONO}>{fmt3(grandTotal)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Modal>
  );
}
