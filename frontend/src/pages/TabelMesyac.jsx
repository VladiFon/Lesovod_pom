import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";
import { openChelovek } from "../components/ChelovekLink.jsx";
import { napechatat } from "../components/pechat.js";

/**
 * Табель за месяц (разбор сайта 09.11.2026, шаг 2).
 *
 * Сетка «люди × числа» поверх GET /api/tabel/mesyac. Протянул мышкой по
 * клеткам (или Shift+клик) — выбрал людей и дни, нажал статус на панели или
 * букву на клавиатуре (Я, В, Б, О, К, Н, Р; Delete — стереть) — готово.
 * «Пустые будни → Я» заполняет явкой всё, что не заполнено, до сегодня.
 * Каждое заполнение можно вернуть кнопкой в всплывашке.
 *
 * Место работы и вид работы ставятся по-прежнему на вкладке «Ввод табеля»
 * (по дню); здесь — только статус дня. Клетка с точкой — место указано.
 */
const MESYACY = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];

const STATUSY = [
  { st: "работал", kod: "Я", label: "Явка", klav: ["я", "z", "1"], cls: "bg-[#dff3e3] text-pine" },
  { st: "выходной", kod: "В", label: "Выходной", klav: ["в", "d", "2"], cls: "bg-[#ecebe6] text-muted-2" },
  { st: "больничный", kod: "Б", label: "Больничный", klav: ["б", ",", "3"], cls: "bg-[#fbe2e0] text-[#a3201b]" },
  { st: "отпуск", kod: "ОТ", label: "Отпуск", klav: ["о", "j", "4"], cls: "bg-[#e1ecf6] text-info" },
  { st: "командировка", kod: "К", label: "Командировка", klav: ["к", "r", "5"], cls: "bg-[#efe6fa] text-[#5b3d8a]" },
  { st: "ремонт", kod: "РМ", label: "Ремонт техники", klav: ["р", "h", "6"], cls: "bg-[#fdf1e4] text-[#8a5a00]" },
  { st: "не работал", kod: "НН", label: "Неявка", klav: ["н", "y", "7"], cls: "bg-[#fbeaea] text-error" },
];
const PO_STATUSU = Object.fromEntries(STATUSY.map((s) => [s.st, s]));

function tekushchiyYm() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function sdvig(ym, n) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function nazvanie(ym) {
  const [y, m] = ym.split("-").map(Number);
  return `${MESYACY[m - 1]} ${y}`;
}

export default function TabelMesyac() {
  const toast = useToast();
  const [ym, setYm] = useState(tekushchiyYm);
  const [t, setT] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(null); // {r0, d0, r1, d1} — индексы строк и дней
  const tyanu = useRef(false);
  const setkaRef = useRef(null);

  const zagruzit = useCallback(() => {
    setLoading(true);
    api.get("/tabel/mesyac", { ym })
      .then(setT)
      .catch(() => setT(null))
      .finally(() => setLoading(false));
  }, [ym]);
  useEffect(() => { zagruzit(); setSel(null); }, [zagruzit]);

  useEffect(() => {
    const up = () => { tyanu.current = false; };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  const segodnya = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const vybrano = useMemo(() => {
    if (!sel || !t) return null;
    const [ra, rb] = [Math.min(sel.r0, sel.r1), Math.max(sel.r0, sel.r1)];
    const [da, db] = [Math.min(sel.d0, sel.d1), Math.max(sel.d0, sel.d1)];
    return {
      ra, rb, da, db,
      lyudi: t.lyudi.slice(ra, rb + 1),
      dni: t.dni.slice(da, db + 1).map((d) => d.den),
    };
  }, [sel, t]);

  // Поставить статус; zapomnit — для «↩ Вернуть» (что было в клетках до этого)
  const primenit = useCallback(async (kletki, status, { opisanie, otmena = false } = {}) => {
    if (!kletki.length || busy) return;
    const bylo = kletki.map(({ sid, den }) => {
      const ch = t.lyudi.find((x) => x.id === sid);
      return { sid, den, status: ch?.dni[String(den)]?.status || "" };
    });
    // сгруппировать в пачки «одни и те же люди × одни и те же дни» нельзя
    // в общем случае — шлём по человеку
    const poCheloveku = {};
    kletki.forEach(({ sid, den }) => { (poCheloveku[sid] = poCheloveku[sid] || []).push(den); });
    setBusy(true);
    try {
      let otvet = null;
      for (const [sid, dni] of Object.entries(poCheloveku)) {
        otvet = await api.post("/tabel/mesyac/zapolnit", { ym, sotrudnik_ids: [Number(sid)], dni, status });
      }
      if (otvet) setT(otvet);
      if (!otmena) {
        toast.show({
          tone: "success",
          title: opisanie || (status ? `${PO_STATUSU[status]?.label}: ${kletki.length} дн.` : `Стёрто: ${kletki.length} дн.`),
          duration: 9000,
          action: {
            label: "↩ Вернуть",
            onClick: async () => {
              const poStatusu = {};
              bylo.forEach((b) => { (poStatusu[b.status] = poStatusu[b.status] || []).push(b); });
              setBusy(false);
              for (const [st, kl] of Object.entries(poStatusu)) {
                // eslint-disable-next-line no-await-in-loop
                await primenit(kl, st, { otmena: true });
              }
              toast.show({ tone: "info", title: "Вернул как было" });
            },
          },
        });
      }
    } catch (e) {
      toast.show({ tone: "danger", title: "Не сохранилось", description: e.message });
    } finally {
      setBusy(false);
    }
  }, [busy, t, ym, toast]);

  const postavit = useCallback((status) => {
    if (!vybrano) return;
    const kletki = [];
    vybrano.lyudi.forEach((ch) => vybrano.dni.forEach((den) => kletki.push({ sid: ch.id, den })));
    primenit(kletki, status);
  }, [vybrano, primenit]);

  const pustyeBudni = useCallback(() => {
    if (!t) return;
    const lyudi = vybrano ? vybrano.lyudi : t.lyudi;
    const kletki = [];
    lyudi.forEach((ch) => t.dni.forEach((d) => {
      if (d.vyhodnoy || d.data > segodnya || ch.dni[String(d.den)]) return;
      kletki.push({ sid: ch.id, den: d.den });
    }));
    if (!kletki.length) {
      toast.show({ tone: "info", title: "Пустых будней нет", description: "Всё до сегодняшнего дня уже заполнено." });
      return;
    }
    primenit(kletki, "работал", { opisanie: `Явка в пустые будни: ${kletki.length} дн.` });
  }, [t, vybrano, segodnya, primenit, toast]);

  // клавиатура: буква статуса / Delete / Esc
  useEffect(() => {
    const onKey = (e) => {
      if (!vybrano) return;
      if (e.target.closest?.("input, textarea, select, [contenteditable]")) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "escape") { setSel(null); return; }
      if (k === "delete" || k === "backspace") { e.preventDefault(); postavit(""); return; }
      const s = STATUSY.find((x) => x.klav.includes(k));
      if (s) { e.preventDefault(); postavit(s.st); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [vybrano, postavit]);

  const skachat = async () => {
    const token = localStorage.getItem("lesovod_token");
    try {
      const res = await fetch(`${API_BASE_URL}/tabel/mesyac.xlsx?ym=${ym}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(`Ошибка ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `Табель ${nazvanie(ym)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
    } catch (e) {
      toast.show({ tone: "danger", title: "Excel не скачался", description: e.message });
    }
  };

  const vKletke = (r, di) => vybrano && r >= vybrano.ra && r <= vybrano.rb && di >= vybrano.da && di <= vybrano.db;

  const nachat = (r, di, e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (e.shiftKey && sel) setSel({ ...sel, r1: r, d1: di });
    else setSel({ r0: r, d0: di, r1: r, d1: di });
    tyanu.current = true;
  };
  const tyanut = (r, di) => {
    if (tyanu.current) setSel((s) => (s ? { ...s, r1: r, d1: di } : s));
  };

  const vsegoPusto = t ? t.lyudi.reduce((a, ch) => a + ch.itogo.pusto, 0) : 0;

  return (
    <div className="p-6 flex flex-col gap-4">
      {/* шапка: месяц и действия */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-surface border border-border rounded-lg shadow-card p-1">
          <button type="button" onClick={() => setYm(sdvig(ym, -1))} className="h-8 w-8 rounded-md hover:bg-hover text-muted" title="Прошлый месяц">‹</button>
          <div className="px-3 min-w-[150px] text-center font-ui font-extrabold text-pine capitalize">{nazvanie(ym)}</div>
          <button type="button" onClick={() => setYm(sdvig(ym, 1))} className="h-8 w-8 rounded-md hover:bg-hover text-muted" title="Следующий месяц">›</button>
          {ym !== tekushchiyYm() && (
            <button type="button" onClick={() => setYm(tekushchiyYm())} className="h-8 px-2.5 rounded-md hover:bg-hover text-[12px] text-pine font-semibold">сейчас</button>
          )}
        </div>
        {t && (
          <div className="text-[12.5px] text-muted">
            рабочих дней по календарю: <b className="text-ink">{t.rabochih_dney}</b>
            {vsegoPusto > 0 && <span className="ml-2 text-[#8a5a00]">· не заполнено будней: <b>{vsegoPusto}</b></span>}
          </div>
        )}
        <div className="flex-1" />
        <Button variant="secondary" onClick={pustyeBudni} disabled={busy || !t} title="Всем (или выделенным) поставить явку в будни, где ничего не стоит, — до сегодняшнего дня">
          ⚡ Пустые будни → Я{vybrano ? ` (${vybrano.lyudi.length} чел.)` : ""}
        </Button>
        <Button variant="secondary" onClick={skachat} disabled={!t}>↓ Excel (Т-13)</Button>
        <Button variant="secondary" onClick={() => napechatat(setkaRef.current, { title: `Табель учёта рабочего времени · ${nazvanie(ym)}`, landscape: true })} disabled={!t}>
          🖨 Печать
        </Button>
      </div>

      {/* панель статусов */}
      <div className={["sticky top-0 z-10 flex items-center gap-1.5 flex-wrap rounded-lg border px-3 py-2 transition-colors",
        vybrano ? "bg-[#f2faf3] border-[#bcefc5]" : "bg-surface-alt border-border"].join(" ")}>
        <span className="text-[12.5px] font-semibold text-muted mr-1">
          {vybrano ? `Выделено: ${vybrano.lyudi.length} чел. × ${vybrano.dni.length} дн. — поставить:` : "Протяните мышкой по клеткам, затем выберите статус или нажмите букву:"}
        </span>
        {STATUSY.map((s) => (
          <button
            key={s.st}
            type="button"
            disabled={!vybrano || busy}
            onClick={() => postavit(s.st)}
            title={`${s.label} — клавиша ${s.klav[0].toUpperCase()} или ${s.klav[2]}`}
            className={["h-7 px-2 rounded-md text-[12px] font-bold border border-transparent disabled:opacity-50 hover:border-pine transition-colors", s.cls].join(" ")}
          >
            {s.kod} <span className="font-medium">{s.label}</span>
          </button>
        ))}
        <button type="button" disabled={!vybrano || busy} onClick={() => postavit("")}
          className="h-7 px-2 rounded-md text-[12px] font-semibold border border-border bg-surface text-muted disabled:opacity-50 hover:border-error hover:text-error">
          ⌫ Стереть
        </button>
        {vybrano && (
          <button type="button" onClick={() => setSel(null)} className="ml-auto h-7 px-2 text-[12px] text-faint hover:text-ink">Снять выделение (Esc)</button>
        )}
      </div>

      {loading && !t ? (
        <div className="text-muted p-6">Загружаю табель…</div>
      ) : !t || !t.lyudi.length ? (
        <EmptyState title="Нет сотрудников" description="Добавьте людей в разделе «Люди» — и здесь появится сетка на месяц." />
      ) : (
        <Card padding={false} className="overflow-hidden">
          <div ref={setkaRef} className="overflow-x-auto select-none">
            <table data-no-export className="border-collapse text-[12px] w-max min-w-full">
              <thead>
                <tr className="bg-surface-alt">
                  <th className="sticky left-0 z-[2] bg-surface-alt text-left px-3 py-1.5 font-semibold text-muted border-b border-border min-w-[190px]">Сотрудник</th>
                  {t.dni.map((d, di) => (
                    <th
                      key={d.den}
                      title={d.prazdnik ? `Праздник: ${d.prazdnik}` : d.data}
                      onMouseDown={(e) => { e.preventDefault(); setSel({ r0: 0, d0: di, r1: t.lyudi.length - 1, d1: di }); }}
                      className={["w-[30px] px-0 py-1 border-b border-l border-border text-center cursor-pointer leading-tight",
                        d.vyhodnoy ? "bg-[#ecebe6] text-[#8a5a00]" : "text-muted",
                        d.data === segodnya ? "!bg-[#bcefc5] !text-pine" : ""].join(" ")}
                    >
                      <div className="font-bold text-[12px]">{d.den}</div>
                      <div className="text-[9.5px] font-normal">{d.nedelya}</div>
                    </th>
                  ))}
                  <th className="px-2 border-b border-l border-border text-[10.5px] text-muted font-semibold" title="Дней явок (Я, К, РМ)">Явки</th>
                  <th className="px-2 border-b border-l border-border text-[10.5px] text-muted font-semibold">Часы</th>
                  <th className="px-2 border-b border-l border-border text-[10.5px] text-muted font-semibold" title="Больничный">Б</th>
                  <th className="px-2 border-b border-l border-border text-[10.5px] text-muted font-semibold" title="Отпуск">ОТ</th>
                  <th className="px-2 border-b border-l border-border text-[10.5px] text-muted font-semibold" title="Неявки">НН</th>
                </tr>
              </thead>
              <tbody>
                {t.lyudi.map((ch, r) => (
                  <tr key={ch.id} className="group">
                    <td className="sticky left-0 z-[1] bg-surface group-hover:bg-[#f7f5ef] px-3 py-1 border-b border-border">
                      <button type="button" onClick={() => openChelovek(ch.id)} className="text-left font-semibold text-ink hover:text-pine hover:underline leading-tight">
                        {ch.fio}
                      </button>
                      {ch.dolzhnost && <div className="text-[10.5px] text-faint leading-tight">{ch.dolzhnost}</div>}
                    </td>
                    {t.dni.map((d, di) => {
                      const z = ch.dni[String(d.den)];
                      const s = z ? PO_STATUSU[z.status] : null;
                      const v = vKletke(r, di);
                      return (
                        <td
                          key={d.den}
                          onMouseDown={(e) => nachat(r, di, e)}
                          onMouseEnter={() => tyanut(r, di)}
                          title={`${ch.fio}, ${d.den} ${MESYACY[Number(ym.slice(5)) - 1]}: ${s ? s.label : "не заполнено"}${z?.mesto ? " · место указано" : ""}`}
                          className={["relative h-8 border-b border-l border-border text-center p-0 cursor-cell",
                            d.vyhodnoy && !s ? "bg-[#f4f3ef]" : "",
                            v ? "outline outline-2 -outline-offset-2 outline-pine" : ""].join(" ")}
                        >
                          {s && (
                            <span className={["absolute inset-[2px] rounded-[5px] flex items-center justify-center font-bold text-[11px]", s.cls].join(" ")}>
                              {s.kod}
                              {z.mesto && <span className="absolute top-[2px] right-[3px] h-[4px] w-[4px] rounded-full bg-current opacity-60" />}
                            </span>
                          )}
                          {!s && !d.vyhodnoy && d.data <= segodnya && <span data-no-print className="text-[#d9d4c8]">·</span>}
                        </td>
                      );
                    })}
                    <td className="px-2 border-b border-l border-border text-center font-bold text-pine tabular-nums">{ch.itogo.yavki || ""}</td>
                    <td className="px-2 border-b border-l border-border text-center tabular-nums">{ch.itogo.chasov || ""}</td>
                    <td className="px-2 border-b border-l border-border text-center tabular-nums text-[#a3201b]">{ch.itogo.bolnichnyy || ""}</td>
                    <td className="px-2 border-b border-l border-border text-center tabular-nums text-info">{ch.itogo.otpusk || ""}</td>
                    <td className="px-2 border-b border-l border-border text-center tabular-nums text-error">{ch.itogo.nn || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="hidden print:flex justify-between gap-8 mt-6 text-[11px]">
              <span>Табель составил: ____________________</span>
              <span>Руководитель: ____________________</span>
            </div>
          </div>
        </Card>
      )}
      <div className="text-[11.5px] text-faint leading-relaxed">
        Клик по числу в шапке — выделить весь день. Shift+клик — продлить выделение. Точка в углу клетки — указано место работы
        (делянка, культуры или проба; ставится на вкладке «Ввод табеля»). Если человека перевести с «Я» на отпуск/больничный, место за этот день стирается.
      </div>
    </div>
  );
}
