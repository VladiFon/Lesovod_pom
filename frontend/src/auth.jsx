import React, { createContext, useContext } from "react";

// Текущий пользователь сайта и его права (список действий из
// webext.PERMISSIONS, который отдаёт /api/auth/me). По нему экраны прячут
// кнопки, недоступные роли, — сервер всё равно проверяет права сам, это
// только чтобы лесничий/наблюдатель не видели «опасных» кнопок вовсе.
const UserContext = createContext(null);

export function UserProvider({ user, children }) {
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}

export function useUser() {
  return useContext(UserContext);
}

export function useCan() {
  const user = useContext(UserContext);
  const perms = new Set(user?.permissions || []);
  return (action) => perms.has(action);
}
