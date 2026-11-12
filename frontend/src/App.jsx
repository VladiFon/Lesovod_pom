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
import KnigaLvlr from "./pages/KnigaLvlr.jsx";
import ProektyLk from "./pages/ProektyLk.jsx";
import Raskhod from "./pages/Raskhod.jsx";
import SkladyEgais from "./pages/SkladyEgais.jsx";
import Inspection from "./pages/Inspection.jsx";
import RubkiUhoda from "./pages/RubkiUhoda.jsx";
import RaspredelenieBrigad from "./pages/RaspredelenieBrigad.jsx";
import PlanRabot from "./pages/PlanRabot.jsx";
import TabelRuchnoy from "./pages/TabelRuchnoy.jsx";
import Sotrudniki from "./pages/Sotrudniki.jsx";
import Chelovek from "./pages/Chelovek.jsx";
import ZhurnalRabot from "./pages/ZhurnalRabot.jsx";
import Skhema from "./pages/Skhema.jsx";
import Attendance from "./pages/Attendance.jsx";
import WorkerNotes from "./pages/WorkerNotes.jsx";
import OtchetySmeny from "./pages/OtchetySmeny.jsx";
import Toplivo from "./pages/Toplivo.jsx";
import Tehnika from "./pages/Tehnika.jsx";
import Putevye from "./pages/Putevye.jsx";
import Archive from "./pages/Archive.jsx";
import CalendarScreen from "./pages/Calendar.jsx";
import { RawReportsTab, CompletedTab } from "./pages/AiLog.jsx";
import TabelMesyac from "./pages/TabelMesyac.jsx";
import Otchety from "./pages/Otchety.jsx";
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
import Gazeta from "./pages/Gazeta.jsx";
import PutDelyanki from "./pages/PutDelyanki.jsx";
import Geroi from "./pages/Geroi.jsx";
import Chellendzhi from "./pages/Chellendzhi.jsx";
import Pochta from "./pages/Pochta.jsx";
import { UserProvider } from "./auth.jsx";
import { ALIASES, applyHash, openScreen, readHash, resolveScreen, setScreenOpener, syncHash } from "./nav.js";
import { ToastProvider } from "./components/Toast.jsx";
import TableExport from "./components/TableExport.jsx";
import { api } from "./api/client.js";

const TABS_KEY = "lesovod_tabs";

const Padded = (Inner) => function PaddedTab() {
  return <div className="p-[18px] flex flex-col gap-[14px]"><Inner /></div>;
};

// Шаг 4 разбора (03.11.2026): похожие пункты меню слиты в один экран с
// вкладками. Старые ключи (ai_log, worker_notes, attendance, work_plan,
// calendar) — алиасы в nav.js, ссылки на них не ломаются.
// «Входящие» (бывшее «С телефона», шаг 4 разбора 04.11.2026): только то,
// что ждёт проверки. Отчёты за смену и журнал выполненных работ — во
// вкладках «Журнала работ», техника и топливо — свой экран (алиасы в nav.js).
const Telefon = makeMergedScreen("telefon", [
  { key: "otchety", label: "Отчёты на проверку", Page: Padded(RawReportsTab) },
  { key: "zametki", label: "Заметки рабочих", Page: WorkerNotes },
]);
// Игровой вид «Входящих» (03.11.2026): «Почта гонцов» + обычные вкладки.
const TelefonIgra = makeMergedScreen("telefon", [
  { key: "pochta", label: "📬 Почта гонцов", Page: Pochta },
  { key: "otchety", label: "Отчёты на проверку", Page: Padded(RawReportsTab) },
  { key: "zametki", label: "Заметки рабочих", Page: WorkerNotes },
]);
// «Журнал работ»: общая лента + исходные журналы вкладками.
const Raboty = makeMergedScreen("raboty", [
  { key: "lenta", label: "📒 Вся лента", Page: ZhurnalRabot },
  { key: "smena", label: "🚜 Отчёты за смену", Page: OtchetySmeny },
  { key: "zhurnal", label: "✅ Журнал выполненных работ", Page: Padded(CompletedTab) },
]);
const TehnikaToplivo = makeMergedScreen("tehnika", [
  { key: "tehnika", label: "🚜 Техника", Page: Tehnika },
  { key: "toplivo", label: "⛽ Топливо", Page: Toplivo },
  { key: "putevye", label: "📝 Путевые листы", Page: Putevye },
]);
// Шаг 3 разбора сайта (09.11.2026): «Формы и книги» — всё, что сдаётся
// бумагой по лесу. Старые адреса tek_izm / kniga_lvlr — алиасы в nav.js.
const Formy = makeMergedScreen("formy", [
  { key: "tek_izm", label: "📑 Текущие изменения", Page: TekushchieIzmeneniya },
  { key: "kniga", label: "📗 Книга ЛВ и ЛР", Page: KnigaLvlr },
]);
const Tabel = makeMergedScreen("tabel", [
  // Игровой вид (переключатель в шапке/Настройках) — «Перекличка» вместо
  // обычного ввода; обычный ввод никуда не делся.
  { key: "vvod", label: "Ввод табеля", Page: poVidu(TabelRuchnoy, TabelIgra) },
  { key: "mesyac", label: "📅 Месяц", Page: TabelMesyac },
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
  { key: "sklady", label: "Склады и остатки", Page: SkladyEgais },
]);
// Обычный вид: Расход + «Склады и остатки» из ЕГАИС (11.11.2026)
const RaskhodObych = makeMergedScreen("raskhod", [
  { key: "raskhod", label: "Расход", Page: Raskhod },
  { key: "sklady", label: "Склады и остатки", Page: SkladyEgais },
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
  { key: "proekty", label: "📐 Проекты", Page: ProektyLk },
]);
// Обычный вид «Лесокультур»: участки + проекты лесных культур из АРМ ЛВ
// (прил. 5 Положения ЛВ/ЛР, Влад 12.11.2026).
const LesokulturyObych = makeMergedScreen("forestry", [
  { key: "uchastki", label: "Участки", Page: Lesokultury },
  { key: "proekty", label: "📐 Проекты", Page: ProektyLk },
]);
// Игровой вид «Делянок» (03.11.2026): «Путь делянки» + обычный список.
const PlotsIgra = makeMergedScreen("plots", [
  { key: "put", label: "🧭 Путь делянки", Page: PutDelyanki },
  { key: "spisok", label: "Список", Page: Plots },
]);
// Игровой вид «Сотрудников» (03.11.2026): «Карточки героев» + справочник.
const SotrudnikiIgra = makeMergedScreen("sotrudniki", [
  { key: "geroi", label: "🧑‍🌾 Карточки героев", Page: Geroi },
  { key: "kartochka", label: "👤 Люди", Page: Chelovek },
  { key: "spisok", label: "Справочник", Page: Sotrudniki },
]);
// Карточка человека (04.11.2026, «сайт разбросан»): всё о человеке в одном
// месте — первая вкладка «Сотрудников»; справочник (правка, PIN) — вторая.
const SotrudnikiObych = makeMergedScreen("sotrudniki", [
  { key: "kartochka", label: "👤 Люди", Page: Chelovek },
  { key: "spisok", label: "Справочник", Page: Sotrudniki },
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
  dashboard: { title: "Сегодня", subtitle: "Дела на сегодня, как идёт заготовка и когда закончим делянки", Page: poVidu(Dashboard, DashboardIgra), search: true, primaryAction: true },
  // Плоты сами управляют своим тулбаром (поиск, "Показывать архивные",
  // "Импорт МДО" в левой колонке) — по аналогии с Settings/Dashboard,
  // TopBar здесь без search/primaryAction, чтобы не дублировать поиск.
  otchety: { title: "Отчёты", subtitle: "Сводка месяца для начальства и все выгрузки сайта в одном месте", Page: Otchety },
  plots: { title: "Делянки", subtitle: "Карточки делянок, документы, импорт из МДО", Page: poVidu(Plots, PlotsIgra) },
  // Этап 5 (часть 2): сквозной список документов по всем делянкам, с
  // фильтрами и массовыми действиями — см. pages/Documents.jsx.
  documents: { title: "Документы", subtitle: "Все документы по всем делянкам: фильтры, массовые действия", Page: Documents },
  // "Живая карта" (LiveMap.jsx, react-leaflet + импорт слоя из QGIS) убрана
  // из меню по решению пользователя — карты ведутся в самом QGIS, экран не
  // нужен. Backend (app/routers/map.py) не трогали, файл страницы удалён.
  taxation: { title: "Выдел", subtitle: "Таксация выдела и его жизнь: делянки, культуры, рубки ухода, кто работал", Page: Taxation },
  forestry: { title: "Лесокультуры", subtitle: "Проекты лесных культур, участки и журнал мероприятий по уходу", Page: poVidu(LesokulturyObych, LesokulturyIgra) },
  // Ведомости текущих изменений по приказу Минлесхоза №130 (Word по шаблону).
  // Книга учёта площадей ЛВ и ЛР (прил. 6 Положения, Влад 09.11.2026).
  formy: { title: "Формы и книги", subtitle: "Текущие изменения (прил. 1–15 для Белгослеса) и Книга учёта площадей ЛВ и ЛР", Page: Formy },
  raskhod: { title: "Расход / ЕГАИС", subtitle: "Баланс лимитов и факта по выделам, наряды-задания", Page: poVidu(RaskhodObych, RaskhodIgra) },
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
  sotrudniki: { title: "Люди", subtitle: "Карточка человека: табель, работы, задачи, техника — и справочник", Page: poVidu(SotrudnikiObych, SotrudnikiIgra) },
  // Планирование распределения бригад (см. backend/legacy/brigada.py) —
  // сигнал "делянка близка к завершению" (те же % освоения лимита/срок
  // вывозки, что и в "Инспекции") + состав бригад + назначение/
  // перемещение на делянку с диапазоном дат.
  raspredelenie: { title: "Бригады", subtitle: "Делянки, близкие к завершению — куда направить бригаду дальше", Page: poVidu(RaspredelenieBrigad, FrontRabot) },
  // Односторонние ленты "рабочий -> мастер" (мобильное приложение ->
  // веб), см. app/routers/attendance.py и app/routers/notes.py.
  telefon: { title: "Входящие", subtitle: "Ждёт проверки: отчёты рабочих с телефона и их заметки", Page: poVidu(Telefon, TelefonIgra) },
  // Шаг 3 разбора «сайт разбросан» (04.11.2026): единый журнал работ и
  // живая схема «как работает сайт» (что от чего зависит, что висит).
  raboty: { title: "Журнал работ", subtitle: "Всё, что сделано: смены с телефона, культуры, рубки ухода, табель — одной лентой", Page: Raboty },
  tehnika: { title: "Техника и топливо", subtitle: "Машины, закрепление за людьми, заправки, расход топлива и путевые листы", Page: TehnikaToplivo },
  skhema: { title: "Как работает сайт", subtitle: "Схема: откуда что берётся, кто что делает и что висит прямо сейчас", Page: Skhema },
  archive: { title: "Архив", subtitle: "Ручной архив документов: сканы приказов, списки делянок", Page: Archive },
  // Удалённые делянки/участки лежат здесь 30 дней (app/korzina.py).
  korzina: { title: "Корзина", subtitle: "Удалённые делянки и участки — можно вернуть в течение 30 дней", Page: Korzina },
  // Режим «Квесты» (03.11.2026): та же работа из «Ждёт меня» в виде квестов
  // с опытом и серией — отдельная вкладка рядом с обычными экранами.
  kvesty: { title: "🎯 Квесты", subtitle: "Дела дня как квесты: опыт, уровень, серия дней, свои галочки", Page: Kvesty },
  gazeta: { title: "📰 Лесная правда", subtitle: "Газета недели: кто герой, сколько нарубили и вывезли, кого разыскивают", Page: Gazeta },
  chellendzhi: { title: "🔥 Челленджи", subtitle: "Общие цели на всю команду: одна шкала, в конце звание", Page: Chellendzhi },
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
  // Разбор 09.11.2026: набор вкладок и вторая панель запоминаются в
  // браузере — после F5 / перезапуска рабочий стол такой же, как был.
  const [tabState, rawDispatch] = useReducer(tabsReducer, null, () => {
    const screen = readHash().screen ? resolveScreen(readHash().screen, readHash().params).screen : null;
    let saved = null;
    try {
      const raw = JSON.parse(localStorage.getItem(TABS_KEY) || "null");
      // старые ключи (tek_izm → formy и т.п.) — на новые, без повторов
      const tabs = Array.isArray(raw?.tabs)
        ? [...new Set(raw.tabs.map((t) => ALIASES[t]?.screen || t))].filter((t) => READY_SCREENS[t])
        : [];
      if (tabs.length) {
        const rightId = tabs.includes(raw.rightId) ? raw.rightId : null;
        saved = { tabs, activeId: tabs.includes(raw.activeId) && raw.activeId !== rightId ? raw.activeId : tabs[0], rightId };
      }
    } catch { /* хранилище недоступно — начнём с дашборда */ }
    if (saved) {
      if (screen && READY_SCREENS[screen] && screen !== saved.rightId) {
        const tabs = saved.tabs.includes(screen) ? saved.tabs : [...saved.tabs, screen];
        return { ...saved, tabs, activeId: screen };
      }
      return saved;
    }
    if (screen && READY_SCREENS[screen] && screen !== "dashboard") {
      return { tabs: ["dashboard", screen], activeId: screen, rightId: null };
    }
    return { tabs: ["dashboard"], activeId: "dashboard", rightId: null };
  });
  useEffect(() => {
    try { localStorage.setItem(TABS_KEY, JSON.stringify(tabState)); } catch { /* приватный режим */ }
  }, [tabState]);

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
      <TableExport />
    </ToastProvider>
    </UserProvider>
  );
}
