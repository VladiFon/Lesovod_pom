import React, { useEffect, useState } from "react";
import { useCan } from "../auth.jsx";
import { openScreen } from "../nav.js";
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
 *   Панель поиска (лесничество/квартал/выдел + "Найти участок") → та же панель
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
  // По умолчанию — дополнить. Заменить весь справочник может только
  // администратор, и перед этим переспрашиваем (анализ удобства 01.10.2026).
  const can = useCan();
  const [reset, setReset] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleUpload = async () => {
    if (files.length === 0) return;
    if (reset && !window.confirm("Заменить ВЕСЬ справочник таксации? Прежние кварталы и выделы будут стёрты и загружены заново из выбранных файлов. Перед этим сохранится автокопия базы.")) return;
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
      {can("taxation.replace") && <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
        <input
          type="checkbox"
          checked={reset}
          onChange={(e) => setReset(e.target.checked)}
          className="h-4 w-4 rounded border-2 border-pine accent-pine cursor-pointer"
        />
        Заменить весь справочник (обычно не нужно — без галочки дополняет)
      </label>}
      <Button variant="secondary" size="sm" onClick={handleUpload} loading={submitting} disabled={files.length === 0}>
        ↑ Загрузить описание (.docx)
      </Button>
    </div>
  );
}

/**
 * «Что было на выделе»: делянки, лесные культуры с мероприятиями и
 * выполненные работы с телефона — та же история, что в приложении
 * (анализ удобства 01.10.2026: на сайте её не было).
 */
function VydelHistory({ history }) {
  if (!history) return null;
  const { delyanki = [], lesokultury = [], meropriyatiya = [], works = [] } = history;
  if (!delyanki.length && !lesokultury.length && !works.length) {
    return (
      <div className="bg-surface border border-border rounded-lg px-4 py-3.5 text-sm text-muted">
        История выдела: делянок, лесных культур и отметок о работах пока нет.
      </div>
    );
  }
  return (
    <div className="bg-surface border border-border rounded-lg px-4 py-3.5 flex flex-col gap-3">
      <div className="text-[14px] font-extrabold text-pine">Что было на выделе</div>
      {delyanki.length > 0 && (
        <div>
          <div className="text-[11.5px] text-muted-2 mb-1">Делянки</div>
          <div className="flex flex-wrap gap-1.5">
            {delyanki.map((d) => (
              <button
                key={d.delyanka_id}
                type="button"
                onClick={() => openScreen("plots", { d: d.delyanka_id })}
                className="rounded-md border border-border bg-surface-alt px-2.5 py-1 text-sm text-ink hover:bg-hover"
              >
                {d.nazvanie || `Делянка №${d.delyanka_id}`} · {d.status_rabot}
              </button>
            ))}
          </div>
        </div>
      )}
      {lesokultury.length > 0 && (
        <div>
          <div className="text-[11.5px] text-muted-2 mb-1">Лесные культуры</div>
          {lesokultury.map((u) => (
            <div key={u.id} className="text-sm text-ink">
              {u.god_sozdaniya ? `${u.god_sozdaniya} г. · ` : ""}
              {u.sostav_formula || u.glavnaya_poroda || "участок"}
              {u.ploshad ? ` · ${u.ploshad} га` : ""}
              {meropriyatiya.filter((m) => m.uchastok_id === u.id).length > 0 && (
                <span className="text-muted">
                  {" "}— {meropriyatiya.filter((m) => m.uchastok_id === u.id).slice(0, 4).map((m) => `${m.tip}${m.data ? ` ${m.data}` : ""}`).join(", ")}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {works.length > 0 && (
        <div>
          <div className="text-[11.5px] text-muted-2 mb-1">Работы (отметки с телефона)</div>
          {works.slice(0, 10).map((w, i) => (
            <div key={w.id ?? i} className="text-sm text-ink">
              {w.data_vypolneniya || "—"} · {w.tip_raboty || "работа"}
              {w.ispolnitel_fio ? ` · ${w.ispolnitel_fio}` : ""}
            </div>
          ))}
        </div>
      )}
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
  const [history, setHistory] = useState(null);

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
      setHistory(null);
      api
        .get("/taxation/vydel-history", { kvartal: kvartal.trim(), vydel: vydel.trim(), lesnichestvo: lesnichestvo || undefined })
        .then(setHistory)
        .catch(() => setHistory(null));
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
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex flex-col gap-4">
          <div className="flex items-end gap-4 flex-wrap">
            <div className="min-w-[200px]">
              <label className="block text-[11.5px] font-semibold text-muted mb-1">
                Лесничество
              </label>
              <select
                value={lesnichestvo}
                onChange={(e) => setLesnichestvo(e.target.value)}
                className="w-full bg-surface border border-border focus:border-pine focus:bg-surface rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none transition-colors"
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
              Найти участок
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
        <div className="flex flex-col gap-[14px]">
          <div className="bg-surface border border-border rounded-lg px-4 py-3.5 flex flex-col gap-3.5">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="min-w-0">
                <div className="text-[14.5px] font-extrabold text-pine">
                  кв. {card.kvartal_nomer} / выд. {card.nomer}
                </div>
                <div className="font-mono text-[10.5px] text-muted-2 mt-[3px]">лесничество {card.lesnichestvo || "—"}</div>
              </div>
            </div>

            <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
              {[
                ["Площадь, га", card.ploshad],
                ["Категория лесов", card.kategoriya_lesov],
                ["Подкатегория", card.podkategoriya_lesov],
                ["Возраст, лет", primaryAge(card)],
                [
                  "Класс / группа возраста",
                  card.klass_vozrasta != null || card.gruppa_vozrasta != null
                    ? `${card.klass_vozrasta ?? "—"} / ${card.gruppa_vozrasta ?? "—"}`
                    : null,
                ],
                ["Тип леса", card.tip_lesa],
                ["ТЛУ", card.tlu],
                ["Бонитет", card.bonitet],
                ["Полнота", card.polnota],
                ["Класс товарности", card.kl_tovarnosti],
                ["Запас, м³/га", card.zapas_na_ga_display],
                ["Запас на выделе, м³", card.zapas_na_vydele],
                ["Особая земля", yesNo(card.osobaya_zemlya)],
                ["Покрыто лесом", yesNo(card.is_forested)],
              ].map(([label, value]) => (
                <div key={label} className="rounded-[10px] bg-surface-alt px-3 py-2 min-w-0">
                  <div className="text-[11.5px] text-muted-2">{label}</div>
                  <div className="font-mono text-[13px] font-semibold text-ink mt-0.5 break-words">{value ?? "—"}</div>
                </div>
              ))}
            </div>

            <div>
              <div className="font-mono text-[10.5px] uppercase tracking-[.1em] text-muted-2 mb-1.5">формула состава</div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[22px] font-bold text-pine">{card.formula_sostava || "—"}</span>
              </div>
              {card.formula_sostava_2_yarus && (
                <div className="text-[12.5px] text-muted mt-1">2 ярус: {card.formula_sostava_2_yarus}</div>
              )}
              {card.sostav?.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2.5">
                  {card.sostav.map((s, i) => {
                    const p = percentFromDolya(s.dolya);
                    return (
                      <div key={i} className="flex items-center gap-1.5 bg-surface-alt rounded-full px-3 py-1 text-[12.5px] text-ink">
                        <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: CHIP_COLORS[i % CHIP_COLORS.length] }} />
                        {s.poroda || "—"} ({p && p >= 5 ? `${p}%` : "единично"})
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="h-2.5 rounded-full bg-hover mt-3 overflow-hidden">
                <div className="h-full bg-pine rounded-full transition-all" style={{ width: `${dominantPercent(card)}%` }} />
              </div>
            </div>

            <div>
              <div className="font-mono text-[10.5px] uppercase tracking-[.1em] text-muted-2 mb-1.5">состав по элементам леса</div>
              <div className="border border-border rounded-[10px] overflow-hidden overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="bg-surface-alt border-b border-border text-left text-muted-2 text-[11.5px] font-medium">
                      <th className="px-3 py-2">Порода</th>
                      <th className="px-3 py-2">Возраст, лет</th>
                      <th className="px-3 py-2">Высота, м</th>
                      <th className="px-3 py-2">Диаметр, см</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(card.sostav || []).map((s, i) => (
                      <tr key={i} className="border-b border-hover last:border-b-0">
                        <td className="px-3 py-2 text-ink font-semibold">{s.poroda || "—"}</td>
                        <td className="px-3 py-2 text-ink font-mono">{s.vozrast ?? "—"}</td>
                        <td className="px-3 py-2 text-ink font-mono">{s.vysota ?? "—"}</td>
                        <td className="px-3 py-2 text-ink font-mono">{s.diametr ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {(card.lesnye_kultury || card.podlesok || card.podrost || card.tselevaya_poroda || card.ptg || card.povrezhdenie) && (
              <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))" }}>
                {[
                  ["Лесные культуры", card.lesnye_kultury],
                  ["Подлесок", card.podlesok],
                  ["Подрост", card.podrost],
                  ["Целевая порода", card.tselevaya_poroda],
                  ["ПТГ", card.ptg],
                  ["Повреждение", card.povrezhdenie],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-[10px] bg-surface-alt px-3 py-2 min-w-0">
                    <div className="text-[11.5px] text-muted-2">{label}</div>
                    <div className="font-mono text-[13px] font-semibold text-ink mt-0.5 break-words">{value ?? "—"}</div>
                  </div>
                ))}
              </div>
            )}

            {card.primechaniya && (
              <div className="rounded-[10px] bg-mint-soft px-3.5 py-3 text-[12.5px] text-ink leading-relaxed whitespace-pre-wrap">
                {card.primechaniya}
              </div>
            )}
          </div>
          <VydelHistory history={history} />
        </div>
      )}
    </div>
  );
}
