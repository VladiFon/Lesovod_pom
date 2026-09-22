import React, { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import TopBar from "./components/TopBar.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Plots from "./pages/Plots.jsx";
import Documents from "./pages/Documents.jsx";
import Taxation from "./pages/Taxation.jsx";
import Lesokultury from "./pages/Lesokultury.jsx";
import Raskhod from "./pages/Raskhod.jsx";
import Inspection from "./pages/Inspection.jsx";
import RubkiUhoda from "./pages/RubkiUhoda.jsx";
import PlanRabot from "./pages/PlanRabot.jsx";
import Sotrudniki from "./pages/Sotrudniki.jsx";
import Attendance from "./pages/Attendance.jsx";
import WorkerNotes from "./pages/WorkerNotes.jsx";
import Archive from "./pages/Archive.jsx";
import CalendarScreen from "./pages/Calendar.jsx";
import AiLog from "./pages/AiLog.jsx";
import Settings from "./pages/Settings.jsx";
import ComponentGallery from "./pages/ComponentGallery.jsx";
import { ToastProvider } from "./components/Toast.jsx";
import Button from "./components/Button.jsx";
import { api } from "./api/client.js";

// Этап 4: экраны переписываются по одному, от простого к сложному
// (план, порядок 1→10). Готовы: "settings" (реальный backend) и
// "dashboard"/"gallery" (моковые, из Этапа 3). Остальные пункты Sidebar
// пока ведут на заглушку со ссылкой "что уже готово".
const READY_SCREENS = {
  dashboard: { title: "Дашборд", subtitle: "Обзор по всем делянкам за текущий период", Page: Dashboard, search: true, primaryAction: true },
  // Плоты сами управляют своим тулбаром (поиск, "Показывать архивные",
  // "Импорт МДО" в левой колонке) — по аналогии с Settings/Dashboard,
  // TopBar здесь без search/primaryAction, чтобы не дублировать поиск.
  plots: { title: "Делянки", subtitle: "Карточки делянок, документы, импорт из МДО", Page: Plots },
  // Этап 5 (часть 2): сквозной список документов по всем делянкам, с
  // фильтрами и массовыми действиями — см. pages/Documents.jsx.
  documents: { title: "Документы", subtitle: "Все документы по всем делянкам: фильтры, массовые действия", Page: Documents },
  // "Живая карта" (LiveMap.jsx, react-leaflet + импорт слоя из QGIS) убрана
  // из меню по решению пользователя — карты ведутся в самом QGIS, экран не
  // нужен. Backend (app/routers/map.py) не трогали, файл страницы удалён.
  taxation: { title: "Таксация", subtitle: "Поиск участка по кварталу/выделу и карточка-досье", Page: Taxation },
  forestry: { title: "Лесокультуры", subtitle: "Участки лесных культур и журнал мероприятий по уходу", Page: Lesokultury },
  raskhod: { title: "Расход / ЕГАИС", subtitle: "Баланс лимитов и факта по выделам, наряды-задания", Page: Raskhod },
  inspection: { title: "Инспекция", subtitle: "Акты освидетельствования: сроки, чек-лист, справки", Page: Inspection },
  // C.3 плана — независимые пробы рубок ухода (не привязаны к делянке,
  // см. docstring backend/legacy/uhody.py): своя ведомость перечёта и
  // обмера укладок хвороста, расчёт запаса, экспорт в Word/Excel.
  uhody: { title: "Рубки ухода", subtitle: "Пробы, обмер укладок хвороста, ведомость перечёта", Page: RubkiUhoda },
  // Фаза 4 плана доработки — постановка задач сотрудникам (work_plan),
  // веб-половина уже существующей мобильной функции (см. app/routers/bot.py).
  work_plan: { title: "План работ", subtitle: "Постановка задач сотрудникам: дата, делянка, статус", Page: PlanRabot },
  // Перенесено из Settings.jsx (WorkersCard) — тот же /api/auth/workers,
  // полноценный экран вместо блока внутри "Настроек".
  sotrudniki: { title: "Сотрудники", subtitle: "Справочник работников: ФИО, должность, участок", Page: Sotrudniki },
  // Односторонние ленты "рабочий -> мастер" (мобильное приложение ->
  // веб), см. app/routers/attendance.py и app/routers/notes.py.
  attendance: { title: "Присутствие", subtitle: "Кто сегодня работал — отметки из мобильного приложения", Page: Attendance },
  worker_notes: { title: "Заметки", subtitle: "Заметки рабочих начальнику — лента, непрочитанные наверху", Page: WorkerNotes },
  archive: { title: "Архив", subtitle: "Ручной архив документов: сканы приказов, списки делянок", Page: Archive },
  calendar: { title: "Календарь", subtitle: "Рабочий календарь: разовые и периодические задачи", Page: CalendarScreen },
  ai_log: { title: "ИИ-журнал", subtitle: "Разбор отчётов telegram-бота и журнал выполненных работ", Page: AiLog },
  settings: { title: "Настройки", subtitle: "Ключи доступа и данные лесничего — общие для всех", Page: Settings },
  gallery: { title: "Витрина компонентов", subtitle: "Все базовые компоненты дизайн-системы на моковых данных", Page: ComponentGallery },
};

// Отображаемое имя роли (для Sidebar) — по коду роли из webext.ROLES.
const ROLE_LABELS = {
  admin: "Администратор",
  lesovod: "Лесовод",
  viewer: "Наблюдатель",
};

/**
 * Блок 1 плана доработки, п.2: на старте проверяем GET /api/auth/me.
 * - Токена нет или он просрочен/отозван (401) → показываем Login вместо
 *   всего остального приложения.
 * - Токен валиден → прокидываем реального user в Sidebar (проп там уже
 *   принимался, просто раньше никто не передавал ничего, кроме
 *   MOCK_USER).
 */
export default function App() {
  const [active, setActive] = useState("settings");
  const [search, setSearch] = useState("");

  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = localStorage.getItem("lesovod_token");
      if (!token) {
        if (!cancelled) setAuthChecked(true);
        return;
      }
      try {
        const me = await api.get("/auth/me");
        if (!cancelled) setUser(me);
      } catch {
        // токен просрочен/отозван/невалиден — тихо очищаем и показываем Login
        localStorage.removeItem("lesovod_token");
      } finally {
        if (!cancelled) setAuthChecked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // даже если запрос не прошёл (сеть/сервер недоступен), локально всё
      // равно разлогиниваем — токен ниже удаляется в любом случае
    } finally {
      localStorage.removeItem("lesovod_token");
      setUser(null);
    }
  };

  if (!authChecked) {
    return <div className="h-screen w-screen bg-surface-alt" />;
  }

  if (!user) {
    return <Login onLoggedIn={setUser} />;
  }

  const screen = READY_SCREENS[active];
  const sidebarUser = { fio: user.fio || user.login, role: ROLE_LABELS[user.role] || user.role };

  return (
    <ToastProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar active={active} onNavigate={setActive} user={sidebarUser} onLogout={handleLogout} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <TopBar
            title={screen?.title ?? active}
            subtitle={screen?.subtitle}
            search={screen?.search ? search : undefined}
            onSearchChange={screen?.search ? setSearch : undefined}
            hasNotifications
            primaryAction={screen?.primaryAction ? { label: "+ Новая делянка", onClick: () => {} } : undefined}
          />
          <div className="flex-1 overflow-y-auto">
            {screen ? (
              <screen.Page currentUser={user} />
            ) : (
              <div className="p-8">
                <div className="text-muted text-base mb-3">
                  Экран «{active}» ещё не переписан (см. порядок в плане, Этап 4) — сейчас готовы
                  «Настройки» и эталонный «Дашборд».
                </div>
                <Button variant="secondary" onClick={() => setActive("settings")}>
                  Открыть «Настройки»
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </ToastProvider>
  );
}
