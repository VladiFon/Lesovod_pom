import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import Modal from "../components/Modal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Табель — ручной ввод" (часть раздела "Люди", по просьбе
 * пользователя, 24.09.2026) — построчная форма на ОДИН день поверх
 * GET/POST /api/tabel/day (см. app/routers/tabel.py): строка на каждого
 * активного сотрудника (в отличие от "Присутствие", где виден только тот,
 * кто сам отметился в мобильном приложении — рядовые рабочие туда пока не
 * попадают, мобильное приложение есть только у начальства).
 *
 * На строку: статус (5 вариантов, тот же набор что и в месячной сетке
 * "Присутствие"), место работы (реальная делянка или участок лесных
 * культур — тот же принцип поиска/привязки, что и в "План работ",
 * PlanRabot.jsx), вид работы (справочник vidy_rabot + возможность завести
 * новый на месте) и комментарий. Сохранение — пакетное, одной кнопкой:
 * POST /api/tabel/day целиком заменяет записи выбранного дня (UPSERT на
 * бэкенде, повторное сохранение правит уже введённое, а не плодит дубли).
 */
const STATUSES = [
  { value: "", label: "— не указано —" },
  { value: "работал", label: "Работал" },
  { value: "не работал", label: "Не работал" },
  { value: "больничный", label: "Больничный" },
  { value: "отпуск", label: "Отпуск" },
  { value: "выходной", label: "Выходной" },
];

const MOBILE_STATUS_LABEL = { "работаю": "работаю", "не работаю": "не работаю", "больничный": "больничный" };

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function serverRowToLocal(r) {
  const targetType = r.lesokultury_uchastok_id ? "lesokultury" : r.delyanka_item_id ? "delyanka" : null;
  return {
    sotrudnik_id: r.sotrudnik_id,
    fio: r.fio,
    dolzhnost: r.dolzhnost,
    mobile_status: r.mobile_status,
    status: r.status || "",
    vid_raboty_id: r.vid_raboty_id || "",
    kommentariy: r.kommentariy || "",
    targetType,
    delyanka_item_id: r.delyanka_item_id || null,
    delyankaLabel: r.delyanka_item_id ? `кв. ${r.d_kvartal || "—"} / выд. ${r.d_vydel || "—"}` : null,
    delyankaKvartal: r.d_kvartal || "",
    delyankaVydel: r.d_vydel || "",
    lesokultury_uchastok_id: r.lesokultury_uchastok_id || null,
    lesokulturyLabel: r.lesokultury_uchastok_id
      ? `кв. ${r.lku_kvartal || "—"} / выд. ${r.lku_vydel || "—"}${r.lku_glavnaya_poroda ? ` · ${r.lku_glavnaya_poroda}` : ""}`
      : null,
  };
}

export default function TabelRuchnoy() {
  const toast = useToast();

  const [date, setDate] = useState(todayIso());
  const [rows, setRows] = useState(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);

  const [vidyRabot, setVidyRabot] = useState([]);
  const [locModal, setLocModal] = useState(null);
  const [newVidSotrudnikId, setNewVidSotrudnikId] = useState(null);
  const [newVidName, setNewVidName] = useState("");
  const [savingVid, setSavingVid] = useState(false);

  useEffect(() => {
    api.get("/tabel/vidy-rabot").then(setVidyRabot).catch(() => {});
  }, []);

  const loadDay = useCallback(() => {
    setRows(null);
    api
      .get("/tabel/day", { data: date })
      .then((data) => setRows(data.map(serverRowToLocal)))
      .catch((err) => {
        toast.show({ tone: "danger", title: "Не удалось загрузить табель", description: err instanceof ApiError ? err.message : "Неизвестная ошибка" });
        setRows([]);
      });
  }, [date]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadDay();
  }, [loadDay]);

  const updateRow = (sotrudnikId, patch) => {
    setRows((prev) => prev.map((r) => (r.sotrudnik_id === sotrudnikId ? { ...r, ...patch } : r)));
  };

  const filteredRows = useMemo(() => {
    if (!rows) return [];
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.fio.toLowerCase().includes(q) || (r.dolzhnost || "").toLowerCase().includes(q));
  }, [rows, search]);

  const filledCount = useMemo(() => (rows ?? []).filter((r) => r.status).length, [rows]);

  const handleSave = async () => {
    const entries = (rows ?? [])
      .filter((r) => r.status)
      .map((r) => ({
        sotrudnik_id: r.sotrudnik_id,
        status: r.status,
        delyanka_item_id: r.targetType === "delyanka" ? r.delyanka_item_id : null,
        lesokultury_uchastok_id: r.targetType === "lesokultury" ? r.lesokultury_uchastok_id : null,
        vid_raboty_id: r.vid_raboty_id || null,
        kommentariy: r.kommentariy || "",
      }));
    if (entries.length === 0) {
      toast.show({ tone: "warning", title: "Отметьте статус хотя бы одному сотруднику" });
      return;
    }
    setSaving(true);
    try {
      const data = await api.post("/tabel/day", { data: date, entries });
      setRows(data.map(serverRowToLocal));
      toast.show({ tone: "success", title: "Табель сохранён", description: `Записей: ${entries.length}` });
    } catch (err) {
      toast.show({ tone: "danger", title: "Не удалось сохранить табель", description: err instanceof ApiError ? err.message : "Неизвестная ошибка" });
    } finally {
      setSaving(false);
    }
  };

  // --- Модалка выбора места работы (делянка / лесные культуры), тот же
  // принцип поиска, что и в PlanRabot.jsx, но заведён на локальное состояние
  // одной строки табеля, а не всей формы.
  const openLocationModal = (row) => {
    setLocModal({
      sotrudnikId: row.sotrudnik_id,
      targetType: row.targetType || "delyanka",
      kvartal: row.delyankaKvartal || "",
      vydel: row.delyankaVydel || "",
      delyankaLookup: row.delyanka_item_id ? { item_id: row.delyanka_item_id, nazvanie: row.delyankaLabel } : null,
      lookingUp: false,
      lesokulturySearch: "",
      lesokulturyOptions: [],
      lesokulturyLoading: false,
      lesokulturyUchastok: row.lesokultury_uchastok_id ? { id: row.lesokultury_uchastok_id } : null,
    });
  };

  useEffect(() => {
    if (!locModal || locModal.targetType !== "lesokultury") return;
    setLocModal((m) => (m ? { ...m, lesokulturyLoading: true } : m));
    const t = setTimeout(() => {
      api
        .get("/tabel/lesokultury-uchastki", { search: locModal.lesokulturySearch.trim() || undefined })
        .then((opts) => setLocModal((m) => (m ? { ...m, lesokulturyOptions: opts, lesokulturyLoading: false } : m)))
        .catch(() => setLocModal((m) => (m ? { ...m, lesokulturyLoading: false } : m)));
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locModal?.targetType, locModal?.lesokulturySearch]);

  const handleLocLookupDelyanka = async () => {
    if (!locModal.kvartal.trim() || !locModal.vydel.trim()) {
      setLocModal((m) => ({ ...m, delyankaLookup: null }));
      return;
    }
    setLocModal((m) => ({ ...m, lookingUp: true }));
    try {
      const results = await api.get("/delyanki/by-location", { kvartal: locModal.kvartal.trim(), vydel: locModal.vydel.trim() });
      setLocModal((m) => ({
        ...m,
        lookingUp: false,
        delyankaLookup: results.length === 0 ? "not_found" : { item_id: results[0].item_id, nazvanie: results[0].nazvanie },
      }));
    } catch {
      setLocModal((m) => ({ ...m, lookingUp: false, delyankaLookup: "not_found" }));
    }
  };

  const handleLocationConfirm = () => {
    if (locModal.targetType === "delyanka") {
      const ok = locModal.delyankaLookup && locModal.delyankaLookup !== "not_found";
      updateRow(locModal.sotrudnikId, {
        targetType: "delyanka",
        delyanka_item_id: ok ? locModal.delyankaLookup.item_id : null,
        delyankaLabel: ok ? locModal.delyankaLookup.nazvanie || `делянка №${locModal.delyankaLookup.item_id}` : null,
        delyankaKvartal: locModal.kvartal,
        delyankaVydel: locModal.vydel,
        lesokultury_uchastok_id: null,
        lesokulturyLabel: null,
      });
    } else {
      if (!locModal.lesokulturyUchastok?.id) {
        toast.show({ tone: "warning", title: "Выберите участок лесных культур из списка" });
        return;
      }
      const u = locModal.lesokulturyUchastok;
      updateRow(locModal.sotrudnikId, {
        targetType: "lesokultury",
        lesokultury_uchastok_id: u.id,
        lesokulturyLabel: `кв. ${u.kvartal || "—"} / выд. ${u.vydel || "—"}${u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}`,
        delyanka_item_id: null,
        delyankaLabel: null,
      });
    }
    setLocModal(null);
  };

  const handleLocationClear = () => {
    updateRow(locModal.sotrudnikId, {
      targetType: null,
      delyanka_item_id: null,
      delyankaLabel: null,
      lesokultury_uchastok_id: null,
      lesokulturyLabel: null,
    });
    setLocModal(null);
  };

  // --- Новый вид работы на месте
  const handleVidSelect = (row, value) => {
    if (value === "__new__") {
      setNewVidSotrudnikId(row.sotrudnik_id);
      setNewVidName("");
      return;
    }
    updateRow(row.sotrudnik_id, { vid_raboty_id: value ? Number(value) : "" });
  };

  const handleCreateVid = async () => {
    if (!newVidName.trim()) return;
    setSavingVid(true);
    try {
      const created = await api.post("/tabel/vidy-rabot", { nazvanie: newVidName.trim() });
      setVidyRabot((prev) => (prev.some((v) => v.id === created.id) ? prev : [...prev, created].sort((a, b) => a.nazvanie.localeCompare(b.nazvanie, "ru"))));
      updateRow(newVidSotrudnikId, { vid_raboty_id: created.id });
      setNewVidSotrudnikId(null);
    } catch (err) {
      toast.show({ tone: "danger", title: "Не удалось создать вид работы", description: err instanceof ApiError ? err.message : "Неизвестная ошибка" });
    } finally {
      setSavingVid(false);
    }
  };

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <TextField label="Дата" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <TextField label="Поиск сотрудника" placeholder="ФИО или должность…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="ml-auto flex items-center gap-3">
            <span className="text-[12.5px] text-muted">Заполнено: {filledCount} из {rows?.length ?? 0}</span>
            <Button variant="primary" onClick={handleSave} loading={saving}>
              Сохранить табель
            </Button>
          </div>
        </div>
      </Card>

      <Card padding={false}>
        {rows !== null && rows.length === 0 ? (
          <EmptyState icon="🗓️" title="Нет активных сотрудников" description="Добавьте сотрудников в справочнике «Сотрудники»." />
        ) : (
          <div className={`overflow-x-auto transition-opacity ${rows === null ? "opacity-50" : ""}`} aria-busy={rows === null}>
            <table className="w-full border-separate border-spacing-0 text-[13px]">
              <thead>
                <tr className="text-left">
                  <th className="sticky left-0 z-10 bg-surface-alt px-3 py-2 min-w-[190px] text-muted font-semibold border-b border-border">Сотрудник</th>
                  <th className="px-2 py-2 min-w-[150px] text-muted font-semibold border-b border-border bg-surface-alt">Статус</th>
                  <th className="px-2 py-2 min-w-[190px] text-muted font-semibold border-b border-border bg-surface-alt">Место работы</th>
                  <th className="px-2 py-2 min-w-[170px] text-muted font-semibold border-b border-border bg-surface-alt">Вид работы</th>
                  <th className="px-2 py-2 min-w-[200px] text-muted font-semibold border-b border-border bg-surface-alt">Комментарий</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => {
                  const canPlace = row.status === "работал";
                  return (
                    <tr key={row.sotrudnik_id} className="group">
                      <td className="sticky left-0 z-10 bg-surface px-3 py-2 border-b border-border group-hover:bg-hover align-top">
                        <div className="font-medium text-ink leading-4">{row.fio}</div>
                        <div className="text-muted-2 text-[11px]">{row.dolzhnost || "—"}</div>
                        {row.mobile_status && (
                          <div className="text-[10.5px] text-pine mt-0.5" title="Уже отметился в мобильном приложении">
                            📱 {MOBILE_STATUS_LABEL[row.mobile_status] || row.mobile_status}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2 border-b border-border align-top">
                        <select
                          value={row.status}
                          onChange={(e) => updateRow(row.sotrudnik_id, { status: e.target.value })}
                          className="bg-surface border border-border focus:border-pine rounded-[10px] px-2 h-9 text-[12.5px] text-ink outline-none w-full"
                        >
                          {STATUSES.map((s) => (
                            <option key={s.value} value={s.value}>{s.label}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-2 py-2 border-b border-border align-top">
                        {canPlace ? (
                          <button
                            type="button"
                            onClick={() => openLocationModal(row)}
                            className="text-left w-full text-[12.5px] px-2 py-1.5 rounded-[8px] border border-border hover:bg-hover"
                          >
                            {row.delyankaLabel || row.lesokulturyLabel ? (
                              <span className="text-ink">{row.delyankaLabel || row.lesokulturyLabel}</span>
                            ) : (
                              <span className="text-faint">Указать место…</span>
                            )}
                          </button>
                        ) : (
                          <span className="text-faint text-[12.5px]">—</span>
                        )}
                      </td>
                      <td className="px-2 py-2 border-b border-border align-top">
                        {canPlace ? (
                          <select
                            value={row.vid_raboty_id || ""}
                            onChange={(e) => handleVidSelect(row, e.target.value)}
                            className="bg-surface border border-border focus:border-pine rounded-[10px] px-2 h-9 text-[12.5px] text-ink outline-none w-full"
                          >
                            <option value="">— не указано —</option>
                            {vidyRabot.map((v) => (
                              <option key={v.id} value={v.id}>{v.nazvanie}</option>
                            ))}
                            <option value="__new__">+ новый вид работы…</option>
                          </select>
                        ) : (
                          <span className="text-faint text-[12.5px]">—</span>
                        )}
                      </td>
                      <td className="px-2 py-2 border-b border-border align-top">
                        <input
                          type="text"
                          value={row.kommentariy}
                          onChange={(e) => updateRow(row.sotrudnik_id, { kommentariy: e.target.value })}
                          placeholder="комментарий…"
                          className="bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[12.5px] text-ink outline-none w-full"
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal
        open={!!locModal}
        onClose={() => setLocModal(null)}
        title="Место работы"
        size="sm"
        footer={
          <div className="flex items-center justify-between w-full">
            <button type="button" className="text-muted text-sm underline" onClick={handleLocationClear}>
              Очистить место
            </button>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setLocModal(null)}>Отмена</Button>
              <Button variant="primary" onClick={handleLocationConfirm}>Сохранить</Button>
            </div>
          </div>
        }
      >
        {locModal && (
          <div className="flex flex-col gap-3">
            <div className="flex gap-2">
              <Button
                type="button"
                variant={locModal.targetType === "delyanka" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setLocModal((m) => ({ ...m, targetType: "delyanka" }))}
              >
                Делянка
              </Button>
              <Button
                type="button"
                variant={locModal.targetType === "lesokultury" ? "primary" : "secondary"}
                size="sm"
                onClick={() => setLocModal((m) => ({ ...m, targetType: "lesokultury" }))}
              >
                Лесные культуры
              </Button>
            </div>

            {locModal.targetType === "delyanka" ? (
              <>
                <div className="flex items-end gap-2">
                  <TextField
                    label="Квартал"
                    value={locModal.kvartal}
                    onChange={(e) => setLocModal((m) => ({ ...m, kvartal: e.target.value }))}
                    onBlur={handleLocLookupDelyanka}
                  />
                  <TextField
                    label="Выдел"
                    value={locModal.vydel}
                    onChange={(e) => setLocModal((m) => ({ ...m, vydel: e.target.value }))}
                    onBlur={handleLocLookupDelyanka}
                  />
                  <Button variant="secondary" onClick={handleLocLookupDelyanka} loading={locModal.lookingUp}>
                    Найти
                  </Button>
                </div>
                {locModal.delyankaLookup === "not_found" && (
                  <p className="text-warning text-sm">Делянка с таким кварталом/выделом не найдена.</p>
                )}
                {locModal.delyankaLookup && locModal.delyankaLookup !== "not_found" && (
                  <p className="text-pine text-sm">
                    Найдена: {locModal.delyankaLookup.nazvanie || `делянка №${locModal.delyankaLookup.item_id}`}
                  </p>
                )}
              </>
            ) : (
              <>
                {locModal.lesokulturyUchastok?.kvartal && (
                  <p className="text-pine text-sm">
                    Выбран: кв. {locModal.lesokulturyUchastok.kvartal || "—"} / выд. {locModal.lesokulturyUchastok.vydel || "—"}
                  </p>
                )}
                <TextField
                  placeholder="Поиск участка: квартал, выдел, лесничество, порода"
                  value={locModal.lesokulturySearch}
                  onChange={(e) => setLocModal((m) => ({ ...m, lesokulturySearch: e.target.value }))}
                />
                <div className="max-h-48 overflow-y-auto border border-border rounded-md">
                  {locModal.lesokulturyLoading ? (
                    <div className="p-3 flex justify-center">
                      <div className="h-4 w-4 rounded-full border-2 border-pine border-t-transparent animate-spin" />
                    </div>
                  ) : locModal.lesokulturyOptions.length === 0 ? (
                    <div className="p-3 text-sm text-muted text-center">Ничего не найдено</div>
                  ) : (
                    locModal.lesokulturyOptions.map((u) => (
                      <button
                        type="button"
                        key={u.id}
                        onClick={() => setLocModal((m) => ({ ...m, lesokulturyUchastok: u }))}
                        className={[
                          "w-full text-left px-3 py-2 border-b border-hover last:border-b-0 hover:bg-hover",
                          locModal.lesokulturyUchastok?.id === u.id ? "bg-mint" : "",
                        ].join(" ")}
                      >
                        <div className="text-sm text-ink">Кв. {u.kvartal || "—"} / Выд. {u.vydel || "—"}</div>
                        <div className="text-xs text-muted">{u.lesnichestvo || "—"}{u.glavnaya_poroda ? ` · ${u.glavnaya_poroda}` : ""}</div>
                      </button>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </Modal>

      <Modal
        open={newVidSotrudnikId !== null}
        onClose={() => setNewVidSotrudnikId(null)}
        title="Новый вид работы"
        size="sm"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setNewVidSotrudnikId(null)}>Отмена</Button>
            <Button variant="primary" onClick={handleCreateVid} loading={savingVid}>Создать</Button>
          </div>
        }
      >
        <TextField label="Название" value={newVidName} onChange={(e) => setNewVidName(e.target.value)} placeholder="например: заготовка семян" />
      </Modal>
    </div>
  );
}
