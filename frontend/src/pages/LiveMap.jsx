import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  GeoJSON,
  CircleMarker,
  Marker,
  Popup,
  LayersControl,
  LayerGroup,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api, API_BASE_URL } from "../api/client.js";
import { pollTask } from "../hooks/useTaskPolling.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import Modal from "../components/Modal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * Экран "Живая карта" (screens/live_map/) — Блок 2 плана доработки
 * (PLAN_DORABOTKI.md), заменяет версию Этапа 6 (folium HTML в <iframe>).
 *
 * Backend: GET /api/map/kvartaly и GET /api/map/vydela (app/routers/map.py
 * + forest_map.get_map_layer_geojson, новое в этом заходе) — те же
 * .geojson границ, что и раньше, но отдаются частями по bbox текущего
 * вида карты и с упрощением геометрии под zoom, а не целиком одним HTML.
 *
 * Перенесено 1:1 (см. docstring generate_forest_map в forest_map.py):
 *   Слой "Кварталы" (чёрный контур + подпись номера)  → GeoJSON + bindTooltip(permanent)
 *   Слой "Выдела" (заливка по категории работ)         → GeoJSON, style из status_color/status_label
 *   Попап по клику на выдел                            → Modal, тот же набор полей, что в HTML-попапе
 *   Слой "Усыхание леса" (маркеры)                     → CircleMarker + Popup, теперь поверх карты,
 *                                                          а не отдельной таблицей снизу (как было в Этапе 6)
 *   LayerControl (вкл/выкл слоёв)                       → <LayersControl>
 *   Легенда категорий работ                             → тот же список цветов, обычный div поверх карты
 *   "🔄 Обновить карту" (folium) / QWebEngineView       → POST /api/map/generate остался как есть в
 *                                                          backend'е, на фронте — кнопка "Экспорт в HTML"
 *                                                          (офлайн-версия одним файлом, открывается в новой
 *                                                          вкладке), см. "Сознательно упрощено" ниже.
 *
 * Клик по полигону выдела → карточка (п.2 Блока 2 плана "можно
 * переиспользовать логику из Plots.jsx"): по факту переиспользуется не
 * Plots.jsx, а уже готовый GET /api/taxation/vydel (Taxation.jsx),
 * дополненный новым GET /api/delyanki/by-location — так карточка сразу
 * показывает и таксационные данные, и делянку, если она на этот выдел
 * уже заведена.
 *
 * Сознательно упрощено:
 *   1. Поиск по номеру квартала (folium.plugins.Search) — не перенесён.
 *      В HTML-версии поиск работал по уже загруженному в браузер целиком
 *      слою кварталов; здесь слой стримится по bbox видимой области, и
 *      честной реализации поиска "по всему лесничеству" без отдельного
 *      серверного индекса не получится — карта в реальном использовании
 *      (полевой ноутбук/планшет лесника) и так открывается с
 *      приблизительным знанием местности, поэтому пока проще прокрутить/
 *      отдалить карту руками. Если понадобится — отдельный маленький
 *      эндпоинт "найти bbox квартала по номеру" сделает это тем же
 *      _read_filtered_layer (без изменений здесь).
 *   2. Начальный вид карты — фиксированные координаты (см.
 *      DEFAULT_MAP_CENTER ниже), а не автоматический fit_bounds по
 *      данным лесничества, как в HTML-версии: сама идея bbox-стриминга
 *      в том, чтобы не читать все границы лесничества целиком просто
 *      чтобы посчитать, куда центрировать карту. Проще подобрать
 *      разумный дефолт под ваш лесхоз один раз (см. константу), чем
 *      платить лишним чтением 56 МБ на каждое открытие экрана.
 *   3. Слой "Усыхание леса" не пересчитывает квартал/выдел на лету при
 *      клике по карте (как в get_sanitary_vydely — точка-в-полигоне
 *      через shapely) — GET /api/map/sanitary не менялся и уже отдаёт
 *      готовые kvartal/vydel, посчитанные один раз на бэкенде.
 */

// Приблизительный центр по умолчанию — подобран по названиям лесничеств
// в тестовом lch_map.json (Болбасовское/Аслановичское — Оршанский район,
// Витебская область). Замените на координаты вашего лесхоза, если они
// не подходят — единственное место, которое это трогает.
const DEFAULT_MAP_CENTER = [54.51, 30.41];
const DEFAULT_MAP_ZOOM = 12;
const VIEWPORT_DEBOUNCE_MS = 300;

const WORK_LEGEND = [
  { color: "#ff4444", label: "Рубка" },
  { color: "#ffeb3b", label: "Уход / осветление" },
  { color: "#4caf50", label: "Посадка / дополнение" },
  { color: "#8bc34a", label: "Прочие работы" },
];

function boundsToBBoxString(bounds) {
  const sw = bounds.getSouthWest();
  const ne = bounds.getNorthEast();
  return `${sw.lng},${sw.lat},${ne.lng},${ne.lat}`;
}

function kvartalyStyle() {
  return { fillColor: "#000000", fillOpacity: 0, color: "#1a1a1a", weight: 2 };
}

/** То же самое сопоставление, что _vydel_style() в forest_map.py: если
 * бэкенд посчитал status_color (есть выполненные работы) — красим
 * заливку, иначе — только тонкий серый контур без заливки. */
function vydelaStyle(feature) {
  const color = feature?.properties?.status_color;
  if (color) return { fillColor: color, fillOpacity: 0.65, color: "#333333", weight: 1 };
  return { fillColor: "#00ff00", fillOpacity: 0, color: "#666666", weight: 1 };
}

/** Слушает moveend/zoomend карты и с debounce 300мс (как и просил план)
 * зовёт onViewportChange(bounds, zoom). Рендерит null — только логика,
 * без собственной разметки. */
function MapViewportWatcher({ onViewportChange }) {
  const timeoutRef = useRef(null);

  const map = useMapEvents({
    moveend() {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => onViewportChange(map.getBounds(), map.getZoom()), VIEWPORT_DEBOUNCE_MS);
    },
    zoomend() {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => onViewportChange(map.getBounds(), map.getZoom()), VIEWPORT_DEBOUNCE_MS);
    },
  });

  useEffect(() => {
    // первая загрузка — сразу по начальному виду карты, без debounce
    onViewportChange(map.getBounds(), map.getZoom());
    return () => clearTimeout(timeoutRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}

// 📦 divIcon для складов — не зависит от набора иконок leaflet по
// умолчанию (те требуют отдельной настройки путей к PNG при сборке
// через Vite), поэтому используем обычный emoji в HTML-разметке.
const SKLAD_ICON = L.divIcon({
  html: '<div style="font-size:22px;line-height:1;filter:drop-shadow(0 1px 1px rgba(0,0,0,.5))">📦</div>',
  className: "livemap-sklad-icon",
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

function ImportLayerModal({ open, onClose, lesnichestvoNum, batches, onImported, onDeleted }) {
  const toast = useToast();
  const [file, setFile] = useState(null);
  const [layerName, setLayerName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  const reset = () => {
    setFile(null);
    setLayerName("");
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!file) return;
    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await api.upload("/map/import-layer", formData, {
        layer_name: layerName.trim() || undefined,
        lesnichestvo_num: lesnichestvoNum || undefined,
      });
      toast.show({ tone: "success", title: `Слой загружен: ${result?.created ?? 0} объектов` });
      reset();
      onImported();
    } catch (e) {
      toast.show({ tone: "danger", title: "Импорт не удался", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (batchId) => {
    setDeletingId(batchId);
    try {
      await api.delete(`/map/import-layers/${batchId}`);
      onDeleted();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить слой", description: e.message });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Modal open={open} onClose={handleClose} title="Импорт слоя из QGIS" size="md">
      <div className="flex flex-col gap-4">
        <div>
          <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
            Файл (.geojson / .json / .zip с Shapefile)
          </label>
          <input
            type="file"
            accept=".geojson,.json,.zip,.shp"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full text-base text-ink file:mr-3 file:px-3.5 file:py-2 file:rounded-md file:border-0 file:bg-mint-soft file:text-pine file:font-semibold file:cursor-pointer"
          />
          {file && <p className="text-faint text-xs mt-1.5">Выбран файл: {file.name}</p>}
        </div>
        <label className="block">
          <span className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
            Название слоя (необязательно)
          </span>
          <input
            type="text"
            placeholder="например, Съёмка делянки №12"
            value={layerName}
            onChange={(e) => setLayerName(e.target.value)}
            className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
          />
        </label>
        <p className="text-faint text-xs">
          Файл ляжет на карту отдельным слоем поверх кварталов/выделов — делянки при этом
          не создаются. Квартал/выдел/название подхватываются из атрибутов слоя для
          подписи в попапе, если такие колонки есть.
        </p>
        <Button variant="primary" onClick={handleSubmit} loading={submitting} disabled={!file}>
          Загрузить на карту
        </Button>

        {batches.length > 0 && (
          <div className="pt-3 border-t border-border">
            <div className="font-ui font-bold text-ink text-sm mb-2">Загруженные слои</div>
            <div className="flex flex-col gap-1.5">
              {batches.map((b) => (
                <div key={b.batch_id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-ink truncate">
                    {b.layer_name || "Без названия"} — {b.n_features} объектов
                  </span>
                  <Button
                    variant="ghost"
                    onClick={() => handleDelete(b.batch_id)}
                    loading={deletingId === b.batch_id}
                  >
                    🗑️
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

function AddSkladModal({ open, onClose, onAdded }) {
  const toast = useToast();
  const [nazvanie, setNazvanie] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setNazvanie("");
    setLat("");
    setLon("");
    setComment("");
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    const latNum = parseFloat(lat.replace(",", "."));
    const lonNum = parseFloat(lon.replace(",", "."));
    if (!nazvanie.trim() || Number.isNaN(latNum) || Number.isNaN(lonNum)) return;
    setSubmitting(true);
    try {
      await api.post("/map/sklady", { nazvanie: nazvanie.trim(), lat: latNum, lon: lonNum, comment: comment.trim() || undefined });
      toast.show({ tone: "success", title: "Склад добавлен на карту" });
      reset();
      onClose();
      onAdded();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось добавить склад", description: e.message });
    } finally {
      setSubmitting(false);
    }
  };

  const valid = nazvanie.trim() && !Number.isNaN(parseFloat(lat.replace(",", "."))) && !Number.isNaN(parseFloat(lon.replace(",", ".")));

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Добавить склад"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Отмена
          </Button>
          <Button variant="primary" onClick={handleSubmit} loading={submitting} disabled={!valid}>
            Добавить
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <label className="block">
          <span className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Название</span>
          <input
            type="text"
            placeholder="например, Склад №3 у объездной"
            value={nazvanie}
            onChange={(e) => setNazvanie(e.target.value)}
            className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
          />
        </label>
        <div className="flex gap-3">
          <label className="block flex-1">
            <span className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Широта</span>
            <input
              type="text"
              inputMode="decimal"
              placeholder="54.512345"
              value={lat}
              onChange={(e) => setLat(e.target.value)}
              className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
            />
          </label>
          <label className="block flex-1">
            <span className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">Долгота</span>
            <input
              type="text"
              inputMode="decimal"
              placeholder="30.412345"
              value={lon}
              onChange={(e) => setLon(e.target.value)}
              className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
            />
          </label>
        </div>
        <label className="block">
          <span className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
            Комментарий (необязательно)
          </span>
          <input
            type="text"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
          />
        </label>
        <p className="text-faint text-xs">
          Склад покажется на карте отдельным значком 📦 независимо от выбранного лесничества.
          Координаты — широта и долгота в десятичном виде (как в QGIS/Google Maps).
        </p>
      </div>
    </Modal>
  );
}

export default function LiveMap() {
  const toast = useToast();
  const [lesnichestva, setLesnichestva] = useState({});
  const [selected, setSelected] = useState("");

  const [kvartaly, setKvartaly] = useState(null);
  const [vydela, setVydela] = useState(null);
  const [loadingLayers, setLoadingLayers] = useState(false);
  const [layerError, setLayerError] = useState(null);
  const lastViewportRef = useRef(null); // {bounds, zoom} — для кнопки "Обновить"
  const fetchGenRef = useRef(0); // счётчик запросов — отбрасываем устаревшие ответы
  // Счётчик успешных загрузок слоёв — используется как React-key для
  // <GeoJSON>, чтобы гарантированно пересоздать слой при новых данных.
  // Раньше ключ строился через JSON.stringify(vydela).length — на
  // тысячах точек это заметная синхронная работа на каждый рендер
  // (в т.ч. на зуме/движении карты), просто чтобы получить число.
  const [layerVersion, setLayerVersion] = useState(0);

  const [sanitary, setSanitary] = useState([]);

  // Самостоятельный слой из импорта QGIS (см. app/routers/map.py:
  // /import-layer) — независим от делянок, грузится целиком (не по
  // bbox: это съёмка в десятки-сотни объектов, не 56 МБ map_vydela.
  // geojson) один раз при выборе лесничества, а не на каждый пан/зум.
  const [importLayer, setImportLayer] = useState(null);
  const [importLayerModalOpen, setImportLayerModalOpen] = useState(false);
  const [importBatches, setImportBatches] = useState([]);

  // Склады — не завязаны на выбранное лесничество, грузятся один раз при
  // открытии страницы (см. чат: "хочу видеть где что у меня находится").
  const [sklady, setSklady] = useState([]);
  const [addSkladOpen, setAddSkladOpen] = useState(false);

  const loadSklady = useCallback(async () => {
    try {
      const rows = await api.get("/map/sklady");
      setSklady(rows || []);
    } catch (e) {
      // необязательный слой — не мешаем основной карте тостом об ошибке
      setSklady([]);
    }
  }, []);

  useEffect(() => {
    loadSklady();
  }, [loadSklady]);

  const handleDeleteSklad = useCallback(
    async (id) => {
      try {
        await api.delete(`/map/sklady/${id}`);
        loadSklady();
      } catch (e) {
        toast.show({ tone: "danger", title: "Не удалось удалить склад", description: e.message });
      }
    },
    [loadSklady, toast]
  );

  const [selectedVydel, setSelectedVydel] = useState(null); // {kvartal, vydel}
  const [vydelCard, setVydelCard] = useState({ loading: false, error: null, taxation: null, delyanki: [] });

  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.get("/map/lesnichestva");
        setLesnichestva(data || {});
        const first = Object.values(data || {})[0];
        if (first !== undefined) setSelected(String(first));
      } catch (e) {
        toast.show({ tone: "danger", title: "Не удалось загрузить список лесничеств", description: e.message });
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const lesnichestvoName = useMemo(
    () => Object.entries(lesnichestva).find(([, num]) => String(num) === String(selected))?.[0] || "",
    [lesnichestva, selected]
  );

  const loadSanitary = useCallback(async (num) => {
    try {
      const rows = await api.get("/map/sanitary", { lesnichestvo_num: num });
      setSanitary(rows || []);
    } catch (e) {
      // необязательный слой — не мешаем основной карте тостом об ошибке
      setSanitary([]);
    }
  }, []);

  const loadImportLayer = useCallback(async (num) => {
    if (!num) return;
    try {
      const [fc, batches] = await Promise.all([
        api.get("/map/import-layers", { lesnichestvo_num: num }),
        api.get("/map/import-layers/batches", { lesnichestvo_num: num }),
      ]);
      setImportLayer(fc || null);
      setImportBatches(batches || []);
    } catch (e) {
      // необязательный слой — не мешаем основной карте тостом об ошибке
      setImportLayer(null);
      setImportBatches([]);
    }
  }, []);

  useEffect(() => {
    setKvartaly(null);
    setVydela(null);
    setSelectedVydel(null);
    setImportLayer(null);
    setImportBatches([]);
    if (selected) {
      loadSanitary(selected);
      loadImportLayer(selected);
    }
  }, [selected, loadSanitary, loadImportLayer]);

  const fetchLayers = useCallback(
    async (bounds, zoom) => {
      if (!selected) return;
      lastViewportRef.current = { bounds, zoom };
      const bbox = boundsToBBoxString(bounds);
      const myGen = ++fetchGenRef.current;
      setLoadingLayers(true);
      setLayerError(null);
      try {
        const [kv, vd] = await Promise.all([
          api.get("/map/kvartaly", { lesnichestvo_num: selected, bbox, zoom }),
          api.get("/map/vydela", { lesnichestvo_num: selected, bbox, zoom }),
        ]);
        if (myGen !== fetchGenRef.current) return; // карту успели подвинуть ещё раз — этот ответ устарел
        setKvartaly(kv);
        setVydela(vd);
        setLayerVersion((v) => v + 1);
      } catch (e) {
        if (myGen !== fetchGenRef.current) return;
        setLayerError(e.message);
      } finally {
        if (myGen === fetchGenRef.current) setLoadingLayers(false);
      }
    },
    [selected]
  );

  const handleRefresh = () => {
    if (lastViewportRef.current) fetchLayers(lastViewportRef.current.bounds, lastViewportRef.current.zoom);
  };

  const openVydelCard = useCallback(
    async (kvartal, vydel) => {
      setSelectedVydel({ kvartal, vydel });
      setVydelCard({ loading: true, error: null, taxation: null, delyanki: [] });
      const [taxationResult, delyankiResult] = await Promise.allSettled([
        api.get("/taxation/vydel", { kvartal, vydel, lesnichestvo: lesnichestvoName || undefined }),
        api.get("/delyanki/by-location", { kvartal, vydel, lesnichestvo: lesnichestvoName || undefined }),
      ]);
      setVydelCard({
        loading: false,
        error: taxationResult.status === "rejected" ? taxationResult.reason.message : null,
        taxation: taxationResult.status === "fulfilled" ? taxationResult.value : null,
        delyanki: delyankiResult.status === "fulfilled" ? delyankiResult.value : [],
      });
    },
    [lesnichestvoName]
  );

  const onEachKvartal = useCallback((feature, layer) => {
    const num = feature?.properties?.num_kv;
    if (num !== undefined && num !== null) {
      layer.bindTooltip(String(num), { permanent: true, direction: "center", className: "livemap-kvartal-label" });
    }
  }, []);

  const onEachVydel = useCallback(
    (feature, layer) => {
      const { num_kv, num_vd, status_label } = feature?.properties || {};
      let tooltipHtml = `Квартал: ${num_kv ?? "—"}, Выдел: ${num_vd ?? "—"}`;
      if (status_label) tooltipHtml += `<br>Статус: Выполнено (${status_label})`;
      layer.bindTooltip(tooltipHtml, { sticky: true });
      layer.on("click", () => openVydelCard(num_kv, num_vd));
    },
    [openVydelCard]
  );

  const importLayerStyle = useCallback(
    () => ({ fillColor: "#8e44ad", fillOpacity: 0.25, color: "#8e44ad", weight: 2, dashArray: "6 4" }),
    []
  );

  const onEachImportFeature = useCallback((feature, layer) => {
    const props = feature?.properties || {};
    const rows = Object.entries(props.raw || {})
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([k, v]) => `<div><b>${k}:</b> ${v}</div>`)
      .join("");
    layer.bindPopup(
      `<div class="text-sm"><div class="font-bold mb-1">${props.nazvanie || props.layer_name || "Импорт QGIS"}</div>${rows}</div>`
    );
  }, []);

  const handleExportHtml = async () => {
    if (!selected) return;
    setExporting(true);
    try {
      const { task_id } = await api.post("/map/generate", undefined, { lesnichestvo_num: selected });
      const result = await pollTask(task_id, { timeoutMs: 10 * 60 * 1000 });
      const docId = result?.document_ids?.[0];
      if (!docId) throw new Error("Сервер не вернул файл карты");
      window.open(`${API_BASE_URL}/documents/${docId}/download`, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось экспортировать карту", description: e.message });
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="p-8 flex flex-col gap-6 h-full">
      <Card>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex-1 min-w-[220px]">
            <label className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
              Лесничество
            </label>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="w-full bg-surface-alt border border-transparent focus:border-pine focus:bg-surface rounded-md px-3.5 py-2.5 text-base text-ink outline-none transition-colors"
            >
              {Object.entries(lesnichestva).map(([name, num]) => (
                <option key={num} value={num}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <Button variant="secondary" onClick={handleRefresh} disabled={!selected || loadingLayers}>
            🔄 Обновить видимую область
          </Button>
          <Button variant="ghost" onClick={handleExportHtml} loading={exporting} disabled={!selected}>
            📄 Экспорт в HTML
          </Button>
          <Button variant="ghost" onClick={() => setImportLayerModalOpen(true)} disabled={!selected}>
            📥 Импорт слоя из QGIS
            {importLayer?.features?.length > 0 ? ` (${importLayer.features.length})` : ""}
          </Button>
          <Button variant="ghost" onClick={() => setAddSkladOpen(true)}>
            📦 Добавить склад
          </Button>
          {sanitary.length > 0 && (
            <span className="text-sm text-muted px-1">🍂 Сигналов об усыхании: {sanitary.length}</span>
          )}
        </div>
        <p className="text-sm text-muted mt-3">
          Кварталы и выдела подгружаются по видимой области карты — переместите и приблизьте карту к нужному
          участку.
        </p>
      </Card>

      <Card className="flex-1 min-h-[520px] relative" padding={false}>
        {!selected ? (
          <div className="p-5">
            <EmptyState icon="🗺️" title="Выберите лесничество" description="Список лесничеств ещё не загружен." />
          </div>
        ) : (
          <>
            <MapContainer
              key={selected}
              center={DEFAULT_MAP_CENTER}
              zoom={DEFAULT_MAP_ZOOM}
              className="w-full h-full min-h-[520px] rounded-2xl"
            >
              <MapViewportWatcher onViewportChange={fetchLayers} />
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <LayersControl position="topright">
                <LayersControl.Overlay checked name="Кварталы">
                  <LayerGroup>
                    {kvartaly && (
                      <GeoJSON
                        key={`kv-${layerVersion}`}
                        data={kvartaly}
                        style={kvartalyStyle}
                        onEachFeature={onEachKvartal}
                      />
                    )}
                  </LayerGroup>
                </LayersControl.Overlay>
                <LayersControl.Overlay checked name="Выдела">
                  <LayerGroup>
                    {vydela && (
                      <GeoJSON
                        key={`vd-${layerVersion}`}
                        data={vydela}
                        style={vydelaStyle}
                        onEachFeature={onEachVydel}
                      />
                    )}
                  </LayerGroup>
                </LayersControl.Overlay>
                <LayersControl.Overlay checked name="Импорт QGIS">
                  <LayerGroup>
                    {importLayer && importLayer.features?.length > 0 && (
                      <GeoJSON
                        key={`imp-${importLayer.features.length}-${selected}`}
                        data={importLayer}
                        style={importLayerStyle}
                        onEachFeature={onEachImportFeature}
                      />
                    )}
                  </LayerGroup>
                </LayersControl.Overlay>
                <LayersControl.Overlay checked name="Усыхание леса">
                  <LayerGroup>
                    {sanitary.map((s, i) => (
                      <CircleMarker
                        key={i}
                        center={[s.lat, s.lon]}
                        radius={8}
                        pathOptions={{ color: "#c0392b", fillColor: "#e74c3c", fillOpacity: 0.85, weight: 2 }}
                      >
                        <Popup>
                          <div className="text-sm">
                            <div className="font-bold mb-1">🍂 {s.prichina || "Усыхание"}</div>
                            {s.kvartal && (
                              <div>
                                Квартал {s.kvartal}
                                {s.vydel ? ` / Выдел ${s.vydel}` : ""}
                              </div>
                            )}
                          </div>
                        </Popup>
                      </CircleMarker>
                    ))}
                  </LayerGroup>
                </LayersControl.Overlay>
                <LayersControl.Overlay checked name="Склады">
                  <LayerGroup>
                    {sklady.map((s) => (
                      <Marker key={s.id} position={[s.lat, s.lon]} icon={SKLAD_ICON}>
                        <Popup>
                          <div className="text-sm">
                            <div className="font-bold mb-1">📦 {s.nazvanie}</div>
                            {s.comment && <div className="mb-2">{s.comment}</div>}
                            <button
                              type="button"
                              onClick={() => handleDeleteSklad(s.id)}
                              className="text-error underline cursor-pointer bg-transparent border-0 p-0 text-sm"
                            >
                              Удалить склад
                            </button>
                          </div>
                        </Popup>
                      </Marker>
                    ))}
                  </LayerGroup>
                </LayersControl.Overlay>
              </LayersControl>
            </MapContainer>

            <div className="absolute bottom-4 left-4 z-[1000] bg-surface/95 border border-border rounded-md px-3.5 py-3 shadow-card text-sm leading-relaxed pointer-events-none">
              <div className="font-ui font-bold text-ink mb-1.5">Легенда</div>
              {WORK_LEGEND.map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <span
                    className="inline-block w-3.5 h-3.5 rounded-sm border border-muted-2/40"
                    style={{ background: item.color }}
                  />
                  {item.label}
                </div>
              ))}
              <div className="flex items-center gap-2">
                <span className="inline-block w-3.5 h-3.5 rounded-sm border border-muted-2/60" />
                Работы не проводились
              </div>
            </div>

            {loadingLayers && (
              <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-surface/95 border border-border rounded-full px-4 py-1.5 shadow-card text-sm text-muted">
                Загружаем участки…
              </div>
            )}
            {layerError && (
              <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[1000] bg-error-soft border border-error rounded-full px-4 py-1.5 shadow-card text-sm text-error">
                {layerError}
              </div>
            )}
          </>
        )}
      </Card>

      <Modal
        open={!!selectedVydel}
        onClose={() => setSelectedVydel(null)}
        title={selectedVydel ? `Квартал ${selectedVydel.kvartal} / Выдел ${selectedVydel.vydel}` : ""}
        size="md"
      >
        {vydelCard.loading && <p className="text-muted">Загрузка…</p>}

        {!vydelCard.loading && vydelCard.error && !vydelCard.taxation && (
          <p className="text-muted">{vydelCard.error}</p>
        )}

        {vydelCard.taxation && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-base">
            <dt className="text-muted-2">Площадь</dt>
            <dd className="text-ink">{vydelCard.taxation.ploshad ?? "—"}</dd>
            <dt className="text-muted-2">Состав</dt>
            <dd className="text-ink">{vydelCard.taxation.formula_sostava || "—"}</dd>
            <dt className="text-muted-2">Возраст</dt>
            <dd className="text-ink">{vydelCard.taxation.vozrast ?? "—"}</dd>
            <dt className="text-muted-2">Бонитет</dt>
            <dd className="text-ink">{vydelCard.taxation.bonitet ?? "—"}</dd>
            <dt className="text-muted-2">Полнота</dt>
            <dd className="text-ink">{vydelCard.taxation.polnota ?? "—"}</dd>
            <dt className="text-muted-2">Тип леса</dt>
            <dd className="text-ink">{vydelCard.taxation.tip_lesa ?? "—"}</dd>
            <dt className="text-muted-2">Запас на га</dt>
            <dd className="text-ink">{vydelCard.taxation.zapas_na_ga_display ?? "—"}</dd>
          </dl>
        )}

        {!vydelCard.loading && vydelCard.delyanki?.length > 0 && (
          <div className="mt-4 pt-4 border-t border-border">
            <div className="font-ui font-bold text-ink text-sm mb-2">Делянки на этом выделе</div>
            {vydelCard.delyanki.map((d) => (
              <div key={d.item_id} className="text-base text-ink">
                №{d.delyanka_id} «{d.nazvanie}» — {d.status_rabot || d.delyanka_status}
              </div>
            ))}
          </div>
        )}
      </Modal>

      <ImportLayerModal
        open={importLayerModalOpen}
        onClose={() => setImportLayerModalOpen(false)}
        lesnichestvoNum={selected}
        batches={importBatches}
        onImported={() => loadImportLayer(selected)}
        onDeleted={() => loadImportLayer(selected)}
      />

      <AddSkladModal open={addSkladOpen} onClose={() => setAddSkladOpen(false)} onAdded={loadSklady} />

      <style>{`
        .livemap-kvartal-label {
          background: transparent;
          border: none;
          box-shadow: none;
          font-weight: bold;
          font-size: 13px;
          color: #111;
          text-shadow: 1px 1px 2px #fff, -1px -1px 2px #fff, 1px -1px 2px #fff, -1px 1px 2px #fff;
        }
        .livemap-kvartal-label::before { display: none; }
      `}</style>
    </div>
  );
}
