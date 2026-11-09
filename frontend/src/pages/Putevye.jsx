import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useScreenParam } from "../nav.js";
import { useToast } from "../components/Toast.jsx";
import { napechatat } from "../components/pechat.js";

/**
 * «📝 Путевые листы» (09.11.2026, просьба Влада). Листы пишутся рукой —
 * экран подсказывает, что вписать. Вводится только пробег и заправка,
 * остальное считается цепочкой с прошлого листа машины:
 *   спидометр возврат = выезд + пробег;
 *   остаток выезд = остаток возврат прошлого листа + заправка;
 *   остаток возврат = остаток выезд − пробег × норма (л/км).
 * «Заполнить месяц» раскладывает пробег и заправки по рабочим дням 5/2
 * (праздники РБ, отпуск/больничный водителя по табелю).
 * Сервер: routers/putevye.py, логика — app/putevye.py.
 */

const C = { pine: "#1a4331", line: "#e5e2db", muted: "#565f59", moss: "#eaf7ec", danger: "#ba1a1a", gold: "#b07d0c", goldSoft: "#fbf1d6", grey: "#f4f3f0", info: "#2f5d8a" };
const inp = "border border-border rounded-[8px] px-2 h-9";
const DN = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const MES = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];

const num = (v, d = 1) => (v == null || v === "" ? "" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: d }));
const toNum = (s) => {
  if (s == null || String(s).trim() === "") return null;
  const n = Number(String(s).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : NaN;
};
function sdvig(mesyac, k) {
  const [g, m] = mesyac.split("-").map(Number);
  const d = new Date(g, m - 1 + k, 1, 12);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const segodnyaMes = () => new Date().toISOString().slice(0, 7);
const ddmm = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

function Plashka({ title, value, sub, tone }) {
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: "8px 14px", minWidth: 140 }}>
      <div style={{ fontSize: 12, color: C.muted }}>{title}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: tone || C.pine }}>{value}</div>
      {sub && <div style={{ fontSize: 11.5, color: C.muted }}>{sub}</div>}
    </div>
  );
}

function Preduprezhdeniya({ list, onZapravka }) {
  if (!list?.length) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {list.map((p, i) => (
        <span key={i} style={{ fontSize: 11.5, color: p.ton === "danger" ? C.danger : p.ton === "warn" ? C.gold : C.info }}>
          {p.ton === "danger" ? "⚠ " : p.ton === "warn" ? "• " : "📱 "}{p.text}
          {p.zapravka_iz_smeny != null && onZapravka && (
            <button type="button" onClick={() => onZapravka(p.zapravka_iz_smeny)} style={{ marginLeft: 6, textDecoration: "underline" }}>поставить</button>
          )}
        </span>
      ))}
    </div>
  );
}

/** Ячейка ввода: сохраняет по Enter / уходу с поля. */
function Vvod({ value, onSave, disabled, width = 76, placeholder }) {
  const [v, setV] = useState(value ?? "");
  useEffect(() => { setV(value ?? ""); }, [value]);
  const commit = () => {
    if (String(v) === String(value ?? "")) return;
    const n = toNum(v);
    if (Number.isNaN(n)) { setV(value ?? ""); return; }
    onSave(n ?? 0);
  };
  return (
    <input className={inp} style={{ width, textAlign: "right", background: disabled ? C.grey : "#fff" }} value={v} disabled={disabled}
      placeholder={placeholder} inputMode="decimal"
      onChange={(e) => setV(e.target.value)} onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") { e.currentTarget.blur(); } }} />
  );
}

// Подпись над полем. Объявлена на уровне модуля: компонент, созданный
// внутри render, пересоздаётся на каждую букву и поле теряет фокус.
function L({ t, children, flex }) {
  return <label style={{ fontSize: 12, color: C.muted, flex, minWidth: flex ? 160 : undefined }}>{t}<br />{children}</label>;
}

// ------------------------------------------------------------ карточка ---

function Kartochka({ m, d, edinica, onSaved, toast }) {
  const [f, setF] = useState(null);
  const [nn, setNn] = useState({ s_daty: `${new Date().toISOString().slice(0, 7)}-01`, norma: "" });
  useEffect(() => {
    setF({ marka: m.marka || "", edinica: m.edinica || "км", bak_l: m.bak_l ?? "", start_data: m.start_data || "",
      start_spidometr: m.start_spidometr ?? "", start_ostatok: m.start_ostatok ?? "",
      vremya_vyezd: m.vremya_vyezd || "08:00", vremya_vozvrat: m.vremya_vozvrat || "17:00", marshrut: m.marshrut || "" });
  }, [m.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!f) return null;
  const sohranit = async () => {
    const body = { ...f };
    for (const k of ["bak_l", "start_spidometr", "start_ostatok"]) {
      const n = toNum(body[k]);
      if (Number.isNaN(n)) return toast.show({ tone: "danger", title: "Число не распознано", description: k });
      body[k] = n;
    }
    body.start_data = body.start_data || null;
    try {
      await api.put(`/putevye/mashina/${m.id}`, body);
      toast.show({ tone: "success", title: "Карточка сохранена", description: "Листы пересчитаны" });
      onSaved();
    } catch (e) { toast.show({ tone: "danger", title: "Не сохранилось", description: e.message }); }
  };
  const dobavitNormu = async () => {
    const n = toNum(nn.norma);
    if (!n || Number.isNaN(n)) return toast.show({ tone: "danger", title: "Впишите норму, например 0,1392" });
    try {
      const r = await api.post(`/putevye/mashina/${m.id}/norma`, { s_daty: nn.s_daty, norma: n });
      toast.show({ tone: "success", title: "Норма сохранена", description: r.pereschitano ? `Пересчитано листов: ${r.pereschitano}` : undefined });
      setNn({ ...nn, norma: "" });
      onSaved();
    } catch (e) { toast.show({ tone: "danger", title: "Норма не сохранилась", description: e.message }); }
  };
  const udalitNormu = async (x) => {
    if (!window.confirm(`Удалить норму ${x.norma} с ${x.s_daty}? Листы с этой даты пересчитаются.`)) return;
    try { await api.delete(`/putevye/norma/${x.id}`); onSaved(); } catch (e) { toast.show({ tone: "danger", title: "Не удалилось", description: e.message }); }
  };
  return (
    <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ fontWeight: 800, color: C.pine }}>🪪 Карточка «{m.nazvanie}» для путевых</div>
      <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
        <L t="Марка"><input className={inp} value={f.marka} onChange={(e) => setF({ ...f, marka: e.target.value })} placeholder="УАЗ-3909" style={{ width: 130 }} /></L>
        <L t="Учёт пробега"><select className={inp} value={f.edinica} onChange={(e) => setF({ ...f, edinica: e.target.value })}>
          {d.edinicy.map((x) => <option key={x} value={x}>{x === "км" ? "километры (спидометр)" : "моточасы (счётчик)"}</option>)}</select></L>
        <L t="⛽ Объём бака, л"><input className={inp} value={f.bak_l} onChange={(e) => setF({ ...f, bak_l: e.target.value })} placeholder="78" style={{ width: 90 }} inputMode="decimal" /></L>
        <L t="Начать учёт с"><input type="date" className={inp} value={f.start_data} onChange={(e) => setF({ ...f, start_data: e.target.value })} /></L>
        <L t={edinica === "км" ? "Спидометр на старте" : "Счётчик на старте"}><input className={inp} value={f.start_spidometr} onChange={(e) => setF({ ...f, start_spidometr: e.target.value })} placeholder="306715" style={{ width: 110 }} inputMode="decimal" /></L>
        <L t="В баке на старте, л"><input className={inp} value={f.start_ostatok} onChange={(e) => setF({ ...f, start_ostatok: e.target.value })} placeholder="20" style={{ width: 90 }} inputMode="decimal" /></L>
      </div>
      <div className="flex flex-wrap items-end" style={{ gap: 10 }}>
        <L t="Выезд"><input type="time" className={inp} value={f.vremya_vyezd} onChange={(e) => setF({ ...f, vremya_vyezd: e.target.value })} /></L>
        <L t="Возврат"><input type="time" className={inp} value={f.vremya_vozvrat} onChange={(e) => setF({ ...f, vremya_vozvrat: e.target.value })} /></L>
        <label style={{ fontSize: 12, color: C.muted, flex: 1, minWidth: 200 }}>Маршрут по умолчанию<br /><input className={inp + " w-full"} value={f.marshrut} onChange={(e) => setF({ ...f, marshrut: e.target.value })} placeholder="Болбасово — лесничество — делянки" /></label>
        <button type="button" onClick={sohranit} style={{ background: C.pine, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>Сохранить карточку</button>
      </div>
      <div style={{ borderTop: `1px solid ${C.line}`, paddingTop: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Норма расхода, л на 1 {edinica}</div>
        <div className="flex flex-wrap items-center" style={{ gap: 8, fontSize: 13 }}>
          {m.normy?.length ? m.normy.map((x, i) => (
            <span key={x.id} style={{ background: i === m.normy.length - 1 ? C.moss : C.grey, borderRadius: 8, padding: "4px 8px" }}>
              <b>{String(x.norma).replace(".", ",")}</b> с {ddmm(x.s_daty)}.{x.s_daty.slice(2, 4)}
              <button type="button" onClick={() => udalitNormu(x)} title="Удалить" style={{ marginLeft: 6, color: C.muted }}>×</button>
            </span>
          )) : <span style={{ color: C.danger }}>норма не задана — расход не посчитается</span>}
          <span style={{ color: C.muted }}>· новая:</span>
          <input className={inp} style={{ width: 90 }} value={nn.norma} onChange={(e) => setNn({ ...nn, norma: e.target.value })} placeholder="0,1392" inputMode="decimal" />
          <span style={{ color: C.muted }}>с</span>
          <input type="date" className={inp} value={nn.s_daty} onChange={(e) => setNn({ ...nn, s_daty: e.target.value })} />
          <button type="button" onClick={dobavitNormu} style={{ border: `1px solid ${C.pine}`, color: C.pine, borderRadius: 8, padding: "6px 10px", fontWeight: 700 }}>＋ Норма</button>
        </div>
        <div style={{ fontSize: 11.5, color: C.muted, marginTop: 4 }}>Новая норма действует с выбранной даты: старые листы считаются по старой (зимняя надбавка — просто норма с 1 ноября, летняя — с 1 апреля).</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------- «Заполнить месяц» ---

function Generator({ d, lyudi, onClose, onSaved, toast }) {
  const m = d.mashina;
  const [dni, setDni] = useState(() => new Set(d.dni.filter((x) => x.rabochiy).map((x) => x.data)));
  const [f, setF] = useState({ sotrudnik_id: m.zakreplen_sotrudnik_id || "", rezhim_km: "vsego", probeg_vsego: "", km_v_den: "",
    razbros: "0.1", zapravki: m.bak_l ? "avto" : "vsego", litrov_vsego: "", raz: "4", porog: "0.25",
    vremya_vyezd: m.vremya_vyezd || "08:00", vremya_vozvrat: m.vremya_vozvrat || "17:00", marshrut: m.marshrut || "" });
  const [po, setPo] = useState([{ data: "", l: "" }]);
  const [ch, setCh] = useState(null);
  const [seed, setSeed] = useState(0);
  const ruchnye = new Set(d.listy.filter((x) => x.istochnik === "ruchnoy").map((x) => x.data));

  const body = () => ({
    tehnika_id: m.id, mesyac: d.mesyac, dni: [...dni].sort(), sotrudnik_id: f.sotrudnik_id ? Number(f.sotrudnik_id) : null,
    probeg_vsego: f.rezhim_km === "vsego" ? toNum(f.probeg_vsego) : null, km_v_den: f.rezhim_km === "den" ? toNum(f.km_v_den) : null,
    razbros: Number(f.razbros), zapravki: f.zapravki, litrov_vsego: toNum(f.litrov_vsego), raz: Number(f.raz) || 1,
    porog: Number(f.porog), po_datam: Object.fromEntries(po.filter((x) => x.data && toNum(x.l)).map((x) => [x.data, toNum(x.l)])),
    vremya_vyezd: f.vremya_vyezd, vremya_vozvrat: f.vremya_vozvrat, marshrut: f.marshrut, seed: seed || null,
  });
  const poschitat = async (s = seed) => {
    try { setCh(await api.post("/putevye/generator", { ...body(), seed: s || null })); }
    catch (e) { toast.show({ tone: "danger", title: "Не посчиталось", description: e.message }); }
  };
  const zapisat = async () => {
    const zamena = d.listy.filter((x) => x.istochnik === "generator").length;
    if (zamena && !window.confirm(`Листы, заполненные программой раньше (${zamena}), заменятся. Внесённые руками останутся. Записать?`)) return;
    try {
      const r = await api.post("/putevye/generator/sohranit", body());
      toast.show({ tone: "success", title: `Записано листов: ${r.zapisano}` });
      onSaved();
    } catch (e) { toast.show({ tone: "danger", title: "Не записалось", description: e.message }); }
  };
  const [g, mm] = d.mesyac.split("-").map(Number);
  const pervyy = (new Date(g, mm - 1, 1).getDay() + 6) % 7;
  const ed = m.edinica;

  return (
    <div style={{ background: "#fff", border: `2px solid ${C.pine}`, borderRadius: 12, padding: 12, display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="flex items-center" style={{ gap: 10 }}>
        <div style={{ fontWeight: 800, color: C.pine, flex: 1 }}>🗓 Заполнить {MES[mm - 1]} {g} — «{m.nazvanie}»</div>
        <button type="button" onClick={onClose} style={{ color: C.muted }}>✕ закрыть</button>
      </div>

      <div className="flex flex-wrap" style={{ gap: 18 }}>
        <div>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 4 }}>Дни выезда ({dni.size}) — клик включает/выключает</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 34px)", gap: 3, fontSize: 12 }}>
            {DN.map((x) => <div key={x} style={{ textAlign: "center", color: C.muted }}>{x}</div>)}
            {Array.from({ length: pervyy }).map((_, i) => <div key={`p${i}`} />)}
            {d.dni.map((x) => {
              const on = dni.has(x.data);
              const r = ruchnye.has(x.data);
              return (
                <button key={x.data} type="button" title={r ? "лист внесён руками — останется как есть" : x.prichina || "рабочий день"}
                  onClick={() => { const s = new Set(dni); on ? s.delete(x.data) : s.add(x.data); setDni(s); }}
                  style={{ height: 30, borderRadius: 6, fontWeight: on ? 700 : 400, border: `1px solid ${r ? C.gold : C.line}`,
                    background: on ? (r ? C.goldSoft : C.moss) : x.prichina?.startsWith("праздник") || x.prichina?.startsWith("по табелю") ? "#f8e1e1" : C.grey,
                    color: on ? C.pine : C.muted }}>{Number(x.data.slice(8))}</button>
              );
            })}
          </div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 4, maxWidth: 260 }}>
            Зелёные — выезд, розовые — праздник РБ или отпуск/больничный водителя по табелю, жёлтая рамка — лист уже внесён руками.
            Переносы рабочих дней (рабочие субботы) отметьте сами.
          </div>
          {d.dni.filter((x) => x.prichina && !x.prichina.startsWith("выходной")).map((x) => (
            <div key={x.data} style={{ fontSize: 11, color: C.danger }}>{ddmm(x.data)} — {x.prichina}</div>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: 1, minWidth: 280 }}>
          <label style={{ fontSize: 12, color: C.muted }}>Водитель<br />
            <select className={inp} value={f.sotrudnik_id} onChange={(e) => setF({ ...f, sotrudnik_id: e.target.value })}>
              <option value="">— не указан —</option>{lyudi.map((l) => <option key={l.id} value={l.id}>{l.fio}</option>)}</select></label>
          <div className="flex flex-wrap items-end" style={{ gap: 8 }}>
            <select className={inp} value={f.rezhim_km} onChange={(e) => setF({ ...f, rezhim_km: e.target.value })}>
              <option value="vsego">Пробег за месяц, {ed}</option><option value="den">Примерно в день, {ed}</option></select>
            {f.rezhim_km === "vsego"
              ? <input className={inp} style={{ width: 100 }} value={f.probeg_vsego} onChange={(e) => setF({ ...f, probeg_vsego: e.target.value })} placeholder="3000" inputMode="decimal" />
              : <input className={inp} style={{ width: 100 }} value={f.km_v_den} onChange={(e) => setF({ ...f, km_v_den: e.target.value })} placeholder="150" inputMode="decimal" />}
            <label style={{ fontSize: 12, color: C.muted }}>разброс по дням<br />
              <select className={inp} value={f.razbros} onChange={(e) => setF({ ...f, razbros: e.target.value })}>
                <option value="0">ровно</option><option value="0.1">±10%</option><option value="0.25">±25%</option></select></label>
          </div>
          <div className="flex flex-wrap items-end" style={{ gap: 8 }}>
            <label style={{ fontSize: 12, color: C.muted }}>Заправки<br />
              <select className={inp} value={f.zapravki} onChange={(e) => setF({ ...f, zapravki: e.target.value })}>
                <option value="vsego">Всего литров за N раз</option>
                <option value="po_datam">По датам (чеки, ведомость)</option>
                <option value="avto">Доливать до полного бака</option>
                <option value="net">Без заправок</option>
              </select></label>
            {f.zapravki === "vsego" && <>
              <input className={inp} style={{ width: 90 }} value={f.litrov_vsego} onChange={(e) => setF({ ...f, litrov_vsego: e.target.value })} placeholder="420 л" inputMode="decimal" />
              <span style={{ fontSize: 12, color: C.muted }}>за</span>
              <input className={inp} style={{ width: 54 }} value={f.raz} onChange={(e) => setF({ ...f, raz: e.target.value })} inputMode="numeric" />
              <span style={{ fontSize: 12, color: C.muted }}>раз</span>
            </>}
            {f.zapravki === "avto" && (m.bak_l ? (
              <label style={{ fontSize: 12, color: C.muted }}>когда в баке меньше<br />
                <select className={inp} value={f.porog} onChange={(e) => setF({ ...f, porog: e.target.value })}>
                  <option value="0.15">15%</option><option value="0.25">четверти</option><option value="0.5">половины</option></select> бака {num(m.bak_l)} л</label>
            ) : <span style={{ fontSize: 12, color: C.danger }}>впишите объём бака в карточке</span>)}
          </div>
          {f.zapravki === "po_datam" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {po.map((x, i) => (
                <div key={i} className="flex items-center" style={{ gap: 6 }}>
                  <select className={inp} value={x.data} onChange={(e) => setPo(po.map((y, j) => (j === i ? { ...y, data: e.target.value } : y)))}>
                    <option value="">дата</option>{[...dni].sort().map((dd) => <option key={dd} value={dd}>{ddmm(dd)}</option>)}</select>
                  <input className={inp} style={{ width: 80 }} value={x.l} onChange={(e) => setPo(po.map((y, j) => (j === i ? { ...y, l: e.target.value } : y)))} placeholder="л" inputMode="decimal" />
                  <button type="button" onClick={() => setPo(po.filter((_, j) => j !== i))} style={{ color: C.muted }}>×</button>
                </div>
              ))}
              <button type="button" onClick={() => setPo([...po, { data: "", l: "" }])} style={{ alignSelf: "flex-start", color: C.pine, fontSize: 13 }}>＋ ещё заправка</button>
            </div>
          )}
          <div className="flex flex-wrap items-end" style={{ gap: 8 }}>
            <label style={{ fontSize: 12, color: C.muted }}>Выезд<br /><input type="time" className={inp} value={f.vremya_vyezd} onChange={(e) => setF({ ...f, vremya_vyezd: e.target.value })} /></label>
            <label style={{ fontSize: 12, color: C.muted }}>Возврат<br /><input type="time" className={inp} value={f.vremya_vozvrat} onChange={(e) => setF({ ...f, vremya_vozvrat: e.target.value })} /></label>
            <label style={{ fontSize: 12, color: C.muted, flex: 1, minWidth: 160 }}>Маршрут<br /><input className={inp + " w-full"} value={f.marshrut} onChange={(e) => setF({ ...f, marshrut: e.target.value })} /></label>
          </div>
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            <button type="button" onClick={() => poschitat()} style={{ background: C.pine, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>Посчитать</button>
            {ch && <button type="button" onClick={() => { const s = seed + 1; setSeed(s); poschitat(s); }} style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "8px 12px" }} title="Другой разброс по дням">🎲 Перемешать</button>}
            {ch && <button type="button" onClick={zapisat} style={{ background: C.gold, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>Записать листы</button>}
          </div>
        </div>
      </div>

      {ch && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div className="flex flex-wrap" style={{ gap: 8 }}>
            <Plashka title="Дней" value={ch.itogi.dney} />
            <Plashka title={`Пробег, ${ed}`} value={num(ch.itogi.probeg)} sub={`${num(ch.nachalo.spidometr, 0)} → ${num(ch.itogi.spid_konec, 0)}`} />
            <Plashka title="Заправлено, л" value={num(ch.itogi.zapravka)} />
            <Plashka title="Расход по норме, л" value={num(ch.itogi.rashod)} />
            <Plashka title="В баке на конец, л" value={num(ch.itogi.ost_konec)} sub={`на начало ${num(ch.nachalo.ostatok)}`} tone={ch.itogi.ost_konec < 0 ? C.danger : undefined} />
          </div>
          {ch.preduprezhdeniya.map((p, i) => <div key={i} style={{ color: C.danger, fontSize: 13 }}>⚠ {p}</div>)}
          <div style={{ overflowX: "auto" }}>
            <table style={{ fontSize: 12.5, minWidth: 620, borderCollapse: "collapse" }}>
              <thead><tr style={{ color: C.muted, textAlign: "right" }}>
                <th style={{ textAlign: "left", padding: "4px 8px" }}>День</th><th style={{ padding: "4px 8px" }}>Спид. выезд</th><th style={{ padding: "4px 8px" }}>Пробег</th>
                <th style={{ padding: "4px 8px" }}>Спид. возврат</th><th style={{ padding: "4px 8px" }}>Заправка</th><th style={{ padding: "4px 8px" }}>Ост. выезд</th>
                <th style={{ padding: "4px 8px" }}>Расход</th><th style={{ padding: "4px 8px" }}>Ост. возврат</th></tr></thead>
              <tbody>{ch.stroki.map((s) => (
                <tr key={s.data} style={{ borderTop: `1px solid ${C.line}`, textAlign: "right", background: s.ruchnoy ? C.goldSoft : undefined }}>
                  <td style={{ textAlign: "left", padding: "3px 8px" }}>{ddmm(s.data)} {DN[(new Date(s.data).getDay() + 6) % 7]}{s.ruchnoy ? " ✍" : ""}</td>
                  <td style={{ padding: "3px 8px" }}>{num(s.spid_vyezd, 1)}</td><td style={{ padding: "3px 8px", fontWeight: 700 }}>{num(s.probeg, 1)}</td>
                  <td style={{ padding: "3px 8px" }}>{num(s.spid_vozvrat, 1)}</td><td style={{ padding: "3px 8px", fontWeight: 700 }}>{s.zapravka ? num(s.zapravka) : ""}</td>
                  <td style={{ padding: "3px 8px" }}>{num(s.ost_vyezd)}</td><td style={{ padding: "3px 8px" }}>{num(s.rashod)}</td>
                  <td style={{ padding: "3px 8px", fontWeight: 700, color: s.ost_vozvrat < 0 ? C.danger : C.pine }}>{num(s.ost_vozvrat)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------- сводка всех машин ---

function Svodka({ mesyac, toast }) {
  const [s, setS] = useState(null);
  useEffect(() => {
    api.get("/putevye/svodka", { mesyac }).then(setS).catch((e) => toast.show({ tone: "danger", title: "Сводка не загрузилась", description: e.message }));
  }, [mesyac]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!s) return <div style={{ color: C.muted }}>Считаю…</div>;
  if (!s.mashiny.length) return <div style={{ padding: 20, color: C.muted, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12 }}>За этот месяц путевых листов нет.</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="flex flex-wrap" style={{ gap: 8 }}>
        {Object.entries(s.po_toplivu).map(([t, v]) => (
          <Plashka key={t} title={t === "—" ? "тип топлива не указан" : t} value={`${num(v.rashod)} л`} sub={`заправлено ${num(v.zapravka)} л · пробег ${num(v.probeg)}`} />
        ))}
      </div>
      <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, overflowX: "auto" }}>
        <table className="w-full" style={{ fontSize: 13, minWidth: 760 }}>
          <thead><tr style={{ color: C.muted, textAlign: "right" }}>
            <th style={{ textAlign: "left", padding: "6px 10px" }}>Машина</th><th style={{ padding: "6px 10px" }}>Листов</th><th style={{ padding: "6px 10px" }}>Пробег</th>
            <th style={{ padding: "6px 10px" }}>Спидометр</th><th style={{ padding: "6px 10px" }}>Остаток нач.</th><th style={{ padding: "6px 10px" }}>Заправлено</th>
            <th style={{ padding: "6px 10px" }}>Расход</th><th style={{ padding: "6px 10px" }}>Остаток кон.</th><th style={{ padding: "6px 10px" }}>📱 По отчётам: заправка / расход</th></tr></thead>
          <tbody>{s.mashiny.map((x) => (
            <tr key={x.tehnika_id} style={{ borderTop: `1px solid ${C.line}`, textAlign: "right" }}>
              <td style={{ textAlign: "left", padding: "6px 10px" }}><b>{x.nazvanie}</b> <span style={{ color: C.muted }}>{x.nomer} · {x.toplivo}</span>{x.zakryt && " 🔒"}</td>
              <td style={{ padding: "6px 10px" }}>{x.listov}</td><td style={{ padding: "6px 10px" }}>{num(x.probeg)} {x.edinica}</td>
              <td style={{ padding: "6px 10px", color: C.muted }}>{num(x.spid_nachalo, 1)} → {num(x.spid_konec, 1)}</td>
              <td style={{ padding: "6px 10px" }}>{num(x.ost_nachalo)}</td><td style={{ padding: "6px 10px" }}>{num(x.zapravka)}</td>
              <td style={{ padding: "6px 10px", fontWeight: 700 }}>{num(x.rashod)}</td>
              <td style={{ padding: "6px 10px", fontWeight: 700, color: x.ost_konec < 0 ? C.danger : C.pine }}>{num(x.ost_konec)}</td>
              <td style={{ padding: "6px 10px", color: C.info }}>{x.smena_zapravka || x.smena_rashod ? `${num(x.smena_zapravka)} / ${num(x.smena_rashod)}` : "—"}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  );
}

// --------------------------------------------------------------- экран ---

// Бланк путевого листа для печати (09.11.2026, разбор сайта шаг 2):
// упрощённая форма — всё, что считает программа, плюс места для подписей.
// По два листа на страницу A4.
function BlankList({ x, m, ed }) {
  const td = { border: "1px solid #444", padding: "3px 6px" };
  const strochka = (t, v) => (
    <div style={{ display: "flex", gap: 6, marginTop: 3 }}>
      <span style={{ color: "#444", whiteSpace: "nowrap" }}>{t}</span>
      <span style={{ flex: 1, borderBottom: "1px solid #888", fontWeight: 600, minHeight: 16 }}>{v}</span>
    </div>
  );
  const [y, mo, dd] = x.data.split("-");
  return (
    <div style={{ border: "1.5px solid #222", borderRadius: 4, padding: "10px 14px", fontSize: 11.5, color: "#111", height: 128 * 3.6, boxSizing: "border-box", breakInside: "avoid", marginBottom: 14, display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <b style={{ fontSize: 15, letterSpacing: ".02em" }}>ПУТЕВОЙ ЛИСТ № {x.nomer || "____"}</b>
        <span>от <b>{dd}.{mo}.{y}</b></span>
      </div>
      {strochka("Организация:", "")}
      {strochka("Машина:", `${m.nazvanie}${m.marka ? `, ${m.marka}` : ""}${m.nomer ? ` · гос. № ${m.nomer}` : ""}`)}
      {strochka("Водитель:", x.fio || "")}
      {strochka("Маршрут:", x.marshrut || m.marshrut || "")}
      <table style={{ borderCollapse: "collapse", width: "100%", marginTop: 8, textAlign: "center" }}>
        <thead><tr><th style={{ ...td, textAlign: "left" }} /><th style={td}>Выезд</th><th style={td}>Возврат</th></tr></thead>
        <tbody>
          <tr><td style={{ ...td, textAlign: "left" }}>Время</td><td style={td}>{x.vremya_vyezd || ""}</td><td style={td}>{x.vremya_vozvrat || ""}</td></tr>
          <tr><td style={{ ...td, textAlign: "left" }}>{ed === "км" ? "Спидометр, км" : "Счётчик, моточасы"}</td><td style={td}>{num(x.spid_vyezd, 1)}</td><td style={td}>{num(x.spid_vozvrat, 1)}</td></tr>
          <tr><td style={{ ...td, textAlign: "left" }}>Остаток топлива, л</td><td style={td}>{num(x.ost_vyezd)}</td><td style={td}>{num(x.ost_vozvrat)}</td></tr>
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 18, marginTop: 6 }}>
        <span>Пробег: <b>{num(x.probeg)} {ed}</b></span>
        <span>Заправлено: <b>{num(x.zapravka) || "0"} л</b></span>
        <span>Расход по норме{x.norma != null ? ` (${String(x.norma).replace(".", ",")} л/${ed})` : ""}: <b>{num(x.rashod)} л</b></span>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 24px", fontSize: 10.5, color: "#333" }}>
        <span>Водитель ______________</span>
        <span>Выпуск разрешил (механик) ______________</span>
        <span>Медосмотр пройден ______________</span>
        <span>Машину принял ______________</span>
      </div>
    </div>
  );
}

function BlankiListov({ d }) {
  const ed = d.mashina.edinica || "км";
  return <div>{d.listy.map((x) => <BlankList key={x.id} x={x} m={d.mashina} ed={ed} />)}</div>;
}

export default function Putevye() {
  const toast = useToast();
  const [mParam, setMParam] = useScreenParam("tehnika", "m");
  const [mesParam, setMesParam] = useScreenParam("tehnika", "mes");
  const mesyac = mesParam || segodnyaMes();
  const [spisok, setSpisok] = useState(null);
  const [d, setD] = useState(null);
  const [kart, setKart] = useState(false);
  const [gen, setGen] = useState(false);
  const [vid, setVid] = useState("mashina");
  const [detal, setDetal] = useState(null);
  const [pechatListov, setPechatListov] = useState(false);
  const vedomostRef = useRef(null);
  const listyRef = useRef(null);

  const loadSpisok = useCallback(async () => {
    try {
      const s = await api.get("/putevye/mashiny");
      setSpisok(s);
      if (!mParam && s.mashiny.length) setMParam(s.mashiny[0].id);
    } catch (e) { toast.show({ tone: "danger", title: "Машины не загрузились", description: e.message }); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const load = useCallback(async () => {
    if (!mParam) return;
    try { setD(await api.get("/putevye", { tehnika_id: mParam, mesyac })); }
    catch (e) { setD(null); toast.show({ tone: "danger", title: "Листы не загрузились", description: e.message }); }
  }, [mParam, mesyac]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadSpisok(); }, [loadSpisok]);
  useEffect(() => { load(); setGen(false); setDetal(null); }, [load]);
  // Печать бланков: сначала рисуем их (скрыто), потом печатаем копию
  useEffect(() => {
    if (!pechatListov || !d) return;
    const [gg, mn] = mesyac.split("-").map(Number);
    napechatat(listyRef.current, { title: `Путевые листы · ${d.mashina.nazvanie} · ${MES[mn - 1]} ${gg}` });
    setPechatListov(false);
  }, [pechatListov, d, mesyac]);
  const obnovit = () => { load(); loadSpisok(); };

  const poDnyam = useMemo(() => Object.fromEntries((d?.listy || []).map((x) => [x.data, x])), [d]);

  const sohranitList = async (x, izm) => {
    const body = { ...Object.fromEntries(["nomer", "sotrudnik_id", "probeg", "zapravka", "spid_vyezd_fix", "ost_vyezd_fix", "vremya_vyezd", "vremya_vozvrat", "marshrut", "kommentariy"].map((k) => [k, x[k]])), ...izm };
    try { await api.put(`/putevye/list/${x.id}`, body); load(); }
    catch (e) { toast.show({ tone: "danger", title: "Не сохранилось", description: e.message }); }
  };
  const novyy = async (data, izm = {}) => {
    const m = d.mashina;
    try {
      await api.post("/putevye/list", { tehnika_id: m.id, data, probeg: 0, zapravka: 0, vremya_vyezd: m.vremya_vyezd, vremya_vozvrat: m.vremya_vozvrat, marshrut: m.marshrut, ...izm });
      load();
    } catch (e) { toast.show({ tone: "danger", title: "Лист не добавился", description: e.message }); }
  };
  const udalit = async (x) => {
    if (!window.confirm(`Удалить лист №${x.nomer || ""} за ${ddmm(x.data)}? Следующие листы пересчитаются.`)) return;
    try { await api.delete(`/putevye/list/${x.id}`); load(); } catch (e) { toast.show({ tone: "danger", title: "Не удалилось", description: e.message }); }
  };
  const zakryt = async (on) => {
    if (on && !window.confirm("Закрыть месяц? Листы сданы — править и пересчитывать их будет нельзя, пока не откроете.")) return;
    try { await api.post("/putevye/mesyac/zakryt", null, { tehnika_id: d.mashina.id, mesyac, on }); load(); }
    catch (e) { toast.show({ tone: "danger", title: "Не получилось", description: e.message }); }
  };

  if (!spisok) return <div style={{ padding: 24, color: C.muted }}>Загружаю машины…</div>;
  if (!spisok.mashiny.length) return <div style={{ padding: 24, color: C.muted }}>Сначала добавьте машину на вкладке «🚜 Техника».</div>;

  const m = d?.mashina;
  const ed = m?.edinica || "км";
  const [g, mm] = mesyac.split("-").map(Number);
  const nuzhnaKartochka = m && (!d.normy.length || m.start_spidometr == null);
  const ro = d && !d.mozhno_pravit;

  return (
    <div style={{ padding: "16px 18px 40px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
        <div className="flex" style={{ border: `1px solid ${C.line}`, borderRadius: 8, overflow: "hidden" }}>
          {[["mashina", "По машине"], ["svodka", "Сводка всех за месяц"]].map(([k, t]) => (
            <button key={k} type="button" onClick={() => setVid(k)} style={{ padding: "6px 12px", fontWeight: 700, background: vid === k ? C.pine : "#fff", color: vid === k ? "#fff" : C.pine }}>{t}</button>
          ))}
        </div>
        <button type="button" onClick={() => setMesParam(sdvig(mesyac, -1))} style={{ padding: "4px 10px", fontSize: 18 }}>‹</button>
        <b style={{ minWidth: 120, textAlign: "center" }}>{MES[mm - 1]} {g}</b>
        <button type="button" onClick={() => setMesParam(sdvig(mesyac, 1))} style={{ padding: "4px 10px", fontSize: 18 }}>›</button>
      </div>

      {vid === "svodka" ? <Svodka mesyac={mesyac} toast={toast} /> : (<>
        <div className="flex flex-wrap" style={{ gap: 6 }}>
          {spisok.mashiny.map((x) => (
            <button key={x.id} type="button" onClick={() => setMParam(x.id)}
              style={{ border: `1px solid ${String(x.id) === String(mParam) ? C.pine : C.line}`, background: String(x.id) === String(mParam) ? C.moss : "#fff", borderRadius: 999, padding: "5px 12px", fontSize: 13 }}>
              <b>{x.nazvanie}</b>{x.nomer && <span style={{ color: C.muted }}> {x.nomer}</span>}
              <span style={{ color: x.norma ? C.muted : C.danger }}> · {x.norma ? `${String(x.norma).replace(".", ",")} л/${x.edinica}` : "нет нормы"}</span>
            </button>
          ))}
        </div>

        {!d ? <div style={{ color: C.muted }}>Загружаю листы…</div> : (<>
          <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
            <Plashka title={`Пробег, ${ed}`} value={num(d.itogi.probeg)} sub={d.itogi.spid_nachalo != null ? `${num(d.itogi.spid_nachalo, 1)} → ${num(d.itogi.spid_konec, 1)}` : undefined} />
            <Plashka title="Заправлено, л" value={num(d.itogi.zapravka) || "0"} sub={d.itogi.smena_zapravka ? `📱 в отчётах ${num(d.itogi.smena_zapravka)}` : undefined} />
            <Plashka title="Расход по норме, л" value={num(d.itogi.rashod) || "0"} />
            <Plashka title="В баке на конец, л" value={num(d.itogi.ost_konec) || "0"} sub={`на начало ${num(d.itogi.ost_nachalo) || 0}${m.bak_l ? ` · бак ${num(m.bak_l)}` : ""}`} tone={d.itogi.ost_konec < 0 ? C.danger : undefined} />
            <Plashka title="Листов" value={d.itogi.listov} sub={d.zakryt ? "🔒 месяц закрыт" : ro ? "🔒 закрыт более поздний месяц" : "месяц открыт"} />
          </div>

          <div className="flex flex-wrap" style={{ gap: 8 }}>
            <button type="button" onClick={() => setGen(!gen)} disabled={ro} style={{ background: ro ? C.grey : C.pine, color: ro ? C.muted : "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>🗓 Заполнить месяц 5/2</button>
            <button type="button" onClick={() => setKart(!kart)} style={{ border: `1px solid ${nuzhnaKartochka ? C.danger : C.line}`, color: nuzhnaKartochka ? C.danger : C.pine, borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>
              🪪 Карточка машины{nuzhnaKartochka ? " — заполните" : ""}</button>
            {d.zakryt
              ? <button type="button" onClick={() => zakryt(false)} style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "8px 14px" }}>🔓 Открыть месяц</button>
              : <button type="button" onClick={() => zakryt(true)} disabled={ro || !d.listy.length} style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: "8px 14px", color: ro || !d.listy.length ? C.muted : undefined }}>🔒 Закрыть месяц (сдан)</button>}
            <span style={{ flex: 1 }} />
            <button type="button" onClick={() => setPechatListov(true)} disabled={!d.listy.length}
              title="Каждый лист месяца — бланком, по два на страницу A4: машина, водитель, маршрут, время, спидометр, топливо, места для подписей"
              style={{ border: `1px solid ${C.line}`, background: "#fff", color: d.listy.length ? C.pine : C.muted, borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>🖨 Листы на печать ({d.listy.length})</button>
            <button type="button" onClick={() => napechatat(vedomostRef.current, { title: `Путевые листы · ${m.nazvanie}${m.nomer ? ` ${m.nomer}` : ""} · ${MES[mm - 1]} ${g}`, landscape: true })}
              disabled={!d.listy.length}
              title="Таблица месяца на одном листе — сдать в бухгалтерию"
              style={{ border: `1px solid ${C.line}`, background: "#fff", color: d.listy.length ? C.pine : C.muted, borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>🖨 Ведомость месяца</button>
          </div>

          {(kart || nuzhnaKartochka) && <Kartochka m={{ ...m, normy: d.normy }} d={spisok} edinica={ed} onSaved={obnovit} toast={toast} />}
          {gen && <Generator d={d} lyudi={spisok.lyudi} onClose={() => setGen(false)} onSaved={() => { setGen(false); obnovit(); }} toast={toast} />}

          <div ref={vedomostRef} style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, overflowX: "auto" }}>
            <table style={{ fontSize: 13, minWidth: 900, width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ color: C.muted, textAlign: "right", fontSize: 12 }}>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>День</th><th style={{ padding: "6px 8px" }}>№</th>
                <th style={{ padding: "6px 8px" }}>{ed === "км" ? "Спидометр" : "Счётчик"} выезд</th>
                <th style={{ padding: "6px 8px", color: C.pine }}>Пробег, {ed} ✍</th>
                <th style={{ padding: "6px 8px" }}>{ed === "км" ? "Спидометр" : "Счётчик"} возврат</th>
                <th style={{ padding: "6px 8px", color: C.pine }}>Заправка, л ✍</th>
                <th style={{ padding: "6px 8px" }}>Остаток выезд</th><th style={{ padding: "6px 8px" }}>Расход</th>
                <th style={{ padding: "6px 8px" }}>Остаток возврат</th><th style={{ textAlign: "left", padding: "6px 8px" }}>Подсказки</th><th data-no-print /></tr></thead>
              <tbody>
                {d.dni.map((den) => {
                  const x = poDnyam[den.data];
                  const dn = DN[den.den_nedeli];
                  if (!x) {
                    return (
                      <tr key={den.data} style={{ borderTop: `1px solid ${C.line}`, color: C.muted, background: den.rabochiy ? undefined : C.grey }}>
                        <td style={{ padding: "4px 8px" }}>{ddmm(den.data)} {dn}</td>
                        <td colSpan={8} style={{ padding: "4px 8px", fontSize: 12 }}>{den.prichina || ""}</td>
                        <td style={{ padding: "4px 8px" }}>{!ro && <button data-no-print type="button" onClick={() => novyy(den.data)} style={{ color: C.pine, fontSize: 12 }}>＋ лист</button>}</td><td data-no-print />
                      </tr>
                    );
                  }
                  const otkryt = detal === x.id;
                  return (
                    <React.Fragment key={den.data}>
                      <tr style={{ borderTop: `1px solid ${C.line}`, textAlign: "right" }}>
                        <td style={{ textAlign: "left", padding: "4px 8px", whiteSpace: "nowrap" }}><b>{ddmm(den.data)}</b> {dn}
                          {x.istochnik === "generator" && <span title="заполнено программой" style={{ marginLeft: 4 }}>🗓</span>}</td>
                        <td style={{ padding: "4px 8px", color: C.muted }}>{x.nomer}</td>
                        <td style={{ padding: "4px 8px" }}>{num(x.spid_vyezd, 1)}{x.spid_vyezd_fix != null && " 📌"}</td>
                        <td style={{ padding: "4px 8px" }}><Vvod value={x.probeg} disabled={ro} onSave={(v) => sohranitList(x, { probeg: v })} /></td>
                        <td style={{ padding: "4px 8px", fontWeight: 700 }}>{num(x.spid_vozvrat, 1)}</td>
                        <td style={{ padding: "4px 8px" }}><Vvod value={x.zapravka || ""} placeholder="0" disabled={ro} onSave={(v) => sohranitList(x, { zapravka: v })} /></td>
                        <td style={{ padding: "4px 8px" }}>{num(x.ost_vyezd)}{x.ost_vyezd_fix != null && " 📌"}</td>
                        <td style={{ padding: "4px 8px", color: C.muted }} title={`${num(x.probeg)} × ${x.norma ?? "—"}`}>{num(x.rashod)}</td>
                        <td style={{ padding: "4px 8px", fontWeight: 700, color: x.ost_vozvrat < 0 ? C.danger : C.pine }}>{num(x.ost_vozvrat)}</td>
                        <td style={{ textAlign: "left", padding: "4px 8px", maxWidth: 260 }}>
                          <Preduprezhdeniya list={x.preduprezhdeniya} onZapravka={ro ? null : (v) => sohranitList(x, { zapravka: v })} />
                          {x.fio && <span style={{ fontSize: 11.5, color: C.muted }}>{x.fio}</span>}
                        </td>
                        <td data-no-print style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>
                          <button type="button" onClick={() => setDetal(otkryt ? null : x.id)} title="Подробнее">✏️</button>
                          {!ro && <button type="button" onClick={() => udalit(x)} title="Удалить" style={{ color: C.muted, marginLeft: 4 }}>🗑</button>}
                        </td>
                      </tr>
                      {otkryt && <Detal x={x} lyudi={spisok.lyudi} ro={ro} ed={ed} onSave={(izm) => sohranitList(x, izm)} />}
                    </React.Fragment>
                  );
                })}
              </tbody>
              <tfoot><tr style={{ borderTop: `2px solid ${C.pine}`, textAlign: "right", fontWeight: 700 }}>
                <td style={{ textAlign: "left", padding: "6px 8px" }}>Итого</td><td style={{ padding: "6px 8px", color: C.muted }}>листов: {d.itogi.listov}</td><td />
                <td style={{ padding: "6px 8px" }}>{num(d.itogi.probeg)}</td><td />
                <td style={{ padding: "6px 8px" }}>{num(d.itogi.zapravka)}</td><td />
                <td style={{ padding: "6px 8px" }}>{num(d.itogi.rashod)}</td>
                <td style={{ padding: "6px 8px" }}>{num(d.itogi.ost_konec)}</td><td /><td data-no-print />
              </tr></tfoot>
            </table>
          </div>
          {pechatListov && (
            <div style={{ position: "fixed", left: -10000, top: 0, width: 760 }} aria-hidden="true">
              <div ref={listyRef}><BlankiListov d={d} /></div>
            </div>
          )}
          <div style={{ fontSize: 11.5, color: C.muted }}>
            ✍ — вводите только пробег и заправку (Enter или Tab сохраняет), остальное считается от прошлого листа. Правка в середине месяца пересчитывает все листы после неё.
            Лист, поправленный руками, при повторном «Заполнить месяц» остаётся как есть. 📌 — показание при выезде прибито руками (например, заменили спидометр).
          </div>
        </>)}
      </>)}
    </div>
  );
}

function Detal({ x, lyudi, ro, ed, onSave }) {
  const [f, setF] = useState({ nomer: x.nomer ?? "", sotrudnik_id: x.sotrudnik_id || "", vremya_vyezd: x.vremya_vyezd || "", vremya_vozvrat: x.vremya_vozvrat || "",
    marshrut: x.marshrut || "", kommentariy: x.kommentariy || "", spid_vyezd_fix: x.spid_vyezd_fix ?? "", ost_vyezd_fix: x.ost_vyezd_fix ?? "" });
  const save = () => {
    const nomer = toNum(f.nomer), sf = toNum(f.spid_vyezd_fix), of = toNum(f.ost_vyezd_fix);
    if ([nomer, sf, of].some(Number.isNaN)) return;
    onSave({ ...f, nomer: nomer == null ? null : Math.round(nomer), sotrudnik_id: f.sotrudnik_id ? Number(f.sotrudnik_id) : null, spid_vyezd_fix: sf, ost_vyezd_fix: of });
  };
  return (
    <tr style={{ background: C.grey }}>
      <td colSpan={11} style={{ padding: 10 }}>
        <div className="flex flex-wrap items-end" style={{ gap: 8 }}>
          <L t="№ листа"><input className={inp} style={{ width: 70 }} value={f.nomer} disabled={ro} onChange={(e) => setF({ ...f, nomer: e.target.value })} /></L>
          <L t="Водитель"><select className={inp} value={f.sotrudnik_id} disabled={ro} onChange={(e) => setF({ ...f, sotrudnik_id: e.target.value })}>
            <option value="">—</option>{lyudi.map((l) => <option key={l.id} value={l.id}>{l.fio}</option>)}</select></L>
          <L t="Выезд"><input type="time" className={inp} value={f.vremya_vyezd} disabled={ro} onChange={(e) => setF({ ...f, vremya_vyezd: e.target.value })} /></L>
          <L t="Возврат"><input type="time" className={inp} value={f.vremya_vozvrat} disabled={ro} onChange={(e) => setF({ ...f, vremya_vozvrat: e.target.value })} /></L>
          <L t="Маршрут" flex={1}><input className={inp + " w-full"} value={f.marshrut} disabled={ro} onChange={(e) => setF({ ...f, marshrut: e.target.value })} /></L>
        </div>
        <div className="flex flex-wrap items-end" style={{ gap: 8, marginTop: 8 }}>
          <L t={`📌 ${ed === "км" ? "Спидометр" : "Счётчик"} при выезде вручную`}><input className={inp} style={{ width: 120 }} value={f.spid_vyezd_fix} disabled={ro} placeholder="пусто — от прошлого" onChange={(e) => setF({ ...f, spid_vyezd_fix: e.target.value })} /></L>
          <L t="📌 В баке до заправки вручную, л"><input className={inp} style={{ width: 120 }} value={f.ost_vyezd_fix} disabled={ro} placeholder="пусто — от прошлого" onChange={(e) => setF({ ...f, ost_vyezd_fix: e.target.value })} /></L>
          <L t="Комментарий" flex={1}><input className={inp + " w-full"} value={f.kommentariy} disabled={ro} onChange={(e) => setF({ ...f, kommentariy: e.target.value })} /></L>
          {!ro && <button type="button" onClick={save} style={{ background: C.pine, color: "#fff", borderRadius: 8, padding: "8px 14px", fontWeight: 700 }}>Сохранить</button>}
        </div>
      </td>
    </tr>
  );
}
