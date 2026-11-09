import React, { useState } from "react";
import { api } from "../api/client.js";
import { useToast } from "./Toast.jsx";

/**
 * «🗺 Показать в QGIS» (шаг 5 разбора сайта 09.11.2026). Карты на сайте нет —
 * она в QGIS (Влад). Кнопка просит сервер, а плагин «Лесовод-мост» (0.10.0+)
 * у открытого QGIS приближает карту к объекту и открывает карточку.
 * Работает с любого компьютера: QGIS может быть открыт на другом ПК.
 *
 * tip: delyanka | lesokultury | vydel | proba; id — для делянки/культур/пробы;
 * kvartal/vydel — запасной путь (и единственный для выдела).
 */
export default function QgisButton({ tip, id, kvartal, vydel, lesnichestvo, nazvanie, size = "sm", className = "" }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.post("/map/qgis/pokazat", {
        tip, id: id ?? null, kvartal: kvartal != null ? String(kvartal) : null,
        vydel: vydel != null ? String(vydel) : null, lesnichestvo: lesnichestvo || null, nazvanie: nazvanie || null,
      });
      toast.show({
        tone: "success",
        title: "Отправлено в QGIS",
        description: "Через пару секунд карта в QGIS приблизится сама. Не двигается — проверьте, что QGIS открыт, а в «Лесовод-мосте» стоит галочка «Показывать в QGIS то, что выбрали на сайте».",
        duration: 6000,
      });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не отправилось в QGIS", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      onClick={go}
      disabled={busy}
      title="Приблизить карту в QGIS к этому месту (нужен плагин «Лесовод-мост» 0.10.0)"
      className={[
        "inline-flex items-center gap-1.5 rounded-[8px] border border-border bg-surface text-pine font-semibold whitespace-nowrap hover:bg-mint-soft hover:border-pine transition-colors disabled:opacity-60",
        size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[12.5px]",
        className,
      ].join(" ")}
    >
      🗺 {busy ? "Отправляю…" : "Показать в QGIS"}
    </button>
  );
}
