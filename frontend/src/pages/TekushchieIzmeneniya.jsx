import React, { useCallback, useEffect, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import TextField from "../components/TextField.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

/**
 * «Текущие изменения» (приказ Минлесхоза №130 от 10.06.2026) — ведомости
 * для РУП «Белгослес». Пока прил. 4, 7, 14 из «Лесных культур»: на экране
 * строки и замечания (чего не хватает), кнопка — Word по шаблону
 * «Таблицы … ЗАПОЛНЯТЬ ЗДЕСЬ» (встроенному или своему). См.
 * backend/app/tekushchie_izmeneniya.py.
 */

async function downloadDocx(formData, fallbackName) {
  const token = localStorage.getItem("lesovod_token");
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE_URL}/tekushchie-izmeneniya/lesokultury/docx`, {
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
  URL.revokeObjectURL(url);
}

function PrilozhenieCard({ p }) {
  const [showAll, setShowAll] = useState(false);
  const rows = showAll ? p.rows : p.rows.slice(0, 15);
  return (
    <Card>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-ui font-extrabold text-pine text-[14px]">{p.title}</h3>
          <span className="text-xs text-muted">
            участков: {p.uchastki} · строк: {p.rows.length}
          </span>
        </div>
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
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-t border-border">
                    {r.map((v, j) => (
                      <td key={j} className="p-1.5 whitespace-nowrap">{v || <span className="text-faint">—</span>}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {p.rows.length > 15 && (
          <div>
            <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Свернуть" : `Показать все ${p.rows.length}`}
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function TekushchieIzmeneniya() {
  const toast = useToast();
  const [god, setGod] = useState(String(new Date().getFullYear()));
  const [lesnichestvo, setLesnichestvo] = useState("");
  const [shablon, setShablon] = useState(null);
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
      setData(await api.get("/tekushchie-izmeneniya/lesokultury", { god, lesnichestvo: lesnichestvo.trim() || undefined }));
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
            Заполняются прил. 4, 7 и 14 из «Лесокультур»; остальные приложения и шапки шаблона остаются как есть,
            меняются только год и дата заполнения. Без своего шаблона берётся «Таблицы 2026 ЗАПОЛНЯТЬ ЗДЕСЬ».
            Если участок в нескольких выделах, задайте на его карточке части по выделам — тогда в ведомости будет
            строка на каждый подвыдел.
          </p>
        </div>
      </Card>

      {data ? (
        data.prilozheniya.map((p) => <PrilozhenieCard key={p.nomer} p={p} />)
      ) : (
        <Card>
          <EmptyState icon="📄" title="Выберите год и нажмите «Показать»" description="Или сразу «Скачать Word»." />
        </Card>
      )}
    </div>
  );
}
