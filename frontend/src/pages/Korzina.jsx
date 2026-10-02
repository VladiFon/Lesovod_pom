import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import DataTable from "../components/DataTable.jsx";
import { useToast } from "../components/Toast.jsx";
import { useCan } from "../auth.jsx";

const SOSTAV_LABELS = {
  delyanka_item: "выделов",
  raskhod_naryad: "нарядов",
  raskhod_pozitsiya: "позиций нарядов",
  lesokultury_meropriyatiya: "мероприятий",
  osvidetelstvovanie_acts: "актов освид.",
  brigada_naznachenie: "назначений бригад",
};

function sostavText(sostav) {
  return Object.entries(sostav || {})
    .filter(([k, n]) => SOSTAV_LABELS[k] && n > 0)
    .map(([k, n]) => `${n} ${SOSTAV_LABELS[k]}`)
    .join(", ");
}

/**
 * Корзина: удалённые делянки и участки лесных культур хранятся 30 дней
 * (backend app/korzina.py). «Вернуть» — лесничий и администратор,
 * «Стереть навсегда» — только администратор.
 */
export default function Korzina() {
  const toast = useToast();
  const can = useCan();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/korzina/");
      setRows(res.items || []);
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось открыть корзину", description: e.message });
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const restore = async (row) => {
    setBusy(row.id);
    try {
      await api.post(`/korzina/${row.id}/restore`);
      toast.show({ tone: "success", title: "Возвращено", description: `${row.tip_label} «${row.nazvanie}» снова в списке` });
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось вернуть", description: e.message });
    } finally {
      setBusy(null);
    }
  };

  const purge = async (row) => {
    if (!window.confirm(`Стереть «${row.nazvanie}» навсегда? Вернуть будет нельзя.`)) return;
    setBusy(row.id);
    try {
      await api.delete(`/korzina/${row.id}`);
      load();
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось стереть", description: e.message });
    } finally {
      setBusy(null);
    }
  };

  const columns = [
    { key: "tip_label", header: "Что", width: 170 },
    {
      key: "nazvanie",
      header: "Название",
      render: (r) => (
        <div>
          <div className="font-semibold text-ink">{r.nazvanie || `№${r.obj_id}`}</div>
          {sostavText(r.sostav) && <div className="text-xs text-muted">вместе с: {sostavText(r.sostav)}</div>}
        </div>
      ),
    },
    { key: "deleted_by", header: "Кто удалил", width: 120 },
    { key: "deleted_at", header: "Когда", width: 150 },
    { key: "udalit_do", header: "Хранится до", width: 110 },
    {
      key: "actions",
      header: "",
      width: 250,
      render: (r) => (
        <div className="flex gap-2 justify-end">
          <Button variant="primary" size="sm" loading={busy === r.id} onClick={() => restore(r)}>
            ↩ Вернуть
          </Button>
          {can("korzina.purge") && (
            <Button variant="secondary" size="sm" disabled={busy === r.id} onClick={() => purge(r)}>
              Стереть
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="p-6 flex flex-col gap-4">
      <Card
        title="Удалённое за последние 30 дней"
        subtitle="Делянка возвращается вместе с выделами, нарядами, актами и назначениями бригад. Через 30 дней запись стирается сама."
      >
        <DataTable
          columns={columns}
          rows={rows}
          loading={loading}
          emptyTitle="Корзина пуста"
          emptyDescription="Если удалить делянку или участок лесных культур, они появятся здесь, и их можно будет вернуть."
        />
      </Card>
    </div>
  );
}
