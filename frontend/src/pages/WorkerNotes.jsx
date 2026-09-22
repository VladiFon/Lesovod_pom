import React, { useEffect, useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";
import { api } from "../api/client.js";

/**
 * Экран "Заметки" (часть раздела "Люди") — односторонняя лента
 * "рабочий -> мастер" поверх GET/PATCH /api/notes (см.
 * app/routers/notes.py). Рабочий пишет в мобильном приложении
 * (POST /api/bot/notes), здесь только читают и отмечают прочитанным —
 * это НЕ переписка, ответа обратно рабочему не предусмотрено.
 */
function formatDateTime(s) {
  if (!s) return "—";
  const [date, time] = s.split(" ");
  return `${date.split("-").reverse().join(".")} ${time?.slice(0, 5) ?? ""}`;
}

function NoteCard({ note, onMarkRead }) {
  const unread = !note.is_read;
  return (
    <Card className={unread ? "border-pine" : ""}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {unread && <span className="h-2 w-2 rounded-full bg-pine shrink-0" aria-hidden="true" />}
            <span className="font-ui font-bold text-ink">{note.sotrudnik_fio}</span>
            <span className="text-muted-2 text-xs">{note.sotrudnik_dolzhnost}</span>
          </div>
          <p className="text-muted text-xs mt-0.5">{formatDateTime(note.created_at)}</p>
        </div>
        {unread && (
          <Button variant="secondary" size="sm" onClick={() => onMarkRead(note.id)}>
            Прочитано
          </Button>
        )}
      </div>
      <p className="text-ink text-base mt-3 whitespace-pre-line">{note.text}</p>
    </Card>
  );
}

export default function WorkerNotes() {
  const toast = useToast();
  const [notes, setNotes] = useState(null);

  const load = () =>
    api
      .get("/notes/")
      .then(setNotes)
      .catch((e) => toast.show({ tone: "danger", title: "Не удалось загрузить заметки", description: e.message }));

  useEffect(() => {
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

  const unreadCount = (notes ?? []).filter((n) => !n.is_read).length;

  return (
    <div className="p-8 flex flex-col gap-4">
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
            <NoteCard key={note.id} note={note} onMarkRead={handleMarkRead} />
          ))}
        </div>
      )}
    </div>
  );
}
