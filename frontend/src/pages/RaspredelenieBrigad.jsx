import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import Modal from "../components/Modal.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Распределение бригад" — когда делянка близка к завершению (по
 * % освоения лимита / остатку площади / сроку вывозки, см. backend/
 * legacy/brigada.py:list_delyanki_dlya_raspredeleniya, те же функции
 * raskhod_v2, что уже использует "Инспекция"), нужно решить, куда
 * дальше направить бригаду/рабочего — сюда собраны обе таблицы:
 * "какие делянки заканчиваются" и "какие бригады есть и где они сейчас
 * работают", плюс действие "назначить"/"переместить" поверх
 * app/routers/brigady.py.
 *
 * Пороги для подсветки продублированы с backend'а (PCT_OSVOENIYA_LIMITA_
 * PORIG=85, PLOSHAD_OSTATOK_PCT_PORIG=15, SROK_DNEI_PORIG=14) — тот же
 * приём, что и URGENT_SOON_DAYS в Inspection.jsx: сигнал считает бэкенд
 * (is_zavershaetsya), здесь только раскраска на основе тех же цифр.
 */
const PCT_OSVOENIYA_PORIG = 85;
const PLOSHAD_OSTATOK_PORIG = 15;
const SROK_DNEI_PORIG = 14;

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function daysUntil(isoOrRuDate) {
  if (!isoOrRuDate) return null;
  let d;
  if (isoOrRuDate.includes(".")) {
    const [dd, mm, yyyy] = isoOrRuDate.split(".").map((p) => parseInt(p, 10));
    if (!dd || !mm || !yyyy) return null;
    d = new Date(yyyy, mm - 1, dd);
  } else {
    d = new Date(isoOrRuDate + "T00:00:00");
  }
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return Math.round((d - today) / (1000 * 60 * 60 * 24));
}

function pctBadge(value, threshold, aboveIsBad) {
  if (value == null) return <StatusBadge tone="neutral" label="—" />;
  const bad = aboveIsBad ? value >= threshold : value <= threshold;
  return <StatusBadge tone={bad ? "danger" : "neutral"} label={`${value}%`} />;
}

function srokBadge(sroku) {
  if (!sroku) return <StatusBadge tone="neutral" label="срок не задан" />;
  const days = daysUntil(sroku);
  if (days == null) return <StatusBadge tone="neutral" label={sroku} />;
  if (days < 0) return <StatusBadge tone="danger" label={`просрочен на ${-days} дн.`} />;
  if (days <= SROK_DNEI_PORIG) return <StatusBadge tone="warning" label={`через ${days} дн.`} />;
  return <StatusBadge tone="neutral" label={sroku} />;
}

function emptyBrigadaForm() {
  return { nazvanie: "", brigadir_sotrudnik_id: "" };
}

function emptyNaznachenieForm() {
  return {
    executorType: "brigada",
    brigada_id: "",
    sotrudnik_id: "",
    targetType: "delyanka",
    delyanka_id: "",
    lesokultury_uchastok_id: "",
    data_nachala: todayIso(),
    data_okonchaniya: "",
    kommentariy: "",
  };
}

export default function RaspredelenieBrigad() {
  const toast = useToast();

  const [delyankiStatus, setDelyankiStatus] = useState(null);
  const [brigady, setBrigady] = useState(null);
  const [sotrudniki, setSotrudniki] = useState([]);
  const [activnyeDelyanki, setActivnyeDelyanki] = useState([]);
  const [activnyeLesokultury, setActivnyeLesokultury] = useState([]);

  const [brigadaModalOpen, setBrigadaModalOpen] = useState(false);
  const [brigadaForm, setBrigadaForm] = useState(emptyBrigadaForm());
  const [savingBrigada, setSavingBrigada] = useState(false);

  const [sostavModalOpen, setSostavModalOpen] = useState(false);
  const [sostavBrigadaId, setSostavBrigadaId] = useState(null);
  const [sostavSelection, setSostavSelection] = useState([]);
  const [savingSostav, setSavingSostav] = useState(false);

  const [naznachenieModalOpen, setNaznachenieModalOpen] = useState(false);
  const [naznachenieForm, setNaznachenieForm] = useState(emptyNaznachenieForm());
  const [executorLocked, setExecutorLocked] = useState(false);
  const [closingCurrent, setClosingCurrent] = useState(false); // "переместить" vs "назначить"
  const [savingNaznachenie, setSavingNaznachenie] = useState(false);

  const load = useCallback(() => {
    setDelyankiStatus(null);
    setBrigady(null);
    Promise.all([
      api.get("/brigady/delyanki-status"),
      api.get("/brigady/"),
      api.get("/brigady/sotrudniki"),
      api.get("/delyanki/", { status: "активна" }),
      api.get("/brigady/lesokultury-uchastki"),
    ])
      .then(([status, br, sotr, delyanki, lesokultury]) => {
        setDelyankiStatus(status);
        setBrigady(br);
        setSotrudniki(sotr);
        setActivnyeDelyanki(delyanki);
        setActivnyeLesokultury(lesokultury);
      })
      .catch((err) => {
        toast.show({
          tone: "danger",
          title: "Не удалось загрузить данные",
          description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
        });
        setDelyankiStatus([]);
        setBrigady([]);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const delyankaNameById = useMemo(() => {
    const map = new Map();
    for (const d of activnyeDelyanki) map.set(d.id, d.nazvanie || `Делянка №${d.id}`);
    for (const d of delyankiStatus || []) if (!map.has(d.id)) map.set(d.id, d.nazvanie || `Делянка №${d.id}`);
    return map;
  }, [activnyeDelyanki, delyankiStatus]);

  const sotrudnikFioById = useMemo(() => {
    const map = new Map();
    for (const s of sotrudniki) map.set(s.id, s.fio);
    return map;
  }, [sotrudniki]);

  const brigadaNameById = useMemo(() => {
    const map = new Map();
    for (const b of brigady || []) map.set(b.id, b.nazvanie);
    return map;
  }, [brigady]);

  const lesokulturyLabelById = useMemo(() => {
    const map = new Map();
    for (const u of activnyeLesokultury) {
      map.set(u.id, `кв. ${u.kvartal || "—"} / выд. ${u.vydel || "—"}${u.lesnichestvo ? ` (${u.lesnichestvo})` : ""}`);
    }
    return map;
  }, [activnyeLesokultury]);

  const executorLabel = (naznachenie) => {
    if (!naznachenie) return "—";
    if (naznachenie.brigada_id) return brigadaNameById.get(naznachenie.brigada_id) || `Бригада №${naznachenie.brigada_id}`;
    if (naznachenie.sotrudnik_id) return sotrudnikFioById.get(naznachenie.sotrudnik_id) || `Сотрудник №${naznachenie.sotrudnik_id}`;
    return "—";
  };

  // Назначение бригады/рабочего теперь целится либо в делянку, либо в
  // участок лесных культур (ровно одно из двух, см. brigada.py) — этот
  // помощник резолвит название места по тому, какое поле заполнено.
  const targetLabel = (naznachenie) => {
    if (!naznachenie) return "—";
    if (naznachenie.delyanka_id) return delyankaNameById.get(naznachenie.delyanka_id) || `Делянка №${naznachenie.delyanka_id}`;
    if (naznachenie.lesokultury_uchastok_id) {
      return lesokulturyLabelById.get(naznachenie.lesokultury_uchastok_id) || `Участок №${naznachenie.lesokultury_uchastok_id}`;
    }
    return "—";
  };

  const naznachenieRange = (naznachenie) => {
    if (!naznachenie) return "";
    return naznachenie.data_okonchaniya
      ? `${naznachenie.data_nachala} — ${naznachenie.data_okonchaniya}`
      : `с ${naznachenie.data_nachala}`;
  };

  // --- бригады: создание ---
  const openCreateBrigada = () => {
    setBrigadaForm(emptyBrigadaForm());
    setBrigadaModalOpen(true);
  };

  const handleSaveBrigada = async () => {
    if (!brigadaForm.nazvanie.trim()) {
      toast.show({ tone: "warning", title: "Укажите название бригады" });
      return;
    }
    setSavingBrigada(true);
    try {
      await api.post("/brigady/", {
        nazvanie: brigadaForm.nazvanie.trim(),
        brigadir_sotrudnik_id: brigadaForm.brigadir_sotrudnik_id ? Number(brigadaForm.brigadir_sotrudnik_id) : null,
      });
      toast.show({ tone: "success", title: "Бригада создана" });
      setBrigadaModalOpen(false);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось создать бригаду", description: e instanceof ApiError ? e.message : "Неизвестная ошибка" });
    } finally {
      setSavingBrigada(false);
    }
  };

  // --- бригады: состав ---
  const openSostav = (brigada) => {
    setSostavBrigadaId(brigada.id);
    setSostavSelection(brigada.sostav.map((s) => s.id));
    setSostavModalOpen(true);
  };

  const handleSaveSostav = async () => {
    setSavingSostav(true);
    try {
      await api.patch(`/brigady/${sostavBrigadaId}/sostav`, { sotrudnik_ids: sostavSelection });
      toast.show({ tone: "success", title: "Состав бригады обновлён" });
      setSostavModalOpen(false);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить состав", description: e instanceof ApiError ? e.message : "Неизвестная ошибка" });
    } finally {
      setSavingSostav(false);
    }
  };

  // --- назначения: создание/перемещение ---
  const openNaznachenieGeneric = () => {
    setNaznachenieForm(emptyNaznachenieForm());
    setExecutorLocked(false);
    setClosingCurrent(false);
    setNaznachenieModalOpen(true);
  };

  const openNaznachenieForBrigada = (brigada) => {
    setNaznachenieForm({
      ...emptyNaznachenieForm(),
      executorType: "brigada",
      brigada_id: String(brigada.id),
    });
    setExecutorLocked(true);
    setClosingCurrent(!!brigada.tekushee_naznachenie);
    setNaznachenieModalOpen(true);
  };

  const openNaznachenieForDelyankaRow = (row) => {
    const tekushee = row.tekushee_naznachenie;
    if (!tekushee) return;
    setNaznachenieForm({
      ...emptyNaznachenieForm(),
      executorType: tekushee.brigada_id ? "brigada" : "sotrudnik",
      brigada_id: tekushee.brigada_id ? String(tekushee.brigada_id) : "",
      sotrudnik_id: tekushee.sotrudnik_id ? String(tekushee.sotrudnik_id) : "",
    });
    setExecutorLocked(true);
    setClosingCurrent(true);
    setNaznachenieModalOpen(true);
  };

  const handleSaveNaznachenie = async () => {
    const {
      executorType, brigada_id, sotrudnik_id, targetType, delyanka_id, lesokultury_uchastok_id,
      data_nachala, data_okonchaniya, kommentariy,
    } = naznachenieForm;
    const targetId = targetType === "delyanka" ? delyanka_id : lesokultury_uchastok_id;
    if (!targetId || !data_nachala || (executorType === "brigada" ? !brigada_id : !sotrudnik_id)) {
      toast.show({ tone: "warning", title: "Заполните исполнителя, место работы и дату начала" });
      return;
    }
    setSavingNaznachenie(true);
    try {
      await api.post("/brigady/naznacheniya", {
        delyanka_id: targetType === "delyanka" ? Number(delyanka_id) : null,
        lesokultury_uchastok_id: targetType === "lesokultury" ? Number(lesokultury_uchastok_id) : null,
        data_nachala,
        data_okonchaniya: data_okonchaniya || null,
        brigada_id: executorType === "brigada" ? Number(brigada_id) : null,
        sotrudnik_id: executorType === "sotrudnik" ? Number(sotrudnik_id) : null,
        kommentariy: kommentariy.trim() || null,
        close_current_for_brigada: closingCurrent,
      });
      toast.show({ tone: "success", title: closingCurrent ? "Бригада перемещена" : "Назначение создано" });
      setNaznachenieModalOpen(false);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить назначение", description: e instanceof ApiError ? e.message : "Неизвестная ошибка" });
    } finally {
      setSavingNaznachenie(false);
    }
  };

  const handleZavershit = async (naznachenie) => {
    if (!window.confirm("Завершить работу этой бригады/рабочего на текущей делянке?")) return;
    try {
      await api.patch(`/brigady/naznacheniya/${naznachenie.id}`, {
        status: "завершено",
        data_okonchaniya: todayIso(),
      });
      toast.show({ tone: "info", title: "Работа на делянке завершена" });
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось завершить назначение", description: e instanceof ApiError ? e.message : "Неизвестная ошибка" });
    }
  };

  // Ближе к верху — те, у кого сигнал "близка к завершению" уже сработал
  // и совсем нет плана, куда двинется бригада дальше — именно они требуют
  // внимания лесничего прямо сейчас (тот же принцип, что и URGENCY_RANK в
  // Inspection.jsx).
  const sortedDelyankiStatus = useMemo(() => {
    const rows = delyankiStatus || [];
    return [...rows].sort((a, b) => {
      const aUrgent = a.is_zavershaetsya && !a.sleduyushee_naznachenie;
      const bUrgent = b.is_zavershaetsya && !b.sleduyushee_naznachenie;
      if (aUrgent !== bUrgent) return aUrgent ? -1 : 1;
      if (a.is_zavershaetsya !== b.is_zavershaetsya) return a.is_zavershaetsya ? -1 : 1;
      return 0;
    });
  }, [delyankiStatus]);

  const delyankiColumns = useMemo(
    () => [
      { key: "nazvanie", header: "Делянка", render: (r) => r.nazvanie || `Делянка №${r.id}` },
      { key: "pct_osvoeniya_limita", header: "% освоения", render: (r) => pctBadge(r.pct_osvoeniya_limita, PCT_OSVOENIYA_PORIG, true) },
      { key: "pct_ploshad_ostatka", header: "% площади в остатке", render: (r) => pctBadge(r.pct_ploshad_ostatka, PLOSHAD_OSTATOK_PORIG, false) },
      { key: "srok_okonchaniya_vyvozki", header: "Срок вывозки", render: (r) => srokBadge(r.srok_okonchaniya_vyvozki) },
      { key: "tekushee", header: "Сейчас работает", render: (r) => executorLabel(r.tekushee_naznachenie) },
      {
        key: "sleduyushee",
        header: "Следующая делянка",
        render: (r) => {
          if (!r.tekushee_naznachenie) return "—";
          if (!r.sleduyushee_naznachenie) {
            return <StatusBadge tone="warning" label="не запланировано" />;
          }
          return `${targetLabel(r.sleduyushee_naznachenie)} (${naznachenieRange(r.sleduyushee_naznachenie)})`;
        },
      },
      {
        key: "actions",
        header: "",
        render: (r) =>
          r.tekushee_naznachenie ? (
            <Button size="sm" variant="ghost" onClick={() => openNaznachenieForDelyankaRow(r)}>
              Переместить бригаду
            </Button>
          ) : null,
      },
    ],
    [delyankaNameById, brigadaNameById, sotrudnikFioById, lesokulturyLabelById] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const brigadyColumns = useMemo(
    () => [
      { key: "nazvanie", header: "Название", sortable: true },
      {
        key: "brigadir",
        header: "Бригадир",
        render: (b) => (b.brigadir_sotrudnik_id ? sotrudnikFioById.get(b.brigadir_sotrudnik_id) || "—" : "—"),
      },
      {
        key: "sostav",
        header: "Состав",
        render: (b) => (b.sostav.length ? b.sostav.map((s) => s.fio).join(", ") : <span className="text-muted">пусто</span>),
      },
      {
        key: "tekushee",
        header: "Текущее место работы",
        render: (b) =>
          b.tekushee_naznachenie
            ? `${targetLabel(b.tekushee_naznachenie)} (${naznachenieRange(b.tekushee_naznachenie)})`
            : "—",
      },
      {
        key: "sleduyushee",
        header: "Следующее место работы",
        render: (b) =>
          b.sleduyushee_naznachenie
            ? `${targetLabel(b.sleduyushee_naznachenie)} (${naznachenieRange(b.sleduyushee_naznachenie)})`
            : "—",
      },
      { key: "is_active", header: "Статус", render: (b) => <StatusBadge tone={b.is_active ? "success" : "neutral"} label={b.is_active ? "Активна" : "Не активна"} /> },
      {
        key: "actions",
        header: "",
        render: (b) => (
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={() => openSostav(b)}>Состав</Button>
            <Button size="sm" variant="ghost" onClick={() => openNaznachenieForBrigada(b)}>
              {b.tekushee_naznachenie ? "Переместить" : "Назначить"}
            </Button>
            {b.tekushee_naznachenie && (
              <Button size="sm" variant="ghost" onClick={() => handleZavershit(b.tekushee_naznachenie)}>
                Завершить работу здесь
              </Button>
            )}
          </div>
        ),
      },
    ],
    [delyankaNameById, sotrudnikFioById, lesokulturyLabelById] // eslint-disable-line react-hooks/exhaustive-deps
  );

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card
        title="Делянки, близкие к завершению"
        subtitle="% освоения лимита, остаток площади и срок вывозки — те же данные, что и в «Инспекции»"
      >
        <DataTable
          columns={delyankiColumns}
          rows={sortedDelyankiStatus}
          loading={delyankiStatus === null}
          emptyTitle="Активных делянок нет"
          emptyDescription="Делянки появятся здесь после активации на экране «Делянки»."
        />
      </Card>

      <Card
        title="Бригады"
        actions={
          <Button variant="secondary" size="sm" onClick={openNaznachenieGeneric}>
            + Новое назначение
          </Button>
        }
        subtitle="Состав, текущая делянка и куда бригада поедет дальше"
      >
        <div className="flex justify-end mb-2.5">
          <Button variant="primary" size="sm" onClick={openCreateBrigada}>
            + Новая бригада
          </Button>
        </div>
        <DataTable
          columns={brigadyColumns}
          rows={brigady ?? []}
          loading={brigady === null}
          emptyTitle="Бригад пока нет"
          emptyDescription="Создайте первую бригаду кнопкой «+ Новая бригада» выше."
        />
      </Card>

      {/* Создание бригады */}
      <Modal
        open={brigadaModalOpen}
        onClose={() => setBrigadaModalOpen(false)}
        title="Новая бригада"
        footer={
          <>
            <Button variant="secondary" onClick={() => setBrigadaModalOpen(false)}>Отмена</Button>
            <Button variant="primary" loading={savingBrigada} onClick={handleSaveBrigada}>Создать</Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <TextField
            label="Название"
            value={brigadaForm.nazvanie}
            onChange={(e) => setBrigadaForm((f) => ({ ...f, nazvanie: e.target.value }))}
            placeholder="например: Бригада №1"
          />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted font-medium">Бригадир (необязательно)</label>
            <select
              value={brigadaForm.brigadir_sotrudnik_id}
              onChange={(e) => setBrigadaForm((f) => ({ ...f, brigadir_sotrudnik_id: e.target.value }))}
              className="bg-surface border border-border focus:border-pine rounded-md px-3 py-2.5 text-base text-ink outline-none"
            >
              <option value="">Не выбран</option>
              {sotrudniki.map((s) => (
                <option key={s.id} value={s.id}>{s.fio}{s.dolzhnost ? ` (${s.dolzhnost})` : ""}</option>
              ))}
            </select>
          </div>
        </div>
      </Modal>

      {/* Состав бригады */}
      <Modal
        open={sostavModalOpen}
        onClose={() => setSostavModalOpen(false)}
        title="Состав бригады"
        footer={
          <>
            <Button variant="secondary" onClick={() => setSostavModalOpen(false)}>Отмена</Button>
            <Button variant="primary" loading={savingSostav} onClick={handleSaveSostav}>Сохранить</Button>
          </>
        }
      >
        <p className="text-sm text-muted mb-3">
          Работник, снятый отсюда, автоматически выходит из бригады (с сегодняшней датой в истории членства); выбранный
          заново работник, уже состоящий в другой бригаде, переводится сюда.
        </p>
        <div className="max-h-72 overflow-y-auto flex flex-col gap-1">
          {sotrudniki.map((s) => (
            <label key={s.id} className="flex items-center gap-2.5 px-2 py-1.5 rounded-md hover:bg-hover cursor-pointer">
              <input
                type="checkbox"
                checked={sostavSelection.includes(s.id)}
                onChange={(e) =>
                  setSostavSelection((sel) => (e.target.checked ? [...sel, s.id] : sel.filter((id) => id !== s.id)))
                }
                className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
              />
              <span className="text-sm text-ink">{s.fio}</span>
              {s.dolzhnost && <span className="text-xs text-muted">{s.dolzhnost}</span>}
            </label>
          ))}
        </div>
      </Modal>

      {/* Назначение / перемещение */}
      <Modal
        open={naznachenieModalOpen}
        onClose={() => setNaznachenieModalOpen(false)}
        title={closingCurrent ? "Переместить бригаду" : "Назначить на делянку"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setNaznachenieModalOpen(false)}>Отмена</Button>
            <Button variant="primary" loading={savingNaznachenie} onClick={handleSaveNaznachenie}>
              {closingCurrent ? "Переместить" : "Назначить"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {!executorLocked && (
            <div className="flex gap-2">
              <Button
                type="button"
                variant={naznachenieForm.executorType === "brigada" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setNaznachenieForm((f) => ({ ...f, executorType: "brigada" }))}
              >
                Бригада
              </Button>
              <Button
                type="button"
                variant={naznachenieForm.executorType === "sotrudnik" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setNaznachenieForm((f) => ({ ...f, executorType: "sotrudnik" }))}
              >
                Отдельный рабочий
              </Button>
            </div>
          )}

          {naznachenieForm.executorType === "brigada" ? (
            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-muted font-medium">Бригада</label>
              <select
                value={naznachenieForm.brigada_id}
                disabled={executorLocked}
                onChange={(e) => setNaznachenieForm((f) => ({ ...f, brigada_id: e.target.value }))}
                className="bg-surface border border-border focus:border-pine rounded-md px-3 py-2.5 text-base text-ink outline-none disabled:opacity-60"
              >
                <option value="">Выберите бригаду…</option>
                {(brigady ?? []).map((b) => (
                  <option key={b.id} value={b.id}>{b.nazvanie}</option>
                ))}
              </select>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <label className="text-sm text-muted font-medium">Рабочий</label>
              <select
                value={naznachenieForm.sotrudnik_id}
                disabled={executorLocked}
                onChange={(e) => setNaznachenieForm((f) => ({ ...f, sotrudnik_id: e.target.value }))}
                className="bg-surface border border-border focus:border-pine rounded-md px-3 py-2.5 text-base text-ink outline-none disabled:opacity-60"
              >
                <option value="">Выберите рабочего…</option>
                {sotrudniki.map((s) => (
                  <option key={s.id} value={s.id}>{s.fio}{s.dolzhnost ? ` (${s.dolzhnost})` : ""}</option>
                ))}
              </select>
            </div>
          )}

          <div>
            <div className="text-sm text-muted font-medium mb-1.5">Место работы</div>
            <div className="flex gap-2 mb-3">
              <Button
                type="button"
                variant={naznachenieForm.targetType === "delyanka" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setNaznachenieForm((f) => ({ ...f, targetType: "delyanka", lesokultury_uchastok_id: "" }))}
              >
                Делянка
              </Button>
              <Button
                type="button"
                variant={naznachenieForm.targetType === "lesokultury" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setNaznachenieForm((f) => ({ ...f, targetType: "lesokultury", delyanka_id: "" }))}
              >
                Лесные культуры
              </Button>
            </div>

            {naznachenieForm.targetType === "delyanka" ? (
              <select
                value={naznachenieForm.delyanka_id}
                onChange={(e) => setNaznachenieForm((f) => ({ ...f, delyanka_id: e.target.value }))}
                className="w-full bg-surface border border-border focus:border-pine rounded-md px-3 py-2.5 text-base text-ink outline-none"
              >
                <option value="">Выберите делянку…</option>
                {activnyeDelyanki.map((d) => (
                  <option key={d.id} value={d.id}>{d.nazvanie || `Делянка №${d.id}`}</option>
                ))}
              </select>
            ) : (
              <select
                value={naznachenieForm.lesokultury_uchastok_id}
                onChange={(e) => setNaznachenieForm((f) => ({ ...f, lesokultury_uchastok_id: e.target.value }))}
                className="w-full bg-surface border border-border focus:border-pine rounded-md px-3 py-2.5 text-base text-ink outline-none"
              >
                <option value="">Выберите участок…</option>
                {activnyeLesokultury.map((u) => (
                  <option key={u.id} value={u.id}>{lesokulturyLabelById.get(u.id)}</option>
                ))}
              </select>
            )}
          </div>

          <div className="flex gap-3">
            <TextField
              label="Дата начала"
              type="date"
              value={naznachenieForm.data_nachala}
              onChange={(e) => setNaznachenieForm((f) => ({ ...f, data_nachala: e.target.value }))}
            />
            <TextField
              label="Дата окончания (необязательно)"
              type="date"
              value={naznachenieForm.data_okonchaniya}
              onChange={(e) => setNaznachenieForm((f) => ({ ...f, data_okonchaniya: e.target.value }))}
            />
          </div>
          <TextAreaField
            label="Комментарий (необязательно)"
            value={naznachenieForm.kommentariy}
            onChange={(e) => setNaznachenieForm((f) => ({ ...f, kommentariy: e.target.value }))}
          />
          {closingCurrent && (
            <p className="text-sm text-muted">
              Текущее назначение на прежней делянке будет автоматически укорочено — оно закончится днём раньше даты
              начала нового.
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}
