import React, { useCallback, useEffect, useState } from "react";
import Card from "../components/Card.jsx";
import StatCard from "../components/StatCard.jsx";
import DataTable from "../components/DataTable.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import Modal from "../components/Modal.jsx";
import BarChart from "../components/BarChart.jsx";
import { useToast } from "../components/Toast.jsx";
import { api, ApiError } from "../api/client.js";

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

function InsightEntry({ category, timestamp, title, description, severity }) {
  const color =
    severity === "critical" ? "var(--color-error, #ba1a1a)" : severity === "warning" ? "var(--color-oak)" : "var(--color-pine)";
  return (
    <div className="border-l-4 pl-3 py-0.5" style={{ borderLeftColor: color }}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold tracking-wide uppercase" style={{ color }}>
          {category}
        </span>
        <span className="text-faint text-xs shrink-0">{timestamp}</span>
      </div>
      <div className="font-semibold text-ink text-sm mt-0.5">{title}</div>
      <div className="text-muted text-sm">{description}</div>
    </div>
  );
}

function WeatherCard({ weather, loading, error, onRefresh }) {
  const fireClass = weather?.fire_danger_class ?? null;
  const fire = FIRE_CLASSES[fireClass];

  return (
    <Card
      title="🌦️ Погода в лесу"
      actions={
        <button
          onClick={onRefresh}
          disabled={loading}
          title="Обновить погоду сейчас"
          className="h-7 w-7 rounded-md flex items-center justify-center text-muted hover:bg-hover hover:text-pine disabled:opacity-60"
        >
          {loading ? "⏳" : "🔄"}
        </button>
      }
    >
      <div className="text-2xl font-extrabold text-pine-deep">
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
            className="w-full bg-surface-alt border border-transparent focus:border-pine rounded-md px-3 py-2 text-base text-ink outline-none"
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

export default function Dashboard() {
  const toast = useToast();

  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState(null);

  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [savingPlan, setSavingPlan] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get("/dashboard/summary");
      setSummary(data);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "Не удалось загрузить дашборд");
    } finally {
      setLoading(false);
    }
  }, []);

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

  return (
    <div className="p-8 flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="font-ui font-bold text-lg text-ink">🌲 Обзор управления</h2>
          <p className="text-muted text-base mt-0.5">
            {new Date().toLocaleDateString("ru-RU")} — сводка по текущим показателям
          </p>
        </div>
        <Button
          variant="primary"
          disabled
          title="Экран «Делянки» ещё не переписан (Этап 4, следующий пункт по плану) — кнопка появится рабочей после него"
        >
          ＋ Новый аудит делянки
        </Button>
      </div>

      {loadError && (
        <Card className="border-error/40">
          <p className="text-error text-base">{loadError}</p>
        </Card>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard icon="🌳" title="Делянки в работе" value={loading ? "…" : String(metrics?.delyanki_count ?? 0)} caption="Актуально на сегодня" />
        <StatCard icon="✅" title="Выполнено работ" value={loading ? "…" : String(metrics?.completed_count ?? 0)} caption="Все зафиксированные работы" />
        <StatCard icon="🪵" title="Заготовлено, м³" value={loading ? "…" : metrics?.volume_m3_fmt ?? "0"} caption="По журналу расхода" />
        <StatCard
          icon="🚨"
          title="Очередь ИИ"
          value={loading ? "…" : String(metrics?.ai_queue_count ?? 0)}
          caption={metrics?.ai_queue_count ? `${metrics.ai_queue_count} новых отчётов` : "Нет новых отчётов"}
          alert={Boolean(metrics?.ai_queue_alert)}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-6">
          <Card
            title="Обзор заготовки"
            subtitle={chart ? `План ${chart.total_plan.toFixed(1)} м³ · Факт ${chart.total_fact.toFixed(1)} м³` : "Последние 6 месяцев"}
            actions={
              <Button variant="ghost" size="sm" onClick={() => setPlanModalOpen(true)}>
                ✏️ Задать план на месяц
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
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "#e5e2db" }} /> План (м³)
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-sm text-muted">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: "#1a4331" }} /> Факт (м³)
                  </span>
                </div>
              </>
            )}
          </Card>

          <Card
            title="Активные делянки"
            actions={
              <Button variant="ghost" size="sm" disabled title="Экран «Делянки» ещё не переписан (Этап 4, следующий пункт)">
                Смотреть все
              </Button>
            }
            padding={false}
          >
            <div className="px-5 pb-5">
              <DataTable
                loading={loading}
                columns={[
                  { key: "nazvanie", header: "Делянка", sortable: true },
                  { key: "status", header: "Статус", sortable: true, render: (row) => <StatusBadge status={row.status} /> },
                  { key: "created_at", header: "Создано", sortable: true },
                ]}
                rows={plots}
                emptyTitle="Активных делянок нет"
                emptyDescription="Создайте делянку на экране «Делянки», и она появится здесь."
              />
            </div>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <Card title="🧠 ИИ-аналитика">
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
