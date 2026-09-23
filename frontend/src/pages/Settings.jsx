import React, { useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import Modal from "../components/Modal.jsx";
import DataTable from "../components/DataTable.jsx";
import { useToast } from "../components/Toast.jsx";
import { api, ApiError } from "../api/client.js";

/**
 * Settings — экран "Настройки" (Этап 4, первый переписанный экран).
 *
 * Референс функциональности: screens/settings/screen_ui.py +
 * screen_actions.py. Backend: app/routers/settings.py (Этап 1/2, уже
 * существует в приложенном lesovod_backend_stage2.zip).
 *
 * ─── Перенесено 1:1 ──────────────────────────────────────────────────
 *  • Ключ OpenRouter API — GET/POST/DELETE /api/settings/secrets/openrouter
 *    (маскированный статус, ввод/сохранение/удаление; ключ никогда не
 *    приходит с сервера в открытом виде — то же ограничение, что и в
 *    desktop-версии, secrets_store.mask_api_key).
 *  • Токен Telegram-бота — то же самое, .../secrets/telegram.
 *  • Данные лесничего (ФИО/должность/лесничество) — GET/POST
 *    /api/settings/lesnichiy, список лесничеств для подсказки —
 *    GET /api/settings/lesnichestva (editable combo → <input list>).
 *
 * ─── Перенесено 1:1 (продолжение) ────────────────────────────────────
 *  • «Проверить ключ» / «Проверить токен» (Блок 5 доработки, п.1.1) —
 *    POST /api/settings/secrets/{name}/test. Секрет не отправляется из
 *    браузера на сторонний сервис напрямую — backend сам делает лёгкий
 *    запрос (OpenRouter GET /key, Telegram GET /getMe — см.
 *    legacy/key_test.py) и возвращает {ok, message}. Если в поле есть
 *    ещё не сохранённое значение — проверяется оно; иначе проверяется
 *    то, что уже сохранено на сервере.
 *
 * ─── Сознательно упрощено / не перенесено (и почему) ─────────────────
 *  1. «Общая база лесничества» (сетевая папка с lesovod.db) — по смыслу
 *     миграции backend САМ становится этой общей точкой (см. план,
 *     раздел "Целевое состояние"), поэтому настройка теряет смысл:
 *     все браузеры и так ходят на один сервер. Экран убран целиком.
 *  2. Автозапуск при включении ПК / сворачивание в трей — это свойства
 *     desktop-процесса конкретного компьютера, а не веб-клиента,
 *     открытого в браузере. Аналог этой задачи — автозапуск САМОГО
 *     backend'а как службы Windows — переезжает в Этап 8 (там уже есть
 *     пункт про nssm/автозапуск), а не в этот экран.
 *  3. Путь к LibreOffice (soffice.exe) — конвертация МДО теперь всегда
 *     идёт на сервере: ОДНА серверная настройка на всех, а не десктопная
 *     "у каждого свой soffice.exe" (Блок 5 доработки: GET/POST/DELETE
 *     /api/settings/libreoffice-path + POST .../test, по образцу секретов
 *     выше — карточка LibreOfficeCard ниже).
 *  4. QR-код подключения мобильного приложения — раньше QR вёл на
 *     builtin HTTP-сервер desktop-приложения (MobileServerWorker).
 *     Теперь мобильные устройства заходят в ТОТ ЖЕ браузерный адрес,
 *     что и десктопы (см. план, "Целевое состояние") — поэтому карточка
 *     переосмыслена: показывает текущий адрес сервера
 *     (window.location.origin, работает без похода на backend, т.к.
 *     если страница открылась — адрес уже правильный) и QR на него же,
 *     для быстрого открытия на телефоне.
 */

const SECRET_FIELDS = [
  {
    name: "openrouter",
    title: "ИИ-ассистент (OpenRouter API)",
    hint: "Распознавание фото ведомости перечёта («Рубки ухода») и сканов документов в «Архиве». Получить ключ: openrouter.ai → Sign in → Keys → Create Key.",
    placeholder: "Вставьте ключ сюда (из openrouter.ai/keys)…",
  },
  {
    name: "telegram",
    title: "Telegram-бот",
    hint: "Токен бота, который принимает отчёты о работах от рабочих в Telegram. Получить токен: @BotFather → /newbot (или /token для существующего бота).",
    placeholder: "Вставьте токен сюда (из @BotFather)…",
  },
];

function SecretCard({ field, status, onSave, onClear, onTest, savingName, testingName, testResult }) {
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const isSaving = savingName === field.name;
  const isTesting = testingName === field.name;
  const hasSaved = Boolean(status);

  return (
    <Card title={field.title}>
      <p className="text-muted text-base mb-3">{field.hint}</p>

      {hasSaved && (
        <div className="flex items-center gap-2 mb-3 text-sm">
          <span className="font-mono text-ink bg-surface-alt px-2 py-1 rounded-sm">{status}</span>
          <span className="text-faint">— сохранён на сервере</span>
        </div>
      )}

      {testResult && (
        <p className={`text-sm mb-3 ${testResult.ok ? "text-pine" : "text-error"}`}>
          {testResult.ok ? "" : ""}
          {testResult.message}
        </p>
      )}

      <div className="flex items-center gap-2">
        <TextField
          className="flex-1"
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={hasSaved ? "Введите новое значение, чтобы заменить…" : field.placeholder}
          suffix={
            <button
              type="button"
              onClick={() => setVisible((v) => !v)}
              className="h-8 w-8 flex items-center justify-center text-faint hover:text-pine"
              aria-label={visible ? "Скрыть значение" : "Показать значение"}
            >
              {visible ? "🙈" : "👁"}
            </button>
          }
        />
        <Button
          variant="ghost"
          loading={isTesting}
          disabled={!value.trim() && !hasSaved}
          title={
            value.trim()
              ? "Проверить введённое значение (без сохранения)"
              : "Проверить сохранённое на сервере значение"
          }
          onClick={() => onTest(field.name, value.trim() || undefined)}
        >
          ⚡ Проверить
        </Button>
      </div>

      <div className="flex items-center gap-3 mt-3">
        <Button
          variant="primary"
          size="sm"
          loading={isSaving}
          disabled={!value.trim()}
          onClick={() => onSave(field.name, value).then(() => setValue(""))}
        >
          Сохранить
        </Button>
        {hasSaved && (
          <Button variant="danger" size="sm" onClick={() => onClear(field.name)}>
            Удалить сохранённое значение
          </Button>
        )}
      </div>
    </Card>
  );
}

function LibreOfficeCard({ status, onSave, onReset, onTest, saving, testing, testResult }) {
  const [path, setPath] = useState("");

  const effective = status?.effective_path;
  const isManual = Boolean(status?.is_manual);

  return (
    <Card title="LibreOffice (конвертация МДО)">
      <p className="text-muted text-base mb-3">
        Путь к soffice.exe/soffice — нужен для конвертации ведомости МДО (.rtf) при импорте делянок.
        Одна настройка на сервер, общая для всех, кто заходит в веб-версию.
      </p>

      <div className="flex items-center gap-2 mb-3 text-sm">
        {effective ? (
          <>
            <span className="font-mono text-ink bg-surface-alt px-2 py-1 rounded-sm break-all">{effective}</span>
            <span className="text-faint">{isManual ? "— задан вручную" : "— найден автоматически"}</span>
          </>
        ) : (
          <span className="text-error">LibreOffice не найден автоматически — укажите путь вручную ниже.</span>
        )}
      </div>

      {testResult && (
        <p className={`text-sm mb-3 ${testResult.ok ? "text-pine" : "text-error"}`}>
          {testResult.ok ? "" : ""}
          {testResult.message}
        </p>
      )}

      <div className="flex items-center gap-2">
        <TextField
          className="flex-1"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder={isManual ? "Введите новый путь, чтобы заменить…" : "Например: C:\\Program Files\\LibreOffice\\program\\soffice.exe"}
        />
        <Button variant="ghost" loading={testing} onClick={() => onTest(path.trim() || undefined)}>
          ⚡ Проверить
        </Button>
      </div>

      <div className="flex items-center gap-3 mt-3">
        <Button
          variant="primary"
          size="sm"
          loading={saving}
          disabled={!path.trim()}
          onClick={() => onSave(path.trim()).then(() => setPath(""))}
        >
          Сохранить и проверить
        </Button>
        {isManual && (
          <Button variant="danger" size="sm" onClick={onReset}>
            Сбросить на автопоиск
          </Button>
        )}
      </div>
    </Card>
  );
}

function MobileCard() {
  const [qrOpen, setQrOpen] = useState(false);
  const [qrDataUrl, setQrDataUrl] = useState(null);
  const origin = window.location.origin;

  useEffect(() => {
    if (!qrOpen) return;
    QRCode.toDataURL(origin, { margin: 1, width: 240, color: { dark: "#1a4331", light: "#ffffff" } })
      .then(setQrDataUrl)
      .catch(() => setQrDataUrl(null));
  }, [qrOpen, origin]);

  const copyAddress = async () => {
    try {
      await navigator.clipboard.writeText(origin);
    } catch {
      /* clipboard недоступен (например, не https) — молча игнорируем, адрес и так виден на экране */
    }
  };

  return (
    <Card title="Подключение с телефона / другого компьютера">
      <p className="text-muted text-base mb-3">
        Веб-версия открывается по этому же адресу с любого устройства в локальной сети — отдельное
        мобильное приложение и сопряжение больше не нужны.
      </p>
      <div className="flex items-center gap-2">
        <code className="flex-1 bg-surface-alt px-3.5 py-2.5 rounded-md text-ink font-mono text-sm truncate">
          {origin}
        </code>
        <Button variant="secondary" size="sm" onClick={copyAddress}>
          Копировать
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setQrOpen(true)}>
          Показать QR-код
        </Button>
      </div>

      <Modal open={qrOpen} onClose={() => setQrOpen(false)} title="Откройте камеру телефона на этот код">
        <div className="flex flex-col items-center gap-3">
          {qrDataUrl ? (
            <img src={qrDataUrl} alt={`QR-код на ${origin}`} className="rounded-md border border-border" />
          ) : (
            <div className="h-60 w-60 rounded-md bg-surface-alt animate-pulse" />
          )}
          <p className="text-muted text-sm text-center">{origin}</p>
        </div>
      </Modal>
    </Card>
  );
}

const ROLE_OPTIONS = [
  { value: "admin", label: "Администратор" },
  { value: "lesovod", label: "Лесовод" },
  { value: "viewer", label: "Наблюдатель" },
];

/**
 * UsersCard — Блок 1 плана доработки, п.6: форма смены пароля (в первую
 * очередь для admin/admin, который ensure_bootstrap_admin() создаёт при
 * первом запуске) + заодно управление ролями/активностью — раз уж
 * инфраструктура (GET/POST /api/auth/users, PATCH .../role|active) уже
 * готова и протестирована (Этап 2), но до сих пор не имела интерфейса.
 * Показывается только пользователю с ролью admin (users.manage) —
 * остальным backend всё равно ответит 403 на каждый из этих запросов.
 */
function UsersCard() {
  const toast = useToast();
  const [users, setUsers] = useState(null);
  const [loadError, setLoadError] = useState(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ login: "", password: "", fio: "", role: "viewer" });
  const [creating, setCreating] = useState(false);

  const [passwordTarget, setPasswordTarget] = useState(null); // { id, login } | null
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  const loadUsers = () =>
    api
      .get("/auth/users")
      .then(setUsers)
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "Не удалось загрузить список пользователей"));

  useEffect(() => {
    loadUsers();
  }, []);

  const handleCreate = async () => {
    if (!createForm.login.trim() || !createForm.password) {
      toast.show({ tone: "warning", title: "Заполните логин и пароль" });
      return;
    }
    setCreating(true);
    try {
      await api.post("/auth/users", createForm);
      toast.show({ tone: "success", title: "Пользователь создан" });
      setCreateOpen(false);
      setCreateForm({ login: "", password: "", fio: "", role: "viewer" });
      loadUsers();
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось создать пользователя",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    } finally {
      setCreating(false);
    }
  };

  const handleSetRole = async (userId, role) => {
    try {
      await api.patch(`/auth/users/${userId}/role`, { role });
      loadUsers();
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось изменить роль",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    }
  };

  const handleSetActive = async (userId, isActive) => {
    try {
      await api.patch(`/auth/users/${userId}/active`, { is_active: isActive });
      loadUsers();
      toast.show({ tone: "info", title: isActive ? "Учётная запись включена" : "Учётная запись отключена" });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось изменить статус",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    }
  };

  const handleSavePassword = async () => {
    if (!passwordTarget || newPassword.length < 4) {
      toast.show({ tone: "warning", title: "Пароль слишком короткий", description: "Минимум 4 символа." });
      return;
    }
    setSavingPassword(true);
    try {
      await api.patch(`/auth/users/${passwordTarget.id}/password`, { password: newPassword });
      toast.show({ tone: "success", title: `Пароль для «${passwordTarget.login}» обновлён` });
      setPasswordTarget(null);
      setNewPassword("");
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось сменить пароль",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    } finally {
      setSavingPassword(false);
    }
  };

  const columns = [
    { key: "login", header: "Логин", sortable: true },
    { key: "fio", header: "ФИО", render: (u) => u.fio || "—" },
    {
      key: "role",
      header: "Роль",
      render: (u) => (
        <select
          value={u.role}
          onChange={(e) => handleSetRole(u.id, e.target.value)}
          className="bg-surface border border-border focus:border-pine rounded-md px-2 py-1.5 text-sm text-ink outline-none"
        >
          {ROLE_OPTIONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: "is_active",
      header: "Статус",
      render: (u) => (
        <button
          onClick={() => handleSetActive(u.id, !u.is_active)}
          className={[
            "text-xs font-semibold rounded-full px-2.5 py-1 border",
            u.is_active
              ? "border-pine text-pine bg-mint-soft hover:bg-mint"
              : "border-error text-error bg-error-soft hover:bg-error-soft/70",
          ].join(" ")}
        >
          {u.is_active ? "Активен" : "Отключён"}
        </button>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (u) => (
        <Button variant="ghost" size="sm" onClick={() => setPasswordTarget({ id: u.id, login: u.login })}>
          Сменить пароль
        </Button>
      ),
    },
  ];

  return (
    <Card
      title="Пользователи"
      actions={
        <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)}>
          + Новый пользователь
        </Button>
      }
    >
      <p className="text-muted text-base mb-4">
        Роли: администратор (полный доступ, включая эту страницу), лесовод (делянки/документы),
        наблюдатель (только просмотр). Сразу после установки смените пароль встроенной учётной
        записи <code className="font-mono text-sm bg-surface-alt px-1.5 py-0.5 rounded-sm">admin</code>.
      </p>

      {loadError && <p className="text-error text-base mb-3">{loadError}</p>}

      <DataTable
        columns={columns}
        rows={users ?? []}
        loading={users === null}
        emptyTitle="Пользователей пока нет"
        emptyDescription="Создайте первую учётную запись кнопкой выше."
      />

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Новый пользователь">
        <div className="flex flex-col gap-4">
          <TextField
            label="Логин"
            value={createForm.login}
            onChange={(e) => setCreateForm((s) => ({ ...s, login: e.target.value }))}
          />
          <TextField
            label="Пароль"
            type="password"
            value={createForm.password}
            onChange={(e) => setCreateForm((s) => ({ ...s, password: e.target.value }))}
          />
          <TextField
            label="ФИО"
            value={createForm.fio}
            onChange={(e) => setCreateForm((s) => ({ ...s, fio: e.target.value }))}
          />
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">
              Роль
            </label>
            <select
              value={createForm.role}
              onChange={(e) => setCreateForm((s) => ({ ...s, role: e.target.value }))}
              className="w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none"
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 mt-6">
          <Button variant="secondary" onClick={() => setCreateOpen(false)}>
            Отмена
          </Button>
          <Button variant="primary" loading={creating} onClick={handleCreate}>
            Создать
          </Button>
        </div>
      </Modal>

      <Modal
        open={Boolean(passwordTarget)}
        onClose={() => setPasswordTarget(null)}
        title={`Новый пароль для «${passwordTarget?.login ?? ""}»`}
      >
        <TextField
          label="Пароль"
          type="password"
          autoFocus
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          hint="Минимум 4 символа. Все текущие сессии этого пользователя будут завершены."
        />
        <div className="flex items-center justify-end gap-2 mt-6">
          <Button variant="secondary" onClick={() => setPasswordTarget(null)}>
            Отмена
          </Button>
          <Button variant="primary" loading={savingPassword} onClick={handleSavePassword}>
            Сохранить
          </Button>
        </div>
      </Modal>
    </Card>
  );
}

// WorkersCard (создание/список/вкл-выкл сотрудников) перенесён отсюда в
// отдельный полноценный экран — frontend/src/pages/Sotrudniki.jsx (тот же
// /api/auth/workers), по решению пользователя не дублировать UI в двух
// местах.

export default function Settings({ currentUser }) {
  const toast = useToast();

  const [secrets, setSecrets] = useState(null);
  const [savingSecret, setSavingSecret] = useState(null);
  const [testingSecret, setTestingSecret] = useState(null);
  const [secretTestResults, setSecretTestResults] = useState({});

  const [libreoffice, setLibreoffice] = useState(null);
  const [savingLibreoffice, setSavingLibreoffice] = useState(false);
  const [testingLibreoffice, setTestingLibreoffice] = useState(false);
  const [libreofficeTestResult, setLibreofficeTestResult] = useState(null);

  const [lesnichiy, setLesnichiy] = useState({ fio: "", dolzhnost: "", lesnichestvo: "" });
  const [lesnichestva, setLesnichestva] = useState([]);
  const [loadingLesnichiy, setLoadingLesnichiy] = useState(true);
  const [savingLesnichiy, setSavingLesnichiy] = useState(false);

  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [secretsRes, libreofficeRes, lesnichiyRes, lesnichestvaRes] = await Promise.all([
          api.get("/settings/secrets"),
          api.get("/settings/libreoffice-path"),
          api.get("/settings/lesnichiy"),
          api.get("/settings/lesnichestva"),
        ]);
        if (cancelled) return;
        setSecrets(secretsRes);
        setLibreoffice(libreofficeRes);
        if (lesnichiyRes) setLesnichiy({ fio: "", dolzhnost: "", lesnichestvo: "", ...lesnichiyRes });
        setLesnichestva(lesnichestvaRes ?? []);
      } catch (err) {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : "Не удалось загрузить настройки");
      } finally {
        if (!cancelled) setLoadingLesnichiy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const secretStatus = useMemo(
    () => ({
      openrouter: secrets?.openrouter_api_key ?? null,
      telegram: secrets?.telegram_bot_token ?? null,
    }),
    [secrets]
  );

  const handleSaveSecret = async (name, value) => {
    setSavingSecret(name);
    setSecretTestResults((s) => ({ ...s, [name]: null }));
    try {
      await api.post(`/settings/secrets/${name}`, { value });
      const fresh = await api.get("/settings/secrets");
      setSecrets(fresh);
      toast.show({ tone: "success", title: "Сохранено", description: "Значение записано на сервере." });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось сохранить",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
      throw err;
    } finally {
      setSavingSecret(null);
    }
  };

  const handleClearSecret = async (name) => {
    try {
      await api.delete(`/settings/secrets/${name}`);
      const fresh = await api.get("/settings/secrets");
      setSecrets(fresh);
      setSecretTestResults((s) => ({ ...s, [name]: null }));
      toast.show({ tone: "info", title: "Значение удалено" });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось удалить",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    }
  };

  const handleTestSecret = async (name, value) => {
    setTestingSecret(name);
    setSecretTestResults((s) => ({ ...s, [name]: null }));
    try {
      const result = await api.post(`/settings/secrets/${name}/test`, value ? { value } : undefined);
      setSecretTestResults((s) => ({ ...s, [name]: { ok: result.ok, message: result.message } }));
    } catch (err) {
      setSecretTestResults((s) => ({
        ...s,
        [name]: { ok: false, message: err instanceof ApiError ? err.message : "Неизвестная ошибка" },
      }));
    } finally {
      setTestingSecret(null);
    }
  };

  const handleSaveLibreoffice = async (path) => {
    setSavingLibreoffice(true);
    setLibreofficeTestResult(null);
    try {
      const result = await api.post("/settings/libreoffice-path", { path });
      setLibreofficeTestResult({ ok: result.ok, message: result.message });
      const fresh = await api.get("/settings/libreoffice-path");
      setLibreoffice(fresh);
      if (result.ok) {
        toast.show({ tone: "success", title: "Путь сохранён", description: "LibreOffice найден и отвечает." });
      } else {
        toast.show({ tone: "warning", title: "Путь сохранён, но проверка не прошла", description: result.message });
      }
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось сохранить путь",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
      throw err;
    } finally {
      setSavingLibreoffice(false);
    }
  };

  const handleResetLibreoffice = async () => {
    try {
      await api.delete("/settings/libreoffice-path");
      const fresh = await api.get("/settings/libreoffice-path");
      setLibreoffice(fresh);
      setLibreofficeTestResult(null);
      toast.show({ tone: "info", title: "Сброшено на автопоиск" });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось сбросить",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    }
  };

  const handleTestLibreoffice = async (path) => {
    setTestingLibreoffice(true);
    try {
      const result = await api.post("/settings/libreoffice-path/test", path ? { path } : undefined);
      setLibreofficeTestResult({ ok: result.ok, message: result.message });
    } catch (err) {
      setLibreofficeTestResult({
        ok: false,
        message: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    } finally {
      setTestingLibreoffice(false);
    }
  };

  const handleSaveLesnichiy = async () => {
    if (!lesnichiy.fio.trim()) {
      toast.show({ tone: "warning", title: "ФИО обязательно", description: "Поле «ФИО лесничего» не может быть пустым." });
      return;
    }
    setSavingLesnichiy(true);
    try {
      await api.post("/settings/lesnichiy", lesnichiy);
      toast.show({ tone: "success", title: "Данные лесничего сохранены" });
    } catch (err) {
      toast.show({
        tone: "danger",
        title: "Не удалось сохранить",
        description: err instanceof ApiError ? err.message : "Неизвестная ошибка",
      });
    } finally {
      setSavingLesnichiy(false);
    }
  };

  return (
    <div className="p-[18px] max-w-3xl flex flex-col gap-6">
      <div>
        <h2 className="font-ui font-extrabold text-pine text-[16px]">Настройки</h2>
        <p className="text-muted text-base mt-1">
          Ключи доступа к ИИ и данные лесничего, которые сервер сам подставляет в документы и
          распознавание фото — общие для всех, кто заходит в веб-версию.
        </p>
      </div>

      {loadError && (
        <Card className="border-error/40">
          <p className="text-error text-base">{loadError}</p>
        </Card>
      )}

      {SECRET_FIELDS.map((field) => (
        <SecretCard
          key={field.name}
          field={field}
          status={secretStatus[field.name]}
          savingName={savingSecret}
          testingName={testingSecret}
          testResult={secretTestResults[field.name]}
          onSave={handleSaveSecret}
          onClear={handleClearSecret}
          onTest={handleTestSecret}
        />
      ))}

      <LibreOfficeCard
        status={libreoffice}
        saving={savingLibreoffice}
        testing={testingLibreoffice}
        testResult={libreofficeTestResult}
        onSave={handleSaveLibreoffice}
        onReset={handleResetLibreoffice}
        onTest={handleTestLibreoffice}
      />

      <Card title="Данные лесничего">
        <p className="text-muted text-base mb-4">
          Используются для автозаполнения актов, ведомостей и техкарт.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <TextField
            label="ФИО лесничего"
            placeholder="Иванов Иван Иванович"
            value={lesnichiy.fio}
            disabled={loadingLesnichiy}
            onChange={(e) => setLesnichiy((s) => ({ ...s, fio: e.target.value }))}
          />
          <TextField
            label="Должность"
            placeholder="Главный лесничий"
            value={lesnichiy.dolzhnost}
            disabled={loadingLesnichiy}
            onChange={(e) => setLesnichiy((s) => ({ ...s, dolzhnost: e.target.value }))}
          />
          <div className="sm:col-span-2">
            <TextField
              label="Лесничество по умолчанию"
              placeholder={lesnichestva.length ? "Выберите или введите вручную" : "Справочник недоступен — введите вручную"}
              value={lesnichiy.lesnichestvo}
              disabled={loadingLesnichiy}
              list="lesnichestva-list"
              onChange={(e) => setLesnichiy((s) => ({ ...s, lesnichestvo: e.target.value }))}
            />
            <datalist id="lesnichestva-list">
              {lesnichestva.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </div>
        </div>
        <Button variant="primary" className="mt-4" loading={savingLesnichiy} onClick={handleSaveLesnichiy}>
          💾 Сохранить данные лесничего
        </Button>
      </Card>

      <MobileCard />

      {currentUser?.role === "admin" && <UsersCard />}
    </div>
  );
}
