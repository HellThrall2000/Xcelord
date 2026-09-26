// AG Grid wrapper. Theme params point at our CSS variables, so switching
// light/dark needs no grid re-render.

const numberFmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 });

function buildTheme() {
  const { themeQuartz } = window.agGrid;
  return themeQuartz.withParams({
    fontFamily: "inherit",
    fontSize: 13,
    headerFontSize: 12,
    headerFontWeight: 600,
    backgroundColor: "var(--surface)",
    foregroundColor: "var(--text)",
    headerBackgroundColor: "var(--surface-2)",
    headerTextColor: "var(--text-2)",
    borderColor: "var(--border)",
    rowBorder: { color: "var(--border)" },
    columnBorder: { color: "var(--border)" },
    oddRowBackgroundColor: "var(--row-alt)",
    rowHoverColor: "var(--row-hover)",
    selectedRowBackgroundColor: "var(--accent-soft)",
    accentColor: "var(--accent)",
    inputFocusBorder: { color: "var(--accent)" },
    rangeSelectionBorderColor: "var(--accent)",
    wrapperBorder: false,
    wrapperBorderRadius: 0,
    rowHeight: 32,
    headerHeight: 36,
    spacing: 6,
    cellHorizontalPadding: 10,
  });
}

export class SheetGrid {
  constructor(el, { onEdit } = {}) {
    this.el = el;
    this.onEdit = onEdit;
    this.mode = "live";
    this.highlight = new Set();
    this.addedCols = new Set();
    const agGrid = window.agGrid;
    if (agGrid.ModuleRegistry && agGrid.AllCommunityModule) {
      agGrid.ModuleRegistry.registerModules([agGrid.AllCommunityModule]);
    }
    this.api = agGrid.createGrid(el, {
      theme: buildTheme(),
      columnDefs: [],
      rowData: [],
      animateRows: false,
      suppressDragLeaveHidesColumns: true,
      stopEditingWhenCellsLoseFocus: true,
      enableCellTextSelection: true,
      getRowId: (p) => String(p.data.__i),
      defaultColDef: {
        resizable: true,
        sortable: false,
        filter: false,
        minWidth: 90,
        suppressHeaderMenuButton: true,
      },
      onCellValueChanged: (e) => this._changed(e),
      overlayNoRowsTemplate: '<span class="grid-empty">This sheet is empty</span>',
    });
  }

  show(sheet, { mode = "live", cells = [], addedColumns = [] } = {}) {
    this.mode = mode;
    this.sheet = sheet;
    this.highlight = new Set(cells.map(([r, c]) => `${r}:${c}`));
    this.addedCols = new Set(addedColumns);
    const editable = mode === "live";

    const cols = [{
      headerName: "",
      field: "__n",
      valueGetter: (p) => p.data.__i + 1,
      width: 58, minWidth: 48, maxWidth: 80,
      pinned: "left",
      editable: false,
      cellClass: "rownum",
      headerClass: "rownum-head",
      suppressMovable: true,
    }];
    sheet.columns.forEach((name, j) => {
      const type = sheet.types[j];
      const col = {
        headerName: name,
        headerTooltip: name,
        field: `c${j}`,
        editable,
        cellDataType: type === "number" ? "number" : type === "bool" ? "boolean" : "text",
        cellClassRules: { "cell-changed": (p) => this.highlight.has(`${p.data.__i}:${j}`) },
        headerClass: this.addedCols.has(name) ? "col-added" : undefined,
        cellClass: type === "number" ? "num" : type === "date" ? "date" : undefined,
      };
      if (type === "number") col.valueFormatter = (p) => (p.value == null || p.value === "" ? "" : numberFmt.format(p.value));
      col.initialWidth = Math.min(280, Math.max(110, name.length * 9 + 40));
      cols.push(col);
    });

    const rows = sheet.rows.map((r, i) => {
      const o = { __i: i };
      for (let j = 0; j < r.length; j++) o[`c${j}`] = r[j];
      return o;
    });
    this.api.setGridOption("columnDefs", cols);
    this.api.setGridOption("rowData", rows);
    if (cells.length) {
      const [r] = cells[0];
      this.api.ensureIndexVisible(r, "middle");
    }
  }

  _changed(e) {
    if (this.mode !== "live" || !this.onEdit || this._reverting) return;
    const col = Number(e.colDef.field.slice(1));
    this.onEdit(e.data.__i, col, e.newValue, () => {
      this._reverting = true;
      e.node.setDataValue(e.colDef.field, e.oldValue);
      this._reverting = false;
    });
  }

  clear() {
    this.api.setGridOption("columnDefs", []);
    this.api.setGridOption("rowData", []);
  }
}
