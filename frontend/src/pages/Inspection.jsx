import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import { pollTask } from "../hooks/useTaskPolling.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import TextAreaField from "../components/TextAreaField.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Modal from "../components/Modal.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Акты освидетельствования" (screens/inspection/) — Этап 10 плана.
 *
 * app/routers/inspection.py оборачивает db.py (чек-лист/сроки/пресеты/
 * история актов) + spravka_generator.py/osvidetelstvovanie_generator.py
 * (генерация теперь идёт по официальным бланкам templates/*_shablon.docx —
 * SpravkaIn обновлён под новый набор полей spravka_generator.generate_spravka).
 * STANDARD_CHECKLIST_ITEMS и все поля act_data — как в самом роутере.
 *
 * Перенесено 1:1:
 *   Список делянок с бейджами срочности/% освоения/чек-листом → таблица (GET /api/inspection/)
 *   Сроки заготовки/вывозки (редактирование)                   → инлайн-поля + PATCH .../sroki
 *   Чек-лист подготовки (стандартный + свои пункты)             → чекбоксы + "Добавить пункт"
 *   Пресет комиссии/организационных полей акта                  → выпадающий список, заполняет форму
 *   "Справка об объёмах" (по официальному бланку spravka_shablon.docx)   → модалка → POST .../documents/spravka
 *   "📝 Акт освидетельствования" (полная форма, см. докстринг
 *     osvidetelstvovanie_generator.generate_akt_osvidetelstvovaniya) → модалка (все поля) → POST .../documents/akt-osvidetelstvovaniya
 *   "↓ Пустой бланк акта"                               → кнопка в шапке → POST /documents/blank-template
 *   История актов по делянке                                    → таблица, GET .../acts
 */

const CHECKLIST_STANDARD_HINT = "Стандартный чек-лист (8 пунктов) — из STANDARD_CHECKLIST_ITEMS.";

function parseNamedList(text) {
  return (text || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      if (line.includes(";")) {
        const [dolzhnost, fio] = line.split(";", 2);
        return { dolzhnost: dolzhnost.trim(), fio: (fio || "").trim() };
      }
      return { dolzhnost: "", fio: line };
    });
}
function formatNamedList(list) {
  return (list || []).map((c) => (c.dolzhnost ? `${c.dolzhnost}; ${c.fio}` : c.fio)).join("\n");
}
function parseNarusheniya(text) {
  return (text || "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [vid, kolichestvo] = line.split(";", 2);
      return { vid: vid.trim(), kolichestvo: (kolichestvo || "").trim() };
    });
}
function formatNarusheniya(list) {
  return (list || []).map((n) => `${n.vid}; ${n.kolichestvo}`).join("\n");
}

function emptyActForm() {
  return {
    act_date: "", oblast_rayon: "",
    osnovanie_nomer: "", osnovanie_data: "", izveshchenie_data: "",
    predsedatel_dolzhnost: "", predsedatel_fio: "", chleny_text: "",
    predstavitel_lesxoza_dolzhnost: "", predstavitel_lesxoza_fio: "",
    predstavitel_lesopolz_organizatsiya: "", predstavitel_lesopolz_dolzhnost: "", predstavitel_lesopolz_fio: "",
    predstavitel_lesopolzovaniya_dolzhnost: "", predstavitel_lesopolzovaniya_fio: "",
    vid_osvidetelstvovaniya: "", sposob_rubki: "", sposob_ucheta: "", sposob_ochistki: "",
    ploshad_razresheno: "", ploshad_fakt: "", ploshad_nevyvezeno: "",
    podrost_ploshad_ga: "", podrost_ploshad_protsent: "", podrost_kolichestvo_tys: "", podrost_kolichestvo_protsent: "",
    harakteristika_podrosta: "", narusheniya_text: "", kachestvo_rubok: "",
    zayavleniya_lesopolzovatelya: "", zayavleniya_drugih: "", prilozhenie_4: "", zaklyuchenie: "",
    drugie_litsa_text: "", rukovoditel_dolzhnost: "", rukovoditel_fio: "",
  };
}

function actFormToPayload(f) {
  const { chleny_text, narusheniya_text, drugie_litsa_text, ...rest } = f;
  return {
    ...rest,
    chleny: parseNamedList(chleny_text),
    narusheniya: parseNarusheniya(narusheniya_text),
    drugie_litsa: parseNamedList(drugie_litsa_text),
  };
}

/** Срок освидетельствования (r.srok_osvidetelstvovaniya) приходит строкой
 * "ДД.ММ.ГГГГ" (deadline = дата вывозки + 30 дней, см. app/routers/
 * inspection.py: list_inspection). Разбираем сами, чтобы отсортировать и
 * подсветить делянки, где срок уже подошёл или подходит скоро — раньше
 * список никак не учитывал срочность, приходилось проглядывать всё подряд. */
function parseRuDate(value) {
  if (!value) return null;
  const parts = String(value).trim().split(".");
  if (parts.length !== 3) return null;
  const [d, m, y] = parts.map((p) => parseInt(p, 10));
  if (!d || !m || !y) return null;
  const date = new Date(y, m - 1, d);
  return Number.isNaN(date.getTime()) ? null : date;
}

const URGENT_SOON_DAYS = 7;

function inspectionUrgency(row) {
  const date = parseRuDate(row.srok_osvidetelstvovaniya);
  if (!date) return { days: null, level: "none" };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  date.setHours(0, 0, 0, 0);
  const days = Math.round((date - today) / (1000 * 60 * 60 * 24));
  if (days < 0) return { days, level: "overdue" };
  if (days <= URGENT_SOON_DAYS) return { days, level: "soon" };
  return { days, level: "ok" };
}

const URGENCY_RANK = { overdue: 0, soon: 1, ok: 2, none: 3 };

function Section({ title, children }) {
  return (
    <div>
      <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase mb-2 mt-1">{title}</div>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

function ActModal({ open, onClose, delyankaId, presets, onGenerated, onPresetsChanged }) {
  const toast = useToast();
  const [form, setForm] = useState(emptyActForm());
  const [submitting, setSubmitting] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState("");
  const [draftPresetName, setDraftPresetName] = useState(null);
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  useEffect(() => {
    if (open) {
      setForm(emptyActForm());
      setSelectedPreset("");
      setDraftPresetName(null);
    }
  }, [open]);

  const applyPreset = (nazvanie) => {
    const p = presets.find((p) => p.nazvanie === nazvanie);
    if (!p) return;
    setForm((f) => ({
      ...f,
      predsedatel_dolzhnost: p.predsedatel_dolzhnost || "",
      predsedatel_fio: p.predsedatel_fio || "",
      chleny_text: formatNamedList(p.chleny),
      oblast_rayon: p.oblast_rayon || "",
      predstavitel_lesxoza_dolzhnost: p.predstavitel_lesxoza_dolzhnost || "",
      predstavitel_lesxoza_fio: p.predstavitel_lesxoza_fio || "",
      predstavitel_lesopolz_organizatsiya: p.lesopolz_organizatsiya || "",
      predstavitel_lesopolz_dolzhnost: p.lesopolz_dolzhnost || "",
      predstavitel_lesopolz_fio: p.lesopolz_fio || "",
      predstavitel_lesopolzovaniya_dolzhnost: p.sign_lesopolz_dolzhnost || "",
      predstavitel_lesopolzovaniya_fio: p.sign_lesopolz_fio || "",
      vid_osvidetelstvovaniya: p.vid_osvidetelstvovaniya || "",
      sposob_rubki: p.sposob_rubki || "",
      sposob_ucheta: p.sposob_ucheta || "",
      sposob_ochistki: p.sposob_ochistki || "",
      rukovoditel_dolzhnost: p.rukovoditel_dolzhnost || "",
      rukovoditel_fio: p.rukovoditel_fio || "",
    }));
  };

  // Сохранение/удаление пресетов (Блок 5, PLAN_DORABOTKI, п. "создание/
  // удаление пресетов") — эндпоинты POST/DELETE /inspection/presets в
  // app/routers/inspection.py уже были готовы, здесь только фронтенд поверх
  // них. nazvanie у этого роутера — query-параметр, а не часть тела (в
  // отличие от /delyanki/presets/*), поэтому передаём его третьим
  // аргументом api.post, а не внутри body.
  const savePreset = async (nazvanie) => {
    try {
      await api.post(
        "/inspection/presets",
        {
          predsedatel_dolzhnost: form.predsedatel_dolzhnost || "",
          predsedatel_fio: form.predsedatel_fio || "",
          chleny: parseNamedList(form.chleny_text),
          oblast_rayon: form.oblast_rayon || "",
          predstavitel_lesxoza_dolzhnost: form.predstavitel_lesxoza_dolzhnost || "",
          predstavitel_lesxoza_fio: form.predstavitel_lesxoza_fio || "",
          lesopolz_organizatsiya: form.predstavitel_lesopolz_organizatsiya || "",
          lesopolz_dolzhnost: form.predstavitel_lesopolz_dolzhnost || "",
          lesopolz_fio: form.predstavitel_lesopolz_fio || "",
          sign_lesopolz_dolzhnost: form.predstavitel_lesopolzovaniya_dolzhnost || "",
          sign_lesopolz_fio: form.predstavitel_lesopolzovaniya_fio || "",
          vid_osvidetelstvovaniya: form.vid_osvidetelstvovaniya || "",
          sposob_rubki: form.sposob_rubki || "",
          sposob_ucheta: form.sposob_ucheta || "",
          sposob_ochistki: form.sposob_ochistki || "",
          rukovoditel_dolzhnost: form.rukovoditel_dolzhnost || "",
          rukovoditel_fio: form.rukovoditel_fio || "",
        },
        { nazvanie }
      );
      toast.show({ tone: "success", title: "Пресет сохранён" });
      onPresetsChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить пресет", description: e.message });
    }
  };

  const deletePreset = async (nazvanie) => {
    try {
      await api.delete(`/inspection/presets/${encodeURIComponent(nazvanie)}`);
      toast.show({ tone: "success", title: "Пресет удалён" });
      setSelectedPreset("");
      onPresetsChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить пресет", description: e.message });
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const { task_id } = await api.post(`/inspection/${delyankaId}/documents/akt-osvidetelstvovaniya`, actFormToPayload(form));
      const result = await pollTask(task_id, { timeoutMs: 5 * 60 * 1000 });
      const docId = result?.document_ids?.[0];
      toast.show({ tone: "success", title: "Акт освидетельствования готов" });
      if (docId) window.open(`${API_BASE_URL}/documents/${docId}/download`, "_blank");
      onClose();
      onGenerated();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось составить акт", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Акт освидетельствования лесосеки"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>Сформировать акт</Button>
        </>
      }
    >
      <div className="max-h-[65vh] overflow-y-auto pr-1 flex flex-col gap-5">
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase">Пресет</label>
            {draftPresetName === null && (
              <button
                type="button"
                onClick={() => setDraftPresetName("")}
                className="text-xs font-semibold text-pine hover:underline"
              >
                + Сохранить как пресет
              </button>
            )}
          </div>

          {presets.length > 0 ? (
            <div className="flex items-center gap-2">
              <select
                value={selectedPreset}
                onChange={(e) => {
                  setSelectedPreset(e.target.value);
                  if (e.target.value) applyPreset(e.target.value);
                }}
                className="flex-1 bg-surface border border-border focus:border-pine rounded-md px-3.5 py-2.5 text-base text-ink outline-none"
              >
                <option value="" disabled>Заполнить организационные поля из пресета…</option>
                {presets.map((p) => (
                  <option key={p.nazvanie} value={p.nazvanie}>{p.nazvanie}</option>
                ))}
              </select>
              {selectedPreset && (
                <button
                  type="button"
                  title="Удалить пресет"
                  onClick={() => deletePreset(selectedPreset)}
                  className="shrink-0 rounded-md border border-transparent px-2.5 py-2 text-muted-2 hover:border-error hover:text-error transition-colors"
                >
                  ✕
                </button>
              )}
            </div>
          ) : (
            draftPresetName === null && (
              <p className="text-sm text-muted-2">Пресетов пока нет — заполните поля ниже и сохраните.</p>
            )
          )}

          {draftPresetName !== null && (
            <div className="mt-2 flex items-center gap-2">
              <input
                autoFocus
                value={draftPresetName}
                onChange={(e) => setDraftPresetName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && draftPresetName.trim()) {
                    savePreset(draftPresetName.trim());
                    setDraftPresetName(null);
                  }
                  if (e.key === "Escape") setDraftPresetName(null);
                }}
                placeholder="Название пресета"
                className="flex-1 bg-surface border border-border focus:border-pine focus:bg-surface rounded-md px-3.5 py-2 text-sm text-ink outline-none transition-colors"
              />
              <Button
                size="sm"
                variant="primary"
                disabled={!draftPresetName.trim()}
                onClick={() => {
                  savePreset(draftPresetName.trim());
                  setDraftPresetName(null);
                }}
              >
                Сохранить
              </Button>
              <button
                type="button"
                onClick={() => setDraftPresetName(null)}
                className="px-1 text-sm text-muted-2 hover:text-ink"
              >
                Отмена
              </button>
            </div>
          )}
        </div>

        <Section title="Общие сведения">
          <div className="grid grid-cols-3 gap-3">
            <TextField label="Дата акта" placeholder="ДД.ММ.ГГГГ" value={form.act_date} onChange={setField("act_date")} />
            <TextField label="Область/район" value={form.oblast_rayon} onChange={setField("oblast_rayon")} className="col-span-2" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <TextField label="№ основания рубки" value={form.osnovanie_nomer} onChange={setField("osnovanie_nomer")} />
            <TextField label="Дата основания" placeholder="ДД.ММ.ГГГГ" value={form.osnovanie_data} onChange={setField("osnovanie_data")} />
            <TextField label="Дата извещения" placeholder="ДД.ММ.ГГГГ" value={form.izveshchenie_data} onChange={setField("izveshchenie_data")} />
          </div>
        </Section>

        <Section title="Комиссия">
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Председатель, должность" value={form.predsedatel_dolzhnost} onChange={setField("predsedatel_dolzhnost")} />
            <TextField label="Председатель, ФИО" value={form.predsedatel_fio} onChange={setField("predsedatel_fio")} />
          </div>
          <TextAreaField label="Члены комиссии" rows={2} value={form.chleny_text} onChange={setField("chleny_text")} hint="По одному на строку: Должность; ФИО" />
        </Section>

        <Section title="Представители">
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Лесхоз, должность" value={form.predstavitel_lesxoza_dolzhnost} onChange={setField("predstavitel_lesxoza_dolzhnost")} />
            <TextField label="Лесхоз, ФИО" value={form.predstavitel_lesxoza_fio} onChange={setField("predstavitel_lesxoza_fio")} />
          </div>
          <TextField label="Лесопользователь, организация" value={form.predstavitel_lesopolz_organizatsiya} onChange={setField("predstavitel_lesopolz_organizatsiya")} />
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Лесопользователь, должность" value={form.predstavitel_lesopolz_dolzhnost} onChange={setField("predstavitel_lesopolz_dolzhnost")} />
            <TextField label="Лесопользователь, ФИО" value={form.predstavitel_lesopolz_fio} onChange={setField("predstavitel_lesopolz_fio")} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Подписант от лесопольз., должность" value={form.predstavitel_lesopolzovaniya_dolzhnost} onChange={setField("predstavitel_lesopolzovaniya_dolzhnost")} />
            <TextField label="Подписант от лесопольз., ФИО" value={form.predstavitel_lesopolzovaniya_fio} onChange={setField("predstavitel_lesopolzovaniya_fio")} />
          </div>
        </Section>

        <Section title="Способы">
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Вид освидетельствования" value={form.vid_osvidetelstvovaniya} onChange={setField("vid_osvidetelstvovaniya")} />
            <TextField label="Способ рубки" value={form.sposob_rubki} onChange={setField("sposob_rubki")} />
            <TextField label="Способ учёта" value={form.sposob_ucheta} onChange={setField("sposob_ucheta")} />
            <TextField label="Способ очистки" value={form.sposob_ochistki} onChange={setField("sposob_ochistki")} />
          </div>
        </Section>

        <Section title="Площадь, га">
          <div className="grid grid-cols-3 gap-3">
            <TextField label="Разрешено" type="number" step="0.01" value={form.ploshad_razresheno} onChange={setField("ploshad_razresheno")} />
            <TextField label="Фактически" type="number" step="0.01" value={form.ploshad_fakt} onChange={setField("ploshad_fakt")} />
            <TextField label="Не вывезено" type="number" step="0.01" value={form.ploshad_nevyvezeno} onChange={setField("ploshad_nevyvezeno")} />
          </div>
        </Section>

        <Section title="Подрост">
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Площадь, га" type="number" step="0.01" value={form.podrost_ploshad_ga} onChange={setField("podrost_ploshad_ga")} />
            <TextField label="Площадь, %" type="number" step="0.1" value={form.podrost_ploshad_protsent} onChange={setField("podrost_ploshad_protsent")} />
            <TextField label="Количество, тыс. шт/га" type="number" step="0.1" value={form.podrost_kolichestvo_tys} onChange={setField("podrost_kolichestvo_tys")} />
            <TextField label="Количество, %" type="number" step="0.1" value={form.podrost_kolichestvo_protsent} onChange={setField("podrost_kolichestvo_protsent")} />
          </div>
          <TextAreaField label="Характеристика подроста" rows={2} value={form.harakteristika_podrosta} onChange={setField("harakteristika_podrosta")} />
        </Section>

        <Section title="Нарушения">
          <TextAreaField label="Выявленные нарушения" rows={2} value={form.narusheniya_text} onChange={setField("narusheniya_text")} hint="По одному на строку: Вид нарушения; Количество" />
        </Section>

        <Section title="Качество, заявления, заключение">
          <TextAreaField label="Качество рубок" rows={2} value={form.kachestvo_rubok} onChange={setField("kachestvo_rubok")} />
          <TextAreaField label="Заявления лесопользователя" rows={2} value={form.zayavleniya_lesopolzovatelya} onChange={setField("zayavleniya_lesopolzovatelya")} />
          <TextAreaField label="Заявления других лиц" rows={2} value={form.zayavleniya_drugih} onChange={setField("zayavleniya_drugih")} />
          <TextField label="Приложение №4" value={form.prilozhenie_4} onChange={setField("prilozhenie_4")} />
          <TextAreaField label="Заключение" rows={2} value={form.zaklyuchenie} onChange={setField("zaklyuchenie")} />
        </Section>

        <Section title="Прочее">
          <TextAreaField label="Другие лица" rows={2} value={form.drugie_litsa_text} onChange={setField("drugie_litsa_text")} hint="По одному на строку: Должность; ФИО" />
          <div className="grid grid-cols-2 gap-3">
            <TextField label="Руководитель, должность" value={form.rukovoditel_dolzhnost} onChange={setField("rukovoditel_dolzhnost")} />
            <TextField label="Руководитель, ФИО" value={form.rukovoditel_fio} onChange={setField("rukovoditel_fio")} />
          </div>
        </Section>
      </div>
    </Modal>
  );
}

function SpravkaModal({ open, onClose, delyankaId, onGenerated }) {
  const toast = useToast();
  const [form, setForm] = useState({
    ploshad_proydennaya: "", likvid_such_krony: "0",
    lesopolzovatel: "", rukovoditel_fio: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const body = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, ["lesopolzovatel", "rukovoditel_fio"].includes(k) ? v : (v === "" ? undefined : Number(v))])
      );
      const { task_id } = await api.post(`/inspection/${delyankaId}/documents/spravka`, body);
      const result = await pollTask(task_id, { timeoutMs: 5 * 60 * 1000 });
      const docId = result?.document_ids?.[0];
      toast.show({ tone: "success", title: "Справка готова" });
      if (docId) window.open(`${API_BASE_URL}/documents/${docId}/download`, "_blank");
      onClose();
      onGenerated();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сформировать справку", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Справка об объёмах заготовки"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>Отмена</Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting}>Сформировать</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <TextField label="Площадь пройденная, га" type="number" step="0.01" value={form.ploshad_proydennaya} onChange={setField("ploshad_proydennaya")} />
          <TextField label="Ликвид сучьев и кроны, м³" type="number" step="0.01" value={form.likvid_such_krony} onChange={setField("likvid_such_krony")} />
        </div>
        <TextField label="Лесопользователь" value={form.lesopolzovatel} onChange={setField("lesopolzovatel")} />
        <TextField label="Руководитель, ФИО" value={form.rukovoditel_fio} onChange={setField("rukovoditel_fio")} />
      </div>
    </Modal>
  );
}

function InspectionDetail({ row, onSrokiSaved }) {
  const toast = useToast();
  const [srokZagotovki, setSrokZagotovki] = useState(row.srok_okonchaniya_zagotovki || "");
  const [srokVyvozki, setSrokVyvozki] = useState(row.srok_okonchaniya_vyvozki || "");
  const [savingSroki, setSavingSroki] = useState(false);
  const [checklist, setChecklist] = useState(row.checklist || []);
  const [newItemText, setNewItemText] = useState("");
  const [ensuring, setEnsuring] = useState(false);
  const [presets, setPresets] = useState([]);
  const [acts, setActs] = useState(row.acts || []);
  const [actModalOpen, setActModalOpen] = useState(false);
  const [spravkaModalOpen, setSpravkaModalOpen] = useState(false);

  useEffect(() => {
    setSrokZagotovki(row.srok_okonchaniya_zagotovki || "");
    setSrokVyvozki(row.srok_okonchaniya_vyvozki || "");
    setChecklist(row.checklist || []);
    setActs(row.acts || []);
  }, [row]);

  const reloadPresets = useCallback(() => {
    api.get("/inspection/presets").then(setPresets).catch(() => setPresets([]));
  }, []);

  useEffect(() => {
    reloadPresets();
  }, [reloadPresets]);

  const reloadActs = () => {
    api.get(`/inspection/${row.id}/acts`).then(setActs).catch(() => {});
  };

  const handleSaveSroki = async () => {
    setSavingSroki(true);
    try {
      await api.patch(`/inspection/${row.id}/sroki`, { srok_zagotovki: srokZagotovki, srok_vyvozki: srokVyvozki });
      toast.show({ tone: "success", title: "Сроки сохранены" });
      onSrokiSaved();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить сроки", description: e.message });
    } finally {
      setSavingSroki(false);
    }
  };

  const handleEnsureChecklist = async () => {
    setEnsuring(true);
    try {
      await api.post(`/inspection/${row.id}/checklist/ensure`);
      const items = await api.get(`/inspection/${row.id}/checklist`);
      setChecklist(items);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось создать чек-лист", description: e.message });
    } finally {
      setEnsuring(false);
    }
  };

  const handleToggle = async (item) => {
    setChecklist((list) => list.map((it) => (it.id === item.id ? { ...it, is_done: !it.is_done } : it)));
    try {
      await api.patch(`/inspection/checklist/${item.id}`, undefined, { is_done: !item.is_done });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось изменить пункт", description: e.message });
      setChecklist((list) => list.map((it) => (it.id === item.id ? { ...it, is_done: item.is_done } : it)));
    }
  };

  const handleAddItem = async () => {
    if (!newItemText.trim()) return;
    try {
      const { id } = await api.post(`/inspection/${row.id}/checklist`, undefined, { text: newItemText.trim() });
      setChecklist((list) => [...list, { id, text: newItemText.trim(), is_done: false, is_custom: true }]);
      setNewItemText("");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось добавить пункт", description: e.message });
    }
  };

  const handleDeleteItem = async (item) => {
    try {
      await api.delete(`/inspection/checklist/${item.id}`);
      setChecklist((list) => list.filter((it) => it.id !== item.id));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить пункт", description: e.message });
    }
  };

  const doneCount = checklist.filter((i) => i.is_done).length;

  return (
    <Card>
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="font-ui font-extrabold text-pine" style={{ fontSize: 16 }}>{row.nazvanie || `Делянка №${row.id}`}</h2>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => setSpravkaModalOpen(true)}>Справка об объёмах</Button>
            <Button variant="primary" size="sm" onClick={() => setActModalOpen(true)}>Акт освидетельствования</Button>
          </div>
        </div>

        <div className="grid gap-3.5 items-end grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
          <TextField label="Срок окончания заготовки" placeholder="ДД.ММ.ГГГГ" value={srokZagotovki} onChange={(e) => setSrokZagotovki(e.target.value)} />
          <TextField label="Срок окончания вывозки" placeholder="ДД.ММ.ГГГГ" value={srokVyvozki} onChange={(e) => setSrokVyvozki(e.target.value)} />
          <Button variant="secondary" onClick={handleSaveSroki} loading={savingSroki}>Сохранить сроки</Button>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-ui font-bold text-ink text-md">Чек-лист подготовки {checklist.length > 0 && `(${doneCount}/${checklist.length})`}</h3>
            {checklist.length === 0 && (
              <Button variant="ghost" size="sm" onClick={handleEnsureChecklist} loading={ensuring} title={CHECKLIST_STANDARD_HINT}>
                + Стандартный чек-лист
              </Button>
            )}
          </div>
          {checklist.length > 0 && (
            <ul className="flex flex-col gap-1.5 mb-3">
              {checklist.map((item) => (
                <li key={item.id} className="flex items-center gap-2.5">
                  <input
                    type="checkbox"
                    checked={item.is_done}
                    onChange={() => handleToggle(item)}
                    className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer shrink-0"
                  />
                  <span className={["text-base flex-1", item.is_done ? "text-muted line-through" : "text-ink"].join(" ")}>{item.text}</span>
                  {item.is_custom ? (
                    <button onClick={() => handleDeleteItem(item)} className="text-error text-sm font-semibold">✕</button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-center gap-2">
            <TextField placeholder="Свой пункт чек-листа…" value={newItemText} onChange={(e) => setNewItemText(e.target.value)} className="flex-1" />
            <Button variant="ghost" size="sm" onClick={handleAddItem}>Добавить</Button>
          </div>
        </div>

        <div>
          <h3 className="font-mono text-[10.5px] uppercase tracking-[.1em] text-muted-2 mb-2">история актов</h3>
          <DataTable
            columns={[
              { key: "act_date", header: "Дата" },
              { key: "created_at", header: "Создан" },
              {
                key: "actions", header: "",
                render: (a) => a.file_path ? (
                  <a
                    href={`${API_BASE_URL}/inspection/acts/${a.id}/download`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-pine text-sm font-semibold hover:text-pine-hover hover:underline"
                  >
                    Файл: {a.file_path.split("/").pop()}
                  </a>
                ) : null,
              },
            ]}
            rows={acts}
            emptyTitle="Актов ещё нет"
            emptyDescription="Составьте акт освидетельствования кнопкой выше."
          />
        </div>
      </div>

      <ActModal
        open={actModalOpen}
        onClose={() => setActModalOpen(false)}
        delyankaId={row.id}
        presets={presets}
        onGenerated={reloadActs}
        onPresetsChanged={reloadPresets}
      />
      <SpravkaModal open={spravkaModalOpen} onClose={() => setSpravkaModalOpen(false)} delyankaId={row.id} onGenerated={() => {}} />
    </Card>
  );
}

export default function Inspection() {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [blankLoading, setBlankLoading] = useState(false);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get("/inspection/");
      setRows(data || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить список", description: e.message });
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const handleBlankTemplate = async () => {
    setBlankLoading(true);
    try {
      const { task_id } = await api.post("/inspection/documents/blank-template");
      const result = await pollTask(task_id);
      const docId = result?.document_ids?.[0];
      if (docId) window.open(`${API_BASE_URL}/documents/${docId}/download`, "_blank");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось получить бланк", description: e.message });
    } finally {
      setBlankLoading(false);
    }
  };

  const selected = rows.find((r) => r.id === selectedId) || null;

  // Ближе к верху — те, у кого срок освидетельствования уже прошёл или
  // подходит в течение URGENT_SOON_DAYS (см. inspectionUrgency выше),
  // дальше — остальные по возрастанию срока, в конце — те, у кого срока
  // вообще нет. Поиск — по названию делянки (единственное текстовое поле,
  // по которому лесничий вообще может искать в этом списке).
  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows
      .filter((r) => !q || (r.nazvanie || `Делянка №${r.id}`).toLowerCase().includes(q))
      .map((r) => ({ row: r, urgency: inspectionUrgency(r) }))
      .sort((a, b) => {
        const rankDiff = URGENCY_RANK[a.urgency.level] - URGENCY_RANK[b.urgency.level];
        if (rankDiff !== 0) return rankDiff;
        if (a.urgency.days == null || b.urgency.days == null) return 0;
        return a.urgency.days - b.urgency.days;
      })
      .map(({ row }) => row);
  }, [rows, search]);

  return (
    <div className="p-[18px] flex flex-wrap gap-[14px] items-start">
      <Card padding={false} className="flex flex-col" style={{ flex: "1 1 280px", maxWidth: 420 }}>
        <div className="p-3.5 flex flex-col gap-2.5 border-b border-border">
          <Button variant="secondary" size="sm" onClick={handleBlankTemplate} loading={blankLoading} className="self-start">
            ↓ Пустой бланк акта
          </Button>
          <TextField placeholder="Поиск по названию делянки…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <span className="font-mono text-[10.5px] text-faint">{visibleRows.length} · сначала просроченные</span>
        </div>
        <div className="p-2.5 flex flex-col gap-1.5">
          {loading ? (
            <div className="p-5 flex justify-center">
              <div className="h-5 w-5 rounded-full border-2 border-pine border-t-transparent animate-spin" />
            </div>
          ) : visibleRows.length === 0 ? (
            <EmptyState title="Делянок нет" description="Создайте делянки на экране «Делянки» — сюда они попадут автоматически." />
          ) : (
            visibleRows.map((r) => {
              const u = r.srok_osvidetelstvovaniya ? inspectionUrgency(r) : null;
              const srokLabel = !r.srok_osvidetelstvovaniya
                ? "срок не задан"
                : u?.level === "overdue"
                  ? `просрочен на ${-u.days} дн.`
                  : u?.level === "soon"
                    ? `через ${u.days} дн.`
                    : r.srok_osvidetelstvovaniya;
              const tone = u?.level === "overdue" ? "danger" : u?.level === "soon" ? "warning" : "neutral";
              const done = r.checklist?.filter((c) => c.is_done).length ?? 0;
              return (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => setSelectedId(r.id)}
                  className={[
                    "w-full text-left px-3 py-2.5 rounded-[10px] border flex flex-col gap-1 transition-colors",
                    selectedId === r.id ? "bg-mint-soft border-pine" : "border-border bg-surface hover:bg-hover",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[13.5px] font-semibold text-ink">{r.nazvanie || `Делянка №${r.id}`}</span>
                    <StatusBadge tone={tone} label={srokLabel} />
                  </div>
                  <span className="font-mono text-[10.5px] text-faint">
                    заготовка {r.srok_okonchaniya_zagotovki || "—"} · вывозка {r.srok_okonchaniya_vyvozki || "—"}
                  </span>
                  <span className="font-mono text-[10.5px] text-muted-2">
                    {r.pct_osvoeniya_limita != null ? `${r.pct_osvoeniya_limita}% освоено` : "— % освоено"} · чек-лист{" "}
                    {r.checklist?.length ? `${done}/${r.checklist.length}` : "—"} · актов {r.acts?.length ?? 0}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </Card>

      <div className="min-w-0" style={{ flex: "2 1 420px" }}>
      {selected ? (
        <InspectionDetail row={selected} onSrokiSaved={load} />
      ) : (
        <Card>
          <EmptyState icon="✅" title="Выберите делянку из списка" description="Сроки, чек-лист подготовки и акты освидетельствования — здесь." />
        </Card>
      )}
      </div>
    </div>
  );
}
