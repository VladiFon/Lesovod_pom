import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import Card from "./Card.jsx";
import Button from "./Button.jsx";
import { useToast } from "./Toast.jsx";

/** Настройки → «Карты: что не показывать» (app/karta_pometki.py): общие
 * правила для QGIS-плагина и телефона + список скрытого вручную с «Вернуть». */
export default function KartaSkrytyeCard() {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/karta/pometki").then(setD).catch(() => setD(null));
  useEffect(() => { load(); }, []);
  if (!d) return null;
  const n = d.nastroyki;
  const save = async (patch) => {
    setBusy(true);
    try {
      await api.put("/karta/nastroyki", patch);
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const vernut = async (p) => {
    setBusy(true);
    try {
      await api.post("/karta/pometki", { istochnik: p.istochnik, klyuchi: [p.klyuch], skryta: false, lesokultury: "avto" });
      toast.show({ tone: "success", title: "Вернули на карты" });
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const udalitSloy = async (b) => {
    if (!window.confirm(`Удалить с сервера слой «${b.layer_name}» (${b.n_features} контуров)? Из QGIS его можно опубликовать заново.`)) return;
    setBusy(true);
    try {
      await api.delete(`/map/import-layers/${encodeURIComponent(b.batch_id)}`);
      toast.show({ tone: "success", title: "Слой удалён — в телефоне пропадёт после «Обновить» на карте" });
      await load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить", description: e.message });
    } finally {
      setBusy(false);
    }
  };
  const vid = (kod, on) => save({ skryt_vidy: on ? [...n.skryt_vidy, kod] : n.skryt_vidy.filter((x) => x !== kod) });
  const dis = !d.mozhno || busy;
  return (
    <Card
      title="Карты: что не показывать"
      subtitle="Для QGIS-плагина «Лесовод-мост» и карты в телефоне. Ничего не удаляется — скрытое возвращается здесь же."
    >
      <div className="flex flex-col gap-3 text-sm text-ink">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" className="h-4 w-4 accent-pine" disabled={dis} checked={n.skryt_zakrytye}
            onChange={(e) => save({ skryt_zakrytye: e.target.checked })} />
          Не показывать закрытые делянки (архив после акта)
        </label>
        <label className="flex items-center gap-2">
          Лесосеки ГИСлесхоза старше
          <select className="bg-surface border border-border rounded-[8px] h-8 px-2" disabled={dis} value={n.gisleshoz_let}
            onChange={(e) => save({ gisleshoz_let: Number(e.target.value) })}>
            {[0, 1, 2, 3, 5, 10].map((v) => <option key={v} value={v}>{v === 0 ? "— показывать все —" : `${v} ${v === 1 ? "года" : "лет"}`}</option>)}
          </select>
          не показывать <span className="text-muted-2 text-[12.5px]">(по году в поле «date» лесосеки)</span>
        </label>
        <div>
          <div className="text-[12.5px] font-semibold text-muted-2 mb-1.5">Виды рубок, которые не показывать совсем</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {d.vidy_rubok.map((v) => (
              <label key={v.kod} className="flex items-center gap-1.5 cursor-pointer" title={v.label}>
                <input type="checkbox" disabled={dis} checked={n.skryt_vidy.includes(v.kod)} onChange={(e) => vid(v.kod, e.target.checked)} />
                <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: v.color }} />
                {v.kod} <span className="text-muted-2">{v.label}</span>
              </label>
            ))}
          </div>
        </div>
        {d.sloi && d.sloi.length > 0 && (
          <div>
            <div className="text-[12.5px] font-semibold text-muted-2 mb-1.5">
              Загруженные на сервер слои контуров — их рисует телефон. «Опубликовать в Лесовод» из QGIS заменяет только
              «лесосеки_qgis»; старые файлы, загруженные руками, остаются, пока их не удалить здесь
            </div>
            <div className="flex flex-col divide-y divide-border">
              {d.sloi.map((b) => (
                <div key={b.batch_id} className="flex items-center gap-3 py-1.5">
                  <span className="flex-1">
                    {b.layer_name || "без имени"}
                    <span className="text-muted-2 text-[12.5px]">
                      {" "}· {b.lesnichestvo || "без лесничества"} · {b.n_features} конт. · {String(b.created_at || "").slice(0, 16)}
                      {b.iz_qgis ? " · из QGIS" : " · загружен руками"}
                      {!b.lesoseki ? " · в телефоне не рисуется" : ""}
                    </span>
                  </span>
                  {d.mozhno_udalyat_sloi && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => udalitSloy(b)}>Удалить</Button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        <div>
          <div className="text-[12.5px] font-semibold text-muted-2 mb-1.5">
            Скрыто и помечено вручную ({d.skrytye.length}) — ставится в карточке делянки, в QGIS по выделенным и в телефоне
          </div>
          {d.skrytye.length === 0 ? (
            <div className="text-muted-2">Пока ничего.</div>
          ) : (
            <div className="flex flex-col divide-y divide-border">
              {d.skrytye.map((p) => (
                <div key={p.id} className="flex items-center gap-3 py-1.5">
                  <span className="flex-1">
                    {p.nazvanie}
                    <span className="text-muted-2 text-[12.5px]">
                      {" "}· {p.istochnik_label}
                      {p.skryta ? " · скрыта" : ""}
                      {p.lesokultury === true ? " · 🌲 культуры" : p.lesokultury === false ? " · не культуры" : ""}
                      {p.kto ? ` · ${p.kto}` : ""}
                    </span>
                  </span>
                  <Button size="sm" variant="ghost" disabled={dis} onClick={() => vernut(p)}>Вернуть</Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
