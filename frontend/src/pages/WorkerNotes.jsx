import React, { useEffect, useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";
import { api } from "../api/client.js";
import ZadachaModal from "../components/ZadachaModal.jsx";

/**
 * Экран "Заметки" (часть раздела "Люди") — односторонняя лента
 * "рабочий -> мастер" поверх GET/PATCH /api/notes (см.
 * app/routers/notes.py). Рабочий пишет в мобильном приложении
 * (POST /api/bot/notes), здесь читают, отмечают прочитанным, отвечают
 * (ответ виден рабочему в «Моих заметках», POST /api/notes/{id}/reply) и
 * одним нажатием ставят из заметки или метки с карты задачу (01.10.2026).
 */
function formatDateTime(s) {
  if (!s) return "—";
  const [date, time] = s.split(" ");
  return `${date.split("-").reverse().join(".")} ${time?.slice(0, 5) ?? ""}`;
}

function NoteCard({ note, onMarkRead, onReply, onZadacha }) {
  const unread = !note.is_read;
  const [otvet, setOtvet] = useState(null);
  return (
    <Card className={unread ? "border-pine" : ""}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {unread && <span className="h-2 w-2 rounded-full bg-pine shrink-0" aria-hidden="true" />}
            <span className="font-ui font-bold text-[13.5px] text-ink">{note.sotrudnik_fio}</span>
            <span className="text-muted-2 text-xs">{note.sotrudnik_dolzhnost}</span>
          </div>
          <p className="text-muted text-xs mt-0.5">{formatDateTime(note.created_at)}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="ghost" size="sm" onClick={() => onZadacha(note)}>Сделать задачей</Button>
          {!note.otvet && otvet === null && (
            <Button variant="ghost" size="sm" onClick={() => setOtvet("")}>Ответить</Button>
          )}
          {unread && (
            <Button variant="secondary" size="sm" onClick={() => onMarkRead(note.id)}>
              Прочитано
            </Button>
          )}
        </div>
      </div>
      <p className="text-ink text-[13px] leading-[1.45] mt-2.5 whitespace-pre-line">{note.text}</p>
      {note.otvet && (
        <div className="mt-2.5 rounded-[10px] bg-mint-soft px-3 py-2 text-[12.5px] text-ink">
          <span className="text-muted-2">Ответ{note.otvet_by ? ` (${note.otvet_by})` : ""}, {formatDateTime(note.otvet_at)}:</span> {note.otvet}
        </div>
      )}
      {otvet !== null && (
        <div className="mt-2.5 flex gap-2 items-start">
          <textarea
            autoFocus
            value={otvet}
            onChange={(e) => setOtvet(e.target.value)}
            rows={2}
            placeholder="Ответ увидит рабочий в «Моих заметках» в приложении"
            className="flex-1 bg-surface border border-border focus:border-pine rounded-[10px] px-3 py-2 text-[13px] text-ink outline-none"
          />
          <Button variant="primary" size="sm" disabled={!otvet.trim()} onClick={async () => { if (await onReply(note.id, otvet)) setOtvet(null); }}>
            Отправить
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setOtvet(null)}>Отмена</Button>
        </div>
      )}
    </Card>
  );
}

export default function WorkerNotes() {
  const toast = useToast();
  const [notes, setNotes] = useState(null);
  const [metki, setMetki] = useState([]);
  const [zadacha, setZadacha] = useState(null);

  const load = () =>
    api
      .get("/notes/")
      .then(setNotes)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить заметки", description: e.message }));

  useEffect(() => {
    api.get("/notes/metki").then(setMetki).catch(() => {});
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleMarkRead = async (noteId) => {
    setNotes((prev) => prev.map((n) => (n.id === noteId ? { ...n, is_read: 1 } : n)));
    try {
      await api.patch(`/notes/${noteId}`, { is_read: true });
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось отметить прочитанным", description: e.message });
      setNotes((prev) => prev.map((n) => (n.id === noteId ? { ...n, is_read: 0 } : n)));
    }
  };

  const handleReply = async (noteId, text) => {
    try {
      await api.post(`/notes/${noteId}/reply`, { text });
      toast.show({ tone: "success", title: "Ответ отправлен", description: "Рабочий увидит его в приложении" });
      load();
      return true;
    } catch (e) {
      toast.show({ tone: "danger", title: "Не удалось отправить ответ", description: e.message });
      return false;
    }
  };

  const zadachaIzZametki = (note) =>
    setZadacha({ sotrudnik_id: note.sotrudnik_id, zadacha: note.text });

  const zadachaIzMetki = (m) =>
    setZadacha({
      zadacha: `${m.kategoriya_label}${m.note_text ? `: ${m.note_text}` : ""} (метка ${m.author_fio ? `от ${m.author_fio}, ` : ""}${Number(m.lat).toFixed(5)}, ${Number(m.lon).toFixed(5)})`,
    });

  const unreadCount = (notes ?? []).filter((n) => !n.is_read).length;

  return (
    <div className="p-[18px] flex flex-col gap-4">
      {notes !== null && notes.length > 0 && (
        <p className="text-muted text-base">
          {unreadCount > 0 ? `Непрочитанных: ${unreadCount} из ${notes.length}` : `Все ${notes.length} заметок прочитаны`}
        </p>
      )}

      {notes === null ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <div className="h-3.5 rounded bg-hover animate-pulse" style={{ width: "30%" }} />
              <div className="h-3 mt-3 rounded bg-hover animate-pulse" style={{ width: "80%" }} />
            </Card>
          ))}
        </div>
      ) : notes.length === 0 ? (
        <EmptyState
          icon="📝"
          title="Заметок пока нет"
          description="Рабочие пишут заметки в мобильном приложении — они появятся здесь лентой."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {notes.map((note) => (
            <NoteCard key={note.id} note={note} onMarkRead={handleMarkRead} onReply={handleReply} onZadacha={zadachaIzZametki} />
          ))}
        </div>
      )}

      {metki.length > 0 && (
        <Card title="Метки с карты" subtitle="Что рабочие отметили на карте в приложении: ветровал, склад, плохая дорога… Из метки можно сразу поставить задачу.">
          <div className="flex flex-col divide-y divide-border">
            {metki.slice(0, 30).map((m) => (
              <div key={m.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0 text-[13px]">
                  <div className="text-ink">
                    <b>{m.kategoriya_label}</b>
                    {m.note_text ? ` — ${m.note_text}` : ""}
                  </div>
                  <div className="text-muted-2 text-xs">
                    {formatDateTime(m.created_at)}
                    {m.author_fio ? ` · ${m.author_fio}` : ""} ·{" "}
                    <a
                      className="underline"
                      href={`https://yandex.ru/maps/?pt=${m.lon},${m.lat}&z=16&l=sat`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {Number(m.lat).toFixed(5)}, {Number(m.lon).toFixed(5)}
                    </a>
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => zadachaIzMetki(m)}>Сделать задачей</Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <ZadachaModal open={!!zadacha} initial={zadacha} onClose={() => setZadacha(null)} />
    </div>
  );
}
