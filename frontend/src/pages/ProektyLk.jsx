import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import { useToast } from "../components/Toast.jsx";
import AuthImage from "../components/AuthImage.jsx";
import Modal from "../components/Modal.jsx";
import { openScreen } from "../nav.js";

/**
 * «📐 Проекты» (Влад, 12.11.2026) — проекты лесных культур, прил. 5 к
 * Положению о порядке ЛВ и ЛР. Проекты составляются в АРМ ЛВ и сохраняются
 * в Word (.doc) — здесь они загружаются пачкой (предпросмотр → «Занести»,
 * повторная загрузка без дублей), привязываются к делянке и проверяются по
 * нормам (густота по ТЛУ, размещение по ТКП 667). Исходный файл и план
 * участка хранятся в базе — перепечатать, если бумага потеряется.
 * Сервер: routers/lk_proekty.py, логика — app/lk_proekt.py.
 */

const C = { pine: "var(--color-pine)", line: "var(--color-border)", muted: "var(--color-muted-2)", sun: "var(--c-gold-soft)", danger: "var(--color-error)", ok: "var(--color-mint-soft)" };
const btn = { background: C.pine, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700, fontSize: 13 };
const btn2 = { border: `1px solid ${C.line}`, background: "var(--color-surface)", borderRadius: 8, padding: "6px 10px", fontSize: 13 };
const karta = { background: "var(--color-surface)", border: `1px solid ${C.line}`, borderRadius: 12, padding: 14 };
const STATUSY = [
  ["proekt", "Проект"],
  ["utverzhden", "Утверждён"],
  ["posazhen", "Посажено"],
  ["prinyat", "Принят (техприёмка)"],
  ["otmenen", "Отменён"],
];
const statusTekst = Object.fromEntries(STATUSY);
const tys = (n) => (n == null ? "—" : Math.round(n).toLocaleString("ru-RU"));

async function skachat(path, imya) {
  const token = localStorage.getItem("lesovod_token");
  const res = await fetch(`${API_BASE_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Ошибка сервера (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = imya;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function Proverki({ spisok }) {
  if (!spisok || spisok.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {spisok.map((x, i) => (
        <li key={i} style={{ color: x.uroven === "oshibka" ? C.danger : x.uroven === "ok" ? C.pine : "var(--color-ink)" }}>
          {x.uroven === "oshibka" ? "⛔ " : x.uroven === "ok" ? "✅ " : "⚠ "}
          {x.tekst}
        </li>
      ))}
    </ul>
  );
}

const shema = (porody) =>
  (porody || []).map((x) => `${x.poroda} ${x.mezhduryade}×${x.shag}`).filter((v, i, a) => a.indexOf(v) === i).join(", ");

export default function ProektyLk() {
  const toast = useToast();
  const [spisok, setSpisok] = useState(null);
  const [god, setGod] = useState("");
  const [status, setStatus] = useState("");
  const [vybran, setVybran] = useState(null);
  const [importOpen, setImportOpen] = useState(false);
  const [potr, setPotr] = useState(null);
  const oshibka = (title) => (e) => toast.show({ tone: "danger", title, description: e.message });

  const load = useCallback(async () => {
    try {
      setSpisok(await api.get("/lk-proekty", { god: god || undefined, status: status || undefined }));
    } catch (e) {
      oshibka("Проекты не загрузились")(e);
      setSpisok([]);
    }
  }, [god, status]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const gody = useMemo(() => {
    const s = new Set((spisok || []).map((x) => x.god).filter(Boolean));
    const t = new Date().getFullYear();
    [t, t + 1].forEach((g) => s.add(g));
    return [...s].sort((a, b) => b - a);
  }, [spisok]);

  useEffect(() => {
    api.get("/lk-proekty/potrebnost", { god: god || undefined }).then(setPotr).catch(() => setPotr(null));
  }, [god, spisok]);

  const itog = useMemo(() => {
    const s = (spisok || []).filter((x) => x.status !== "otmenen");
    return { n: s.length, ga: s.reduce((a, x) => a + (x.ploshad || 0), 0), sht: s.reduce((a, x) => a + (x.vsego || 0), 0) };
  }, [spisok]);

  return (
    <div className="p-[18px] flex flex-col gap-[14px]">
      <div style={karta} className="flex flex-wrap items-center gap-3">
        <button style={btn} onClick={() => setImportOpen(true)}>⬆ Загрузить проекты из АРМ ЛВ</button>
        <select value={god} onChange={(e) => setGod(e.target.value)} className="border border-border rounded-[8px] px-2 h-9">
          <option value="">Все годы</option>
          {gody.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="border border-border rounded-[8px] px-2 h-9">
          <option value="">Все статусы</option>
          {STATUSY.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="text-sm" style={{ color: C.muted }}>
          {itog.n} проект(ов) · {itog.ga.toFixed(1)} га · {tys(itog.sht)} шт. посадочного материала
        </span>
      </div>

      <div className="flex flex-wrap gap-[14px] items-start">
        <div style={{ ...karta, flex: "2 1 560px", padding: 0, overflowX: "auto" }}>
          {spisok === null ? (
            <div className="p-5 text-sm" style={{ color: C.muted }}>Загрузка…</div>
          ) : spisok.length === 0 ? (
            <div className="p-6 text-sm" style={{ color: C.muted }}>
              Проектов пока нет. Нажмите «⬆ Загрузить проекты из АРМ ЛВ» и выберите файлы проектов (.doc или .docx) — можно сразу пачкой.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left" style={{ color: C.muted, borderBottom: `1px solid ${C.line}` }}>
                  {["Сезон", "Кв.", "Выделы", "Га", "ТЛУ", "Схема смешения", "Размещение", "шт./га", "Всего", "Делянка", "Статус", ""].map((h) => (
                    <th key={h} className="px-2 py-2 font-semibold whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {spisok.map((x) => (
                  <tr
                    key={x.id}
                    onClick={() => setVybran(x.id)}
                    className="cursor-pointer hover:bg-hover"
                    style={{ borderBottom: `1px solid ${C.line}`, background: vybran === x.id ? C.ok : undefined }}
                  >
                    <td className="px-2 py-2 whitespace-nowrap">{x.sezon} {x.god}</td>
                    <td className="px-2 py-2 font-bold">{x.kvartal}</td>
                    <td className="px-2 py-2">{x.vydely}</td>
                    <td className="px-2 py-2">{x.ploshad}</td>
                    <td className="px-2 py-2 whitespace-nowrap">{x.tlu}</td>
                    <td className="px-2 py-2">{x.shema_smesheniya}</td>
                    <td className="px-2 py-2 whitespace-nowrap">{shema(x.porody)}</td>
                    <td className="px-2 py-2">{tys(x.na_ga)}</td>
                    <td className="px-2 py-2">{tys(x.vsego)}</td>
                    <td className="px-2 py-2">{x.delyanka || <span style={{ color: C.muted }}>не найдена</span>}</td>
                    <td className="px-2 py-2 whitespace-nowrap">{x.status_tekst}</td>
                    <td className="px-2 py-2" title={(x.proverki || []).map((p) => p.tekst).join("\n")}>
                      {(x.proverki || []).some((p) => p.uroven === "oshibka") ? "⛔" : (x.proverki || []).length ? "⚠" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div style={{ ...karta, flex: "1 1 280px" }}>
          <div className="font-bold mb-2">🌱 Посадочный материал{god ? ` на ${god}` : ""}</div>
          {!potr || potr.stroki.length === 0 ? (
            <div className="text-sm" style={{ color: C.muted }}>Посчитается по загруженным проектам.</div>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {potr.stroki.map((s, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${C.line}` }}>
                    <td className="py-1 font-bold">{s.poroda}</td>
                    <td className="py-1">{s.material || "—"}</td>
                    <td className="py-1 text-right">{tys(s.sht)} шт.</td>
                  </tr>
                ))}
                <tr>
                  <td className="py-1 font-bold" colSpan={2}>Всего</td>
                  <td className="py-1 text-right font-bold">{tys(potr.vsego_sht)} шт.</td>
                </tr>
              </tbody>
            </table>
          )}
          <div className="text-xs mt-2" style={{ color: C.muted }}>Без отменённых проектов. Это и есть заявка в питомник.</div>
        </div>
      </div>

      {vybran && <Kartochka key={vybran} pid={vybran} onChanged={load} onClose={() => setVybran(null)} />}
      {importOpen && <ImportModal onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); load(); }} />}
    </div>
  );
}

function Pole({ n, label, value }) {
  if (value == null || value === "") return null;
  return (
    <div className="text-sm py-1" style={{ borderBottom: `1px dashed ${C.line}` }}>
      <span style={{ color: C.muted }}>{n ? `${n}. ` : ""}{label}: </span>
      <span>{value}</span>
    </div>
  );
}

function Kartochka({ pid, onChanged, onClose }) {
  const toast = useToast();
  const [p, setP] = useState(null);
  const oshibka = (title) => (e) => toast.show({ tone: "danger", title, description: e.message });
  const load = useCallback(() => api.get(`/lk-proekty/${pid}`).then(setP).catch(oshibka("Проект не открылся")), [pid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  if (!p) return <div style={karta} className="text-sm">Загрузка…</div>;
  const f = p.polya || {};
  const smenitStatus = async (s) => {
    try {
      setP(await api.put(`/lk-proekty/${pid}`, { status: s }));
      onChanged();
    } catch (e) { oshibka("Статус не сменился")(e); }
  };
  const udalit = async () => {
    if (!window.confirm("Удалить проект из базы? Файл в АРМ ЛВ останется.")) return;
    try {
      await api.delete(`/lk-proekty/${pid}`);
      onChanged();
      onClose();
    } catch (e) { oshibka("Не удалилось")(e); }
  };
  const d = p.dopuski || {};
  return (
    <div style={karta} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-lg font-bold">
          Проект на {p.sezon} {p.god} · кв. {p.kvartal} выд. {p.vydely} · {p.ploshad} га
        </div>
        <select value={p.status} onChange={(e) => smenitStatus(e.target.value)} className="border border-border rounded-[8px] px-2 h-9">
          {STATUSY.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {p.est_fail && (
          <button style={btn2} onClick={() => skachat(`/lk-proekty/${pid}/fail`, p.fail_imya || `proekt_${pid}.doc`).catch(oshibka("Файл не скачался"))}>
            🖨 Исходный файл из АРМ
          </button>
        )}
        {p.delyanka_id && (
          <button style={btn2} onClick={() => openScreen("plots", { d: p.delyanka_id })}>Делянка: {p.delyanka}</button>
        )}
        <button style={{ ...btn2, color: C.danger }} onClick={udalit}>Удалить</button>
        <button style={btn2} onClick={onClose} className="ml-auto">✕</button>
      </div>
      <div className="text-sm" style={{ color: C.muted }}>{p.lesnichestvo} · {p.leshoz || f.leshoz || ""} · статус: {statusTekst[p.status]}</div>

      <div className="flex flex-wrap gap-4 items-start">
        {p.est_plan && (
          <div style={{ flex: "1 1 320px", maxWidth: 520 }}>
            <AuthImage path={`/lk-proekty/${pid}/plan`} caption={`План участка М 1:10 000${f.plan_tekst ? ` · ${f.plan_tekst}` : ""}`} />
          </div>
        )}
        <div style={{ flex: "1 1 320px" }} className="flex flex-col gap-2">
          <div className="font-bold">Проверка по нормам</div>
          <Proverki spisok={p.proverki} />
          {d.gustota_min && (
            <div className="text-sm p-2 rounded-[8px]" style={{ background: C.sun }}>
              <b>Что примут на техприёмке (п.56):</b> густота от {tys(d.gustota_min)} до {tys(d.gustota_max)} шт./га
              {d.mezhduryade_min ? `, междурядье ${d.mezhduryade_min}–${d.mezhduryade_max} м` : ""}; способ обработки почвы — как в проекте.
            </div>
          )}
        </div>
      </div>

      <div>
        <div className="font-bold mb-1">Посадка по породам (п.14–17)</div>
        <table className="text-sm">
          <thead>
            <tr style={{ color: C.muted }} className="text-left">
              {["Порода", "Рядов", "Междурядье × шаг, м", "шт./га", "Всего, шт.", "Материал"].map((h) => <th key={h} className="pr-4 py-1">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {(f.porody || []).map((x, i) => (
              <tr key={i}>
                <td className="pr-4 py-1 font-bold">{x.poroda}</td>
                <td className="pr-4 py-1">{x.ryadov ?? "—"}</td>
                <td className="pr-4 py-1">{x.mezhduryade} × {x.shag}</td>
                <td className="pr-4 py-1">{tys(x.na_ga)}</td>
                <td className="pr-4 py-1">{tys(x.vsego)}</td>
                <td className="pr-4 py-1">{x.material}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-x-6" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))" }}>
        <Pole n="2" label="Категория площади" value={f.kategoriya_t} />
        <Pole n="3" label="Рельеф" value={f.relef} />
        <Pole n="4" label="Почва" value={f.pochva} />
        <Pole n="5" label="Покров" value={f.pokrov} />
        <Pole n="6" label="Тип леса / ТЛУ" value={f.tip_tlu_t} />
        <Pole n="7" label="Естественное возобновление" value={f.estestv} />
        <Pole n="8" label="Лесопатология" value={f.lesopatologiya} />
        <Pole n="9" label="Обработка почвы" value={f.obrabotka} />
        <Pole n="10" label="Размещение борозд" value={f.razmeshchenie} />
        <Pole n="11" label="Реконструируемое насаждение" value={f.rekonstr_sostav} />
        <Pole n="12" label="Способ реконструкции" value={f.rekonstr_sposob} />
        <Pole n="13" label="Метод и способ" value={f.metod} />
        <Pole n="15" label="Схема смешения" value={f.shema_smesheniya} />
        <Pole n="16" label="Главная порода" value={f.glavnaya_poroda} />
        <Pole n="18" label="Подготовка" value={f.podgotovka} />
        <Pole n="19" label="Уходы по годам" value={(f.uhody || []).map((u) => `${u.god} — ${u.kolichestvo}`).join("; ") || f.uhody_t} />
        <Pole n="20" label="Противопожарные" value={f.protivopozhar} />
        <Pole n="21" label="Год перевода" value={f.god_perevoda} />
        <Pole n="22" label="Потребность" value={f.potrebnost?.posadka_tys ? `${f.potrebnost.posadka_tys_ga} тыс. шт./га, ${f.potrebnost.posadka_tys} тыс. шт. всего` : ""} />
        <Pole label="Составил" value={[f.sostavil, f.data_sostavleniya].filter(Boolean).join(", ")} />
        <Pole label="Согласовал" value={[f.soglasoval, f.data_soglasovaniya].filter(Boolean).join(", ")} />
        <Pole n="23" label="Изменения" value={f.izmeneniya} />
      </div>
      <div className="text-xs" style={{ color: C.muted }}>Файл: {p.fail_imya || "—"} · загружен {p.created_at}{p.updated_at && p.updated_at !== p.created_at ? `, обновлён ${p.updated_at}` : ""}</div>
    </div>
  );
}

function ImportModal({ onClose, onDone }) {
  const toast = useToast();
  const vvod = useRef(null);
  const [faily, setFaily] = useState([]);
  const [plan, setPlan] = useState(null);
  const [propustit, setPropustit] = useState({});
  const [idet, setIdet] = useState(false);
  const fd = (extra) => {
    const x = new FormData();
    faily.forEach((f) => x.append("files", f));
    Object.entries(extra || {}).forEach(([k, v]) => x.append(k, v));
    return x;
  };
  const vybrat = async (spisok) => {
    const arr = [...spisok];
    setFaily(arr);
    setPlan(null);
    if (!arr.length) return;
    setIdet(true);
    try {
      const x = new FormData();
      arr.forEach((f) => x.append("files", f));
      const pl = await api.upload("/lk-proekty/import/preview", x);
      setPlan(pl);
      setPropustit(Object.fromEntries(pl.stroki.filter((s) => s.deystvie === "propustit").map((s) => [s.fail, true])));
    } catch (e) {
      toast.show({ tone: "danger", title: "Файлы не разобрались", description: e.message });
    } finally { setIdet(false); }
  };
  const zanesti = async () => {
    setIdet(true);
    try {
      const r = await api.upload("/lk-proekty/import/apply", fd({ propustit: JSON.stringify(Object.keys(propustit).filter((k) => propustit[k])) }));
      toast.show({ tone: "success", title: `Занесено: новых ${r.sozdano.length}, обновлено ${r.obnovleno.length}` });
      onDone();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не занеслось", description: e.message });
    } finally { setIdet(false); }
  };
  const DEYSTVIE = { novyy: "новый", obnovit: "обновить (уже есть)", propustit: "уже есть, не трогаем" };
  return (
    <Modal open onClose={onClose} title="Загрузить проекты из АРМ ЛВ" size="xl">
      <div className="flex flex-col gap-3">
        <div className="text-sm" style={{ color: C.muted }}>
          Выберите файлы проектов из АРМ ЛВ (.doc или .docx) — можно сразу несколько. Сначала покажу, что в них, потом «Занести».
          Повторная загрузка того же проекта не создаёт дубль — обновит, пока проект не посажен.
        </div>
        <div>
          <input ref={vvod} type="file" multiple accept=".doc,.docx" className="hidden" onChange={(e) => vybrat(e.target.files)} />
          <button style={btn2} onClick={() => vvod.current?.click()}>📂 Выбрать файлы…</button>
          {faily.length > 0 && <span className="text-sm ml-2">{faily.length} файл(ов)</span>}
          {idet && <span className="text-sm ml-2" style={{ color: C.muted }}>разбираю…</span>}
        </div>
        {plan && (
          <>
            <div className="text-sm">
              Новых: <b>{plan.itog.novyh}</b> · обновить: <b>{plan.itog.obnovit}</b> · уже есть: <b>{plan.itog.propustit}</b>
              {plan.itog.bez_delyanki ? <> · без делянки: <b>{plan.itog.bez_delyanki}</b></> : null}
              {plan.itog.oshibok ? <> · <span style={{ color: C.danger }}>не разобрались: <b>{plan.itog.oshibok}</b></span></> : null}
            </div>
            <div style={{ overflowX: "auto", maxHeight: "55vh" }}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left" style={{ color: C.muted }}>
                    {["Занести", "Файл", "Сезон", "Кв./выд.", "Га", "ТЛУ", "Схема", "шт./га", "Делянка", "Проверки"].map((h) => <th key={h} className="px-2 py-1">{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {plan.stroki.map((s) => (
                    <tr key={s.fail} style={{ borderTop: `1px solid ${C.line}`, verticalAlign: "top" }}>
                      {s.oshibka ? (
                        <>
                          <td className="px-2 py-1">—</td>
                          <td className="px-2 py-1">{s.fail}</td>
                          <td className="px-2 py-1" colSpan={8} style={{ color: C.danger }}>{s.oshibka}</td>
                        </>
                      ) : (
                        <>
                          <td className="px-2 py-1">
                            <label className="flex items-center gap-1 whitespace-nowrap">
                              <input type="checkbox" checked={!propustit[s.fail]} onChange={(e) => setPropustit({ ...propustit, [s.fail]: !e.target.checked })} />
                              {DEYSTVIE[s.deystvie]}
                            </label>
                          </td>
                          <td className="px-2 py-1">{s.fail}</td>
                          <td className="px-2 py-1 whitespace-nowrap">{s.proekt.sezon} {s.proekt.god}</td>
                          <td className="px-2 py-1 whitespace-nowrap">кв.{s.proekt.kvartal} в.{s.proekt.vydely}</td>
                          <td className="px-2 py-1">{s.proekt.ploshad}</td>
                          <td className="px-2 py-1">{s.proekt.tlu}</td>
                          <td className="px-2 py-1">{s.proekt.shema_smesheniya}</td>
                          <td className="px-2 py-1">{tys(s.proekt.na_ga)}</td>
                          <td className="px-2 py-1">
                            {s.delyanka ? (
                              <>
                                {s.delyanka.nazvanie}
                                {s.delyanka.akt ? <span style={{ color: C.muted }}> · акт {s.delyanka.akt}</span> : null}
                                {s.delyanka.drugie?.length ? <div className="text-xs" style={{ color: C.muted }}>есть ещё {s.delyanka.drugie.length} (дубль?) — взял с актом</div> : null}
                              </>
                            ) : <span style={{ color: C.muted }}>не найдена</span>}
                          </td>
                          <td className="px-2 py-1"><Proverki spisok={s.proverki.filter((x) => x.uroven !== "ok")} /></td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex gap-2 justify-end">
              <button style={btn2} onClick={onClose}>Отмена</button>
              <button style={btn} disabled={idet} onClick={zanesti}>Занести</button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
