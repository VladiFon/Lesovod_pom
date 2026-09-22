import React, { useState } from "react";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import { api, ApiError } from "../api/client.js";

/**
 * Login — форма логин/пароль (Блок 1 плана доработки, п.1).
 *
 * Стучится в POST /api/auth/login, кладёт токен в localStorage под ключом
 * `lesovod_token` (api/client.js уже читает его оттуда для всех
 * последующих запросов) и сообщает App.jsx о свежезалогиненном
 * пользователе через onLoggedIn(user) — тот сам решает, что показывать
 * дальше.
 */
export default function Login({ onLoggedIn }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!login.trim() || !password) {
      setError("Введите логин и пароль");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.post("/auth/login", { login: login.trim(), password });
      localStorage.setItem("lesovod_token", res.token);
      onLoggedIn?.(res.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось связаться с сервером");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-surface-alt">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm bg-surface border border-border rounded-lg shadow-card p-8"
      >
        <div className="mb-6 text-center">
          <div className="font-ui font-extrabold text-2xl text-pine leading-tight">Лесовод</div>
          <div className="font-mono text-xs tracking-widest text-muted-2 uppercase mt-1">
            Цифровой помощник
          </div>
        </div>

        <div className="flex flex-col gap-4">
          <TextField
            label="Логин"
            autoFocus
            autoComplete="username"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
          />
          <TextField
            label="Пароль"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error && <p className="text-error text-sm mt-3">{error}</p>}

        <Button type="submit" variant="primary" className="w-full mt-6" loading={loading}>
          Войти
        </Button>

        <p className="text-faint text-xs mt-4 text-center">
          Первый вход после установки: admin / admin — смените пароль в «Настройках».
        </p>
      </form>
    </div>
  );
}
