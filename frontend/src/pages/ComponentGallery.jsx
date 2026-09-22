import React, { useState } from "react";
import Card from "../components/Card.jsx";
import Button from "../components/Button.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import Modal from "../components/Modal.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { useToast } from "../components/Toast.jsx";

function Section({ title, children }) {
  return (
    <Card title={title}>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </Card>
  );
}

export default function ComponentGallery() {
  const [modalOpen, setModalOpen] = useState(false);
  const toast = useToast();

  return (
    <div className="p-8 flex flex-col gap-6 max-w-4xl">
      <Section title="Button">
        <Button variant="primary">Сохранить</Button>
        <Button variant="secondary">Отмена</Button>
        <Button variant="danger">Удалить</Button>
        <Button variant="ghost">Загрузить файл</Button>
        <Button variant="primary" loading>
          Генерация…
        </Button>
        <Button variant="primary" disabled>
          Недоступно
        </Button>
      </Section>

      <Section title="StatusBadge">
        <StatusBadge status="готов" />
        <StatusBadge status="в процессе" />
        <StatusBadge status="ошибка" />
        <StatusBadge status="архив" />
        <StatusBadge tone="info" label="Новое" />
      </Section>

      <Section title="Toast">
        <Button
          onClick={() =>
            toast.show({ tone: "success", title: "Сохранено", description: "Изменения записаны." })
          }
        >
          success
        </Button>
        <Button
          onClick={() =>
            toast.show({
              tone: "danger",
              title: "Ошибка сети",
              description: "Не удалось связаться с сервером.",
            })
          }
        >
          danger
        </Button>
        <Button
          onClick={() =>
            toast.show({ tone: "warning", title: "Расхождение с ЕГАИС", description: "Проверьте наряд №42." })
          }
        >
          warning
        </Button>
      </Section>

      <Section title="Modal">
        <Button onClick={() => setModalOpen(true)}>Открыть модалку</Button>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Подтверждение"
          footer={
            <>
              <Button variant="secondary" onClick={() => setModalOpen(false)}>
                Отмена
              </Button>
              <Button variant="danger" onClick={() => setModalOpen(false)}>
                Удалить 3 документа
              </Button>
            </>
          }
        >
          <p className="text-ink text-base">
            Действие необратимо. Выбранные документы будут удалены из хранилища и записи в базе.
          </p>
        </Modal>
      </Section>

      <Card title="EmptyState">
        <EmptyState
          title="Ничего не найдено"
          description="Попробуйте изменить фильтры или период."
          action={<Button variant="secondary">Сбросить фильтры</Button>}
        />
      </Card>
    </div>
  );
}
