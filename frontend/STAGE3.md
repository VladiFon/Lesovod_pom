# Этап 3. Дизайн-система для веб-интерфейса

## Важное отличие от плана

В плане Этап 3 рассчитан на приложенные `design-tokens.css` и
`dashboard_mockup.html` — в этой сессии их не было. Вместо того чтобы
выдумывать новую палитру, токены взяты **из уже утверждённого дизайна
десктоп-приложения**: `lesovod_project/styles.py` (тема «Cyber Forester»,
изначально пришла из Google Stitch-макета — так и написано в шапке
файла). Так веб-версия продолжает тот же визуальный язык, а не
становится «третьим дизайном» в проекте.

Если у вас есть более новый `design-tokens.css`/мокап — пришлите
отдельно, нужно будет свести палитру с этой веткой (сейчас источник
истины — `src/design-tokens.css`, туда же смотрит `tailwind.config.js`).

## Что сделано

1. **`tailwind.config.js`** — палитра, шрифты и радиусы Tailwind
   полностью заменены на токены из `src/design-tokens.css` (никакого
   `bg-blue-500` по умолчанию не осталось — только `bg-pine`, `bg-paper`
   и т.п.).
2. **Шрифты** — Manrope (интерфейс) + JetBrains Mono (ID/координаты/
   капслок-подписи), те же, что в `styles.py`. Подключены через Google
   Fonts (`index.html`) — локальных `.woff2` в проект не было, если на
   серверном ПК не будет интернета, нужно будет заменить на
   `@font-face` в `src/index.css`.
3. **Компоненты** (`src/components/`): `Sidebar`, `TopBar`, `Card`,
   `StatCard`, `DataTable` (с чекбоксами/сортировкой/выделением строк),
   `StatusBadge` (готово/в процессе/ошибка/архив), `Button`
   (primary/secondary/danger/ghost), `EmptyState`, `Modal`, `Toast`
   (+`ToastProvider`/`useToast`). Все работают на props/моковых данных.
4. **Эталонный экран** — `src/pages/Dashboard.jsx`: 4 карточки-метрики,
   таблица активных делянок, лента ИИ-инсайтов, карточка погоды — по
   структуре повторяет `screens/dashboard/screen.py`, но собран из новых
   компонентов и на моковых данных.
5. **Витрина компонентов** — `src/pages/ComponentGallery.jsx` (пункт
   «⚙ Витрина компонентов» в сайдбаре) — все варианты Button/StatusBadge/
   Modal/Toast/EmptyState в одном месте, для быстрой приёмки перед
   Этапом 4. Уберите этот пункт меню, когда дизайн утверждён.

## Структура `/frontend/src/components`

```
src/
├── design-tokens.css      # источник истины: цвета/шрифты/радиусы как CSS-переменные
├── index.css               # @tailwind + подключение токенов + базовые стили
├── main.jsx
├── App.jsx                  # сборка Sidebar + TopBar + текущая страница
├── components/
│   ├── Sidebar.jsx          # ↔ QFrame#SideMenu / NavButton / UserAvatar
│   ├── TopBar.jsx            # ↔ QFrame#TopBar / SearchInput / TopBarIconButton
│   ├── Card.jsx               # ↔ QFrame#DossierCard / MetricCard / SearchPanel
│   ├── StatCard.jsx            # ↔ MetricCard + CardIcon/CardValue/CardTitle
│   ├── DataTable.jsx            # ↔ QTableWidget#AILogTable/#ReportsTable
│   ├── StatusBadge.jsx           # готов/в процессе/ошибка/архив
│   ├── Button.jsx                  # primary/secondary/danger/ghost
│   ├── EmptyState.jsx               # пустые списки
│   ├── Modal.jsx                     # ↔ QDialog#StyledInputDialog
│   └── Toast.jsx                      # уведомления о фоновых задачах (Этап 5)
└── pages/
    ├── Dashboard.jsx           # эталонный экран (моковые данные)
    └── ComponentGallery.jsx    # витрина всех компонентов
```

## Как посмотреть

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

`npm run build` уже проверен — собирается без ошибок (43 модуля, ~166 кБ
JS, ~16 кБ CSS до gzip).

## Дальше

- **Этап 4**: переписывать экраны по одному, начиная с «Настройки», как
  в плане — каждый экран использует эти же компоненты и реальные
  эндпоинты backend (Этап 1/2) через `src/api/client.js` (создать в
  начале Этапа 4).
- Когда дизайн утверждён — убрать временный пункт «Витрина компонентов»
  из `Sidebar.jsx` (помечен комментарием «Этап 3, временный пункт»).
- Если появятся собственные `.woff2` Manrope/JetBrains Mono — заменить
  `<link>` в `index.html` на `@font-face` в `src/index.css`.
