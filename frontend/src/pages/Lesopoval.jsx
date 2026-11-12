import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import Modal from "../components/Modal.jsx";
import { useCan } from "../auth.jsx";
import { useToast } from "../components/Toast.jsx";
import { openScreen } from "../nav.js";

/**
 * «🪓 Лесоповал» — игровая карточка делянки (03.11.2026, Влад: «а как
 * смотреть остатки, заносить наряды?»). Открывается из «🚛 Вывозки».
 *  - Освоение делянки: /api/raskhod/delyanki/{id}/osvoenie (тот же расчёт,
 *    что карточка «Освоение делянки» и «Остатки» на телефоне).
 *  - Остатки выдела по породам × сортиментам: /api/raskhod/items/{id}/balance —
 *    «штабели», клик по штабелю кладёт его в наряд.
 *  - Быстрый наряд: тот же POST /api/raskhod/items/{id}/naryady, что форма
 *    в обычном Расходе, с теми же проверками на опечатку (>110%, «лишний ноль»).
 *  - Последние наряды выдела, удалить — DELETE /api/raskhod/naryady/{id}.
 */

const C = {
  pine: "var(--color-pine)", leaf: "var(--c-green-2)", moss: "var(--color-mint-soft)", line: "var(--color-border)", muted: "var(--color-muted-2)", ink: "var(--color-ink)",
  gold: "var(--c-gold)", goldSoft: "var(--c-gold-soft)", danger: "var(--color-error)", dangerSoft: "var(--c-error-soft-2)", wood: "#9a6a3a", woodSoft: "#f6ede2",
};
const SORT = [["KR", "Крупная"], ["SR", "Средняя"], ["ML", "Мелкая"], ["DROVA", "Дрова"]];
const SORT_L = Object.fromEntries(SORT);
const LEVEL = {
  norma: { t: "в пределах лимита", c: C.leaf, bg: C.moss },
  vnimanie: { t: "уже 90% — притормози", c: C.gold, bg: C.goldSoft },
  preduprezhdenie: { t: "лимит выбран — дальше только до 110%", c: "#d9661f", bg: "#fdeee2" },
  pererub: { t: "ПЕРЕРУБ — больше 110%!", c: C.danger, bg: C.dangerSoft },
};
const XP_NARYAD = 10;

function f1(v) {
  return (Math.round((Number(v) || 0) * 10) / 10).toLocaleString("ru-RU");
}
function ruDate(d) {
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
}
function naryadObyom(n) {
  return (n?.pozitsii || []).reduce((s, p) => s + (Number(p.obyom) || 0), 0);
}

function OsvoenieBar({ it }) {
  if (!it) return null;
  const lv = LEVEL[it.level] || LEVEL.norma;
  const pct = it.pct || 0;
  return (
    <div style={{ padding: 12, borderRadius: 12, background: lv.bg, border: `1px solid ${C.line}` }}>
      <div className="flex justify-between" style={{ fontSize: 13, marginBottom: 6 }}>
        <b style={{ color: lv.c }}>🪓 Срублено {f1(it.fakt)} из {f1(it.limit)} м³ · {Math.round(pct)}% — {lv.t}</b>
        <span style={{ color: C.muted }}>наряд {f1(it.fakt_naryad)} · ЕГАИС {f1(it.fakt_egais)}</span>
      </div>
      <div style={{ position: "relative", height: 14, borderRadius: 7, background: "var(--color-surface)", overflow: "hidden", border: `1px solid ${C.line}` }}>
        <div style={{ width: `${Math.min(100, (pct / 110) * 100)}%`, height: "100%", background: lv.c }} />
        {[90, 100].map((p) => (
          <div key={p} style={{ position: "absolute", left: `${(p / 110) * 100}%`, top: 0, bottom: 0, width: 2, background: p === 100 ? C.danger : C.gold }} />
        ))}
      </div>
      <div className="flex flex-wrap" style={{ gap: 14, fontSize: 13, marginTop: 6, color: C.ink }}>
        <span>до 100%: <b>{f1(it.mozhno_do_100)} м³</b></span>
        <span>до 110%: <b>{f1(it.mozhno_do_110)} м³</b></span>
        <span style={{ color: C.muted }}>процент — по большему из наряда и ЕГАИС</span>
      </div>
    </div>
  );
}

function Shtabel({ poroda, code, b, vybran, onPick }) {
  const limit = b?.limit || 0;
  if (!limit && !b?.fakt) return <div />;
  const fakt = Math.max(b.fakt || 0, b.fakt_egais || 0);
  const ost = limit - fakt;
  const pct = limit ? fakt / limit : 1;
  const color = pct > 1.1 ? C.danger : pct > 1 ? "#d9661f" : pct >= 0.9 ? C.gold : C.leaf;
  const brevna = 8;
  const ostalos = limit ? Math.max(0, Math.round((1 - Math.min(pct, 1)) * brevna)) : 0;
  return (
    <button type="button" onClick={() => onPick(poroda, code)} title={`${poroda} · ${SORT_L[code]}: лимит ${f1(limit)}, срублено ${f1(fakt)} (наряд ${f1(b.fakt)}, ЕГАИС ${f1(b.fakt_egais)}). Клик — в наряд`}
      style={{
        textAlign: "left", padding: 8, borderRadius: 10, background: vybran ? C.woodSoft : "var(--color-surface)",
        border: `1.5px solid ${vybran ? C.wood : C.line}`, display: "flex", flexDirection: "column", gap: 4, minWidth: 0,
      }}>
      <div style={{ display: "flex", flexWrap: "wrap-reverse", gap: 2, width: 60 }}>
        {Array.from({ length: brevna }).map((_, i) => (
          <span key={i} style={{ width: 13, height: 7, borderRadius: 4, background: i < ostalos ? "#c99560" : "transparent", border: `1px solid ${i < ostalos ? C.wood : C.line}` }} />
        ))}
      </div>
      <div style={{ fontWeight: 800, color, fontSize: 15 }}>{ost >= 0 ? f1(ost) : `−${f1(-ost)}`} м³</div>
      <div style={{ fontSize: 11, color: C.muted }}>из {f1(limit)} · {Math.round(pct * 100)}%</div>
    </button>
  );
}

export default function Lesopoval({ delyanka, onClose, onSaved }) {
  const toast = useToast();
  const can = useCan();
  const items = delyanka?.items || [];
  const [itemId, setItemId] = useState(items[0]?.item_id || null);
  const [osv, setOsv] = useState(null);
  const [bal, setBal] = useState(null);
  const [naryady, setNaryady] = useState([]);
  const [plo, setPlo] = useState(null);
  const [data, setData] = useState(ruDate(new Date()));
  const [nomer, setNomer] = useState("");
  const [ploshad, setPloshad] = useState("");
  const [poz, setPoz] = useState([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setItemId(items[0]?.item_id || null); }, [delyanka?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(async () => {
    if (!delyanka) return;
    try {
      const [o, b, n, p] = await Promise.all([
        api.get(`/raskhod/delyanki/${delyanka.id}/osvoenie`),
        itemId ? api.get(`/raskhod/items/${itemId}/balance`) : Promise.resolve({}),
        itemId ? api.get(`/raskhod/items/${itemId}/naryady`) : Promise.resolve([]),
        itemId ? api.get(`/raskhod/items/${itemId}/ploshad`) : Promise.resolve(null),
      ]);
      setOsv(o); setBal(b || {}); setNaryady(n || []); setPlo(p);
      const nomera = (n || []).map((x) => parseInt(x.nomer_naryada, 10)).filter((x) => !Number.isNaN(x));
      setNomer(nomera.length ? String(Math.max(...nomera) + 1) : "");
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось загрузить делянку", description: e.message });
    }
  }, [delyanka, itemId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPoz([]); setPloshad(""); load(); }, [load]);

  const porody = useMemo(() => Object.keys(bal || {}), [bal]);
  const obyom = poz.reduce((s, p) => s + (Number(p.obyom) || 0), 0);
  const limitVydela = plo?.limit_kubatura_total || 0;
  const faktVydela = naryady.reduce((s, n) => s + naryadObyom(n), 0);

  // Площадь наряда — как 🧮 в обычной форме: кубатура × площадь / лимит.
  useEffect(() => {
    if (plo?.ploshad_delyanki > 0 && limitVydela > 0 && obyom > 0) {
      setPloshad(((obyom * plo.ploshad_delyanki) / limitVydela).toFixed(2));
    }
  }, [obyom]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (poroda, sortiment) => {
    setPoz((rows) => (rows.some((r) => r.poroda === poroda && r.sortiment === sortiment)
      ? rows.filter((r) => !(r.poroda === poroda && r.sortiment === sortiment))
      : [...rows, { poroda, sortiment, obyom: "" }]));
  };
  const setObyom = (i, v) => setPoz((rows) => rows.map((r, j) => (j === i ? { ...r, obyom: v.replace(",", ".") } : r)));

  const preduprezhdeniya = () => {
    const out = [];
    if (limitVydela > 0) {
      const pct = Math.round(((faktVydela + obyom) / limitVydela) * 100);
      if (pct > 110) out.push(`После наряда по выделу будет ${pct}% лимита — больше 110%.`);
    }
    const ob = naryady.map(naryadObyom).filter((v) => v > 0).sort((a, b) => a - b);
    if (ob.length >= 3) {
      const tip = ob[Math.floor(ob.length / 2)];
      if (obyom >= tip * 3) out.push(`Объём ${f1(obyom)} м³ — в ${Math.round(obyom / tip)} раз(а) больше обычного (около ${f1(tip)}). Нет ли лишнего нуля?`);
    }
    return out;
  };

  const save = async () => {
    if (!/^\d{2}\.\d{2}\.\d{4}$/.test(data.trim())) { toast.show({ tone: "warning", title: "Дата — ДД.ММ.ГГГГ" }); return; }
    const pozitsii = poz.filter((p) => Number(p.obyom) > 0).map((p) => ({ ...p, obyom: Number(p.obyom) }));
    if (!pozitsii.length) { toast.show({ tone: "warning", title: "Кликни штабель и впиши объём" }); return; }
    const pr = preduprezhdeniya();
    if (pr.length && !window.confirm(`Проверь наряд:\n\n• ${pr.join("\n• ")}\n\nСохранить всё равно?`)) return;
    setBusy(true);
    try {
      await api.post(`/raskhod/items/${itemId}/naryady`, { data: data.trim(), nomer_naryada: nomer, ploshad, primechanie: "", pozitsii });
      toast.show({ tone: "success", title: `🪓 Наряд №${nomer || "—"} в деле · +${XP_NARYAD} XP`, description: `${f1(obyom)} м³ срублено на бумаге` });
      setPoz([]); setPloshad("");
      await load();
      onSaved?.();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось сохранить наряд", description: e.message });
    } finally {
      setBusy(false);
    }
  };

  const udalit = async (n) => {
    if (!window.confirm(`Удалить наряд №${n.nomer_naryada || "—"} от ${n.data} (${f1(naryadObyom(n))} м³)?`)) return;
    try {
      await api.delete(`/raskhod/naryady/${n.id}`);
      toast.show({ tone: "success", title: "Наряд удалён" });
      await load();
      onSaved?.();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось удалить", description: e.message });
    }
  };

  const vchera = new Date(); vchera.setDate(vchera.getDate() - 1);
  const mozhno = can("raskhod.edit");
  const posled = [...naryady].sort((a, b) => (b.id || 0) - (a.id || 0)).slice(0, 6);

  return (
    <Modal open={!!delyanka} onClose={onClose} size="xl" title={`🪓 ${delyanka?.nazvanie || ""}`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <OsvoenieBar it={osv?.itogo} />

        {items.length > 1 && (
          <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
            <span style={{ fontSize: 13, color: C.muted }}>Выдел:</span>
            {items.map((it) => (
              <button key={it.item_id} type="button" onClick={() => setItemId(it.item_id)} style={{
                padding: "4px 12px", borderRadius: 999, fontSize: 13, fontWeight: 600,
                background: it.item_id === itemId ? C.pine : "var(--color-surface)", color: it.item_id === itemId ? "#fff" : C.pine, border: `1px solid ${C.pine}`,
              }}>{it.label}</button>
            ))}
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
          <section>
            <div style={{ fontWeight: 800, color: C.pine, marginBottom: 6 }}>🪵 Остатки выдела — клик по штабелю кладёт его в наряд</div>
            {porody.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>Лимитов нет — сначала импортируй МДО выдела.</div>}
            {porody.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "90px repeat(4, minmax(0, 1fr))", gap: 6, alignItems: "stretch" }}>
                <div />
                {SORT.map(([k, l]) => <div key={k} style={{ fontSize: 12, color: C.muted, fontWeight: 700 }}>{l}</div>)}
                {porody.map((p) => (
                  <React.Fragment key={p}>
                    <div style={{ fontWeight: 700, alignSelf: "center" }}>{p}</div>
                    {SORT.map(([k]) => (
                      <Shtabel key={k} poroda={p} code={k} b={bal[p]?.[k]} onPick={pick}
                        vybran={poz.some((r) => r.poroda === p && r.sortiment === k)} />
                    ))}
                  </React.Fragment>
                ))}
              </div>
            )}
            {plo && plo.ploshad_delyanki > 0 && (
              <div style={{ fontSize: 13, color: C.muted, marginTop: 8 }}>
                Площадь выдела {f1(plo.ploshad_delyanki)} га, по нарядам пройдено {f1(plo.ploshad_naryadov)}, осталось <b style={{ color: C.ink }}>{f1(plo.ploshad_ostatok)} га</b>
              </div>
            )}
          </section>

          <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ padding: 12, borderRadius: 12, border: `1.5px dashed ${C.wood}`, background: C.woodSoft }}>
              <div style={{ fontWeight: 800, color: C.wood, marginBottom: 8 }}>📝 Быстрый наряд</div>
              {!mozhno && <div style={{ fontSize: 13, color: C.muted }}>Нет права заносить наряды.</div>}
              {mozhno && (
                <>
                  <div className="flex flex-wrap items-center" style={{ gap: 6, marginBottom: 8 }}>
                    <input value={data} onChange={(e) => setData(e.target.value)} placeholder="ДД.ММ.ГГГГ" aria-label="Дата наряда"
                      style={{ width: 110, padding: "5px 8px", borderRadius: 8, border: `1px solid ${C.line}`, background: "var(--color-surface)" }} />
                    <button type="button" onClick={() => setData(ruDate(new Date()))} style={{ fontSize: 12, padding: "3px 8px", borderRadius: 999, background: "var(--color-surface)", border: `1px solid ${C.line}` }}>сегодня</button>
                    <button type="button" onClick={() => setData(ruDate(vchera))} style={{ fontSize: 12, padding: "3px 8px", borderRadius: 999, background: "var(--color-surface)", border: `1px solid ${C.line}` }}>вчера</button>
                    <span style={{ fontSize: 13, color: C.muted }}>№</span>
                    <input value={nomer} onChange={(e) => setNomer(e.target.value)} aria-label="Номер наряда"
                      style={{ width: 56, padding: "5px 8px", borderRadius: 8, border: `1px solid ${C.line}`, background: "var(--color-surface)" }} />
                    <span style={{ fontSize: 13, color: C.muted }}>га</span>
                    <input value={ploshad} onChange={(e) => setPloshad(e.target.value)} aria-label="Площадь наряда" placeholder="авто"
                      style={{ width: 64, padding: "5px 8px", borderRadius: 8, border: `1px solid ${C.line}`, background: "var(--color-surface)" }} />
                  </div>
                  {poz.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>👈 Кликни штабель (порода × сортимент), который рубили</div>}
                  {poz.map((p, i) => (
                    <div key={`${p.poroda}-${p.sortiment}`} className="flex items-center" style={{ gap: 6, marginBottom: 4 }}>
                      <span style={{ flex: 1, fontSize: 13 }}>{p.poroda} · {SORT_L[p.sortiment]}</span>
                      <input autoFocus={i === poz.length - 1} value={p.obyom} onChange={(e) => setObyom(i, e.target.value)} inputMode="decimal" placeholder="м³"
                        aria-label={`Объём ${p.poroda} ${SORT_L[p.sortiment]}`}
                        onKeyDown={(e) => { if (e.key === "Enter") save(); }}
                        style={{ width: 80, padding: "5px 8px", borderRadius: 8, border: `1px solid ${C.line}`, background: "var(--color-surface)", textAlign: "right" }} />
                      <button type="button" onClick={() => pick(p.poroda, p.sortiment)} aria-label="Убрать" style={{ color: C.muted, padding: "0 4px" }}>×</button>
                    </div>
                  ))}
                  {poz.length > 0 && (
                    <div className="flex items-center justify-between" style={{ marginTop: 8, gap: 8 }}>
                      <span style={{ fontSize: 13 }}>
                        Итого <b>{f1(obyom)} м³</b>
                        {limitVydela > 0 && <span style={{ color: C.muted }}> · станет {Math.round(((faktVydela + obyom) / limitVydela) * 100)}% выдела</span>}
                      </span>
                      <button type="button" disabled={busy} onClick={save} style={{
                        padding: "7px 14px", borderRadius: 8, fontWeight: 800, background: C.wood, color: "#fff", opacity: busy ? 0.6 : 1,
                      }}>🪓 Срубить! +{XP_NARYAD} XP</button>
                    </div>
                  )}
                </>
              )}
            </div>

            <div>
              <div style={{ fontWeight: 800, color: C.pine, marginBottom: 4 }}>📜 Последние наряды выдела · {naryady.length}</div>
              {posled.length === 0 && <div style={{ fontSize: 13, color: C.muted }}>Ещё ни одного — будь первым 🪓</div>}
              {posled.map((n) => (
                <div key={n.id} className="flex items-center justify-between" style={{ fontSize: 13, padding: "4px 0", borderTop: `1px solid ${C.line}`, gap: 6 }}>
                  <span>№{n.nomer_naryada || "—"} · {n.data}</span>
                  <span style={{ color: C.muted, flex: 1, textAlign: "right" }}>
                    {(n.pozitsii || []).map((p) => `${p.poroda} ${SORT_L[p.sortiment] || p.sortiment} ${f1(p.obyom)}`).join(", ")}
                  </span>
                  {mozhno && <button type="button" onClick={() => udalit(n)} aria-label="Удалить наряд" title="Удалить" style={{ color: C.muted, padding: "0 4px" }}>×</button>}
                </div>
              ))}
              <button type="button" onClick={() => { onClose(); openScreen("raskhod", { tab: "raskhod", d: delyanka.id }); }}
                style={{ marginTop: 8, fontSize: 13, color: C.pine, fontWeight: 600 }}>Все наряды, правка и Книга расхода → обычный Расход</button>
            </div>
          </section>
        </div>
      </div>
    </Modal>
  );
}
