import React, { useCallback, useEffect, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * «Текущие изменения» (приказ Минлесхоза №130 от 10.06.2026) — ведомости
 * для РУП «Белгослес», все 15 приложений: строки из лесных культур, делянок
 * и рубок ухода, ручные строки (для приложений, данных которых в программе
 * нет, и дополнения к любому), сводная прил. 2 и замечания (чего не
 * хватает). Кнопка — Word по шаблону «Таблицы … ЗАПОЛНЯТЬ ЗДЕСЬ»
 * (встроенному или своему). См. backend/app/tekushchie_izmeneniya.py.
 */

async function downloadDocx(formData, fallbackName) {
  const token = localStorage.getItem("lesovod_token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE_URL}/tekushchie-izmeneniya/docx`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Ошибка сервера (${res.status})`);
  }
  const disposition = res.headers.get("content-disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Сразу отозванный blob браузер иногда сохраняет без имени — отзываем позже.
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function RuchnayaForm({ columns, initial, onSave, onCancel }) {
  const [values, setValues] = useState(() => columns.map((_, i) => initial?.[i] ?? ""));
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    try {
      await onSave(values);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-2.5 bg-surface-alt">
      <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(130px,1fr))]">
        {columns.map((c, i) => (
          <TextField
            key={i}
            label={c}
            value={values[i]}
            onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
          />
        ))}
      </div>
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={submit} loading={saving}>Сохранить строку</Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>Отмена</Button>
      </div>
    </div>
  );
}

function PrilozhenieCard({ p, god, lesnichestvo, onChanged }) {
  const toast = useToast();
  const [showAll, setShowAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState(null);
  const ruchnyeById = Object.fromEntries(p.ruchnye.map((r, i) => [p.avto + i, r]));
  const visible = showAll ? p.rows : p.rows.slice(0, 15);

  const save = async (values, id) => {
    try {
      if (id) await api.patch(`/tekushchie-izmeneniya/ruchnye/${id}`, { values });
      else await api.post("/tekushchie-izmeneniya/ruchnye", { god: Number(god), lesnichestvo, prilozhenie: p.nomer, values });
      setAdding(false);
      setEditId(null);
      await onChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить строку", description: e.message });
    }
  };
  const remove = async (id) => {
    if (!window.confirm("Удалить строку, введённую вручную?")) return;
    try {
      await api.delete(`/tekushchie-izmeneniya/ruchnye/${id}`);
      await onChanged();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить строку", description: e.message });
    }
  };

  return (
    <Card>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-ui font-extrabold text-pine text-[14px]">{p.title}</h3>
          <span className="text-xs text-muted">
            строк: {p.rows.length}{p.ruchnye.length > 0 && ` (вручную: ${p.ruchnye.length})`}
          </span>
        </div>
        <p className="text-xs text-muted">
          {p.istochnik ? `Откуда: ${p.istochnik}. Можно добавить строки вручную.` : "В программе этих данных нет — строки вводятся вручную."}
        </p>
        {p.warnings.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-oak font-semibold">Не хватает данных: {p.warnings.length}</summary>
            <ul className="mt-1.5 flex flex-col gap-0.5 text-oak max-h-60 overflow-auto">
              {p.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </details>
        )}
        {p.rows.length === 0 ? (
          <p className="text-sm text-muted">За этот год строк нет.</p>
        ) : (
          <div className="overflow-auto border border-border rounded-md">
            <table className="w-full text-xs border-collapse">
              <thead className="bg-surface-alt text-muted text-left">
                <tr>
                  {p.columns.map((c, i) => (
                    <th key={i} className="p-1.5 font-semibold align-bottom">{c}</th>
                  ))}
                  <th className="p-1.5" />
                </tr>
              </thead>
              <tbody>
                {visible.map((r, i) => {
                  const ruch = ruchnyeById[i];
                  if (ruch && editId === ruch.id) {
                    return (
                      <tr key={i} className="border-t border-border">
                        <td colSpan={p.columns.length + 1} className="p-1.5">
                          <RuchnayaForm columns={p.columns} initial={ruch.values}
                            onSave={(values) => save(values, ruch.id)} onCancel={() => setEditId(null)} />
                        </td>
                      </tr>
                    );
                  }
                  return (
                    <tr key={i} className={`border-t border-border ${ruch ? "bg-surface-alt" : ""}`}>
                      {r.map((v, j) => (
                        <td key={j} className="p-1.5 whitespace-nowrap">{v || <span className="text-faint">—</span>}</td>
                      ))}
                      <td className="p-1.5 whitespace-nowrap text-right">
                        {ruch && (
                          <span className="inline-flex gap-1">
                            <Button variant="ghost" size="sm" onClick={() => setEditId(ruch.id)}>Изменить</Button>
                            <Button variant="ghost" size="sm" onClick={() => remove(ruch.id)}>Удалить</Button>
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {p.rows.length > 15 && (
            <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Свернуть" : `Показать все ${p.rows.length}`}
            </Button>
          )}
          {!adding && <Button variant="secondary" size="sm" onClick={() => setAdding(true)}>Добавить строку</Button>}
        </div>
        {adding && <RuchnayaForm columns={p.columns} onSave={(values) => save(values)} onCancel={() => setAdding(false)} />}
      </div>
    </Card>
  );
}

function SvodnayaCard({ rows }) {
  return (
    <Card>
      <div className="flex flex-col gap-3">
        <h3 className="font-ui font-extrabold text-pine text-[14px]">Прил. 2 — сводная ведомость (считается из остальных)</h3>
        <div className="overflow-auto border border-border rounded-md">
          <table className="w-full text-xs border-collapse">
            <thead className="bg-surface-alt text-muted text-left">
              <tr>
                <th className="p-1.5 font-semibold">Мероприятие</th>
                <th className="p-1.5 font-semibold">Площадь, га</th>
                <th className="p-1.5 font-semibold">Участков, шт.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.stroka} className="border-t border-border">
                  <td className="p-1.5">{r.nazvanie}</td>
                  <td className="p-1.5 whitespace-nowrap">{r.ploshad || <span className="text-faint">—</span>}</td>
                  <td className="p-1.5 whitespace-nowrap">{r.kolichestvo || <span className="text-faint">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

const DIAG_LISTS = [
  ["kultury_lesnichestva", "Лесничества у участков культур"],
  ["kultury_gody_sozdaniya", "Годы создания культур (в выбранном лесничестве)"],
  ["zhurnal_po_godam", "Журнал культур: мероприятие — год"],
  ["delyanki_lesnichestva", "Лесничества у выделов делянок"],
  ["delyanki_statusy", "Выделы делянок: статус — год выполнения"],
  ["akty_po_godam", "Акты освидетельствования по годам"],
];

function DiagnostikaCard({ d, open }) {
  return (
    <Card>
      <details open={open} className="text-xs">
        <summary className="cursor-pointer font-semibold text-pine">
          Что есть в базе (если ведомости пустые — посмотрите сюда)
        </summary>
        <div className="mt-2 flex flex-col gap-2">
          <p>
            Участков культур всего: {d.kultury_vsego}, в лесничестве «{d.lesnichestvo_filtr || "все"}»: {d.kultury_v_lesnichestve}.
          </p>
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(240px,1fr))]">
            {DIAG_LISTS.map(([key, title]) => (
              <div key={key}>
                <div className="font-semibold text-muted mb-0.5">{title}</div>
                {(d[key] || []).length === 0 ? (
                  <div className="text-faint">нет</div>
                ) : (
                  <ul>
                    {d[key].map(([k, n]) => (
                      <li key={k}>{k}: {n}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      </details>
    </Card>
  );
}

export default function TekushchieIzmeneniya() {
  const toast = useToast();
  const [god, setGod] = useState(String(new Date().getFullYear()));
  const [lesnichestvo, setLesnichestvo] = useState("");
  const [shablon, setShablon] = useState(null);
  const [ploshadNachalo, setPloshadNachalo] = useState("");
  const [ploshadKonec, setPloshadKonec] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    api.get("/settings/lesnichiy")
      .then((l) => { if (l?.lesnichestvo) setLesnichestvo((cur) => cur || l.lesnichestvo); })
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!/^\d{4}$/.test(god)) {
      toast.show({ tone: "warning", title: "Год — четыре цифры, например 2026" });
      return;
    }
    setLoading(true);
    try {
      setData(await api.get("/tekushchie-izmeneniya", { god, lesnichestvo: lesnichestvo.trim() || undefined }));
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось собрать ведомости", description: e.message });
    } finally {
      setLoading(false);
    }
  }, [god, lesnichestvo]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDownload = async () => {
    const fd = new FormData();
    fd.append("god", god);
    fd.append("lesnichestvo", lesnichestvo.trim());
    fd.append("ploshad_nachalo", ploshadNachalo.trim());
    fd.append("ploshad_konec", ploshadKonec.trim());
    if (shablon) fd.append("shablon", shablon);
    setDownloading(true);
    try {
      await downloadDocx(fd, `Текущие изменения ${god}.docx`);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сформировать Word", description: e.message });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <Card>
        <div className="flex flex-col gap-3">
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(170px,1fr))] items-end">
            <TextField label="Отчётный год" type="number" value={god} onChange={(e) => setGod(e.target.value)} />
            <TextField label="Лесничество" placeholder="все" value={lesnichestvo} onChange={(e) => setLesnichestvo(e.target.value)} />
            <TextField label="Общая площадь на начало года, га" placeholder="для прил. 1" value={ploshadNachalo} onChange={(e) => setPloshadNachalo(e.target.value)} />
            <TextField label="Общая площадь на конец года, га" placeholder="для прил. 1" value={ploshadKonec} onChange={(e) => setPloshadKonec(e.target.value)} />
            <div className="col-span-2">
              <label className="block text-[11.5px] font-semibold text-muted mb-1">
                Свой шаблон Word (необязательно)
              </label>
              <input type="file" accept=".docx" onChange={(e) => setShablon(e.target.files?.[0] || null)} className="text-sm" />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={load} loading={loading}>Показать</Button>
            <Button variant="primary" onClick={handleDownload} loading={downloading}>Скачать Word</Button>
          </div>
          <p className="text-xs text-muted">
            Заполняются все приложения: 4, 7, 14 — из «Лесокультур», 3 и 15 — из делянок (МДО) и рубок ухода,
            2 — сводная из остальных. Для 5, 6, 8–13 данных в программе нет — добавьте строки вручную (и в любое
            другое приложение, если чего-то не хватает). В шапках меняются год и дата заполнения, остальное — как в
            шаблоне; без своего шаблона берётся «Таблицы 2026 ЗАПОЛНЯТЬ ЗДЕСЬ». Если участок культур в нескольких
            выделах, задайте на его карточке части по выделам — тогда будет строка на каждый подвыдел.
          </p>
        </div>
      </Card>

      {data ? (
        <>
          {data.diagnostika && (
            <DiagnostikaCard d={data.diagnostika} open={data.prilozheniya.every((p) => p.avto === 0)} />
          )}
          <SvodnayaCard rows={data.svodnaya} />
          {data.prilozheniya.map((p) => (
            <PrilozhenieCard key={p.nomer} p={p} god={data.god} lesnichestvo={lesnichestvo.trim()} onChanged={load} />
          ))}
        </>
      ) : (
        <Card>
          <EmptyState icon="📄" title="Выберите год и нажмите «Показать»" description="Или сразу «Скачать Word»." />
        </Card>
      )}
    </div>
  );
}
