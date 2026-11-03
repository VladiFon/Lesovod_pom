import React, { useEffect, useReducer, useState } from "react";
import Sidebar from "./components/Sidebar.jsx";
import TabWorkspace, { tabsReducer } from "./components/TabWorkspace.jsx";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Plots from "./pages/Plots.jsx";
import Documents from "./pages/Documents.jsx";
import Taxation from "./pages/Taxation.jsx";
import Lesokultury from "./pages/Lesokultury.jsx";
import TekushchieIzmeneniya from "./pages/TekushchieIzmeneniya.jsx";
import Raskhod from "./pages/Raskhod.jsx";
import Inspection from "./pages/Inspection.jsx";
import RubkiUhoda from "./pages/RubkiUhoda.jsx";
import RaspredelenieBrigad from "./pages/RaspredelenieBrigad.jsx";
import PlanRabot from "./pages/PlanRabot.jsx";
import TabelRuchnoy from "./pages/TabelRuchnoy.jsx";
import Sotrudniki from "./pages/Sotrudniki.jsx";
import Attendance from "./pages/Attendance.jsx";
import WorkerNotes from "./pages/WorkerNotes.jsx";
import Archive from "./pages/Archive.jsx";
import CalendarScreen from "./pages/Calendar.jsx";
import { RawReportsTab, CompletedTab } from "./pages/AiLog.jsx";
import { makeMergedScreen } from "./components/MergedScreen.jsx";
import Settings from "./pages/Settings.jsx";
import ComponentGallery from "./pages/ComponentGallery.jsx";
import Korzina from "./pages/Korzina.jsx";
import Kvesty from "./pages/Kvesty.jsx";
import TabelIgra from "./pages/TabelIgra.jsx";
import { poVidu } from "./vid.jsx";
import UhodyIgra from "./pages/UhodyIgra.jsx";
import FrontRabot from "./pages/FrontRabot.jsx";
import OhotaAktov from "./pages/OhotaAktov.jsx";
import VyvozkaIgra from "./pages/VyvozkaIgra.jsx";
import Shtab from "./pages/Shtab.jsx";
import Reyting from "./pages/Reyting.jsx";
import { UserProvider } from "./auth.jsx";
import { ALIASES, applyHash, openScreen, readHash, resolveScreen, setScreenOpener, syncHash } from "./nav.js";
import { ToastProvider } from "./components/Toast.jsx";
import { api } from "./api/client.js";

const Padded = (Inner) => function PaddedTab() {
  return <div className="p-[18px] flex flex-col gap-[14px]"><Inner /></div>;
};

// Шаг 4 разбора (03.11.2026): похожие пункты меню слиты в один экран с
// вкладками. Старые ключи (ai_log, worker_notes, attendance, work_plan,
// calendar) — алиасы в nav.js, ссылки на них не ломаются.
const Telefon = makeMergedScreen("telefon", [
  { key: "otchety", label: "Отчёты на проверку", Page: Padded(RawReportsTab) },
  { key: "zametki", label: "Заметки рабочих", Page: WorkerNotes },
  { key: "zhurnal", label: "Журнал выполненных работ", Page: Padded(CompletedTab) },
]);
const Tabel = makeMergedScreen("tabel", [
  // Игровой вид (переключатель в шапке/Настройках) — «Перекличка» вместо
  // обычного ввода; обычный ввод никуда не делся.
  { key: "vvod", label: "Ввод табеля", Page: poVidu(TabelRuchnoy, TabelIgra) },
  { key: "prisutstvie", label: "Отметки с телефона", Page: Attendance },
]);
// Игровой вид Дашборда (03.11.2026): «Штаб» — карта всех игровых экранов.
const DashboardIgra = makeMergedScreen("dashboard", [
  { key: "shtab", label: "🏰 Штаб", Page: Shtab },
  { key: "obzor", label: "Обзор", Page: Dashboard },
]);
// Игровой вид «Расхода / ЕГАИС» (03.11.2026): «Вывозка» + обычный Расход.
const RaskhodIgra = makeMergedScreen("raskhod", [
  { key: "vyvozka", label: "🚛 Вывозка", Page: VyvozkaIgra },
  { key: "raskhod", label: "Расход", Page: Raskhod },
]);
// Игровой вид «Инспекции» (03.11.2026): «Охота на акты» + обычный список
// (форма акта — там же, «Составить акт» открывает вкладку «Список»).
const InspectionIgra = makeMergedScreen("inspection", [
  { key: "ohota", label: "🏹 Охота на акты", Page: OhotaAktov },
  { key: "spisok", label: "Список", Page: Inspection },
]);
// Игровой вид «Лесокультур» (03.11.2026): «Огород уходов» + обычный список
// участков второй вкладкой.
const LesokulturyIgra = makeMergedScreen("forestry", [
  { key: "ogorod", label: "🌱 Огород уходов", Page: UhodyIgra },
  { key: "uchastki", label: "Участки", Page: Lesokultury },
]);
const Zadachi = makeMergedScreen("zadachi", [
  { key: "plan", label: "План работ", Page: PlanRabot },
  { key: "kalendar", label: "Календарь", Page: CalendarScreen },
]);

// Этап 4: экраны переписываются по одному, от простого к сложному
// (план, порядок 1→10). Готовы: "settings" (реальный backend) и
// "dashboard"/"gallery" (моковые, из Этапа 3). Остальные пункты Sidebar
// пока ведут на заглушку со ссылкой "что уже готово".
const READY_SCREENS = {
  dashboard: { title: "Дашборд", subtitle: "Обзор по всем делянкам за текущий период", Page: poVidu(Dashboard, DashboardIgra), search: true, primaryAction: true },
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
  forestry: { title: "Лесокультуры", subtitle: "Участки лесных культур и журнал мероприятий по уходу", Page: poVidu(Lesokultury, LesokulturyIgra) },
  // Ведомости текущих изменений по приказу Минлесхоза №130 (Word по шаблону).
  tek_izm: { title: "Текущие изменения", subtitle: "Ведомости для Белгослеса по приказу №130: прил. 1–15", Page: TekushchieIzmeneniya },
  raskhod: { title: "Расход / ЕГАИС", subtitle: "Баланс лимитов и факта по выделам, наряды-задания", Page: poVidu(Raskhod, RaskhodIgra) },
  inspection: { title: "Инспекция", subtitle: "Акты освидетельствования: сроки, чек-лист, справки", Page: poVidu(Inspection, InspectionIgra) },
  // C.3 плана — независимые пробы рубок ухода (не привязаны к делянке,
  // см. docstring backend/legacy/uhody.py): своя ведомость перечёта и
  // обмера укладок хвороста, расчёт запаса, экспорт в Word/Excel.
  uhody: { title: "Рубки ухода", subtitle: "Пробы, обмер укладок хвороста, ведомость перечёта", Page: RubkiUhoda },
  // Фаза 4 плана доработки — постановка задач сотрудникам (work_plan),
  // веб-половина уже существующей мобильной функции (см. app/routers/bot.py).
  zadachi: { title: "Задачи", subtitle: "План работ сотрудникам и рабочий календарь", Page: Zadachi },
  // Ручной ввод табеля (просьба пользователя, 24.09.2026) — пока рядовые
  // рабочие не отмечаются в мобильном приложении сами, лесничий расставляет
  // за них статус, место и вид работы построчно на день. См. app/routers/tabel.py.
  tabel: { title: "Табель", subtitle: "Кто где работал: ввод по дням и отметки рабочих с телефона", Page: Tabel },
  // Перенесено из Settings.jsx (WorkersCard) — тот же /api/auth/workers,
  // полноценный экран вместо блока внутри "Настроек".
  sotrudniki: { title: "Сотрудники", subtitle: "Справочник работников: ФИО, должность, участок", Page: Sotrudniki },
  // Планирование распределения бригад (см. backend/legacy/brigada.py) —
  // сигнал "делянка близка к завершению" (те же % освоения лимита/срок
  // вывозки, что и в "Инспекции") + состав бригад + назначение/
  // перемещение на делянку с диапазоном дат.
  raspredelenie: { title: "Распределение бригад", subtitle: "Делянки, близкие к завершению — куда направить бригаду дальше", Page: poVidu(RaspredelenieBrigad, FrontRabot) },
  // Односторонние ленты "рабочий -> мастер" (мобильное приложение ->
  // веб), см. app/routers/attendance.py и app/routers/notes.py.
  telefon: { title: "С телефона", subtitle: "Отчёты рабочих на проверку, заметки, журнал выполненных работ", Page: Telefon },
  archive: { title: "Архив", subtitle: "Ручной архив документов: сканы приказов, списки делянок", Page: Archive },
  // Удалённые делянки/участки лежат здесь 30 дней (app/korzina.py).
  korzina: { title: "Корзина", subtitle: "Удалённые делянки и участки — можно вернуть в течение 30 дней", Page: Korzina },
  // Режим «Квесты» (03.11.2026): та же работа из «Ждёт меня» в виде квестов
  // с опытом и серией — отдельная вкладка рядом с обычными экранами.
  kvesty: { title: "🎯 Квесты", subtitle: "Дела дня как квесты: опыт, уровень, серия дней, свои галочки", Page: Kvesty },
  reyting: { title: "🏆 Рейтинг", subtitle: "Кто впереди: очки за дни, кубы, задачи и трелёвку; битва звеньев", Page: Reyting },
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
  // Вкладки (дизайн «Вкладки - новый дизайн»): левая панель — activeId,
  // необязательная правая — rightId.
  // Стартовая вкладка — из адреса (#/raskhod?d=5), чтобы F5 и
  // пересланная ссылка открывали тот же экран.
  const [tabState, rawDispatch] = useReducer(tabsReducer, null, () => {
    const screen = readHash().screen ? resolveScreen(readHash().screen).screen : null;
    if (screen && READY_SCREENS[screen] && screen !== "dashboard") {
      return { tabs: ["dashboard", screen], activeId: screen, rightId: null };
    }
    return { tabs: ["dashboard"], activeId: "dashboard", rightId: null };
  });

  // Открытие старого экрана (алиаса) — через openScreen, чтобы выбрать
  // нужную вкладку объединённого экрана.
  const dispatch = React.useCallback((action) => {
    if (action?.type === "open" && ALIASES[action.id]) {
      openScreen(action.id);
      return;
    }
    rawDispatch(action);
  }, []);

  useEffect(() => {
    setScreenOpener((id) => rawDispatch({ type: "open", id }));
    const onPop = () => {
      const screen = applyHash();
      if (screen && READY_SCREENS[screen]) dispatch({ type: "open", id: screen });
    };
    window.addEventListener("popstate", onPop);
    window.addEventListener("hashchange", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("hashchange", onPop);
    };
  }, []);

  useEffect(() => {
    if (tabState.activeId) syncHash(tabState.activeId, { push: readHash().screen !== tabState.activeId });
  }, [tabState.activeId]);

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

  const sidebarUser = { fio: user.fio || user.login, role: ROLE_LABELS[user.role] || user.role };

  return (
    <UserProvider user={user}>
    <ToastProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar
          openKeys={tabState.tabs}
          activeKey={tabState.activeId}
          onNavigate={(id) => dispatch({ type: "open", id })}
          user={sidebarUser}
          onLogout={handleLogout}
          permissions={user.permissions || []}
        />
        <TabWorkspace
          screens={READY_SCREENS}
          tabs={tabState.tabs}
          activeId={tabState.activeId}
          rightId={tabState.rightId}
          dispatch={dispatch}
          currentUser={user}
        />
      </div>
    </ToastProvider>
    </UserProvider>
  );
}
