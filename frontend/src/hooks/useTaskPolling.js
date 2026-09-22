import { api } from "../api/client.js";

/**
 * pollTask — опрашивает GET /api/tasks/{id} (app/routers/tasks.py, статусы
 * из webext.py: pending → running → done|error) до готовности. Единая точка
 * для всех фоновых задач Этапа 5: импорт МДО и генерация Акта/Листков/
 * Техкарт/Акта готовности — все ставятся через BackgroundTasks и отдают
 * один и тот же { task_id }, поэтому один хук закрывает все сценарии
 * (см. заготовку под это в комментарии Dashboard.jsx из Этапа 4).
 *
 * Возвращает task.result при status="done", бросает Error при "error"
 * или по истечении timeoutMs.
 *
 * Блок C.2 плана доработки: импорт МДО может ещё вернуть промежуточный
 * статус "needs_vydel_choice" (составная запись выдела, например "14, 15" —
 * backend просит выбрать, какой считать главным для сверки с таксацией;
 * см. app/routers/delyanki.py::_run_import_mdo). Такой статус не бросает
 * ошибку и не завершает опрос — вызывающий код должен передать
 * onNeedsVydelChoice(task.result) -> Promise<string>, которая покажет
 * диалог выбора и вернёт ответ пользователя; ответ уходит на
 * POST /api/delyanki/import-mdo/{taskId}/resolve-vydel, после чего опрос
 * продолжается (backend снова переводит задачу в "running" и может ещё
 * раз запросить выбор — например, для следующего файла в пачке).
 */
export async function pollTask(
  taskId,
  { intervalMs = 1500, timeoutMs = 5 * 60 * 1000, onNeedsVydelChoice } = {}
) {
  const startedAt = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const task = await api.get(`/tasks/${taskId}`);
    if (task.status === "done") return task.result;
    if (task.status === "error") throw new Error(task.error_text || "Задача завершилась с ошибкой");
    if (task.status === "needs_vydel_choice") {
      if (!onNeedsVydelChoice) {
        throw new Error(
          "МДО содержит составную запись выдела — нужно выбрать главный, " +
            "но экран не поддерживает этот диалог"
        );
      }
      const answer = await onNeedsVydelChoice(task.result || {});
      await api.post(`/delyanki/import-mdo/${taskId}/resolve-vydel`, { answer: answer ?? "" });
      // сервер уже разблокирован (или ждёт следующий выбор) — опрашиваем
      // сразу, не выжидая intervalMs, чтобы UI быстрее увидел прогресс
      continue;
    }
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error("Превышено время ожидания задачи — проверьте статус позже");
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
