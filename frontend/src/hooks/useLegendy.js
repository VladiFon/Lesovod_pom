import { useEffect, useState } from "react";
import { api } from "../api/client.js";

// Справочники видов рубок / видов пользования / видов культур с цветами
// (GET /api/map/legendy) — те же, что в QGIS-плагине и приложении.
let cache = null;

export function useLegendy() {
  const [legendy, setLegendy] = useState(cache);
  useEffect(() => {
    if (cache) return;
    let alive = true;
    api.get("/map/legendy")
      .then((res) => {
        cache = res;
        if (alive) setLegendy(res);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return legendy || { vidy_rubok: [], gruppy_polzovaniya: [], vidy_kultur: [] };
}
