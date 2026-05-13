import { el } from "../core/dom.js";

export function renderTable({ columns, rows, emptyText = "暂无数据", className = "", wrapClassName = "" }) {
  const table = el("table", { class: ["data-table", className].filter(Boolean).join(" ") });
  const colgroup = el(
    "colgroup",
    {},
    columns.map((column) => el("col", column.width ? { style: `width: ${column.width}` } : {})),
  );
  const thead = el("thead", {}, [
    el(
      "tr",
      {},
      columns.map((column) => {
        const header = column.renderHeader ? column.renderHeader(column) : column.title;
        return el("th", { class: column.className ?? "" }, [header instanceof Node ? header : String(header)]);
      }),
    ),
  ]);
  const tbody = el(
    "tbody",
    {},
    rows.length
      ? rows.map((row, index) =>
          el(
            "tr",
            {},
            columns.map((column) => {
              const value = column.render ? column.render(row, index) : row[column.key] ?? "";
              const title = column.titleValue ? column.titleValue(row, index) : null;
              return el(
                "td",
                { class: column.className ?? "", title },
                [value instanceof Node ? value : String(value)],
              );
            }),
          ),
        )
      : [
          el("tr", { class: "empty-row" }, [
            el("td", { class: "empty", colspan: columns.length, text: emptyText }),
          ]),
        ],
  );
  table.append(colgroup, thead, tbody);
  return el("div", { class: ["data-table-wrap", wrapClassName].filter(Boolean).join(" ") }, [table]);
}
