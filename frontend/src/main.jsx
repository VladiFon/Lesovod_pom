import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

import { zagruzitIzdanie } from "./izdanie.js";

// Сначала узнаём издание сервера (лесничество / лесопункт) — от него
// зависит меню. Без ответа сервера рисуем как у лесничества.
zagruzitIzdanie().finally(() => {
  ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
});
