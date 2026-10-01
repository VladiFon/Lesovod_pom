import React, { useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import Button from "./Button.jsx";
import TextField from "./TextField.jsx";
import TextAreaField from "./TextAreaField.jsx";
import { useToast } from "./Toast.jsx";
import { api } from "../api/client.js";

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function addDays(iso, n) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d + n);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

const SELECT_CLS =
  "w-full bg-surface border border-border focus:border-pine rounded-[10px] px-2.5 h-10 text-[13.5px] text-ink outline-none";

/**
 * Постановка задачи (work_plan) одним окном — анализ удобства 01.10.2026:
 * исполнитель — человек ИЛИ вся бригада, место — из активных делянок
 * списком (без поиска по кварталу/выделу), «повторить N дней». Тем же
 * окном задача ставится из заметки или метки рабочего (initial).
 */
export default function ZadachaModal({ open, onClose, initial, onCreated }) {
  const toast = useToast();
  const [sotrudniki, setSotrudniki] = useState([]);
  const [brigady, setBrigady] = useState([]);
  const [mesta, setMesta] = useState([]);
  const [kto, setKto] = useState("");
  const [data, setData] = useState(todayIso());
  const [dney, setDney] = useState(1);
  const [itemId, setItemId] = useState("");
  const [zadacha, setZadacha] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setKto(initial?.sotrudnik_id ? `s:${initial.sotrudnik_id}` : "");
    setData(todayIso());
    setDney(1);
    setItemId(initial?.delyanka_item_id ? String(initial.delyanka_item_id) : "");
    setZadacha(initial?.zadacha || "");
    api.get("/work-plan/sotrudniki").then(setSotrudniki).catch(() => {});
    api.get("/tabel/delyanki", { limit: 200 }).then((rows) => setMesta((rows || []).filter((r) => r.status === "активна"))).catch(() => {});
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return;
    api.get("/tabel/brigady", { data }).then(setBrigady).catch(() => setBrigady([]));
  }, [open, data]);

  // Бригада выбрана — подставляем её делянку на этот день, если место ещё не выбрано.
  useEffect(() => {
    if (!kto.startsWith("b:") || itemId) return;
    const b = brigady.find((x) => String(x.id) === kto.slice(2));
    if (b?.mesta?.length === 1) setItemId(String(b.mesta[0].item_id));
  }, [kto, brigady]); // eslint-disable-line react-hooks/exhaustive-deps

  const ispolniteli = () => {
    if (kto.startsWith("s:")) return [Number(kto.slice(2))];
    if (kto.startsWith("b:")) {
      const b = brigady.find((x) => String(x.id) === kto.slice(2));
      return (b?.sostav || []).map((s) => s.sotrudnik_id);
    }
    return [];
  };

  const save = async () => {
    const ids = ispolniteli();
    if (!ids.length) return toast.show({ tone: "warning", title: "Выберите сотрудника или бригаду" });
    if (!zadacha.trim()) return toast.show({ tone: "warning", title: "Опишите задачу" });
    setSaving(true);
    try {
      let n = 0;
      for (let i = 0; i < dney; i += 1) {
        for (const sid of ids) {
          await api.post("/work-plan/", {
            sotrudnik_id: sid,
            data: addDays(data, i),
            zadacha: zadacha.trim(),
            delyanka_item_id: itemId ? Number(itemId) : null,
          });
          n += 1;
        }
      }
      toast.show({ tone: "success", title: "Задача поставлена", description: n > 1 ? `Записей в плане: ${n}` : "Появится у рабочего в «Мои задачи»" });
      onCreated?.();
      onClose();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось поставить задачу", description: e.message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Новая задача"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          <Button variant="primary" loading={saving} onClick={save}>Поставить задачу</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-muted font-medium">Кому</label>
          <select value={kto} onChange={(e) => setKto(e.target.value)} className={SELECT_CLS}>
            <option value="">Выберите…</option>
            {brigady.length > 0 && (
              <optgroup label="Бригадой (каждому в составе)">
                {brigady.map((b) => (
                  <option key={b.id} value={`b:${b.id}`}>👥 {b.nazvanie} ({(b.sostav || []).length} чел.)</option>
                ))}
              </optgroup>
            )}
            <optgroup label="Сотруднику">
              {sotrudniki.map((s) => (
                <option key={s.id} value={`s:${s.id}`}>{s.fio}{s.dolzhnost ? ` — ${s.dolzhnost}` : ""}</option>
              ))}
            </optgroup>
          </select>
        </div>
        <div className="flex gap-3">
          <TextField label="С какого дня" type="date" value={data} onChange={(e) => setData(e.target.value)} />
          <div className="flex flex-col gap-1.5">
            <label className="text-sm text-muted font-medium">Повторить</label>
            <select value={dney} onChange={(e) => setDney(Number(e.target.value))} className={SELECT_CLS}>
              <option value={1}>только этот день</option>
              <option value={2}>2 дня подряд</option>
              <option value={3}>3 дня подряд</option>
              <option value={5}>5 дней подряд</option>
              <option value={7}>неделю (7 дней)</option>
            </select>
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-muted font-medium">Где (активная делянка)</label>
          <select value={itemId} onChange={(e) => setItemId(e.target.value)} className={SELECT_CLS}>
            <option value="">— без делянки —</option>
            {mesta.map((m) => (
              <option key={m.item_id} value={m.item_id}>
                кв. {m.kvartal} / выд. {m.vydel}{m.lesoseka_nomer ? ` · л.${m.lesoseka_nomer}` : ""} — {m.nazvanie}
              </option>
            ))}
          </select>
        </div>
        <TextAreaField label="Задача" rows={3} value={zadacha} onChange={(e) => setZadacha(e.target.value)} />
      </div>
    </Modal>
  );
}
