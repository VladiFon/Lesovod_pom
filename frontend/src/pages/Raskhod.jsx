import React, { useCallback, useEffect, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import { pollTask } from "../hooks/useTaskPolling.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Расход / ЕГАИС" (screens/raskhod/) — Этап 9 плана.
 *
 * Backend не переписывался — app/routers/raskhod.py уже оборачивает
 * raskhod_v2.py (единый, уже сверенный источник истины — см. докстринг
 * самого роутера/AUDIT.md) без изменений логики.
 *
 * Перенесено 1:1 (см. SORTIMENT_LABELS в screens/raskhod/screen.py):
 *   Баланс лимит/факт/остаток по породам и сортиментам (KR/SR/ML/DROVA/HVOROST)
 *   Наряды-задания (дата, номер, площадь, позиции по породе/сортименту/объёму)
 *   Импорт выгрузки ЕГАИС (.xlsx) — фоновая задача
 *   Экспорт "Книги расхода леса" в Excel — фоновая задача, документ в общем реестре
 *
 * Сознательно упрощено:
 *   1. GET /api/raskhod/remaining — используется только telegram-ботом
 *      (screens/raskhod/screen.py упоминает его как "for_bot"), в
 *      desktop-интерфейсе лесовода нет своего экрана под него — не переносим.
 *   2. Раздел "Осветление" (screens/raskhod/osvetlenie/, отдельный поддомен
 *      с ИИ-распознаванием проб и своим комплектом Word/Excel-экспортов) —
 *      не входит в этот экран, самостоятельная задача на будущее.
 */

const SORTIMENT_LABELS = { KR: "Крупная", SR: "Средняя", ML: "Мелкая", DROVA: "Дрова", HVOROST: "Хворост" };
const SORTIMENT_KEYS = ["KR", "SR", "ML", "DROVA"];

function ImportEgaisModal({ open, onClose }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleClose = () => {
    if (submitting) return;
    setFile(null);
    onClose();
  };

  const handleSubmit = async () => {
    if (!file) return;
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { task_id } = await api.upload("/raskhod/egais/import", formData);
      const result = await pollTask(task_id, { timeoutMs: 10 * 60 * 1000 });
      const added = result?.journal_rows_added;
      toast.show({
        tone: "success",
        title: "Выгрузка ЕГАИС импортирована",
        description: added != null ? `В журнал добавлено новых записей: ${added} из ${result.journal_rows_total} в файле.` : undefined,
      });
      setFile(null);
      onClose();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось импортировать выгрузку", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Импорт выгрузки ЕГАИС"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting} disabled={!file}>Импортировать</Button>
        </>
      }
    >
      <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
        Реестр движения по складам (.xlsx)
      </label>
      <input
        type="file"
        accept=".xlsx"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        className="w-full text-base text-ink file:mr-3 file:px-3.5 file:py-2 file:rounded-md file:border-0 file:bg-mint-soft file:text-pine file:font-semibold file:cursor-pointer"
      />
    </Modal>
  );
}

/**
 * Расход → ЕГАИС: разбор трёх независимых очередей, которые наполняет
 * save_egais_snapshot() при каждом импорте (см. legacy/db.py и
 * legacy/raskhod_v2.py:_save_egais_review_queues, backend не менялся в
 * части баланса/наряды — это отдельный слой поверх уже существующего
 * импорта):
 *   1. Корректировки остатков ЕГАИС — просто требуют внимания лесничего,
 *      сами по себе никогда не прибавляются к объёму делянки.
 *   2. Неизвестные делянки — квартал/выдел из выгрузки, которых нет в
 *      справочнике delyanka_item; можно привязать к существующей делянке
 *      или проигнорировать.
 *   3. Приход на ФЛС без пары — редкий случай полной цепочки складов
 *      (Приход-ФЛС → Расход-ФЛС → Приход-ПЛС → Расход-ПЛС потребителю);
 *      лесничий решает — отдельная заготовка (тогда объём добавляется в
 *      баланс) или уже учтённое продолжение цепочки (тогда не трогаем
 *      баланс вообще).
 */
const EGAIS_REVIEW_TABS = [
  { key: "korrektirovki", label: "Корректировки остатков", summaryKey: "korrektirovki_new", icon: "⚠️" },
  { key: "unmatched", label: "Неизвестные делянки", summaryKey: "unmatched_delyanka_new", icon: "❓" },
  { key: "fls", label: "Приход на ФЛС", summaryKey: "fls_prihod_new", icon: "🌲" },
];

function EgaisReviewRow({ children }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-3 border-b border-border last:border-b-0 flex-wrap">
      {children}
    </div>
  );
}

function KorrektirovkaRow({ row, busy, onResolve }) {
  return (
    <EgaisReviewRow>
      <div className="text-sm text-ink">
        <div className="font-semibold">Кв. {row.kvartal} / Выд. {row.vydel} · {row.poroda || "—"}</div>
        <div className="text-muted text-xs mt-0.5">
          {row.obyom} м³ · {row.data_dok || "дата не указана"} · документ №{row.nomer_dokumenta || "—"}
          {row.sotrudnik ? ` · ${row.sotrudnik}` : ""}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => onResolve(row.id, "ignored")}>
          Игнорировать
        </Button>
        <Button size="sm" variant="primary" loading={busy} onClick={() => onResolve(row.id, "resolved")}>
          Учтено
        </Button>
      </div>
    </EgaisReviewRow>
  );
}

function UnmatchedDelyankaRow({ row, busy, delyanki, onLink, onIgnore }) {
  const [pick, setPick] = useState("");
  return (
    <EgaisReviewRow>
      <div className="text-sm text-ink">
        <div className="font-semibold">Кв. {row.kvartal} / Выд. {row.vydel}</div>
        <div className="text-muted text-xs mt-0.5">
          {row.nazvanie_sklada || "склад не указан"} · последний раз в выгрузке: {row.last_seen_at}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <select
          value={pick}
          onChange={(e) => setPick(e.target.value)}
          className="bg-surface border border-border focus:border-pine rounded-md px-2.5 py-1.5 text-sm text-ink outline-none max-w-[220px]"
        >
          <option value="">Привязать к делянке…</option>
          {delyanki.map((d) => (
            <option key={d.id} value={d.id}>{d.nazvanie || `Делянка №${d.id}`}</option>
          ))}
        </select>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => onIgnore(row.id)}>
          Игнорировать
        </Button>
        <Button size="sm" variant="primary" loading={busy} disabled={!pick} onClick={() => onLink(row.id, pick)}>
          Привязать
        </Button>
      </div>
    </EgaisReviewRow>
  );
}

function FlsPrihodRow({ row, busy, onResolve }) {
  return (
    <EgaisReviewRow>
      <div className="text-sm text-ink">
        <div className="font-semibold">Кв. {row.kvartal} / Выд. {row.vydel} · {row.poroda || "—"}</div>
        <div className="text-muted text-xs mt-0.5">
          {row.obyom} м³ ({row.sortiment}) · {row.data_dok || "дата не указана"} · документ №{row.nomer_dokumenta || "—"}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => onResolve(row.id, "ignored")}>
          Игнорировать
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => onResolve(row.id, "privyazan_k_pls")}>
          Часть цепочки (не считать)
        </Button>
        <Button size="sm" variant="primary" loading={busy} onClick={() => onResolve(row.id, "schitat_otdelno")}>
          Отдельная заготовка (учесть)
        </Button>
      </div>
    </EgaisReviewRow>
  );
}

function EgaisReviewModal({ open, onClose, delyanki }) {
  const toast = useToast();
  const [tab, setTab] = useState("korrektirovki");
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const loadSummary = useCallback(() => {
    api.get("/raskhod/egais/review/summary").then(setSummary).catch(() => {});
  }, []);

  const loadRows = useCallback(async () => {
    setLoading(true);
    try {
      const endpoint =
        tab === "korrektirovki" ? "/raskhod/egais/review/korrektirovki" :
        tab === "unmatched" ? "/raskhod/egais/review/unmatched-delyanka" :
        "/raskhod/egais/review/fls-prihod";
      const res = await api.get(endpoint, { status: "new" });
      setRows(res || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить список", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    loadSummary();
  }, [open, loadSummary]);

  useEffect(() => {
    if (!open) return;
    loadRows();
  }, [open, tab, loadRows]);

  const refresh = () => {
    loadRows();
    loadSummary();
  };

  const withBusy = async (id, fn) => {
    setBusyId(id);
    try {
      await fn();
      refresh();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    } finally {
      setBusyId(null);
    }
  };

  const resolveKorrektirovka = (id, status) =>
    withBusy(id, () => api.post(`/raskhod/egais/review/korrektirovki/${id}/resolve`, { status }));

  const linkUnmatched = (id, delyankaId) =>
    withBusy(id, () => api.post(`/raskhod/egais/review/unmatched-delyanka/${id}/link`, { delyanka_id: Number(delyankaId) }));

  const ignoreUnmatched = (id) =>
    withBusy(id, () => api.post(`/raskhod/egais/review/unmatched-delyanka/${id}/ignore`));

  const resolveFls = (id, status) =>
    withBusy(id, () => api.post(`/raskhod/egais/review/fls-prihod/${id}/resolve`, { status }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Разбор выгрузки ЕГАИС"
      size="lg"
      footer={<Button variant="ghost" onClick={onClose}>Закрыть</Button>}
    >
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        {EGAIS_REVIEW_TABS.map((t) => {
          const count = summary?.[t.summaryKey] ?? 0;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={[
                "flex items-center gap-2 px-3 py-2 rounded-md text-sm font-semibold transition-colors border",
                active ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover",
              ].join(" ")}
            >
              <span>{t.icon} {t.label}</span>
              {count > 0 && <StatusBadge tone={active ? "info" : "warning"} label={count} dot={false} />}
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-6 w-6 rounded-full border-2 border-pine border-t-transparent animate-spin" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState icon="✅" title="Разобрано" description="В этой очереди сейчас нет новых записей." />
      ) : (
        <div className="border border-border rounded-md overflow-y-auto max-h-[50vh]">
          {tab === "korrektirovki" &&
            rows.map((row) => (
              <KorrektirovkaRow key={row.id} row={row} busy={busyId === row.id} onResolve={resolveKorrektirovka} />
            ))}
          {tab === "unmatched" &&
            rows.map((row) => (
              <UnmatchedDelyankaRow
                key={row.id}
                row={row}
                busy={busyId === row.id}
                delyanki={delyanki}
                onLink={linkUnmatched}
                onIgnore={ignoreUnmatched}
              />
            ))}
          {tab === "fls" &&
            rows.map((row) => (
              <FlsPrihodRow key={row.id} row={row} busy={busyId === row.id} onResolve={resolveFls} />
            ))}
        </div>
      )}
    </Modal>
  );
}

function emptyPozitsiya() {
  return { poroda: "", sortiment: "KR", obyom: "" };
}

function NaryadModal({ open, onClose, itemId, porody, editing, onSaved, ploshadDelyanki, limitKubaturaTotal }) {
  const toast = useToast();
  const [data, setData] = useState("");
  const [nomer, setNomer] = useState("");
  const [ploshad, setPloshad] = useState("");
  const [primechanie, setPrimechanie] = useState("");
  const [pozitsii, setPozitsii] = useState([emptyPozitsiya()]);
  const [submitting, setSubmitting] = useState(false);

  // Автоподсчёт площади наряда (B.3 доработок): площадь = заготовленная
  // кубатура ЭТОГО наряда (сумма "Объём, м³" по текущим позициям формы,
  // ещё до сохранения) * площадь делянки / общий лимит кубатуры делянки
  // по всем породам. Округляется до сотых. ploshadDelyanki и
  // limitKubaturaTotal приходят с /raskhod/items/{id}/ploshad через
  // ItemWorkspace — если МДО ещё не загружен (лимита нет) или у выдела
  // не указана площадь, честно предупреждаем вместо тихого деления на 0.
  const handleCalcPloshad = () => {
    if (!limitKubaturaTotal || limitKubaturaTotal <= 0) {
      toast.show({
        tone: "warning",
        title: "Нет данных по лимиту делянки",
        description: "Импортируйте МДО для этого выдела, чтобы рассчитать площадь автоматически.",
      });
      return;
    }
    if (!ploshadDelyanki || ploshadDelyanki <= 0) {
      toast.show({ tone: "warning", title: "У выдела не указана площадь делянки" });
      return;
    }
    const kubaturaNaryada = pozitsii.reduce((sum, p) => sum + (Number(p.obyom) || 0), 0);
    const calculated = (kubaturaNaryada * ploshadDelyanki) / limitKubaturaTotal;
    setPloshad(calculated.toFixed(2));
  };

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setData(editing.data || "");
      setNomer(editing.nomer_naryada || "");
      setPloshad(editing.ploshad || "");
      setPrimechanie(editing.primechanie || "");
      setPozitsii(editing.pozitsii?.length ? editing.pozitsii.map((p) => ({ ...p, obyom: String(p.obyom) })) : [emptyPozitsiya()]);
    } else {
      setData("");
      setNomer("");
      setPloshad("");
      setPrimechanie("");
      setPozitsii([emptyPozitsiya()]);
    }
  }, [open, editing]);

  const setPozitsiyaField = (idx, key) => (e) => {
    const value = e.target.value;
    setPozitsii((rows) => rows.map((r, i) => (i === idx ? { ...r, [key]: value } : r)));
  };
  const addRow = () => setPozitsii((rows) => [...rows, emptyPozitsiya()]);
  const removeRow = (idx) => setPozitsii((rows) => rows.filter((_, i) => i !== idx));

  const handleSubmit = async () => {
    if (!data.trim()) {
      toast.show({ tone: "warning", title: "Укажите дату наряда" });
      return;
    }
    setSubmitting(true);
    try {
      const body = {
        data: data.trim(),
        nomer_naryada: nomer,
        ploshad,
        primechanie,
        pozitsii: pozitsii.filter((p) => p.poroda && p.obyom !== "").map((p) => ({ ...p, obyom: Number(p.obyom) })),
      };
      if (editing) {
        await api.patch(`/raskhod/naryady/${editing.id}`, body);
        toast.show({ tone: "success", title: "Наряд обновлён" });
      } else {
        await api.post(`/raskhod/items/${itemId}/naryady`, body);
        toast.show({ tone: "success", title: "Наряд добавлен" });
      }
      onClose();
      onSaved();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить наряд", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? "Редактировать наряд" : "Новый наряд-задание"}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>Сохранить</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-3 gap-4">
          <TextField label="Дата" placeholder="ДД.ММ.ГГГГ" value={data} onChange={(e) => setData(e.target.value)} />
          <TextField label="№ наряда" value={nomer} onChange={(e) => setNomer(e.target.value)} />
          <TextField
            label="Площадь, га"
            value={ploshad}
            onChange={(e) => setPloshad(e.target.value)}
            suffix={
              <button
                type="button"
                title="Рассчитать по кубатуре наряда"
                onClick={handleCalcPloshad}
                className="text-pine hover:text-pine-hover text-base leading-none px-1.5 py-1 rounded hover:bg-mint-soft"
              >
                🧮
              </button>
            }
          />
        </div>
        <TextAreaField label="Примечание" rows={2} value={primechanie} onChange={(e) => setPrimechanie(e.target.value)} />

        <div>
          <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Позиции</label>
          <div className="flex flex-col gap-2">
            {pozitsii.map((p, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <select
                  value={p.poroda}
                  onChange={setPozitsiyaField(idx, "poroda")}
                  className="flex-1 bg-surface border border-border focus:border-pine rounded-md px-3 py-2 text-sm text-ink outline-none"
                >
                  <option value="">Порода…</option>
                  {porody.map((pd) => (
                    <option key={pd} value={pd}>{pd}</option>
                  ))}
                </select>
                <select
                  value={p.sortiment}
                  onChange={setPozitsiyaField(idx, "sortiment")}
                  className="w-40 bg-surface border border-border focus:border-pine rounded-md px-3 py-2 text-sm text-ink outline-none"
                >
                  {Object.entries(SORTIMENT_LABELS).map(([k, label]) => (
                    <option key={k} value={k}>{label}</option>
                  ))}
                </select>
                <input
                  type="number"
                  step="0.01"
                  placeholder="Объём, м³"
                  value={p.obyom}
                  onChange={setPozitsiyaField(idx, "obyom")}
                  className="w-32 bg-surface border border-border focus:border-pine rounded-md px-3 py-2 text-sm text-ink outline-none"
                />
                <button onClick={() => removeRow(idx)} className="text-error text-sm font-semibold px-2">✕</button>
              </div>
            ))}
          </div>
          <Button variant="ghost" size="sm" onClick={addRow} className="mt-2">+ Позиция</Button>
        </div>
      </div>
    </Modal>
  );
}

/** Цвет ячейки "остаток" по проценту выборки лимита, который относится
 * к этой конкретной колонке (B.2 доработок, расширено под остаток±10%):
 * лимит исчерпан/превышен — красный; выбрано ≥80% — жёлтый (внимание,
 * скоро предел); иначе — зелёный (запас есть). Если лимита нет (0/—),
 * цвет не имеет смысла — нейтральный серый.
 * limitBase — лимит, с которым сравнивается именно эта ostatok-колонка
 * (обычный лимит / лимит+10% / лимит-10%), а не всегда cell.limit. */
function ostatokTone(limitBase, fakt, ostatok) {
  const limit = limitBase ?? 0;
  if (ostatok == null) return "text-muted";
  if (limit <= 0) return "text-muted";
  if (ostatok <= 0) return "text-error font-bold";
  const usedPct = ((fakt ?? 0) / limit) * 100;
  if (usedPct >= 80) return "text-oak font-semibold";
  return "text-pine font-semibold";
}

/** Каждая "факт/остаток"-категория продублирована на пару колонок —
 * "наряд" (из raskhod_pozitsiya, как и раньше) и "ЕГАИС" (из последней
 * выгрузки, см. _fakt_egais_from_entry в raskhod_v2.py) — чтобы лесничий
 * видел расхождение между тем, что записано в наряде, и тем, что реально
 * прошло через ЕГАИС, не переключаясь между вкладками. "Лимит" один на
 * обе колонки (он не зависит от источника факта, дублировать нечего). */
const METRIC_COLUMNS = [
  { key: "limit", label: "лимит" },
  { key: "fakt", label: "факт, наряд" },
  { key: "fakt_egais", label: "факт, ЕГАИС" },
  { key: "ostatok", label: "остаток, наряд" },
  { key: "ostatok_egais", label: "остаток, ЕГАИС" },
  { key: "ostatok_110", label: "ост. +10%, наряд" },
  { key: "ostatok_egais_110", label: "ост. +10%, ЕГАИС" },
  { key: "ostatok_90", label: "ост. -10%, наряд" },
  { key: "ostatok_egais_90", label: "ост. -10%, ЕГАИС" },
];

/** Достраивает по сортиментной ячейке {limit, fakt, ostatok, ostatok_110}
 * из /raskhod/items/{id}/balance недостающий "остаток -10%" —
 * (лимит-10%) - факт. Бэкенд его не отдаёт, но limit и fakt уже есть в
 * ответе, так что считаем на клиенте, без правок API. */
function withOstatok90(cell) {
  const limit = cell?.limit ?? 0;
  const fakt = cell?.fakt ?? 0;
  const faktEgais = cell?.fakt_egais ?? 0;
  return {
    limit,
    fakt,
    ostatok: cell?.ostatok ?? (limit - fakt),
    ostatok_110: cell?.ostatok_110 ?? (limit * 1.1 - fakt),
    ostatok_90: limit * 0.9 - fakt,
    fakt_egais: faktEgais,
    ostatok_egais: cell?.ostatok_egais ?? (limit - faktEgais),
    ostatok_egais_110: cell?.ostatok_egais_110 ?? (limit * 1.1 - faktEgais),
    ostatok_egais_90: limit * 0.9 - faktEgais,
  };
}

/** Суммирует несколько ячеек одного формата (для строк "Деловая" —
 * Кр+Ср+Мелкая — и "Итого" — Деловая+Дрова). */
function sumCells(cells) {
  const out = {
    limit: 0, fakt: 0, ostatok: 0, ostatok_110: 0, ostatok_90: 0,
    fakt_egais: 0, ostatok_egais: 0, ostatok_egais_110: 0, ostatok_egais_90: 0,
  };
  for (const c of cells) {
    if (!c) continue;
    out.limit += c.limit ?? 0;
    out.fakt += c.fakt ?? 0;
    out.ostatok += c.ostatok ?? 0;
    out.ostatok_110 += c.ostatok_110 ?? 0;
    out.ostatok_90 += c.ostatok_90 ?? 0;
    out.fakt_egais += c.fakt_egais ?? 0;
    out.ostatok_egais += c.ostatok_egais ?? 0;
    out.ostatok_egais_110 += c.ostatok_egais_110 ?? 0;
    out.ostatok_egais_90 += c.ostatok_egais_90 ?? 0;
  }
  return out;
}

function toneForColumn(cell, key) {
  if (key === "ostatok") return ostatokTone(cell.limit, cell.fakt, cell.ostatok);
  if (key === "ostatok_110") return ostatokTone(cell.limit * 1.1, cell.fakt, cell.ostatok_110);
  if (key === "ostatok_90") return ostatokTone(cell.limit * 0.9, cell.fakt, cell.ostatok_90);
  if (key === "ostatok_egais") return ostatokTone(cell.limit, cell.fakt_egais, cell.ostatok_egais);
  if (key === "ostatok_egais_110") return ostatokTone(cell.limit * 1.1, cell.fakt_egais, cell.ostatok_egais_110);
  if (key === "ostatok_egais_90") return ostatokTone(cell.limit * 0.9, cell.fakt_egais, cell.ostatok_egais_90);
  return key === "limit" ? "text-muted" : "text-ink";
}

/** Группы-колонки, идущие горизонтально слева направо у каждой породы
 * (порода — единственное, что листается вниз, строка на породу).
 * "delovaya" и "itogo" считаются на лету в BalanceTable (сумма KR+SR+ML,
 * и деловая+дрова), остальные — прямые ключи из balance[poroda].
 * Крупная/Средняя/Мелкая по умолчанию скрыты — раскрываются кликом по
 * заголовку "Деловая" (один переключатель на всю таблицу, т.к. колонки
 * общие для всех строк-пород). */
const HEAD_GROUP = { key: "delovaya", label: "Деловая" };
const DETAIL_GROUPS = [
  { key: "KR", label: "Крупная" },
  { key: "SR", label: "Средняя" },
  { key: "ML", label: "Мелкая" },
];
const TAIL_GROUPS = [
  { key: "DROVA", label: "Дрова" },
  { key: "itogo", label: "Итого (дел.+дрова)" },
];

/** Строка "Площадь делянки / Площадь остаток" над таблицей баланса
 * (B.3 доработок) — из /raskhod/items/{id}/ploshad. Остаток = площадь
 * делянки минус сумма площадей уже заведённых нарядов; если наряды в
 * сумме превысили площадь делянки (например, площадь заносили вручную,
 * не через автоподсчёт), уходит в минус — это подсвечивается красным
 * как сигнал перепроверить наряды, а не скрывается. */
function PloshadSummary({ ploshadInfo }) {
  if (!ploshadInfo) return null;
  const { ploshad_delyanki, ploshad_ostatok } = ploshadInfo;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-3 text-sm">
      <div>
        <span className="text-muted">Площадь делянки: </span>
        <span className="text-ink font-semibold">{(ploshad_delyanki ?? 0).toFixed(2)} га</span>
      </div>
      <div>
        <span className="text-muted">Площадь остаток: </span>
        <span className={["font-semibold", (ploshad_ostatok ?? 0) <= 0 ? "text-error" : "text-pine"].join(" ")}>
          {(ploshad_ostatok ?? 0).toFixed(2)} га
        </span>
      </div>
    </div>
  );
}

/** Переключатель "показывать колонки ЕГАИС" над таблицей баланса —
 * прячет fakt_egais/ostatok_egais* (см. METRIC_COLUMNS), когда лесничему
 * мешают лишние колонки и нужны только данные по нарядам. Ничего не
 * запрашивает у бэкенда - чисто клиентский фильтр видимых колонок,
 * данные ЕГАИС как загружались вместе с /balance, так и загружаются. */
function EgaisColumnsToggle({ checked, onChange }) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-muted cursor-pointer select-none">
      <span
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={[
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
          checked ? "bg-pine" : "bg-border",
        ].join(" ")}
      >
        <span
          className={[
            "inline-block h-4 w-4 transform rounded-full bg-surface transition-transform",
            checked ? "translate-x-4" : "translate-x-0.5",
          ].join(" ")}
        />
      </span>
      Показывать колонки ЕГАИС
    </label>
  );
}

/** Режим "Карточки" баланса (дизайн «Вкладки»): по карточке на породу —
 * два прогресс-бара (наряд / ЕГАИС относительно лимита) и мини-таблица
 * по сортиментам. Данные те же, что и в таблице (rowsData). */
const CARD_TONES = {
  green: ["#eaf7ec", "#1a4331", "в лимите"],
  oak: ["#fdf1e4", "#a8681f", "почти предел"],
  error: ["#fbeaea", "#ba1a1a", "переруб"],
};
function usageTone(limit, fakt) {
  const pct = limit > 0 ? (fakt / limit) * 100 : 0;
  return pct > 100 ? "error" : pct >= 80 ? "oak" : "green";
}
const fmt1 = (v) => (v ?? 0).toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const MONO_STYLE = { fontFamily: "'JetBrains Mono', monospace" };

function ProgressBar({ value, limit, color }) {
  const w = limit > 0 ? Math.min(100, (value / limit) * 100) : 0;
  return (
    <div className="h-2.5 rounded-full bg-hover overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${w}%`, background: color }} />
    </div>
  );
}

function PorodaCard({ title, cell, sorts, hvorost, selected, onClick, total }) {
  const tone = usageTone(cell.limit, Math.max(cell.fakt, cell.fakt_egais));
  const [bg, fg, chip] = CARD_TONES[tone];
  const pct = cell.limit > 0 ? Math.round((cell.fakt / cell.limit) * 100) : 0;
  const delta = cell.fakt_egais - cell.fakt;
  const remainColor = (v) => (v <= 0 ? "#ba1a1a" : "#1a4331");
  return (
    <div
      onClick={onClick}
      className="flex flex-col gap-2.5 rounded-[14px] bg-surface px-4 py-3.5 min-w-0"
      style={{
        flex: "1 1 300px",
        border: `1px solid ${tone === "error" ? "#ba1a1a" : selected ? "#1a4331" : "#e5e2db"}`,
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[15px] font-extrabold text-pine">{title}</span>
        {total ? (
          <span className="text-[10.5px] text-pine" style={MONO_STYLE}>{pct}% лимита выбрано</span>
        ) : (
          <span
            className="text-[10px] uppercase rounded-full px-2 py-[3px]"
            style={{ ...MONO_STYLE, letterSpacing: ".06em", background: bg, color: fg }}
          >
            {chip}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-[5px]">
        <div className="flex items-center justify-between text-[11px] text-muted-2" style={MONO_STYLE}>
          <span>наряд {fmt1(cell.fakt)} / {fmt1(cell.limit)} м³</span>
          {!total && <span>{pct}%</span>}
        </div>
        <ProgressBar value={cell.fakt} limit={cell.limit} color="#1a4331" />
      </div>
      {!total && (
        <div className="flex flex-col gap-[5px]">
          <div className="flex items-center justify-between text-[11px] text-muted-2" style={MONO_STYLE}>
            <span>ЕГАИС {fmt1(cell.fakt_egais)} м³</span>
            <span>расхождение {delta >= 0 ? "+" : "−"}{fmt1(Math.abs(delta))}</span>
          </div>
          <ProgressBar value={cell.fakt_egais} limit={cell.limit} color="#8fb79f" />
        </div>
      )}
      {sorts && (
        <div className="grid gap-x-2 gap-y-[3px] pt-2 border-t border-hover" style={{ gridTemplateColumns: "1.2fr .8fr .8fr .8fr" }}>
          {["сортимент", "лимит", "факт", "остаток"].map((h, i) => (
            <span key={h} className={["text-[10.5px] text-faint", i ? "text-right" : ""].join(" ")}>{h}</span>
          ))}
          {sorts.map(({ label, cell: c }) => {
            const t = CARD_TONES[usageTone(c.limit, Math.max(c.fakt, c.fakt_egais))][1];
            return (
              <React.Fragment key={label}>
                <span className="text-[12.5px] text-ink">{label}</span>
                <span className="text-right text-[12px] text-muted-2" style={MONO_STYLE}>{fmt1(c.limit)}</span>
                <span className="text-right text-[12px] text-muted-2" style={MONO_STYLE}>{fmt1(c.fakt)}</span>
                <span className="text-right text-[12.5px] font-bold" style={{ ...MONO_STYLE, color: t }}>{fmt1(c.ostatok)}</span>
              </React.Fragment>
            );
          })}
        </div>
      )}
      {typeof hvorost === "number" && !total && (
        <div className="text-[11px] text-faint" style={MONO_STYLE}>хворост, факт: {fmt1(hvorost)} м³</div>
      )}
      {total && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1">
          {[
            ["лимит", cell.limit, false],
            ["факт, наряд", cell.fakt, false],
            ["факт, ЕГАИС", cell.fakt_egais, false],
            ["остаток, наряд", cell.ostatok, true],
            ["остаток, ЕГАИС", cell.ostatok_egais, true],
            ["остаток +10%", cell.ostatok_110, true],
            ["остаток −10%", cell.ostatok_90, true],
          ].map(([label, v, colored]) => (
            <React.Fragment key={label}>
              <span className="text-[12.5px] text-muted">{label}</span>
              <span className="text-right text-[13px] font-bold" style={{ ...MONO_STYLE, color: colored ? remainColor(v) : "#414944" }}>
                {fmt1(v)}
              </span>
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

function BalanceCards({ rowsData, totals, selectedPoroda, onSelectPoroda }) {
  return (
    <div className="flex flex-wrap gap-3">
      {rowsData.map(({ poroda, cellsByGroup, hvorostFakt }) => (
        <PorodaCard
          key={poroda}
          title={poroda}
          cell={cellsByGroup.itogo}
          hvorost={hvorostFakt}
          selected={selectedPoroda === poroda}
          onClick={onSelectPoroda ? () => onSelectPoroda(poroda) : undefined}
          sorts={[
            { label: "Крупная", cell: cellsByGroup.KR },
            { label: "Средняя", cell: cellsByGroup.SR },
            { label: "Мелкая", cell: cellsByGroup.ML },
            { label: "Дрова", cell: cellsByGroup.DROVA },
          ]}
        />
      ))}
      <PorodaCard title="Итого по породам" cell={totals} total />
    </div>
  );
}

function ModeButtons({ mode, onChange }) {
  return (
    <div className="flex gap-1.5">
      {[["cards", "Карточки"], ["table", "Таблица"]].map(([k, label]) => (
        <button
          key={k}
          type="button"
          onClick={() => onChange(k)}
          className="h-[30px] px-3 rounded-lg text-[12.5px] font-semibold"
          style={{
            border: `1px solid ${mode === k ? "#1a4331" : "#e5e2db"}`,
            background: mode === k ? "#1a4331" : "#fff",
            color: mode === k ? "#fff" : "#414944",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function BalanceTable({ balance, ploshadInfo, selectedPoroda, onSelectPoroda }) {
  const [showDetail, setShowDetail] = useState(false);
  const [mode, setMode] = useState("cards");
  const [showEgaisColumns, setShowEgaisColumns] = useState(true);
  const porody = Object.keys(balance).sort();
  if (porody.length === 0) {
    return (
      <div>
        <PloshadSummary ploshadInfo={ploshadInfo} />
        <EmptyState icon="⚖️" title="Нет данных МДО для лимитов" description="У этого выдела не найдены объёмы по породам (импорт из МДО)." />
      </div>
    );
  }

  const groupDefs = [HEAD_GROUP, ...(showDetail ? DETAIL_GROUPS : []), ...TAIL_GROUPS];
  const metricColumns = showEgaisColumns
    ? METRIC_COLUMNS
    : METRIC_COLUMNS.filter((c) => !c.key.includes("egais"));

  const rowsData = porody.map((poroda) => {
    const row = balance[poroda] || {};
    const kr = withOstatok90(row.KR);
    const sr = withOstatok90(row.SR);
    const ml = withOstatok90(row.ML);
    const drova = withOstatok90(row.DROVA);
    const delovaya = sumCells([kr, sr, ml]);
    const itogo = sumCells([delovaya, drova]);
    return {
      poroda,
      cellsByGroup: { delovaya, KR: kr, SR: sr, ML: ml, DROVA: drova, itogo },
      hvorostFakt: row.HVOROST?.fakt ?? 0,
    };
  });

  /** Строка "Итого" внизу таблицы — та же сумма по всем породам, что и
   * "Деловая"/"Итого"-колонки суммируют по сортиментам у одной породы
   * (sumCells), только теперь по строкам (породам) для каждой
   * группы-колонки отдельно. Хворост-факт складывается тем же образом,
   * отдельным числом (у него нет группы/METRIC_COLUMNS, только факт). */
  const totalsByGroup = {};
  for (const g of groupDefs) {
    totalsByGroup[g.key] = sumCells(rowsData.map((r) => r.cellsByGroup[g.key]));
  }
  const hvorostTotal = rowsData.reduce((sum, r) => sum + r.hvorostFakt, 0);

  return (
    <div>
    <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
      <PloshadSummary ploshadInfo={ploshadInfo} />
      <div className="flex items-center gap-3 flex-wrap">
        {mode === "table" && <EgaisColumnsToggle checked={showEgaisColumns} onChange={setShowEgaisColumns} />}
        <ModeButtons mode={mode} onChange={setMode} />
      </div>
    </div>
    {mode === "cards" ? (
      <BalanceCards
        rowsData={rowsData}
        totals={totalsByGroup.itogo}
        selectedPoroda={selectedPoroda}
        onSelectPoroda={onSelectPoroda}
      />
    ) : (
    <div className="border border-border rounded-lg overflow-x-auto">
      <table className="text-sm whitespace-nowrap">
        <thead>
          <tr className="bg-surface-alt border-b border-border text-left text-pine font-bold text-[11.5px]">
            <th rowSpan={2} className="px-3 py-2 sticky left-0 bg-surface-alt align-bottom">Порода</th>
            {groupDefs.map((g) => (
              <th key={g.key} colSpan={metricColumns.length} className="px-3 py-1.5 text-center border-l border-border">
                {g.key === "delovaya" ? (
                  <button
                    type="button"
                    onClick={() => setShowDetail((v) => !v)}
                    className="inline-flex items-center gap-1.5 hover:text-pine"
                  >
                    <span className={["inline-block transition-transform text-xs", showDetail ? "rotate-90" : ""].join(" ")}>▶</span>
                    {g.label}
                  </button>
                ) : (
                  g.label
                )}
              </th>
            ))}
            <th rowSpan={2} className="px-3 py-2 text-center border-l border-border align-bottom">Хворост<br />факт</th>
          </tr>
          <tr className="bg-surface-alt border-b border-border text-left text-faint text-xs">
            {groupDefs.map((g) =>
              metricColumns.map((c, i) => (
                <th key={g.key + c.key} className={["px-2 py-1 text-center font-normal", i === 0 ? "border-l border-border" : ""].join(" ")}>
                  {c.label}
                </th>
              ))
            )}
          </tr>
        </thead>
        <tbody>
          {rowsData.map(({ poroda, cellsByGroup, hvorostFakt }) => {
            const isSelected = selectedPoroda === poroda;
            return (
              <tr
                key={poroda}
                onClick={() => onSelectPoroda?.(poroda)}
                className={[
                  "border-b border-border last:border-b-0 transition-colors",
                  onSelectPoroda ? "cursor-pointer" : "",
                  isSelected ? "bg-mint-soft ring-1 ring-inset ring-pine" : "hover:bg-hover",
                ].join(" ")}
              >
                <td
                  className={[
                    "px-3 py-2 font-bold sticky left-0 transition-colors",
                    isSelected ? "bg-mint-soft text-pine" : "bg-surface text-ink",
                  ].join(" ")}
                >
                  {poroda}
                </td>
                {groupDefs.map((g) => {
                  const cell = cellsByGroup[g.key];
                  return metricColumns.map((c, i) => (
                    <td
                      key={g.key + c.key}
                      className={[
                        "px-2 py-2 text-center",
                        i === 0 ? "border-l border-border" : "",
                        toneForColumn(cell, c.key),
                      ].join(" ")}
                    >
                      {(cell[c.key] ?? 0).toFixed(1)}
                    </td>
                  ));
                })}
                <td className="px-3 py-2 text-center text-ink border-l border-border">{hvorostFakt.toFixed(1)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="bg-surface-alt border-t-2 border-border font-bold">
            <td className="px-3 py-2 sticky left-0 bg-surface-alt text-ink">Итого</td>
            {groupDefs.map((g) => {
              const cell = totalsByGroup[g.key];
              return metricColumns.map((c, i) => (
                <td
                  key={g.key + c.key}
                  className={[
                    "px-2 py-2 text-center",
                    i === 0 ? "border-l border-border" : "",
                    toneForColumn(cell, c.key),
                  ].join(" ")}
                >
                  {(cell[c.key] ?? 0).toFixed(1)}
                </td>
              ));
            })}
            <td className="px-3 py-2 text-center text-ink border-l border-border">{hvorostTotal.toFixed(1)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
    )}
    </div>
  );
}

/**
 * Переключатель "Наряды-задания" / "Расход по ЕГАИС" — та же пара
 * pill-кнопок, что и scope-переключатель в SummaryModal. Переключает
 * только НИЖНИЙ блок (список нарядов ↔ список приходов ЕГАИС); верхняя
 * таблица баланса остаток по ЕГАИС показывает отдельными колонками
 * ВСЕГДА, без переключения — см. METRIC_COLUMNS/BalanceTable.
 *
 * Про категории: _egais_krupnost_for_row в raskhod_v2.py классифицирует
 * деловую древесину ЕГАИС по крупности (КР/СР/МЛ) ПО ДИАМЕТРУ строки
 * ("Группа диметров"/"Номенклатура"), а не по колонке "Сорт" (та про
 * качество по ГОСТу) — поэтому строки нижней таблицы группируются по
 * той же породе, что и наряды, а столбец "Сортимент" показывает
 * получившуюся крупность как есть (плюс "Дрова" отдельно). Это ТЕ ЖЕ
 * колонки KR/SR/ML/DROVA, что и в БалансТаблице — не два разных среза,
 * что раньше ошибочно считалось несовместимым.
 */
function NaryadyEgaisToggle({ view, onChange, egaisCount, journalCount }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        onClick={() => onChange("naryady")}
        className={["h-8 px-3.5 rounded-[9px] text-[12.5px] font-semibold transition-colors border",
          view === "naryady" ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover"].join(" ")}
      >
        Наряды-задания
      </button>
      <button
        onClick={() => onChange("egais")}
        className={["h-8 px-3.5 rounded-[9px] text-[12.5px] font-semibold transition-colors border",
          view === "egais" ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover"].join(" ")}
      >
        Расход по ЕГАИС
        {egaisCount > 0 && <StatusBadge tone="info" label={egaisCount} dot={false} className="ml-1.5" />}
      </button>
      <button
        onClick={() => onChange("journal")}
        className={["h-8 px-3.5 rounded-[9px] text-[12.5px] font-semibold transition-colors border",
          view === "journal" ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover"].join(" ")}
      >
        Журнал ЕГАИС
        {journalCount > 0 && <StatusBadge tone="info" label={journalCount} dot={false} className="ml-1.5" />}
      </button>
    </div>
  );
}

// Тип документа ЕГАИС -> как показать строку в журнале. "Расход при
// внутреннем перемещении" помечен нейтральным (не приход и не расход
// делянки — см. чат с пользователем 24.09.2026: он либо задваивал бы
// приход, либо относится к перемещению на чужой склад вне этой выгрузки),
// "Перевод" — тоже нейтральный (переклассификация уже учтённой древесины
// между сортами на том же складе, не новое поступление — подтверждено
// пользователем 24.09.2026).
const EGAIS_JOURNAL_TYPE_TONE = {
  "Приход": "success",
  "Расход при реализации потребителю": "danger",
  "Расход при внутреннем перемещении": "neutral",
  "Перевод": "neutral",
  "Корректировка остатков": "warning",
};

function EgaisJournalTable({ rows, loading }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-10">
        <div className="h-5 w-5 rounded-full border-2 border-pine border-t-transparent animate-spin" />
      </div>
    );
  }
  if (!rows || rows.length === 0) {
    return (
      <EmptyState
        icon="📜"
        title="Журнал ЕГАИС по этому выделу пуст"
        description="Журнал копится при каждом импорте выгрузки — сюда попадает каждая строка (приход, расход, корректировка), без потерь при повторных/ежедневных импортах."
      />
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="text-xs text-muted">
        {rows.length} {rows.length === 1 ? "запись" : "записей"} в журнале — накопительно, по всем импортам выгрузки ЕГАИС.
      </div>
      <div className="border border-border rounded-md overflow-hidden overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-alt border-b border-border text-left text-muted font-semibold">
              <th className="px-3 py-2">Дата</th>
              <th className="px-3 py-2">Тип операции</th>
              <th className="px-3 py-2">Порода</th>
              <th className="px-3 py-2">Сорт / годность</th>
              <th className="px-3 py-2 text-right">Объём, м³</th>
              <th className="px-3 py-2">Склад</th>
              <th className="px-3 py-2">Документ</th>
              <th className="px-3 py-2">Сотрудник</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-border last:border-b-0 align-top">
                <td className="px-3 py-2 text-ink whitespace-nowrap" style={MONO_STYLE}>{r.data_dokumenta || "—"}</td>
                <td className="px-3 py-2">
                  <StatusBadge tone={EGAIS_JOURNAL_TYPE_TONE[r.tip_dokumenta] || "neutral"} label={r.tip_dokumenta || "—"} dot={false} />
                </td>
                <td className="px-3 py-2 text-ink">{r.poroda || "—"}</td>
                <td className="px-3 py-2 text-muted">
                  {r.sort && r.sort !== "без сорта" ? r.sort : ""}
                  {r.tehnicheskaya_godnost === "Дровяная древесина" ? " · дрова" : ""}
                </td>
                <td className={["px-3 py-2 text-right font-semibold", r.obyom > 0 ? "text-pine" : r.obyom < 0 ? "text-red-600" : "text-ink"].join(" ")} style={MONO_STYLE}>
                  {r.obyom > 0 ? "+" : ""}{r.obyom?.toFixed(3)}
                </td>
                <td className="px-3 py-2 text-muted text-xs max-w-[220px] truncate" title={r.sklad}>{r.sklad || "—"}</td>
                <td className="px-3 py-2 text-muted text-xs whitespace-nowrap" style={MONO_STYLE}>{r.nomer_dokumenta || "—"}</td>
                <td className="px-3 py-2 text-muted text-xs">{r.sotrudnik || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EgaisRaskhodTable({ egais }) {
  const porody = egais?.porody ? Object.keys(egais.porody).sort() : [];
  if (porody.length === 0) {
    return (
      <EmptyState
        icon="🌲"
        title="Нет данных ЕГАИС по этому выделу"
        description="Либо выгрузка ЕГАИС ещё не импортирована, либо в ней нет прихода по этому кварталу/выделу."
      />
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {(egais.imported_at || egais.nazvanie_sklada) && (
        <div className="text-xs text-muted">
          {egais.imported_at && <>Данные выгрузки ЕГАИС от {egais.imported_at}</>}
          {egais.nazvanie_sklada && <> · склад: {egais.nazvanie_sklada}</>}
        </div>
      )}
      <div className="border border-border rounded-md overflow-hidden overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-alt border-b border-border text-left text-muted font-semibold">
              <th className="px-3 py-2">Порода</th>
              <th className="px-3 py-2">Сортимент (сорт ЕГАИС)</th>
              <th className="px-3 py-2 text-right">Объём, м³</th>
            </tr>
          </thead>
          <tbody>
            {porody.map((poroda) => {
              const sorts = egais.porody[poroda] || {};
              const sortKeys = Object.keys(sorts).sort((a, b) => (a === "дрова" ? 1 : b === "дрова" ? -1 : a.localeCompare(b)));
              const total = sortKeys.reduce((sum, k) => sum + (sorts[k] || 0), 0);
              return (
                <React.Fragment key={poroda}>
                  {sortKeys.map((sort, i) => (
                    <tr key={poroda + sort} className="border-b border-border last:border-b-0">
                      {i === 0 && (
                        <td rowSpan={sortKeys.length + 1} className="px-3 py-2 text-ink font-semibold align-top border-r border-border">
                          {poroda}
                        </td>
                      )}
                      <td className="px-3 py-2 text-ink">{sort === "дрова" ? "Дрова" : sort}</td>
                      <td className="px-3 py-2 text-right text-ink">{(sorts[sort] || 0).toFixed(1)}</td>
                    </tr>
                  ))}
                  <tr className="border-b border-border last:border-b-0 bg-surface-alt">
                    <td className="px-3 py-2 text-ink font-semibold text-right" colSpan={1}>Итого по породе</td>
                    <td className="px-3 py-2 text-right text-ink font-semibold">{total.toFixed(1)}</td>
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Баннер "расход по ЕГАИС не сходится с приходом" — см. raskhod_v2.
// compute_egais_balance_check. Два состояния: "explained" (дефицит
// покрывается неразобранным приходом на ФЛС/корректировками — просто
// напоминание, где разобрать) и настоящая тревога (ни один из известных
// журналу источников не объясняет дефицит — скорее всего "холодный
// старт": делянка начала отгружаться раньше, чем в приложение стали
// загружать выгрузки ЕГАИС).
function EgaisBalanceBanner({ check, onOpenReview }) {
  if (!check?.has_history || !(check.deficit > 0.01)) return null;
  if (check.explained) {
    return (
      <div className="rounded-lg border border-oak/40 bg-oak-soft px-3.5 py-2.5 text-sm text-ink flex items-center justify-between gap-3 flex-wrap">
        <div>
          <span className="font-semibold text-oak">Расход по ЕГАИС временно больше прихода на {check.deficit.toFixed(2)} м³.</span>{" "}
          Это покрывается ещё не разобранными записями (приход на ФЛС: {check.fls_unresolved.toFixed(2)} м³
          {check.korrektirovki_unresolved > 0 && <>, корректировки остатков: {check.korrektirovki_unresolved.toFixed(2)} м³</>}) —
          разберите их, и баланс сойдётся.
        </div>
        {onOpenReview && (
          <Button variant="secondary" size="sm" onClick={onOpenReview} className="shrink-0">🔎 Разбор ЕГАИС</Button>
        )}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-error/40 bg-error-soft px-3.5 py-2.5 text-sm text-ink">
      <span className="font-semibold text-error">
        Расход по ЕГАИС больше прихода на {check.deficit.toFixed(2)} м³, и это не объясняется данными в журнале.
      </span>{" "}
      Похоже, делянка начала отгружаться раньше, чем в приложение стали загружать выгрузки ЕГАИС («холодный старт» —
      история движения до этого момента в журнале не накопилась). Сделайте отдельную полную выгрузку «Реестр движения
      по складам» именно по этой делянке с самого начала заготовки и импортируйте её — баланс досчитается сам.
    </div>
  );
}

// Компактная сводка по ВСЕЙ делянке (может быть несколько выделов) —
// видна сразу после выбора делянки, ещё до того, как открыт конкретный
// выдел (иначе проблему на "непопулярном" выделе легко не заметить, если
// в него не заходить). Детали — тот же EgaisBalanceBanner ниже, на уровне
// конкретного выдела.
function DelyankaEgaisSummary({ check, onOpenReview }) {
  if (!check?.items?.length) return null;
  const withDeficit = check.items.filter((it) => it.has_history && it.deficit > 0.01);
  if (withDeficit.length === 0) return null;
  const unexplained = withDeficit.filter((it) => !it.explained);
  const tone = unexplained.length > 0 ? "danger" : "warning";
  return (
    <div className={["rounded-lg border px-3.5 py-2.5 text-sm text-ink flex items-center justify-between gap-3 flex-wrap",
      tone === "danger" ? "border-error/40 bg-error-soft" : "border-oak/40 bg-oak-soft"].join(" ")}>
      <div>
        <span className={["font-semibold", tone === "danger" ? "text-error" : "text-oak"].join(" ")}>
          Расход по ЕГАИС не сходится с приходом на {withDeficit.length} из {check.items.length} {check.items.length === 1 ? "выделе" : "выделов"} делянки
        </span>{" "}
        (Кв./Выд.: {withDeficit.map((it) => `${it.kvartal}/${it.vydel}`).join(", ")}){unexplained.length > 0
          ? <> — {unexplained.length} без объяснения в журнале, откройте выдел для подробностей.</>
          : <> — объясняется неразобранным приходом на ФЛС/корректировками.</>}
      </div>
      {onOpenReview && (
        <Button variant="secondary" size="sm" onClick={onOpenReview} className="shrink-0">🔎 Разбор ЕГАИС</Button>
      )}
    </div>
  );
}

function ItemWorkspace({ item, delyankaId, egaisVersion, onOpenEgaisReview }) {
  const toast = useToast();
  const [balance, setBalance] = useState(null);
  const [naryady, setNaryady] = useState([]);
  const [egais, setEgais] = useState(null);
  const [ploshadInfo, setPloshadInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [naryadModal, setNaryadModal] = useState({ open: false, editing: null });
  const [exporting, setExporting] = useState(false);
  const [view, setView] = useState("naryady"); // "naryady" | "egais" | "journal"
  const [selectedPoroda, setSelectedPoroda] = useState(null);
  const [journal, setJournal] = useState(null);
  const [journalLoading, setJournalLoading] = useState(false);
  const [balanceCheck, setBalanceCheck] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [balanceRes, naryadyRes, ploshadRes] = await Promise.all([
        api.get(`/raskhod/items/${item.id}/balance`),
        api.get(`/raskhod/items/${item.id}/naryady`),
        api.get(`/raskhod/items/${item.id}/ploshad`),
      ]);
      setBalance(balanceRes);
      setNaryady(naryadyRes || []);
      setPloshadInfo(ploshadRes);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить баланс", description: e.message });
    } finally {
      setLoading(false);
    }
    // Отдельный try/catch: пока на бэкенде нет /raskhod/items/{id}/egais,
    // отсутствие ЕГАИС-данных не должно ронять загрузку баланса/нарядов.
    try {
      const egaisRes = await api.get(`/raskhod/items/${item.id}/egais`);
      setEgais(egaisRes);
    } catch (e) {
      setEgais(null);
    }
    // Сверка "расход не больше прихода" по журналу — та же логика:
    // отсутствие данных не должно мешать остальному экрану.
    try {
      const checkRes = await api.get(`/raskhod/items/${item.id}/egais/balance-check`);
      setBalanceCheck(checkRes);
    } catch (e) {
      setBalanceCheck(null);
    }
  }, [item.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
    // egaisVersion специально в зависимостях, а не только в load(): импорт
    // ЕГАИС или разбор очереди в EgaisReviewModal могут произойти, пока
    // пользователь уже сидит на этом же выделе (ItemWorkspace не
    // перемонтируется — item.id не меняется). Раньше баланс в этом случае
    // не обновлялся вообще, пока не выбрать делянку/выдел заново — родитель
    // (Raskhod) увеличивает egaisVersion при закрытии модалок импорта/
    // разбора, и это форсирует повторный load() здесь.
    setJournal(null); // форсирует повторную подгрузку журнала ниже
  }, [load, egaisVersion]);

  // Журнал грузится отдельно и лениво (только когда открыта вкладка) —
  // он может быть заметно больше баланса/нарядов (вся накопленная
  // история, а не только текущий снимок), незачем тянуть его для каждого
  // выдела сразу при открытии делянки.
  useEffect(() => {
    if (view !== "journal" || journal !== null) return;
    setJournalLoading(true);
    api.get(`/raskhod/items/${item.id}/egais/journal`)
      .then((res) => setJournal(res?.rows || []))
      .catch(() => setJournal([]))
      .finally(() => setJournalLoading(false));
  }, [view, journal, item.id]);

  const handleDeleteNaryad = async (naryadId) => {
    if (!window.confirm("Удалить этот наряд?")) return;
    try {
      await api.delete(`/raskhod/naryady/${naryadId}`);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить наряд", description: e.message });
    }
  };

  const handleDeleteEgais = async () => {
    if (!window.confirm("Удалить данные выгрузки ЕГАИС по этому выделу? Данные наряда не затронет.")) return;
    try {
      await api.delete(`/raskhod/items/${item.id}/egais`);
      toast.show({ tone: "success", title: "Данные ЕГАИС удалены" });
      // Раньше здесь был только setEgais(null) — сама вкладка "ЕГАИС"
      // очищалась, а fakt_egais/ostatok_egais в таблице баланса выше
      // оставались от старого снапшота до следующей перезагрузки страницы.
      // load() пересчитывает и баланс, и вкладку ЕГАИС из уже пустого
      // снапшота, поэтому оба места сразу показывают актуальные нули.
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить данные ЕГАИС", description: e.message });
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const { task_id } = await api.post(`/raskhod/items/${item.id}/export`);
      const result = await pollTask(task_id, { timeoutMs: 5 * 60 * 1000 });
      const docId = result?.document_ids?.[0];
      toast.show({
        tone: "success",
        title: "Книга расхода готова",
        description: docId ? "Файл открыт в новой вкладке." : undefined,
      });
      if (docId) window.open(`${API_BASE_URL}/documents/${docId}/download`, "_blank");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось экспортировать", description: e.message });
    } finally {
      setExporting(false);
    }
  };

  if (loading || !balance) {
    return (
      <Card>
        <div className="flex items-center justify-center py-16">
          <div className="h-6 w-6 rounded-full border-2 border-pine border-t-transparent animate-spin" />
        </div>
      </Card>
    );
  }

  const porody = Object.keys(balance).sort();
  const egaisPorodyCount = egais?.porody ? Object.keys(egais.porody).length : 0;

  return (
    <div className="flex flex-col gap-[14px]">
      <Card>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-ui font-extrabold text-[14.5px] text-pine">
            Баланс — Кв. {item.kvartal || "—"} / Выд. {item.vydel || "—"}
          </h2>
          <Button variant="secondary" onClick={handleExport} loading={exporting}>↓ Книга расхода .xlsx</Button>
        </div>
        <BalanceTable
          balance={balance}
          ploshadInfo={ploshadInfo}
          selectedPoroda={selectedPoroda}
          onSelectPoroda={setSelectedPoroda}
        />
      </Card>

      <EgaisBalanceBanner check={balanceCheck} onOpenReview={onOpenEgaisReview} />

      <Card>
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <NaryadyEgaisToggle view={view} onChange={setView} egaisCount={egaisPorodyCount} journalCount={journal?.length} />
          {view === "naryady" && (
            <Button variant="primary" size="sm" onClick={() => setNaryadModal({ open: true, editing: null })}>
              + Новый наряд
            </Button>
          )}
          {view === "egais" && egaisPorodyCount > 0 && (
            <Button variant="secondary" size="sm" onClick={handleDeleteEgais}>
              Удалить данные ЕГАИС
            </Button>
          )}
        </div>

        {view === "naryady" ? (
          naryady.length === 0 ? (
            <EmptyState icon="📋" title="Нарядов пока нет" description="Добавьте первый наряд-задание кнопкой выше." />
          ) : (
            <div className="flex flex-col gap-2">
              {naryady.map((n) => (
                <div key={n.id} className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border bg-surface px-3.5 py-3">
                  <div className="min-w-0" style={{ flex: "1 1 220px" }}>
                    <div className="flex items-center flex-wrap gap-2.5">
                      <span className="text-[12px] text-muted-2" style={MONO_STYLE}>{n.data || "—"}</span>
                      <span className="text-[13px] font-bold text-pine">№ {n.nomer_naryada || "—"}</span>
                      <span className="text-[12px] text-muted-2" style={MONO_STYLE}>{n.ploshad ? `${n.ploshad} га` : "— га"}</span>
                    </div>
                    <div className="text-[13px] text-ink mt-[3px]">
                      {n.pozitsii?.length
                        ? n.pozitsii.map((p) => `${p.poroda} · ${SORTIMENT_LABELS[p.sortiment] || p.sortiment} · ${p.obyom} м³`).join("; ")
                        : "—"}
                    </div>
                    {n.primechanie && <div className="text-[12px] text-faint mt-0.5">{n.primechanie}</div>}
                  </div>
                  <div className="flex gap-1.5 shrink-0">
                    <Button variant="secondary" size="sm" onClick={() => setNaryadModal({ open: true, editing: n })}>Изменить</Button>
                    <Button variant="danger" size="sm" onClick={() => handleDeleteNaryad(n.id)}>Удалить</Button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : view === "egais" ? (
          <EgaisRaskhodTable egais={egais} />
        ) : (
          <EgaisJournalTable rows={journal} loading={journalLoading} />
        )}
      </Card>

      <NaryadModal
        open={naryadModal.open}
        onClose={() => setNaryadModal({ open: false, editing: null })}
        itemId={item.id}
        porody={porody}
        editing={naryadModal.editing}
        onSaved={load}
        ploshadDelyanki={ploshadInfo?.ploshad_delyanki}
        limitKubaturaTotal={ploshadInfo?.limit_kubatura_total}
      />
    </div>
  );
}

function SummaryModal({ open, onClose, delyankaId, delyankaLabel }) {
  const toast = useToast();
  const [scope, setScope] = useState("all"); // "all" | "delyanka"
  const [balance, setBalance] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setScope(delyankaId ? "delyanka" : "all");
  }, [open, delyankaId]);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    const params = scope === "delyanka" && delyankaId ? { delyanka_id: delyankaId } : undefined;
    api
      .get("/raskhod/summary", params)
      .then(setBalance)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить сводку", description: e.message }))
      .finally(() => setLoading(false));
  }, [open, scope, delyankaId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Modal open={open} onClose={onClose} title="Сводка по породам" size="lg" footer={<Button variant="ghost" onClick={onClose}>Закрыть</Button>}>
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setScope("all")}
            className={["px-3 py-1.5 rounded-md text-sm font-semibold transition-colors border",
              scope === "all" ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover"].join(" ")}
          >
            По всем делянкам
          </button>
          <button
            onClick={() => setScope("delyanka")}
            disabled={!delyankaId}
            className={["px-3 py-1.5 rounded-md text-sm font-semibold transition-colors border disabled:opacity-40 disabled:cursor-not-allowed",
              scope === "delyanka" ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover"].join(" ")}
          >
            {delyankaLabel ? `По делянке «${delyankaLabel}»` : "По выбранной делянке"}
          </button>
        </div>
        {loading || !balance ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 rounded-full border-2 border-pine border-t-transparent animate-spin" />
          </div>
        ) : (
          <BalanceTable balance={balance} />
        )}
      </div>
    </Modal>
  );
}

export default function Raskhod() {
  const toast = useToast();
  const [delyanki, setDelyanki] = useState([]);
  const [delyankaId, setDelyankaId] = useState("");
  const [items, setItems] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [importOpen, setImportOpen] = useState(false);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [delyankaSearch, setDelyankaSearch] = useState("");
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [egaisReviewOpen, setEgaisReviewOpen] = useState(false);
  const [egaisReviewCount, setEgaisReviewCount] = useState(0);
  const [delyankaEgaisCheck, setDelyankaEgaisCheck] = useState(null);
  // Растёт при каждом закрытии "Импорт ЕГАИС"/"Разбор ЕГАИС" — единственная
  // цель это значения - быть новым числом в deps у ItemWorkspace, чтобы
  // заставить его перечитать /balance и /egais, даже если выбранный выдел
  // (selectedItem) не менялся и компонент не перемонтировался.
  const [egaisVersion, setEgaisVersion] = useState(0);

  const loadDelyankaEgaisCheck = useCallback((id) => {
    if (!id) { setDelyankaEgaisCheck(null); return; }
    api.get(`/raskhod/delyanki/${id}/egais/balance-check`)
      .then(setDelyankaEgaisCheck)
      .catch(() => setDelyankaEgaisCheck(null));
  }, []);

  const loadEgaisReviewSummary = useCallback(() => {
    api
      .get("/raskhod/egais/review/summary")
      .then((s) => setEgaisReviewCount((s?.korrektirovki_new ?? 0) + (s?.unmatched_delyanka_new ?? 0) + (s?.fls_prihod_new ?? 0)))
      .catch(() => {});
  }, []);

  useEffect(() => {
    // Только 'активна' — черновики (сразу после импорта МДО, без номера/даты
    // лесорубочного билета) в расходе не должны быть доступны для выбора.
    api.get("/delyanki/", { status: "активна" }).then(setDelyanki).catch((e) => {
      toast.show({ tone: "danger", title: "Не удалось загрузить делянки", description: e.message });
    });
    loadEgaisReviewSummary();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelyankaChange = async (id) => {
    setDelyankaId(id);
    setSelectedItem(null);
    setItems([]);
    if (!id) return;
    setItemsLoading(true);
    try {
      const res = await api.get(`/delyanki/${id}`);
      setItems(res.items || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить выделы делянки", description: e.message });
    } finally {
      setItemsLoading(false);
    }
  };

  useEffect(() => {
    // Тот же счётчик egaisVersion, что форсирует перезагрузку
    // ItemWorkspace — импорт ЕГАИС/разбор очереди могли поменять картину
    // по делянке в целом, не только по открытому сейчас выделу.
    // loadDelyankaEgaisCheck сама чистит состояние в null при пустом id
    // (делянка не выбрана/сброшена).
    loadDelyankaEgaisCheck(delyankaId);
  }, [egaisVersion, delyankaId, loadDelyankaEgaisCheck]);

  const handleDeleteDelyankaEgais = async () => {
    const label = delyanki.find((d) => String(d.id) === String(delyankaId))?.nazvanie || `Делянка №${delyankaId}`;
    if (!window.confirm(`Удалить данные выгрузки ЕГАИС по ВСЕМ выделам делянки «${label}»? Наряды-задания не затронет.`)) return;
    try {
      const res = await api.delete(`/raskhod/delyanki/${delyankaId}/egais`);
      toast.show({
        tone: "success",
        title: "Данные ЕГАИС удалены",
        description: `Затронуто выделов: ${res.items_affected} из ${res.items_total}.`,
      });
      // Открытая карточка выдела (если она сейчас показывает данные этой
      // же делянки) должна перечитать баланс и вкладку ЕГАИС — тот же
      // счётчик, что и после "Импорт ЕГАИС"/"Разбор ЕГАИС".
      setEgaisVersion((v) => v + 1);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить данные ЕГАИС по делянке", description: e.message });
    }
  };

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex items-end gap-4 flex-wrap">
          <div className="min-w-[220px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Поиск делянки</label>
            <TextField
              placeholder="По названию или №…"
              value={delyankaSearch}
              onChange={(e) => setDelyankaSearch(e.target.value)}
            />
          </div>
          <div className="min-w-[260px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Делянка</label>
            <select
              value={delyankaId}
              onChange={(e) => handleDelyankaChange(e.target.value)}
              className="w-full bg-surface border border-border focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
            >
              <option value="">Выберите делянку…</option>
              {delyanki
                .filter((d) => {
                  const q = delyankaSearch.trim().toLowerCase();
                  if (!q) return true;
                  const label = (d.nazvanie || `Делянка №${d.id}`).toLowerCase();
                  return label.includes(q) || String(d.id).includes(q);
                })
                .map((d) => (
                  <option key={d.id} value={d.id}>{d.nazvanie || `Делянка №${d.id}`}</option>
                ))}
            </select>
          </div>

          {itemsLoading && <div className="h-5 w-5 rounded-full border-2 border-pine border-t-transparent animate-spin" />}

          {items.length > 0 && (
            <div className="flex-1 min-w-[260px]">
              <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Выдел</label>
              <div className="flex flex-wrap gap-2">
                {items.map((it) => (
                  <button
                    key={it.id}
                    onClick={() => setSelectedItem(it)}
                    className={[
                      "px-3 py-2 rounded-md text-sm font-semibold transition-colors border",
                      selectedItem?.id === it.id ? "bg-pine border-pine text-white" : "bg-surface border-border text-muted hover:bg-hover",
                    ].join(" ")}
                  >
                    Кв. {it.kvartal || "—"} / Выд. {it.vydel || "—"}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="ml-auto flex items-center gap-2">
            <Button variant="secondary" onClick={() => setSummaryOpen(true)}>
              📊 Сводка по породам
            </Button>
            {delyankaId && (
              <Button variant="secondary" onClick={handleDeleteDelyankaEgais}>
                🗑️ Удалить ЕГАИС по делянке
              </Button>
            )}
            <Button variant="secondary" onClick={() => setImportOpen(true)}>
              📥 Импорт ЕГАИС
            </Button>
            <Button variant="secondary" onClick={() => setEgaisReviewOpen(true)}>
              🔎 Разбор ЕГАИС
              {egaisReviewCount > 0 && <StatusBadge tone="warning" label={egaisReviewCount} dot={false} className="ml-1" />}
            </Button>
          </div>
        </div>
      </Card>

      <DelyankaEgaisSummary check={delyankaEgaisCheck} onOpenReview={() => setEgaisReviewOpen(true)} />

      {selectedItem ? (
        <ItemWorkspace
          item={selectedItem}
          delyankaId={delyankaId}
          egaisVersion={egaisVersion}
          onOpenEgaisReview={() => setEgaisReviewOpen(true)}
        />
      ) : (
        <Card>
          <EmptyState
            icon="🧮"
            title="Выберите делянку и выдел"
            description="Баланс лимитов/факта и наряды-задания считаются для конкретного выдела делянки."
          />
        </Card>
      )}

      <ImportEgaisModal
        open={importOpen}
        onClose={() => {
          setImportOpen(false);
          loadEgaisReviewSummary();
          setEgaisVersion((v) => v + 1);
        }}
      />
      <EgaisReviewModal
        open={egaisReviewOpen}
        onClose={() => {
          setEgaisReviewOpen(false);
          loadEgaisReviewSummary();
          setEgaisVersion((v) => v + 1);
        }}
        delyanki={delyanki}
      />
      <SummaryModal
        open={summaryOpen}
        onClose={() => setSummaryOpen(false)}
        delyankaId={delyankaId || null}
        delyankaLabel={delyanki.find((d) => String(d.id) === String(delyankaId))?.nazvanie}
      />
    </div>
  );
}
