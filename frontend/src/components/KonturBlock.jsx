import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Button from "./Button.jsx";
import { useToast } from "./Toast.jsx";

/** Кольца полигона (Polygon/MultiPolygon) -> SVG path в квадрате size×size. */
export function konturPath(geometry, size) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates || [];
  const pts = polys.flat(2);
  if (!pts.length) return "";
  const lat0 = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const xs = pts.map((p) => p[0] * k);
  const ys = pts.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = (size - 8) / Math.max(maxX - minX, maxY - minY || 1e-9);
  const tx = (p) => 4 + (p[0] * k - minX) * scale;
  const ty = (p) => size - 4 - (p[1] - minY) * scale;
  return polys.map((poly) => poly.map((ring) =>
    ring.map((p, i) => `${i ? "L" : "M"}${tx(p).toFixed(1)},${ty(p).toFixed(1)}`).join("") + "Z").join("")).join("");
}

/**
 * Собственный контур участка культур или лесосеки — из QGIS/GPS (GeoJSON,
 * shp в .zip, KML, GPKG, JSON «Лесного стража»). На карте в телефоне и в
 * QGIS объект рисуется этим контуром, а не всем выделом.
 * path — адрес API контура (GET/POST/DELETE), напр. /delyanki/items/5/kontur.
 */
export default function KonturBlock({ path, title, extra = null, onChanged }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      setData(await api.get(path));
    } catch {
      setData({ geometry: null });
    }
  }, [path]);
  useEffect(() => { load(); }, [load]);

  const upload = async (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      const r = await api.upload(path, fd);
      toast.show({ tone: r.warning ? "warning" : "success", title: `Контур загружен: ${r.ploshad_kontura} га`, description: r.warning || undefined });
      await load();
      onChanged?.();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить контур", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!window.confirm("Убрать контур? На карте снова будет подсвечен весь выдел.")) return;
    await api.delete(path);
    await load();
    onChanged?.();
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11.5px] font-semibold text-muted">{title}</div>
      <div className="flex flex-wrap items-center gap-3">
        {data?.geometry ? (
          <>
            <svg width="96" height="96" className="bg-surface-alt rounded-md border border-border">
              <path d={konturPath(data.geometry, 96)} fill="rgba(0,229,255,0.25)" stroke="#00a3b8" strokeWidth="1.5" />
            </svg>
            <span className="text-sm">Контур загружен, {data.ploshad_kontura} га</span>
            <Button variant="ghost" size="sm" onClick={remove}>Убрать контур</Button>
          </>
        ) : (
          <span className="text-sm text-muted">Контура нет — на карте подсвечивается весь выдел.</span>
        )}
        <label className="text-[12px] font-semibold text-pine bg-mint-soft hover:bg-mint rounded-lg px-2.5 py-1.5 cursor-pointer">
          {busy ? "Загружаю…" : data?.geometry ? "Заменить файлом" : "Загрузить файл контура"}
          <input type="file" accept=".geojson,.json,.kml,.gpkg,.zip" className="hidden" disabled={busy}
            onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
        {extra}
      </div>
      <p className="text-xs text-muted">
        Из QGIS: выделить полигон → «Экспорт → Сохранить выбранные объекты как…» → GeoJSON (или shp, запаковать в .zip).
        Система координат любая, если записана в файле; без неё метры считаются UTM 35N. Подходит и JSON «Лесного стража».
      </p>
    </div>
  );
}
