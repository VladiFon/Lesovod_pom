/**
 * Чистая печать любого куска сайта (разбор 09.11.2026, шаг 2).
 *
 * Раньше печать была только у «Лесной правды»; Ctrl+P печатал всё окно
 * вместе с меню, вкладками и обрезанной прокруткой. Здесь кусок экрана
 * копируется в невидимый iframe со стилями сайта и печатается отдельно:
 * без меню, кнопок и прокрутки, на белом листе, с заголовком и датой.
 *
 * Что не печатать — пометить классом no-print или атрибутом data-no-print.
 * Поля ввода печатаются своим значением (как текст), а не рамкой.
 */
function poleKakTekst(src, dst) {
  const a = src.querySelectorAll("input, select, textarea");
  const b = dst.querySelectorAll("input, select, textarea");
  a.forEach((el, i) => {
    const d = b[i];
    if (!d) return;
    if (el.type === "checkbox" || el.type === "radio") {
      d.replaceWith(document.createTextNode(el.checked ? "☑ " : "☐ "));
      return;
    }
    const v = el.tagName === "SELECT" ? el.options[el.selectedIndex]?.text ?? "" : el.value;
    const s = document.createElement("span");
    s.textContent = v;
    d.replaceWith(s);
  });
}

export function napechatat(el, { title = "", landscape = false } = {}) {
  if (!el) return;
  const kopiya = el.cloneNode(true);
  poleKakTekst(el, kopiya);
  kopiya.querySelectorAll(".no-print, [data-no-print]").forEach((x) => x.remove());

  const stili = [...document.querySelectorAll('link[rel="stylesheet"], style')]
    .map((s) => s.outerHTML)
    .join("\n");
  const d = new Date();
  const kogda = `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
  const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  const fr = document.createElement("iframe");
  fr.setAttribute("aria-hidden", "true");
  fr.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
  document.body.appendChild(fr);
  const doc = fr.contentDocument;
  doc.open();
  doc.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${esc(title)}</title>${stili}
<style>
  @page { size: A4 ${landscape ? "landscape" : "portrait"}; margin: 10mm; }
  html, body { background: #fff !important; height: auto !important; overflow: visible !important; }
  body { padding: 0; margin: 0; font-size: 12px; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .pechat-shapka { display: flex; justify-content: space-between; align-items: baseline; border-bottom: 1.5px solid #1a4331; padding-bottom: 4px; margin-bottom: 10px; font-family: Manrope, sans-serif; }
  .pechat-shapka b { font-size: 16px; color: #1a4331; }
  .pechat-shapka span { font-size: 10px; color: #555; }
  .pechat-telo, .pechat-telo * { overflow: visible !important; max-height: none !important; }
  .pechat-telo [class*="shadow"] { box-shadow: none !important; }
  .pechat-telo button { cursor: default; }
  .pechat-telo .sticky { position: static !important; }
  .pechat-telo table { width: 100% !important; min-width: 0 !important; font-size: 10.5px; }
  .pechat-telo th, .pechat-telo td { min-width: 0 !important; }
  .pechat-telo .overflow-x-auto { overflow: visible !important; }
  tr, .break-inside-avoid { break-inside: avoid; }
  thead { display: table-header-group; }
</style></head><body>
<div class="pechat-shapka"><b>${esc(title)}</b><span>Лесовод · напечатано ${kogda}</span></div>
<div class="pechat-telo"></div></body></html>`);
  doc.close();
  doc.querySelector(".pechat-telo").appendChild(doc.importNode(kopiya, true));

  const go = () => {
    try {
      fr.contentWindow.focus();
      fr.contentWindow.print();
    } finally {
      setTimeout(() => fr.remove(), 1500);
    }
  };
  // стили-ссылки и шрифты должны успеть загрузиться
  setTimeout(go, 350);
}
