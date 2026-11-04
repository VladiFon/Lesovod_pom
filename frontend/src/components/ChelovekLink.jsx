import React from "react";
import { openScreen } from "../nav.js";

/** Открыть карточку человека (экран «Сотрудники», вкладка «Люди»). */
export function openChelovek(id) {
  if (id) openScreen("sotrudniki", { tab: "kartochka", s: id });
}

/** Открыть экран по ссылке с сервера ({screen, params}). */
export function openSsylka(ssylka) {
  if (ssylka?.screen) openScreen(ssylka.screen, ssylka.params || {});
}

/**
 * ФИО ссылкой на карточку человека (04.11.2026: «сайт разбросан» — по
 * любому имени на любом экране можно провалиться во всё, что о человеке
 * известно). Без id — просто текст (сторонний исполнитель, старая запись).
 */
export default function ChelovekLink({ id, fio, className = "", children }) {
  const text = children ?? fio ?? "—";
  if (!id) return <span className={className}>{text}</span>;
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); openChelovek(id); }}
      title="Открыть карточку человека"
      className={["text-left text-pine hover:underline decoration-dotted underline-offset-2 font-semibold", className].join(" ")}
    >
      {text}
    </button>
  );
}

/** Список людей через запятую, каждый — ссылкой. people: [{id, fio}] */
export function ChelovekList({ people, className = "" }) {
  if (!people?.length) return <span className="text-muted">—</span>;
  return (
    <span className={className}>
      {people.map((p, i) => (
        <React.Fragment key={`${p.id ?? "x"}-${p.fio}-${i}`}>
          {i > 0 && ", "}
          <ChelovekLink id={p.id} fio={p.fio} />
          {p.storonniy && <span className="text-muted-2 text-xs"> (сторонний)</span>}
        </React.Fragment>
      ))}
    </span>
  );
}

/** Открыть выдел в «Таксации» («жизнь выдела»): квартал, выдел, лесничество. */
export function openVydel(kvartal, vydel, lesnichestvo) {
  if (!kvartal || !vydel) return;
  openScreen("taxation", { kv: kvartal, vyd: String(vydel).split(/[,;\s]+/)[0], l: lesnichestvo || "" });
}

/** «кв.71 выд.2» ссылкой на «жизнь выдела» в Таксации. */
export function VydelLink({ kvartal, vydel, lesnichestvo, className = "", children }) {
  if (!kvartal || !vydel) return <span className={className}>{children ?? "—"}</span>;
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); openVydel(kvartal, vydel, lesnichestvo); }}
      title="Что было на выделе (Таксация)"
      className={["text-left text-pine hover:underline decoration-dotted underline-offset-2", className].join(" ")}
    >
      {children ?? `кв.${kvartal} выд.${vydel}`}
    </button>
  );
}
