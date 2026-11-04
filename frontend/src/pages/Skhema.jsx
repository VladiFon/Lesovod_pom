import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api/client.js";
import { openScreen } from "../nav.js";

/**
 * «Как работает сайт» — живая схема (Влад, 04.11.2026: «нарисовать схему
 * работы сайта, всё как работает и от чего зависит, чтобы работник мог
 * посмотреть, что надо сделать»).
 *
 * Три дорожки — заготовка, лес, люди. Каждый шаг: что это, кто делает,
 * откуда берёт данные и кого кормит, живая цифра (сколько сейчас на этом
 * шаге / сколько ждёт) и переход на экран. Сверху — «Сегодня надо».
 * Переключатель роли подсвечивает свои шаги. Цифры: app/routers/skhema.py.
 */

const ROLI = [
  { k: "", label: "Все" },
  { k: "les", label: "🧑‍💼 Лесничий / офис" },
  { k: "mas", label: "👷 Мастер" },
  { k: "rab", label: "📱 Рабочий" },
];
const KTO = { les: "лесничий", mas: "мастер", rab: "рабочий", rob: "робот" };

const n = (v) => Number(v || 0);
function dn(k, u, z) {
  return n(u[k]) + n(z[k]?.count);
}

// Узлы. cifry(u, z) → [{t, tone}] — что показать на узле прямо сейчас.
const DOROZHKI = [
  {
    k: "zag", title: "🪓 Заготовка", sub: "от файла МДО до закрытой делянки",
    uzly: [
      {
        id: "mdo", emoji: "📥", title: "Импорт МДО", screen: "plots", kto: ["les"],
        chto: "Файл МДО → делянка-черновик: выделы, площади, запас по породам.",
        beret: "файл МДО", kormit: "билет, Текущие изменения (прил.3, 15)",
        cifry: (u) => [u.del_chernovik && { t: `${u.del_chernovik} черновик.`, tone: "info" }],
      },
      {
        id: "bilet", emoji: "🎫", title: "Лесорубочный билет", screen: "plots", kto: ["les"],
        chto: "Номер, дата, сроки заготовки и вывозки. С билетом делянка становится активной.",
        beret: "черновик делянки", kormit: "Расход (лимиты), Инспекция (сроки), отсрочка",
        cifry: (u, z) => [z.chernoviki && { t: `${z.chernoviki.count} без билета`, tone: "warn" }],
      },
      {
        id: "rubka", emoji: "🪚", title: "Рубка: наряды и смены", screen: "raskhod", kto: ["mas", "rab"],
        chto: "Наряды-задания в Расходе. Рабочие с телефона шлют «Отчёт за смену»: кубы, рейсы, техника.",
        beret: "билет, бригады, техника", kormit: "% освоения, табель, карточку человека",
        cifry: (u) => [u.del_v_rabote && { t: `${u.del_v_rabote} в работе`, tone: "ok" }, u.smen_segodnya != null && { t: `${u.smen_segodnya} смен сегодня`, tone: "muted" }],
      },
      {
        id: "egais", emoji: "📊", title: "ЕГАИС", screen: "raskhod", params: { razbor: "1" }, kto: ["rob", "les"],
        chto: "Робот в 20:00 выгружает реестр. Сайт сверяет приход и расход по выделам и породам.",
        beret: "десктоп-ЕГАИС", kormit: "Расход (факт), сверку прихода",
        cifry: (u, z) => [
          u.egais_dney != null && { t: u.egais_dney === 0 ? "выгрузка сегодня" : `выгрузка ${u.egais_dney} дн. назад`, tone: u.egais_dney > 2 ? "warn" : "ok" },
          z.egais && { t: `${z.egais.count} разобрать`, tone: "warn" },
        ],
      },
      {
        id: "dorub", emoji: "🏁", title: "Дорублена", screen: "inspection", kto: ["mas", "les"],
        chto: "Площадь пройдена по нарядам (или по справке стороннего заготовителя). Пошли 30 дней на акт.",
        beret: "наряды, справка заготовителя", kormit: "срок акта в Инспекции",
        cifry: (u, z) => [u.del_dorublena && { t: `${u.del_dorublena} дорублено`, tone: "info" }, z.akty_skoro && { t: `${z.akty_skoro.count} акт скоро`, tone: "warn" }, z.akty_prosr && { t: `${z.akty_prosr.count} просрочено`, tone: "bad" }],
      },
      {
        id: "akt", emoji: "📝", title: "Акт освидетельствования", screen: "inspection", kto: ["les"],
        chto: "Акт в 4 шага, «Фактически» — из нарядов. После акта делянка «освидетельствована».",
        beret: "наряды, билет, пресет комиссии", kormit: "закрытие делянки, Документы",
        cifry: (u, z) => [u.del_osvid && { t: `${u.del_osvid} с актом`, tone: "ok" }, z.zakryt && { t: `${z.zakryt.count} закрыть`, tone: "info" }],
      },
      {
        id: "arhiv", emoji: "🗄", title: "Закрыта", screen: "plots", kto: ["les"],
        chto: "Делянка уходит в архив. Вернуть в работу можно из фильтра «Закрыты».",
        beret: "акт", kormit: "Архив, отчёты",
        cifry: (u) => [u.del_zakryta && { t: `${u.del_zakryta} в архиве`, tone: "muted" }],
      },
    ],
    bok: [
      {
        id: "otsr", emoji: "⏳", title: "Отсрочка", screen: "inspection", params: { otsrochka: "1" }, kto: ["les"],
        chto: "Срок заготовки ≤ 30 дней, а лес не вырублен → заявление и новые сроки.",
        cifry: (u, z) => [z.otsrochka && { t: `${z.otsrochka.count} нужна`, tone: z.otsrochka.tone === "danger" ? "bad" : "warn" }],
      },
      {
        id: "docs", emoji: "📄", title: "Документы", screen: "documents", kto: ["les"],
        chto: "Все бумаги по всем делянкам: акты, справки, ведомости.",
        cifry: () => [],
      },
    ],
  },
  {
    k: "les", title: "🌲 Лес", sub: "выдел → культуры → уходы → отчётность",
    uzly: [
      {
        id: "tax", emoji: "🔎", title: "Таксация · жизнь выдела", screen: "taxation", kto: ["les", "mas"],
        chto: "Карточка выдела и всё, что на нём было: рубки, культуры, пробы, кто работал.",
        beret: "ГИСлесхоз, все разделы", kormit: "поиск 71/2 (Ctrl+K)",
        cifry: () => [],
      },
      {
        id: "lk", emoji: "🌱", title: "Лесные культуры", screen: "forestry", kto: ["les"],
        chto: "Книга лесных культур: участок, год, порода, густота, норматив перевода.",
        beret: "выдел, вырубка", kormit: "журнал мероприятий, рубки ухода, прил. ТИ",
        cifry: (u) => [u.lk_aktivnyh != null && { t: `${u.lk_aktivnyh} участков`, tone: "ok" }],
      },
      {
        id: "lkzh", emoji: "📒", title: "Журнал мероприятий", screen: "forestry", kto: ["les", "mas"],
        chto: "Приёмка, уходы, дополнение, инвентаризация 1-го и 3-го года. «Кто делал» → в карточку человека.",
        beret: "участок культур, люди", kormit: "Журнал работ, перевод",
        cifry: (u) => [u.lk_inventarizaciya ? { t: `${u.lk_inventarizaciya} ждут инвентаризацию`, tone: "warn" } : u.lk_aktivnyh != null && { t: "инвентаризации в срок", tone: "ok" }],
      },
      {
        id: "uhody", emoji: "✂️", title: "Рубки ухода", screen: "uhody", kto: ["mas", "rab"],
        chto: "Проба → «Выполнение» по отчётам с телефона → проба закрывается сама на 98% площади.",
        beret: "участок культур / выдел, отчёты за смену", kormit: "журнал, прил. ТИ, хворост",
        cifry: (u) => [u.proby_otkryty != null && { t: `${u.proby_otkryty} проб открыто`, tone: u.proby_otkryty ? "info" : "muted" }, u.proby_zakryty_god && { t: `${u.proby_zakryty_god} закрыто за год`, tone: "ok" }],
      },
      {
        id: "perevod", emoji: "🌳", title: "Перевод в покрытые лесом", screen: "forestry", kto: ["les"],
        chto: "Инвентаризация на перевод → участок выходит из культур.",
        beret: "инвентаризации", kormit: "Текущие изменения",
        cifry: () => [],
      },
      {
        id: "ti", emoji: "📑", title: "Текущие изменения", screen: "tek_izm", kto: ["les"],
        chto: "Ведомости прил. 1–15 для Белгослеса собираются из рубок, культур и уходов.",
        beret: "делянки, культуры, рубки ухода", kormit: "отчётность",
        cifry: () => [],
      },
    ],
  },
  {
    k: "lyudi", title: "👥 Люди", sub: "кто, где, что сделал",
    uzly: [
      {
        id: "sotr", emoji: "👥", title: "Сотрудники и бригады", screen: "sotrudniki", params: { tab: "spisok" }, kto: ["les"],
        chto: "Справочник людей, бригады, закреплённая техника, логины для телефона.",
        beret: "—", kormit: "всё ниже",
        cifry: (u) => [u.lyudey != null && { t: `${u.lyudey} чел.`, tone: "muted" }, u.brigad && { t: `${u.brigad} бригад`, tone: "muted" }],
      },
      {
        id: "zad", emoji: "🗓", title: "Задачи", screen: "zadachi", kto: ["les", "mas"],
        chto: "План работ: кому, где, когда. Рабочий видит задачу в телефоне.",
        beret: "люди, делянки, культуры", kormit: "телефон, Журнал работ",
        cifry: (u) => [u.zadach_aktivnyh != null && { t: `${u.zadach_aktivnyh} активных`, tone: "info" }, u.zadach_prosrocheno && { t: `${u.zadach_prosrocheno} просрочено`, tone: "bad" }],
      },
      {
        id: "tel", emoji: "📱", title: "Телефон", screen: "telefon", kto: ["rab"],
        chto: "Отметка «на работе», отчёт за смену, заметки, фото проб, топливо.",
        beret: "задачи, делянки, пробы", kormit: "табель, Расход, рубки ухода",
        cifry: (u, z) => [u.otmetok_segodnya != null && { t: `${u.otmetok_segodnya} отметились`, tone: "ok" }, z.otchety && { t: `${z.otchety.count} на проверку`, tone: "warn" }, z.zametki && { t: `${z.zametki.count} заметок`, tone: "info" }],
      },
      {
        id: "tabel", emoji: "📋", title: "Табель", screen: "tabel", kto: ["les", "mas"],
        chto: "Кто где работал по дням. Отметки с телефона подставляются сами.",
        beret: "отметки, люди", kormit: "зарплата, карточка человека",
        cifry: (u) => [u.tabel_segodnya != null && u.lyudey != null && { t: `сегодня ${u.tabel_segodnya} из ${u.lyudey}`, tone: u.tabel_segodnya >= u.lyudey ? "ok" : "warn" }],
      },
      {
        id: "zhr", emoji: "📒", title: "Журнал работ", screen: "raboty", kto: ["les", "mas"],
        chto: "Всё сделанное одной лентой: смены, культуры, рубки ухода, табель. Фильтр кто / где / когда.",
        beret: "все журналы сразу", kormit: "—",
        cifry: () => [],
      },
      {
        id: "kart", emoji: "👤", title: "Карточка человека", screen: "sotrudniki", params: { tab: "kartochka" }, kto: ["les", "mas"],
        chto: "Где был, что делал, что «не сходится» между табелем и отчётами.",
        beret: "табель, отчёты, журналы", kormit: "—",
        cifry: () => [],
      },
    ],
  },
];

const SVYAZI = [
  ["🎫 Нет билета", "делянка остаётся черновиком: ни нарядов, ни ЕГАИС, ни сроков акта"],
  ["🏁 Дорублена или вывезена", "30 дней на акт освидетельствования, иначе он краснеет в «Ждёт меня»"],
  ["📱 Отчёт за смену", "одним нажатием попадает в табель-сверку, Расход, рубки ухода и карточку человека"],
  ["✂️ Проба рубок ухода", "сама закрывается, когда по отчётам пройдено ≥ 98% площади"],
  ["🌱 Культуры 1-го и 3-го года", "ждут инвентаризацию — без неё нельзя перевести в покрытые лесом"],
  ["📊 ЕГАИС не грузилась", "факт в Расходе устаревает, лучше проверить робота"],
];

const TONE = {
  ok: "bg-mint-soft text-green",
  info: "bg-mint-soft text-pine",
  warn: "bg-oak-soft text-oak",
  bad: "bg-error-soft text-error",
  muted: "bg-hover text-muted",
};

function Uzel({ u, cifry, rol, bok }) {
  const moy = !rol || u.kto.includes(rol);
  const spisok = (u.cifry ? u.cifry(cifry.u, cifry.z) : []).filter(Boolean);
  const gorit = spisok.some((c) => c.tone === "warn" || c.tone === "bad");
  return (
    <button
      type="button"
      onClick={() => openScreen(u.screen, u.params || {})}
      title="Открыть экран"
      className={[
        "group text-left rounded-xl border bg-surface p-3 flex flex-col gap-1.5 transition hover:border-pine hover:shadow-sm",
        bok ? "w-[230px]" : "w-[210px]",
        gorit ? "border-oak" : "border-border",
        moy ? "" : "opacity-30",
      ].join(" ")}
    >
      <div className="flex items-start gap-2">
        <span className="text-[20px] leading-none">{u.emoji}</span>
        <span className="font-extrabold text-pine text-[13.5px] leading-tight">{u.title}</span>
      </div>
      <p className="text-[12px] text-muted leading-snug">{u.chto}</p>
      {spisok.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {spisok.map((c, i) => (
            <span key={i} className={["px-1.5 py-0.5 rounded-md text-[11px] font-semibold", TONE[c.tone] || TONE.muted].join(" ")}>{c.t}</span>
          ))}
        </div>
      )}
      {(u.beret || u.kormit) && (
        <div className="text-[10.5px] text-muted-2 font-mono leading-snug mt-auto pt-1 border-t border-border border-dashed">
          {u.beret && <div>← {u.beret}</div>}
          {u.kormit && <div>→ {u.kormit}</div>}
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="flex gap-1">
          {u.kto.map((k) => <span key={k} className="text-[10px] font-mono uppercase tracking-wide text-muted-2">{KTO[k]}</span>)}
        </span>
        <span className="text-[11.5px] text-pine opacity-0 group-hover:opacity-100">открыть →</span>
      </div>
    </button>
  );
}

function Strelka() {
  return <span aria-hidden className="self-center text-pine/60 text-[20px] font-bold px-0.5">›</span>;
}

export default function Skhema() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [rol, setRol] = useState(() => { try { return localStorage.getItem("skhema_rol") || ""; } catch { return ""; } });

  useEffect(() => {
    api.get("/skhema").then(setD).catch((e) => setErr(e.message || "Не удалось загрузить цифры"));
  }, []);
  const vybratRol = (k) => { setRol(k); try { localStorage.setItem("skhema_rol", k); } catch { /* приватное окно */ } };

  const cifry = useMemo(() => ({ u: d?.uzly || {}, z: d?.zhdet || {} }), [d]);

  // «Сегодня надо»: «Ждёт меня» + то, что видно только на схеме.
  const nado = useMemo(() => {
    if (!d) return [];
    const u = d.uzly || {};
    const out = (d.zhdet_spisok || []).map((i) => ({ ...i, kto: ["les"] }));
    if (u.zadach_prosrocheno) out.push({ kod: "zad", count: u.zadach_prosrocheno, title: "Задачи с прошедшей датой", hint: "Закрыть или перенести", screen: "zadachi", params: {}, tone: "danger", kto: ["les", "mas"] });
    if (u.lk_inventarizaciya) out.push({ kod: "inv", count: u.lk_inventarizaciya, title: "Культуры ждут инвентаризацию 1-го/3-го года", hint: "Внести в журнал мероприятий", screen: "forestry", params: {}, tone: "warning", kto: ["les", "mas"] });
    const den = new Date().getDay();
    if (den !== 0 && den !== 6 && u.lyudey && n(u.tabel_segodnya) < u.lyudey) out.push({ kod: "tab", count: u.lyudey - n(u.tabel_segodnya), title: "Табель на сегодня заполнен не на всех", hint: "Отметить, кто где работал", screen: "tabel", params: {}, tone: "info", kto: ["les", "mas"] });
    if (u.egais_dney != null && u.egais_dney > 2) out.push({ kod: "eg", count: u.egais_dney, title: `ЕГАИС не обновлялась ${u.egais_dney} дн.`, hint: "Проверить робота выгрузки на ПК с ЕГАИС", screen: "raskhod", params: {}, tone: "warning", kto: ["les"] });
    if (rol === "rab") return [{ kod: "rab", count: 0, title: "Утром — «Я на работе» в телефоне, вечером — «Отчёт за смену»", hint: "Задачи на день — в разделе «Задачи» приложения", screen: "telefon", params: {}, tone: "info", kto: ["rab"] }];
    return out.filter((i) => !rol || i.kto.includes(rol));
  }, [d, rol]);

  return (
    <div className="p-5 flex flex-col gap-5 max-w-[1500px]">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[260px]">
          <p className="text-[13.5px] text-muted">Каждый шаг — откуда берёт данные (←), кого кормит (→) и что на нём висит прямо сейчас. Нажмите на шаг, чтобы открыть экран.</p>
        </div>
        <div className="flex flex-wrap gap-1 bg-hover rounded-xl p-1">
          {ROLI.map((r) => (
            <button key={r.k} type="button" onClick={() => vybratRol(r.k)}
              className={["px-3 h-8 rounded-lg text-[12.5px] font-semibold", rol === r.k ? "bg-surface text-pine shadow-sm" : "text-muted hover:text-pine"].join(" ")}>
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="flex items-baseline gap-2 mb-2">
          <h3 className="font-extrabold text-pine text-[15px]">✅ Сегодня надо</h3>
          <span className="font-mono text-[10.5px] text-muted-2">{d ? (nado.length ? `${nado.length} пунктов` : "") : "считаю…"}</span>
        </div>
        {err && <p className="text-error text-sm">{err}</p>}
        {d && !nado.length && <p className="text-[13px] text-green font-semibold">Всё разобрано. Можно в лес 🌲</p>}
        <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(280px,1fr))]">
          {nado.map((i) => (
            <button key={i.kod} type="button" onClick={() => openScreen(i.screen, i.params || {})}
              className="text-left flex items-start gap-2.5 rounded-lg border border-border px-3 py-2 hover:border-pine">
              {i.count > 0 && (
                <span className={["min-w-[28px] h-7 px-1.5 rounded-md grid place-items-center text-[13px] font-extrabold",
                  i.tone === "danger" ? TONE.bad : i.tone === "warning" ? TONE.warn : TONE.info].join(" ")}>{i.count}</span>
              )}
              <span className="min-w-0">
                <span className="block text-[13px] font-semibold text-ink leading-snug">{i.title}</span>
                {i.hint && <span className="block text-[11.5px] text-muted truncate">{i.hint}</span>}
              </span>
            </button>
          ))}
        </div>
      </div>

      {DOROZHKI.map((dor) => (
        <section key={dor.k} className="rounded-xl border border-border bg-[var(--color-bg,#f7f5f0)] p-4">
          <div className="flex items-baseline gap-2 mb-3">
            <h3 className="font-extrabold text-pine text-[16px]">{dor.title}</h3>
            <span className="font-mono text-[10.5px] text-muted-2">{dor.sub}</span>
          </div>
          <div className="flex flex-wrap items-stretch gap-y-3 gap-x-1">
            {dor.uzly.map((u, i) => (
              <React.Fragment key={u.id}>
                {i > 0 && <Strelka />}
                <Uzel u={u} cifry={cifry} rol={rol} />
              </React.Fragment>
            ))}
          </div>
          {dor.bok && (
            <div className="flex flex-wrap items-stretch gap-3 mt-3 pt-3 border-t border-dashed border-border">
              <span className="self-center font-mono text-[10.5px] text-muted-2 uppercase tracking-wider">сбоку:</span>
              {dor.bok.map((u) => <Uzel key={u.id} u={u} cifry={cifry} rol={rol} bok />)}
            </div>
          )}
        </section>
      ))}

      <div className="rounded-xl border border-border bg-surface p-4">
        <h3 className="font-extrabold text-pine text-[15px] mb-2">🔗 Что от чего зависит</h3>
        <ul className="grid gap-x-6 gap-y-1.5 grid-cols-[repeat(auto-fill,minmax(360px,1fr))] text-[13px]">
          {SVYAZI.map(([a, b]) => (
            <li key={a}><b className="text-ink">{a}</b> <span className="text-muted">→ {b}</span></li>
          ))}
        </ul>
        <p className="mt-3 text-[12px] text-muted-2">
          Найти что угодно — <b>Ctrl+K</b>: фамилия, делянка, «71/2», «проба 12». По любой фамилии и выделу на сайте можно кликнуть.
        </p>
      </div>
    </div>
  );
}
