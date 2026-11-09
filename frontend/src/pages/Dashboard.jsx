import React, { useCallback, useEffect, useState } from "react";
import Card from "../components/Card.jsx";
import StatCard from "../components/StatCard.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import Modal from "../components/Modal.jsx";
import BarChart from "../components/BarChart.jsx";
import { useToast } from "../components/Toast.jsx";
import { api, ApiError } from "../api/client.js";
import { openScreen } from "../nav.js";

/**
 * Dashboard — экран "Главная (Дашборд)" (Этап 4, второй переписанный
 * экран после "Настроек").
 *
 * Референс функциональности: screens/dashboard/screen.py + helpers.py +
 * widgets.py + weather_card.py + weather_worker.py (десктоп). Backend:
 * app/routers/dashboard.py (написан в этом же шаге — существующего
 * роутера под дашборд в приложенных архивах не было, в отличие от
 * settings.py).
 *
 * ─── Перенесено 1:1 ──────────────────────────────────────────────────
 *  • 4 карточки-метрики (делянки/выполнено/заготовлено/очередь ИИ),
 *    включая "тревожный" вид карточки очереди ИИ при новых отчётах —
 *    GET /api/dashboard/summary → metrics.
 *  • Таблица "Активные делянки" (последние 5 неархивных) —
 *    summary.plots, та же выборка, что _load_plots_table().
 *  • Лента "ИИ-аналитика": перерубы (топ-3) → отчёты в очереди →
 *    последние акты → "критичных событий нет" — summary.insights,
 *    та же логика и порядок, что _refresh_ai_insights().
 *  • График "Обзор заготовки" за 6 месяцев (план вручную из
 *    harvest_plan, факт — из нарядов расхода) + диалог "✏️ Задать план
 *    на месяц" — summary.chart и POST /api/dashboard/harvest-plan.
 *  • Карточка "Погода в лесу": температура/влажность/ветер/класс
 *    пожарной опасности с текстом ограничений, кнопка "🔄" ручного
 *    обновления с состоянием "Обновляем…" — summary.weather и
 *    POST /api/dashboard/weather/refresh.
 *
 * ─── Сознательно упрощено (и почему) ──────────────────────────────────
 *  1. Автообновление при каждом показе экрана (showEvent в десктопе) —
 *     в вебе это как минимум GET при каждом переключении вкладки
 *     Sidebar. Пока делаем только загрузку при монтировании страницы +
 *     ручное обновление погоды; авто-опрос раз в N секунд имеет смысл
 *     завести вместе с общим WebSocket/поллингом из Этапа 5 (там он
 *     нужнее — для статусов документов), а не дублировать здесь
 *     отдельным таймером.
 *  2. "＋ Новый аудит делянки" и "Смотреть все" (таблица делянок) —
 *     кнопки на месте, но задизейблены с подсказкой. В десктопе они,
 *     что интересно, тоже ни на что не были подключены
 *     (new_audit_button/view_all_button без .clicked.connect в
 *     screen.py) — но по смыслу должны вести на экран "Делянки",
 *     которого в вебе пока нет (следующий по плану, Этап 4, п.3).
 *  3. Клик по строке таблицы "Активные делянки" (в десктопе — двойной
 *     клик, сигнал plot_selected → переключение на экран "Делянки") —
 *     по той же причине не подключён: экрана-получателя ещё нет.
 *  4. График — обычный SVG-компонент (components/BarChart.jsx) вместо
 *     QPainter-отрисовки; библиотека графиков (recharts и т.п.) не
 *     подключалась — один график из двух серий её не оправдывает.
 */

const FIRE_CLASSES = {
  1: { bg: "#dcefe0", fg: "#1a4331", text: "Отсутствует. Ограничений для лесозаготовки нет." },
  2: { bg: "#eef2c8", fg: "#5c5f1a", text: "Малая. Соблюдайте общие меры пожарной безопасности." },
  3: { bg: "#ffe4c2", fg: "#8a4b06", text: "Средняя. Работы с открытым огнём и техникой — под контролем лесника." },
  4: { bg: "#ffd0c2", fg: "#9c2b0e", text: "Высокая. Разведение костров запрещено, усильте дежурство на делянках." },
  5: { bg: "#ffb3ab", fg: "#7a0000", text: "Чрезвычайная. Лесозаготовительные работы приостановлены." },
};

// Строка ленты с screen/params открывает нужный экран (шаг 4 разбора
// 03.11.2026): переруб — Расход делянки, бригады — Распределение и т.д.
function InsightEntry({ category, timestamp, title, description, severity, screen, params }) {
  const color =
    severity === "critical" ? "var(--color-error, #ba1a1a)" : severity === "warning" ? "var(--color-oak)" : "var(--color-pine)";
  const Tag = screen ? "button" : "div";
  return (
    <Tag
      type={screen ? "button" : undefined}
      onClick={screen ? () => openScreen(screen, params || {}) : undefined}
      className={["border-l-4 pl-3 py-0.5 text-left w-full", screen ? "rounded-r-md hover:bg-hover cursor-pointer" : ""].join(" ")}
      style={{ borderLeftColor: color }}
      title={screen ? "Открыть" : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold tracking-wide uppercase" style={{ color }}>
          {category}
        </span>
        <span className="text-faint text-xs shrink-0">{timestamp}</span>
      </div>
      <div className="font-semibold text-ink text-sm mt-0.5">{title}</div>
      <div className="text-muted text-sm">{description}{screen && <span className="text-pine font-semibold"> → открыть</span>}</div>
    </Tag>
  );
}

// Строка «Как идёт заготовка» (разбор 09.11.2026): полоска освоения с
// чертой 100%, срок и сколько дней осталось; клик — эта делянка.
const LEVEL_BAR = { norma: "bg-pine", vnimanie: "bg-oak", preduprezhdenie: "bg-oak", pererub: "bg-error", net_limita: "bg-border" };
function ruDay(iso) {
  const m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}` : "";
}
function DelyankaRow({ d }) {
  const pct = d.pct == null ? null : Number(d.pct);
  const width = pct == null ? 0 : Math.min(pct, 110) / 110;
  let srok = { text: "срок не задан", cls: "text-faint bg-hover" };
  if (d.dney != null) {
    if (d.dney < 0) srok = { text: `просрочено ${-d.dney} дн.`, cls: "text-error bg-error-soft" };
    else if (d.dney === 0) srok = { text: "срок сегодня", cls: "text-error bg-error-soft" };
    else if (d.dney <= 14) srok = { text: `${d.dney} дн. · до ${ruDay(d.srok)}`, cls: "text-[#8a5a00] bg-oak-soft" };
    else srok = { text: `${d.dney} дн. · до ${ruDay(d.srok)}`, cls: "text-pine bg-mint-soft" };
  }
  return (
    <button
      type="button"
      onClick={() => openScreen("plots", { d: d.id })}
      className="group grid items-center gap-x-4 px-4 py-2.5 text-left hover:bg-[#f2faf3] transition-colors"
      style={{ gridTemplateColumns: "minmax(150px, 1fr) minmax(200px, 2fr) 150px" }}
      title="Открыть делянку"
    >
      <span className="font-semibold text-ink text-[13.5px] truncate group-hover:text-pine">{d.nazvanie}</span>
      <span className="flex items-center gap-3 min-w-0">
        <span className="relative flex-1 h-2 rounded-full bg-hover">
          <span className={["absolute inset-y-0 left-0 rounded-full", LEVEL_BAR[d.level] || "bg-pine"].join(" ")} style={{ width: `${width * 100}%` }} />
          <span className="absolute -top-[3px] -bottom-[3px] w-[2px] rounded bg-[#1c1c18]/40" style={{ left: `${(100 / 110) * 100}%` }} title="100% лимита" />
        </span>
        <span className="shrink-0 w-[128px] text-right tabular-nums text-[12.5px] whitespace-nowrap">
          <b className="text-ink">{pct == null ? "—" : `${Math.round(pct)}%`}</b>
          <span className="text-faint"> · {d.fakt_fmt}/{d.limit_fmt}</span>
        </span>
      </span>
      <span className={["justify-self-end rounded-full px-2.5 py-1 text-[11.5px] font-semibold whitespace-nowrap", srok.cls].join(" ")}>{srok.text}</span>
    </button>
  );
}

function WeatherCard({ weather, loading, error, onRefresh }) {
  const fireClass = weather?.fire_danger_class ?? null;
  const fire = FIRE_CLASSES[fireClass];

  return (
    <Card
      title="Погода в лесу"
      icon="🌤"
      iconTone="info"
      actions={
        <button
          onClick={onRefresh}
          disabled={loading}
          title="Обновить погоду сейчас"
          className="h-7 w-7 rounded-md flex items-center justify-center text-muted hover:bg-hover hover:text-pine disabled:opacity-60"
        >
          {loading ? "…" : "↻"}
        </button>
      }
    >
      <div className="font-mono text-[28px] font-bold text-pine-deep leading-none mt-2">
        {weather?.temperature != null ? `${Math.round(weather.temperature)}°C` : "—°C"}
      </div>
      <div className="grid grid-cols-2 gap-4 mt-2">
        <div>
          <div className="text-faint text-xs">Влажность</div>
          <div className="text-ink text-sm font-medium">
            {weather?.humidity != null ? `${Math.round(weather.humidity)} %` : "— %"}
          </div>
        </div>
        <div>
          <div className="text-faint text-xs">Ветер</div>
          <div className="text-ink text-sm font-medium">
            {weather?.wind_speed != null ? `${weather.wind_speed.toFixed(1)} м/с, ${weather.wind_dir ?? "—"}` : "— м/с, —"}
          </div>
        </div>
      </div>

      <div className="rounded-md px-3 py-2 mt-3" style={{ backgroundColor: fire?.bg ?? "#f1eee7" }}>
        <div className="text-sm font-bold" style={{ color: fire?.fg ?? "#414944" }}>
          Класс пожарной опасности: {fireClass ?? "нет данных"}
        </div>
        <div className="text-sm mt-0.5" style={{ color: fire?.fg ?? "#414944" }}>
          {fire?.text ?? "—"}
        </div>
      </div>

      <div className="text-faint text-xs mt-2" title={error ?? undefined}>
        {loading ? "Обновляем…" : error ? "⚠️ Не удалось обновить" : weather?.updated_at ? `Обновлено: ${weather.updated_at}` : "—"}
      </div>
    </Card>
  );
}

function SetPlanModal({ open, onClose, periods, months, onSave, saving }) {
  const [period, setPeriod] = useState(periods[periods.length - 1] ?? "");
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) {
      setPeriod(periods[periods.length - 1] ?? "");
      setValue("");
    }
  }, [open, periods]);

  return (
    <Modal open={open} onClose={onClose} title="Задать план на месяц">
      <div className="flex flex-col gap-4">
        <div>
          <label className="text-sm font-semibold text-ink block mb-1">Месяц</label>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full bg-surface border border-border focus:border-pine rounded-md px-3 py-2 text-base text-ink outline-none"
          >
            {periods.map((p, i) => (
              <option key={p} value={p}>
                {months[i]} ({p})
              </option>
            ))}
          </select>
        </div>
        <TextField
          label="План, м³"
          type="number"
          min="0"
          step="0.1"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Например, 1500"
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button
            variant="primary"
            loading={saving}
            disabled={!period || value === ""}
            onClick={() => onSave(period, Number(value))}
          >
            Сохранить
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function Dashboard({ onOpenTab }) {
  const toast = useToast();

  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState(null);

  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [savingPlan, setSavingPlan] = useState(false);
  // период для «Выполнено работ» и «Заготовлено за год»: год или всё время
  const tekGod = new Date().getFullYear();
  const [god, setGod] = useState(String(tekGod));

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get(`/dashboard/summary?god=${encodeURIComponent(god)}`);
      setSummary(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Не удалось загрузить дашборд");
    } finally {
      setLoading(false);
    }
  }, [god]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  const handleRefreshWeather = async () => {
    setWeatherLoading(true);
    setWeatherError(null);
    try {
      const weather = await api.post("/dashboard/weather/refresh");
      setSummary((s) => (s ? { ...s, weather } : s));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Сетевая ошибка";
      setWeatherError(message);
      toast.show({ tone: "warning", title: "Не удалось обновить погоду", description: message });
    } finally {
      setWeatherLoading(false);
    }
  };

  const handleSavePlan = async (period, value) => {
    setSavingPlan(true);
    try {
      const chart = await api.post("/dashboard/harvest-plan", { period, value });
      setSummary((s) => (s ? { ...s, chart } : s));
      setPlanModalOpen(false);
      toast.show({ tone: "success", title: "План сохранён", description: `${period}: ${value} м³` });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось сохранить план",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    } finally {
      setSavingPlan(false);
    }
  };

  const metrics = summary?.metrics;
  const chart = summary?.chart;
  const plots = summary?.plots ?? [];
  const insights = summary?.insights ?? [];
  const limitVsego = plots.reduce((sum, d) => sum + (Number(String(d.limit_fmt).replace(",", ".")) || 0), 0);
  const goryat = plots.reduce((acc, d) => {
    if (d.dney == null) return acc;
    if (d.dney < 0) acc.prosrocheno += 1;
    else if (d.dney <= 14) acc.skoro += 1;
    return acc;
  }, { prosrocheno: 0, skoro: 0 });

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      {loadError && (
        <Card className="border-[#ebc0bc]">
          <p className="text-error text-base">{loadError}</p>
        </Card>
      )}

      <div className="flex items-center justify-end gap-2 -mb-1 text-sm text-muted">
        <span>Период:</span>
        <select className="bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-8 text-[13px] text-ink outline-none" value={god} onChange={(e) => setGod(e.target.value)}>
          <option value={String(tekGod)}>{tekGod} год</option>
          <option value={String(tekGod - 1)}>{tekGod - 1} год</option>
          <option value="vse">Всё время</option>
        </select>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard icon="🌳" title="Делянки в работе" onClick={() => openScreen("plots")} value={loading ? "…" : String(metrics?.delyanki_count ?? 0)} caption={[
            metrics?.storonnie_count ? `из них ${metrics.storonnie_count} рубят другие` : "Активные делянки",
            metrics?.chernoviki_count ? `ещё ${metrics.chernoviki_count} в черновиках` : null,
          ].filter(Boolean).join(" · ")} />
        <StatCard icon="🪵" title="Заготовлено на активных, м³" onClick={() => openScreen("raskhod")} value={loading ? "…" : metrics?.volume_m3_fmt ?? "0"}
          progress={limitVsego > 0 ? (metrics?.volume_m3 || 0) / limitVsego : null} progressMark={1}
          caption={[
            limitVsego > 0 ? `${Math.round(((metrics?.volume_m3 || 0) / limitVsego) * 100)}% лимита делянок` : "по нарядам",
            metrics?.volume_egais_m3_fmt != null ? `ЕГАИС ${metrics.volume_egais_m3_fmt}` : null,
            god === "vse" ? `всего ${metrics?.volume_god_m3_fmt ?? "0"}` : `за ${god} год ${metrics?.volume_god_m3_fmt ?? "0"}`,
          ].filter(Boolean).join(" · ")} />
        <StatCard icon="⏰" title="Горят сроки заготовки" onClick={() => openScreen("inspection")}
          tone={goryat.prosrocheno ? "error" : goryat.skoro ? "oak" : "pine"}
          value={loading ? "…" : String(goryat.prosrocheno + goryat.skoro)}
          caption={goryat.prosrocheno ? `${goryat.prosrocheno} просрочено · ${goryat.skoro} в ближайшие 14 дн.` : goryat.skoro ? "в ближайшие 14 дней" : "Сроков рядом нет"} />
        <StatCard
          icon="📥"
          title="Отчёты с телефона"
          onClick={() => openScreen("telefon", { tab: "otchety" })}
          tone={metrics?.ai_queue_count ? "info" : "pine"}
          value={loading ? "…" : String(metrics?.ai_queue_count ?? 0)}
          caption={metrics?.ai_queue_count ? "ждут проверки — открыть Входящие" : "Всё разобрано"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-[14px]">
        <div className="lg:col-span-2 flex flex-col gap-[14px]">
          <Card
            title="Обзор заготовки"
            icon="📊"
            subtitle={chart ? `План ${chart.total_plan.toFixed(1)} м³ · Факт ${chart.total_fact.toFixed(1)} м³` : "Последние 6 месяцев"}
            actions={
              <Button variant="ghost" size="sm" onClick={() => setPlanModalOpen(true)}>
                Задать план на месяц
              </Button>
            }
          >
            {chart && (
              <>
                <BarChart
                  categories={chart.months}
                  series={[
                    { label: "План (м³)", values: chart.plan, color: "#e5e2db" },
                    { label: "Факт (м³)", values: chart.fact, color: "#1a4331" },
                  ]}
                />
                <div className="flex items-center justify-center gap-6 mt-2">
                  <span className="inline-flex items-center gap-1.5 text-sm text-muted">
                    <span className="h-2.5 w-3 rounded-[3px] border-2 border-dashed" style={{ borderColor: "#cfcbc2" }} /> План (м³)
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-sm text-muted">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "#1a4331" }} /> Факт (м³)
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-sm text-muted">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "var(--color-green)" }} /> План выполнен
                  </span>
                </div>
              </>
            )}
          </Card>

          <Card
            title="Как идёт заготовка"
            subtitle="Все делянки в работе · сверху те, у которых раньше срок"
            icon="🪓"
            divider
            actions={
              <Button variant="ghost" size="sm" onClick={() => openScreen("plots")}>
                Все делянки
              </Button>
            }
            padding={false}
          >
            {loading ? (
              <div className="p-4 flex flex-col gap-3">
                {[0, 1, 2].map((i) => <div key={i} className="h-10 rounded-md bg-hover animate-pulse" />)}
              </div>
            ) : plots.length ? (
              <div className="flex flex-col py-1.5">
                {plots.map((d) => <DelyankaRow key={d.id} d={d} />)}
              </div>
            ) : (
              <div className="p-5 text-sm text-muted">Активных делянок нет — создайте делянку на экране «Делянки».</div>
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-[14px]">
          <Card title="Требует внимания" icon="🔔" iconTone="oak">
            {loading ? (
              <div className="flex flex-col gap-3">
                {[0, 1].map((i) => (
                  <div key={i} className="h-10 rounded bg-hover animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {insights.map((entry, i) => (
                  <InsightEntry key={i} {...entry} />
                ))}
              </div>
            )}
          </Card>

          <WeatherCard weather={summary?.weather} loading={weatherLoading} error={weatherError} onRefresh={handleRefreshWeather} />
        </div>
      </div>

      {chart && (
        <SetPlanModal
          open={planModalOpen}
          onClose={() => setPlanModalOpen(false)}
          periods={chart.periods}
          months={chart.months}
          onSave={handleSavePlan}
          saving={savingPlan}
        />
      )}
    </div>
  );
}
