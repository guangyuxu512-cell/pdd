import { el } from "../core/dom.js";

export function renderThumbButton(url, { title = "查看主图", alt = "主图", onOpen } = {}) {
  if (!url) return "";
  return el("button", { class: "product-thumb-button", title, onclick: () => onOpen?.(url) }, [
    el("img", { class: "product-thumb", src: url, alt, loading: "lazy" }),
    el("span", { class: "product-thumb-eye" }),
  ]);
}

export function renderImagePreview({ url, title = "主图预览", alt = "主图预览", onClose }) {
  return el("div", { class: url ? "modal-mask open" : "modal-mask", onclick: onClose }, [
    el("div", { class: "image-preview-modal", onclick: (event) => event.stopPropagation() }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: title }),
        el("button", { class: "ghost", onclick: onClose }, ["关闭"]),
      ]),
      el("div", { class: "image-preview-body" }, [
        url ? el("img", { class: "image-preview", src: url, alt }) : "",
      ]),
    ]),
  ]);
}
