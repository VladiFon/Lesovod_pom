import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { pollTask } from "../hooks/useTaskPolling.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Таксация" (screens/taxation/) — Этап 7 плана.
 *
 * Backend не переписывался (app/routers/taxation.py уже оборачивал
 * db.build_db/db.get_vydel_card) — добавил только один недостающий
 * эндпоинт GET /api/taxation/lesnichestva: в desktop-версии список
 * лесничеств для выпадающего списка собирался прямым SQL-запросом внутри
 * самого экрана (screen_data.py:load_lesnichestva), отдельного
 * backend-эндпоинта под него не было. Остальное — 1:1.
 *
 * Перенесено 1:1 (см. screens/taxation/screen_core.py + screen_data.py):
 *   Панель поиска (лесничество/квартал/выдел + "🔍 Найти участок") → та же панель
 *   Карточка-досье, скрыта до первого поиска                        → та же логика (dossier === null)
 *   Левая колонка (Площадь/Категория/Возраст/Класс-группа/Тип+ТЛУ/Запас) → те же подписи полей
 *   Правая колонка (Формула состава, чипы пород, индикатор доли,
 *     таблица "Порода/Возраст/Высота/Диаметр")                       → тот же набор, тот же расчёт доли (_extract_dominant_percent)
 *   Загрузка таксации (.docx, множественный выбор) + "Заменить/Дополнить" → модалка загрузки + чекбокс reset, POST /api/taxation/build → pollTask
 */

const CHIP_COLORS = ["#1A4331", "#3A6847", "#85B098", "#DF964E", "#A4D0B8"];

/** Доля породы: dolya хранится либо "из 10" (типичная запись таксации,
 * напр. 6 → 60%), либо уже в процентах — тот же эвристический выбор, что
 * _extract_dominant_percent()/_update_composition_chips() в screen_core.py. */
function percentFromDolya(dolya) {
  if (typeof dolya !== "number") return null;
  return dolya <= 10 ? Math.round(dolya * 10) : Math.round(dolya);
}

function dominantPercent(card) {
  const sostav = card.sostav || [];
  if (sostav.length > 0) {
    const p = percentFromDolya(sostav[0].dolya);
    if (p !== null) return p;
  }
  const match = /^(\d+)/.exec(card.formula_sostava || "");
  return match ? Math.min(Number(match[1]) * 10, 100) : 0;
}

function primaryAge(card) {
  const entry = (card.sostav || []).find((s) => s.yarus === "1" && s.vozrast);
  return entry ? String(entry.vozrast) : "—";
}

function Field({ caption, value }) {
  return (
    <div className="mb-2.5">
      <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase">{caption}</div>
      <div className="text-base text-ink font-semibold mt-0.5">{value ?? "—"}</div>
    </div>
  );
}

/** Компактный вариант Field для плотной сетки доп. показателей. */
function FieldCompact({ caption, value }) {
  return (
    <div>
      <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase">{caption}</div>
      <div className="text-sm text-ink font-semibold mt-0.5">{value ?? "—"}</div>
    </div>
  );
}

/** "Да" / "Нет" / "—" для булевых полей таксации (is_forested и т.п.). */
function yesNo(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  if (value === 1 || value === "1") return "Да";
  if (value === 0 || value === "0") return "Нет";
  return String(value);
}

function UploadModalInline({ onDone }) {
  const toast = useToast();
  const [files, setFiles] = useState([]);
  const [reset, setReset] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const handleUpload = async () => {
    if (files.length === 0) return;
    setSubmitting(true);
    try {
      const formData = new FormData();
      files.forEach((f) => formData.append("files", f));
      const { task_id } = await api.upload("/taxation/build", formData, { reset });
      await pollTask(task_id, { timeoutMs: 15 * 60 * 1000 });
      toast.show({ tone: "success", title: "Таксация загружена", description: `Файлов: ${files.length}` });
      setFiles([]);
      onDone();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить таксацию", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <input
        type="file"
        accept=".docx"
        multiple
        onChange={(e) => setFiles(Array.from(e.target.files || []))}
        className="text-sm text-ink file:mr-3 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:bg-mint-soft file:text-pine file:font-semibold file:cursor-pointer"
      />
      <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
        <input
          type="checkbox"
          checked={reset}
          onChange={(e) => setReset(e.target.checked)}
          className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
        />
        Заменить справочник (снять — дополнить существующий)
      </label>
      <Button variant="secondary" size="sm" onClick={handleUpload} loading={submitting} disabled={files.length === 0}>
        📤 Загрузить таксацию (.docx)
      </Button>
    </div>
  );
}

export default function Taxation() {
  const toast = useToast();
  const [lesnichestva, setLesnichestva] = useState([]);
  const [lesnichestvo, setLesnichestvo] = useState("");
  const [kvartal, setKvartal] = useState("");
  const [vydel, setVydel] = useState("");
  const [searching, setSearching] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [card, setCard] = useState(null);

  const loadLesnichestva = () => {
    api
      .get("/taxation/lesnichestva")
      .then((rows) => setLesnichestva(rows || []))
      .catch(() => setLesnichestva([]));
  };

  useEffect(loadLesnichestva, []);

  const handleSearch = async () => {
    if (!kvartal.trim() || !vydel.trim()) {
      toast.show({ tone: "warning", title: "Укажите номер квартала и номер выдела" });
      return;
    }
    setSearching(true);
    setNotFound(false);
    try {
      const result = await api.get("/taxation/vydel", {
        kvartal: kvartal.trim(),
        vydel: vydel.trim(),
        lesnichestvo: lesnichestvo || undefined,
      });
      setCard(result);
    } catch (e) {
      setCard(null);
      if (e.status === 404) {
        setNotFound(true);
      } else {
        toast.show({ tone: "danger", title: "Поиск не удался", description: e.message });
      }
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="p-8 flex flex-col gap-6">
      <Card>
        <div className="flex flex-col gap-4">
          <div className="flex items-end gap-4 flex-wrap">
            <div className="min-w-[200px]">
              <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
                Лесничество
              </label>
              <select
                value={lesnichestvo}
                onChange={(e) => setLesnichestvo(e.target.value)}
                className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
              >
                <option value="">Все лесничества</option>
                {lesnichestva.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <TextField
              label="Квартал"
              placeholder="Квартал…"
              value={kvartal}
              onChange={(e) => setKvartal(e.target.value.replace(/[^\d]/g, ""))}
              className="w-40"
            />
            <TextField
              label="Выдел"
              placeholder="Выдел…"
              value={vydel}
              onChange={(e) => setVydel(e.target.value.replace(/[^\d]/g, ""))}
              className="w-40"
            />
            <Button variant="primary" onClick={handleSearch} loading={searching}>
              🔍 Найти участок
            </Button>
          </div>
          <UploadModalInline onDone={loadLesnichestva} />
        </div>
      </Card>

      {!card && !notFound && (
        <Card>
          <EmptyState icon="🌲" title="Карточка появится после поиска" description="Укажите квартал и выдел выше и нажмите «Найти участок»." />
        </Card>
      )}

      {notFound && (
        <Card>
          <EmptyState icon="🔍" title="Выдел не найден в таксации" description="Проверьте номера квартала/выдела или загрузите таксационное описание (.docx) выше." />
        </Card>
      )}

      {card && (
        <Card>
          <div className="mb-5">
            <h2 className="font-ui font-extrabold text-xl text-ink">
              Квартал {card.kvartal_nomer} / Выдел {card.nomer}
            </h2>
            <p className="text-muted text-sm mt-0.5">Лесничество: {card.lesnichestvo || "—"}</p>
          </div>

          <div className="grid grid-cols-[2fr_3fr] gap-10">
            <div>
              <Field caption="Площадь, га" value={card.ploshad} />

              <div className="bg-mint-soft rounded-md px-4 py-3.5 my-4">
                <div className="flex items-center gap-2 text-pine font-bold text-sm">
                  <span>⚠️</span>
                  <span>Категория защитности</span>
                </div>
                <p className="text-ink text-sm mt-1.5">{card.kategoriya_lesov || "—"}</p>
              </div>

              <Field caption="Подкатегория лесов" value={card.podkategoriya_lesov} />

              <Field caption="Возраст, лет" value={primaryAge(card)} />
              <Field
                caption="Класс / Группа возраста"
                value={
                  card.klass_vozrasta != null || card.gruppa_vozrasta != null
                    ? `${card.klass_vozrasta ?? "—"} / ${card.gruppa_vozrasta ?? "—"}`
                    : null
                }
              />
              <Field caption="Тип леса + ТЛУ" value={card.tip_tlu} />
              <div className="grid grid-cols-2 gap-x-3">
                <Field caption="Тип леса" value={card.tip_lesa} />
                <Field caption="ТЛУ" value={card.tlu} />
              </div>
              <div className="grid grid-cols-2 gap-x-3">
                <Field caption="Бонитет" value={card.bonitet} />
                <Field caption="Полнота" value={card.polnota} />
              </div>
              <Field caption="Класс товарности" value={card.kl_tovarnosti} />
              <Field caption="Запас на 1 га, м³" value={card.zapas_na_ga_display} />
              <Field caption="Запас на выделе, м³" value={card.zapas_na_vydele} />
              <Field caption="Особая земля" value={yesNo(card.osobaya_zemlya)} />
              <Field caption="Покрыто лесом" value={yesNo(card.is_forested)} />
            </div>

            <div>
              <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Формула состава</div>
              <div className="flex items-center gap-2">
                <span className="font-ui font-extrabold text-3xl text-ink">{card.formula_sostava || "—"}</span>
                <span className="text-xl">🌿</span>
              </div>
              {card.formula_sostava_2_yarus && (
                <div className="text-sm text-muted mt-1">2 ярус: {card.formula_sostava_2_yarus}</div>
              )}

              {card.sostav?.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {card.sostav.map((s, i) => {
                    const p = percentFromDolya(s.dolya);
                    return (
                      <div key={i} className="flex items-center gap-1.5 bg-surface-alt rounded-full px-3 py-1.5 text-sm text-ink">
                        <span
                          className="h-2 w-2 rounded-full shrink-0"
                          style={{ backgroundColor: CHIP_COLORS[i % CHIP_COLORS.length] }}
                        />
                        {s.poroda || "—"} ({p && p >= 5 ? `${p}%` : "единично"})
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="h-[7px] rounded-full bg-surface-alt mt-3 overflow-hidden">
                <div className="h-full bg-pine rounded-full transition-all" style={{ width: `${dominantPercent(card)}%` }} />
              </div>

              <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase mt-5 mb-2">
                Таксационные показатели по породам
              </div>
              <div className="border border-border rounded-md overflow-hidden overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-surface-alt border-b border-border text-left text-muted font-semibold">
                      <th className="px-3 py-2">Порода</th>
                      <th className="px-3 py-2">Возраст, лет</th>
                      <th className="px-3 py-2">Высота, м</th>
                      <th className="px-3 py-2">Диаметр, см</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(card.sostav || []).map((s, i) => (
                      <tr key={i} className="border-b border-border last:border-b-0">
                        <td className="px-3 py-2 text-ink">{s.poroda || "—"}</td>
                        <td className="px-3 py-2 text-ink">{s.vozrast ?? "—"}</td>
                        <td className="px-3 py-2 text-ink">{s.vysota ?? "—"}</td>
                        <td className="px-3 py-2 text-ink">{s.diametr ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {(card.lesnye_kultury || card.podlesok || card.podrost || card.tselevaya_poroda || card.ptg || card.povrezhdenie) && (
            <div className="mt-6 pt-5 border-t border-border">
              <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase mb-3">
                Дополнительные показатели
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">
                <FieldCompact caption="Лесные культуры" value={card.lesnye_kultury} />
                <FieldCompact caption="Подлесок" value={card.podlesok} />
                <FieldCompact caption="Подрост" value={card.podrost} />
                <FieldCompact caption="Целевая порода" value={card.tselevaya_poroda} />
                <FieldCompact caption="ПТГ" value={card.ptg} />
                <FieldCompact caption="Повреждение" value={card.povrezhdenie} />
              </div>
            </div>
          )}

          {card.primechaniya && (
            <div className="mt-5 bg-surface-alt rounded-md px-4 py-3.5">
              <div className="text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1">Примечания</div>
              <p className="text-sm text-ink whitespace-pre-wrap">{card.primechaniya}</p>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
