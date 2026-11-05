import React, { useState } from "react";
import Modal from "./Modal.jsx";
import Button from "./Button.jsx";
import { useToast } from "./Toast.jsx";
import { api } from "../api/client.js";

// «Новая делянка из файла» (просьба Влада 05.11.2026, лесопункт): выгрузка
// из QGIS лесничества, KML/GPX навигатора или shp в .zip. Сервер разбирает
// файл на контуры (POST /delyanki/iz-fayla/razbor), человек отмечает
// нужные, поправляет кв/выд/№ — и делянки заводятся сразу с контуром:
// на карте сайта и телефона видны их настоящие границы.

const POLE = "w-full rounded-md border border-border bg-surface px-2 py-1 text-sm text-ink";

function Eskiz({ geometry }) {
  // маленький рисунок контура, чтобы отличать полигоны друг от друга
  const rings = [];
  const add = (poly) => poly[0] && rings.push(poly[0]);
  if (geometry?.type === "Polygon") add(geometry.coordinates);
  if (geometry?.type === "MultiPolygon") geometry.coordinates.forEach(add);
  const pts = rings.flat();
  if (!pts.length) return null;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  // долгота «сжата» на широте Беларуси примерно в 0.58 раза
  const w = (x1 - x0) * 0.58 || 1e-9;
  const h = y1 - y0 || 1e-9;
  const k = Math.min(52 / w, 36 / h);
  const d = rings
    .map((r) => r.map((p, i) => `${i ? "L" : "M"}${(4 + (p[0] - x0) * 0.58 * k).toFixed(1)} ${(40 - (p[1] - y0) * k).toFixed(1)}`).join("") + "Z")
    .join("");
  return (
    <svg width="60" height="44" viewBox="0 0 60 44" aria-hidden="true">
      <path d={d} fill="rgba(47,125,79,.15)" stroke="#2f7d4f" strokeWidth="1.5" />
    </svg>
  );
}

export default function DelyankiIzFayla({ open, onClose, onCreated }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [konturi, setKonturi] = useState(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setFile(null);
    setKonturi(null);
  };
  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const razobrat = async (f) => {
    setFile(f);
    setKonturi(null);
    if (!f) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.upload("/delyanki/iz-fayla/razbor", fd);
      setKonturi(
        (r.konturi || []).map((k) => ({
          ...k,
          vybran: (r.konturi || []).length === 1 || !!k.kvartal,
          kvartal: k.kvartal || "",
          vydel: k.vydel || "",
          lesoseka_nomer: k.lesoseka_nomer || "",
          nazvanie: k.nazvanie || "",
        }))
      );
    } catch (e) {
      toast.show({ tone: "danger", title: "Файл не прочитался", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const pomenyat = (i, patch) => setKonturi((ks) => ks.map((k, j) => (j === i ? { ...k, ...patch } : k)));
  const vybrannye = (konturi || []).filter((k) => k.vybran);
  const bezKv = vybrannye.filter((k) => !k.kvartal.trim()).length;

  const sozdat = async () => {
    setBusy(true);
    try {
      const r = await api.post("/delyanki/iz-fayla", {
        delyanki: vybrannye.map(({ geometry, kvartal, vydel, lesoseka_nomer, nazvanie }) => ({
          geometry, kvartal, vydel, lesoseka_nomer, nazvanie,
        })),
      });
      const n = r.sozdany?.length || 0;
      toast.show({
        tone: "success",
        title: `Заведено делянок: ${n}`,
        description: (r.sozdany || []).map((d) => `${d.nazvanie} — ${d.ploshad} га`).join("; "),
      });
      reset();
      onClose();
      onCreated?.(r.sozdany?.[0]?.delyanka_id);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось завести делянки", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Новая делянка из файла"
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={close} disabled={busy}>
            Отмена
          </Button>
          <Button variant="primary" onClick={sozdat} loading={busy && !!konturi} disabled={!vybrannye.length || bezKv > 0}>
            {vybrannye.length > 1 ? `Завести делянки (${vybrannye.length})` : "Завести делянку"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted">
          Файл от лесничества или с навигатора: выгрузка из QGIS (.geojson, shp в .zip), .kml, .gpx (трек обхода
          границы), .gpkg. Каждый контур станет делянкой с настоящими границами на карте сайта и телефона.
        </p>
        <input
          type="file"
          accept=".geojson,.json,.zip,.kml,.gpx,.gpkg"
          onChange={(e) => razobrat(e.target.files?.[0] || null)}
          className="w-full text-base text-ink file:mr-3 file:px-3.5 file:py-2 file:rounded-md file:border-0 file:bg-mint-soft file:text-pine file:font-semibold file:cursor-pointer"
        />
        {busy && !konturi && file && <p className="text-sm text-muted">Читаю файл…</p>}
        {konturi && (
          <>
            <p className="text-sm text-ink">
              Нашлось контуров: <b>{konturi.length}</b>. Отметьте нужные и проверьте квартал и выдел.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-2 text-xs uppercase">
                    <th className="p-1"></th>
                    <th className="p-1">Контур</th>
                    <th className="p-1">Площадь, га</th>
                    <th className="p-1">Кв.*</th>
                    <th className="p-1">Выд.</th>
                    <th className="p-1">Лес. №</th>
                    <th className="p-1">Название (необяз.)</th>
                  </tr>
                </thead>
                <tbody>
                  {konturi.map((k, i) => (
                    <tr key={i} className="border-t border-border" style={{ opacity: k.vybran ? 1 : 0.55 }}>
                      <td className="p-1">
                        <input
                          type="checkbox"
                          checked={k.vybran}
                          onChange={(e) => pomenyat(i, { vybran: e.target.checked })}
                          className="h-4 w-4 accent-pine cursor-pointer"
                        />
                      </td>
                      <td className="p-1"><Eskiz geometry={k.geometry} /></td>
                      <td className="p-1 font-mono">{k.ploshad}</td>
                      <td className="p-1" style={{ width: 70 }}>
                        <input className={POLE} value={k.kvartal} onChange={(e) => pomenyat(i, { kvartal: e.target.value })} />
                      </td>
                      <td className="p-1" style={{ width: 70 }}>
                        <input className={POLE} value={k.vydel} onChange={(e) => pomenyat(i, { vydel: e.target.value })} />
                      </td>
                      <td className="p-1" style={{ width: 70 }}>
                        <input className={POLE} value={k.lesoseka_nomer} onChange={(e) => pomenyat(i, { lesoseka_nomer: e.target.value })} />
                      </td>
                      <td className="p-1">
                        <input className={POLE} value={k.nazvanie} placeholder={`кв. ${k.kvartal || "…"}${k.vydel ? ` выд. ${k.vydel}` : ""}${k.lesoseka_nomer ? ` лес. №${k.lesoseka_nomer}` : ""}`} onChange={(e) => pomenyat(i, { nazvanie: e.target.value })} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {bezKv > 0 && <p className="text-xs" style={{ color: "#b45309" }}>У отмеченных контуров нужен номер квартала.</p>}
          </>
        )}
      </div>
    </Modal>
  );
}
