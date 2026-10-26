import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Button from "./Button.jsx";
import AuthImage from "./AuthImage.jsx";
import { useToast } from "./Toast.jsx";

/**
 * Пробные площади участка культур, поставленные с телефона (карта →
 * инструменты → «Поставить пробу»). По правилам тех. приёмка,
 * инвентаризация 1-го и 3-го года идут на одной и той же пробе — здесь
 * видно, где она, и какие учёты на ней уже были.
 *
 * Схема: контур участка (если загружен) и границы проб в одном масштабе.
 */
function projector(geometries, size) {
  const pts = geometries.flatMap((g) =>
    (g.type === "Polygon" ? [g.coordinates] : g.coordinates || []).flat(2));
  if (!pts.length) return null;
  const lat0 = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  const xs = pts.map((p) => p[0] * k);
  const ys = pts.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = (size - 16) / Math.max(maxX - minX, maxY - minY || 1e-9);
  const tx = (p) => 8 + (p[0] * k - minX) * scale;
  const ty = (p) => size - 8 - (p[1] - minY) * scale;
  const path = (g) => (g.type === "Polygon" ? [g.coordinates] : g.coordinates || []).map((poly) => poly.map((ring) =>
    ring.map((p, i) => `${i ? "L" : "M"}${tx(p).toFixed(1)},${ty(p).toFixed(1)}`).join("") + "Z").join("")).join("");
  return { path, tx, ty };
}

function Skhema({ kontur, proby, size = 220 }) {
  const geoms = [kontur, ...proby.map((p) => p.geometry)].filter(Boolean);
  const pr = projector(geoms, size);
  if (!pr) return null;
  return (
    <svg width={size} height={size} className="bg-surface-alt rounded-md border border-border shrink-0">
      {kontur && <path d={pr.path(kontur)} fill="rgba(0,229,255,0.12)" stroke="#00a3b8" strokeWidth="1.2" strokeDasharray="5 3" />}
      {proby.filter((p) => p.geometry).map((p) => (
        <g key={p.id}>
          <path d={pr.path(p.geometry)} fill="rgba(46,94,62,0.18)" stroke="#2e5e3e" strokeWidth="1.2" />
          <text x={pr.tx([p.lon, p.lat])} y={pr.ty([p.lon, p.lat]) - 6} fontSize="10" textAnchor="middle" fill="#2e5e3e" fontWeight="700">
            П{p.nomer}
          </text>
        </g>
      ))}
    </svg>
  );
}

function razmer(p) {
  if (p.forma === "krug" && p.radius_m) return `круг R ${p.radius_m} м`;
  if (p.forma === "pryamougolnik" && p.dlina_m) return `${p.dlina_m}×${p.shirina_m} м${p.azimut != null ? `, азимут ${Math.round(p.azimut)}°` : ""}`;
  return p.forma_label || p.forma;
}

function Etapy({ etapy }) {
  if (!etapy?.length) return <span className="text-muted">—</span>;
  return (
    <div className="flex flex-col gap-0.5">
      {etapy.map((e) => (
        <div key={e.tip} className={e.vypolneno ? "" : "text-muted"}>
          {e.vypolneno ? (e.na_probe ? "✅" : "☑️") : "⏳"} {e.tip}
          {e.data ? ` — ${e.data}` : ""}
          {e.prizhivaemost_pct != null ? `, ${e.prizhivaemost_pct}%` : ""}
          {e.vypolneno && !e.na_probe && <span className="text-xs text-muted"> (без отметки пробы)</span>}
        </div>
      ))}
    </div>
  );
}

export default function ProbyBlock({ uchastokId }) {
  const toast = useToast();
  const [proby, setProby] = useState(null);
  const [kontur, setKontur] = useState(null);

  const load = useCallback(async () => {
    try {
      setProby(await api.get("/proby", { uchastok_id: uchastokId }));
    } catch {
      setProby([]);
    }
    try {
      setKontur((await api.get(`/lesokultury/uchastki/${uchastokId}/kontur`))?.geometry || null);
    } catch {
      setKontur(null);
    }
  }, [uchastokId]);
  useEffect(() => { load(); }, [load]);

  const remove = async (p) => {
    if (!window.confirm(`Убрать пробу П${p.nomer} с карты? В базе она останется.`)) return;
    try {
      await api.delete(`/proby/${p.id}`);
      toast.show({ tone: "success", title: `Проба П${p.nomer} убрана с карты` });
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось убрать пробу", description: e.message });
    }
  };

  if (proby === null) return null;
  return (
    <div>
      <h3 className="font-ui font-extrabold text-pine text-[14px] mb-1">Пробы на карте</h3>
      <p className="text-muted text-[12px] mb-3">
        Ставятся с телефона: Карта → инструменты → «Поставить пробу». Тех. приёмка, инвентаризация 1-го и 3-го года — на
        одной и той же пробе; ✅ — учёт был именно на этой пробе.
      </p>
      {proby.length === 0 ? (
        <div className="text-sm text-muted">Проб на этом участке пока нет.</div>
      ) : (
        <div className="flex flex-wrap gap-4 items-start">
          <Skhema kontur={kontur} proby={proby} />
          <div className="flex-1 min-w-[320px] flex flex-col gap-3">
            {proby.map((p) => (
              <div key={p.id} className="border border-border rounded-lg p-3 text-sm flex flex-col gap-1.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold text-pine">
                    П{p.nomer} · {razmer(p)} · {p.ploshad_m2} м²
                  </div>
                  {p.mozhno_pravit && <Button variant="ghost" size="sm" onClick={() => remove(p)}>Убрать</Button>}
                </div>
                <div className="text-[12.5px]">
                  <a
                    className="text-pine underline"
                    href={`https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=19/${p.lat}/${p.lon}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {p.lat.toFixed(6)}, {p.lon.toFixed(6)}
                  </a>
                  {p.tochnost_m != null && <span className="text-muted"> · GPS ±{Math.round(p.tochnost_m)} м</span>}
                </div>
                {p.orientir && <div className="text-[12.5px]">🧭 {p.orientir}</div>}
                <div className="text-[12.5px]"><Etapy etapy={p.etapy} /></div>
                <div className="text-xs text-muted">
                  📱 {p.avtor_fio || "—"} · {(p.created_at || "").slice(0, 10).split("-").reverse().join(".")}
                </div>
                {p.photo_url && <AuthImage path={p.photo_url.replace(/^\/api/, "")} caption="Фото ориентира" />}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
