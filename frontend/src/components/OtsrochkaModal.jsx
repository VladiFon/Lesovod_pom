import React, { useCallback, useEffect, useState } from "react";
import { api, API_BASE_URL } from "../api/client.js";
import Modal from "./Modal.jsx";
import Button from "./Button.jsx";
import TextField from "./TextField.jsx";
import DateField from "./DateField.jsx";
import StatusBadge from "./StatusBadge.jsx";
import { useToast } from "./Toast.jsx";

const fmt = (v) => (v == null ? "—" : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 }));

async function skachat(dney) {
  const token = localStorage.getItem("lesovod_token");
  const res = await fetch(`${API_BASE_URL}/otsrochka/kandidaty.xlsx?dney=${dney}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Ошибка сервера (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `otsrochka_${new Date().toISOString().slice(0, 10)}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * «Нужна отсрочка» (просьба Влада 03.11.2026): делянки, у которых срок
 * заготовки прошёл или подходит, а заготовка не закончена, с остатком м³
 * и га. Excel — к заявлению; после решения — ввести новые сроки сразу
 * нескольким делянкам. Инспекция и колокольчик дальше считают по ним.
 */
export default function OtsrochkaModal({ open, onClose, onSaved, canEdit }) {
  const toast = useToast();
  const [dney, setDney] = useState(30);
  const [rows, setRows] = useState(null);
  const [vybrany, setVybrany] = useState(() => new Set());
  const [srokZag, setSrokZag] = useState("");
  const [srokVyv, setSrokVyv] = useState("");
  const [osnovanie, setOsnovanie] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setRows(null);
    api.get("/otsrochka/kandidaty", { dney })
      .then((r) => { setRows(r || []); setVybrany(new Set((r || []).map((x) => x.id))); })
      .catch((e) => { setRows([]); toast.show({ tone: "danger", title: "Не удалось загрузить список", description: e.message }); });
  }, [dney]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (open) load(); }, [open, load]);

  const toggle = (id) => setVybrany((s) => {
    const n = new Set(s);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const itogo = (rows || []).filter((r) => vybrany.has(r.id)).reduce(
    (a, r) => ({ m3: a.m3 + (r.ostatok || 0), ga: a.ga + (r.ploshad_ostatok || 0) }), { m3: 0, ga: 0 });

  const sohranit = async () => {
    if (!vybrany.size) { toast.show({ tone: "warning", title: "Отметьте делянки" }); return; }
    if (!srokZag && !srokVyv) { toast.show({ tone: "warning", title: "Укажите новый срок заготовки и/или вывозки" }); return; }
    setSaving(true);
    try {
      const r = await api.post("/otsrochka", {
        ids: [...vybrany], srok_zagotovki: srokZag || null, srok_vyvozki: srokVyv || null, osnovanie,
      });
      toast.show({ tone: "success", title: `Отсрочка внесена: ${r?.sdelano ?? 0} дел.`, description: "Инспекция и напоминания теперь считают по новым срокам." });
      setSrokZag(""); setSrokVyv(""); setOsnovanie("");
      onSaved?.();
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось внести отсрочку", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Нужна отсрочка" size="xl">
      <div className="flex flex-col gap-3">
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <label className="block text-[11.5px] font-semibold text-muted mb-1">Срок заготовки истекает в ближайшие</label>
            <select
              value={dney}
              onChange={(e) => setDney(Number(e.target.value))}
              className="bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-9 text-[13.5px] text-ink outline-none"
            >
              {[14, 30, 60, 90].map((n) => <option key={n} value={n}>{n} дней (и просроченные)</option>)}
            </select>
          </div>
          <Button variant="secondary" size="sm" onClick={() => skachat(dney).catch((e) => toast.show({ tone: "danger", title: "Не удалось скачать", description: e.message }))}>
            ↓ Excel для заявления
          </Button>
          <span className="text-sm text-muted ml-auto">
            Отмечено {vybrany.size}: осталось {fmt(itogo.m3)} м³ · {fmt(itogo.ga)} га
          </span>
        </div>

        {rows === null ? (
          <div className="py-6 text-center text-muted text-sm">Загрузка…</div>
        ) : rows.length === 0 ? (
          <div className="py-6 text-center text-muted text-sm">
            Отсрочка никому не нужна: у всех делянок со сроком в эти {dney} дн. заготовка закончена (площадь пройдена или акт есть). 🎉
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-left text-muted-2 text-[11px] uppercase tracking-wide">
                  <th className="py-1.5 pr-2">
                    <input
                      type="checkbox"
                      className="accent-pine"
                      checked={rows.length > 0 && vybrany.size === rows.length}
                      onChange={(e) => setVybrany(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())}
                    />
                  </th>
                  <th className="py-1.5 pr-3 font-semibold">Делянка</th>
                  <th className="py-1.5 pr-3 font-semibold">Билет</th>
                  <th className="py-1.5 pr-3 font-semibold">Срок заготовки</th>
                  <th className="py-1.5 pr-3 font-semibold">Вывозки</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">Лимит, м³</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">Осталось деловой</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">дров</th>
                  <th className="py-1.5 pr-3 font-semibold text-right">всего, м³</th>
                  <th className="py-1.5 font-semibold text-right">Осталось, га</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-border hover:bg-hover cursor-pointer" onClick={() => toggle(r.id)}>
                    <td className="py-2 pr-2"><input type="checkbox" className="accent-pine" checked={vybrany.has(r.id)} readOnly /></td>
                    <td className="py-2 pr-3">
                      <div className="font-semibold text-ink">{r.nazvanie || `Делянка №${r.id}`}</div>
                      <div className="text-[11.5px] text-muted">
                        {r.vydely}{r.lesnichestvo ? ` · ${r.lesnichestvo}` : ""}
                        {r.storonnyaya ? <span className="text-oak"> · рубит {r.storonnyaya.zagotovitel}</span> : null}
                        {r.otsrochek ? <span> · отсрочек было: {r.otsrochek}</span> : null}
                      </div>
                    </td>
                    <td className="py-2 pr-3 text-muted">{r.bilet ? `№${r.bilet}` : "—"}{r.bilet_data ? ` от ${r.bilet_data}` : ""}</td>
                    <td className="py-2 pr-3">
                      <div>{r.srok_zagotovki}</div>
                      <StatusBadge
                        tone={r.prosrochen ? "danger" : r.dney_ostalos <= 7 ? "warning" : "neutral"}
                        label={r.prosrochen ? `просрочен ${-r.dney_ostalos} дн.` : `через ${r.dney_ostalos} дн.`}
                      />
                    </td>
                    <td className="py-2 pr-3 text-muted">{r.srok_vyvozki || "—"}</td>
                    <td className="py-2 pr-3 text-right">{r.limit ? fmt(r.limit) : "нет МДО"}</td>
                    <td className="py-2 pr-3 text-right">{fmt(r.ostatok_delovaya)}</td>
                    <td className="py-2 pr-3 text-right">{fmt(r.ostatok_drova)}</td>
                    <td className="py-2 pr-3 text-right font-semibold">{fmt(r.ostatok)}</td>
                    <td className="py-2 text-right">{fmt(r.ploshad_ostatok)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {canEdit && rows && rows.length > 0 && (
          <div className="rounded-[10px] border border-border bg-surface-alt p-3 flex flex-col gap-2.5">
            <div className="text-sm font-semibold text-ink">Отсрочку дали — внести новые сроки отмеченным делянкам</div>
            <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(190px,1fr))]">
              <DateField label="Новый срок заготовки" value={srokZag} onChange={setSrokZag} />
              <DateField label="Новый срок вывозки" value={srokVyv} onChange={setSrokVyv} />
              <TextField label="Основание (решение, № и дата)" value={osnovanie} onChange={(e) => setOsnovanie(e.target.value)} placeholder="напр. письмо ГПЛХО №123 от 05.11.2026" />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <Button variant="primary" size="sm" onClick={sohranit} loading={saving}>
                Внести отсрочку ({vybrany.size})
              </Button>
              <span className="text-xs text-muted">
                Старые сроки сохранятся в истории делянки; ошибку можно отменить в карточке Инспекции.
              </span>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
