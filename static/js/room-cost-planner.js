(() => {
  "use strict";
  const root = document.querySelector(".room-cost-planner");
  if (!root) return;
  const $ = (selector, scope = root) => scope.querySelector(selector);
  const itemsBody = $("#planner-items");
  const currency = $("#planner-currency");
  const lengthInput = $("#planner-length");
  const widthInput = $("#planner-width");
  const unitInput = $("#planner-unit");
  const taxInput = $("#planner-tax");
  const contingencyInput = $("#planner-contingency");
  const status = $("#planner-status");
  const warningBox = $("#planner-warning");
  const LIMITS = { qty: 1e6, price: 1e9, dim: 1e5, pct: 100 };
  let warnings = new Set();
  let announceEnabled = false;
  let statusTimer = null;
  const digits = () => (currency.value === "TND" ? 3 : 2);
  const roundTo = (value, d) => {
    const factor = 10 ** d;
    return Math.round((value + Number.EPSILON) * factor) / factor;
  };
  const read = (value, max, label) => {
    const raw = String(value == null ? "" : value).trim();
    if (raw === "") return 0;
    const parsed = Number.parseFloat(raw);
    if (!Number.isFinite(parsed)) { warnings.add(label + " must be a number; counted as 0."); return 0; }
    if (parsed < 0) { warnings.add(label + " cannot be negative; counted as 0."); return 0; }
    if (parsed > max) { warnings.add(label + " is limited to " + max.toLocaleString() + "; larger values are capped."); return max; }
    return parsed;
  };
  const money = (value) => {
    const code = currency.value;
    const d = digits();
    if (code === "other") {
      return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " (your currency)";
    }
    return new Intl.NumberFormat(undefined, { style: "currency", currency: code, minimumFractionDigits: d, maximumFractionDigits: d }).format(value);
  };
  function announceTotal(total) {
    if (!status || !announceEnabled) return;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => { status.textContent = "Estimated total: " + money(total); }, 900);
  }
  function createRow(name = "", qty = 1, price = 0) {
    const row = document.createElement("tr");
    row.className = "planner-item-row";
    row.innerHTML = `<td data-label="Item / work"><input class="planner-name" aria-label="Item name" placeholder="Item name"><span class="planner-name-print" aria-hidden="true"></span></td>
      <td data-label="Qty"><input class="planner-qty" aria-label="Quantity" type="number" min="0" max="1000000" step="any"></td>
      <td data-label="Unit price"><input class="planner-price" aria-label="Unit price" type="number" min="0" max="1000000000" step="any"></td>
      <td class="planner-line-total" data-label="Line total">—</td><td><button type="button" class="planner-remove" aria-label="Remove item">×</button></td>`;
    $(".planner-name", row).value = name;
    $(".planner-qty", row).value = qty;
    $(".planner-price", row).value = price;
    return row;
  }
  function updateArea() {
    const length = read(lengthInput.value, LIMITS.dim, "Length");
    const width = read(widthInput.value, LIMITS.dim, "Width");
    const unit = unitInput.value;
    const target = $("#planner-area");
    if (!(length > 0 && width > 0)) {
      target.textContent = "Enter length and width to calculate the floor area.";
      return;
    }
    const area = length * width;
    const sq = unit === "ft" ? "sq ft" : "m²";
    const alternate = unit === "ft" ? area * 0.09290304 : area / 0.09290304;
    const alternateUnit = unit === "ft" ? "m²" : "sq ft";
    const fmt = (n) => n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    target.textContent = `Floor area: ${fmt(area)} ${sq} (about ${fmt(alternate)} ${alternateUnit}).`;
  }
  function calculate() {
    warnings = new Set();
    const d = digits();
    let subtotal = 0;
    Array.from(itemsBody.querySelectorAll(".planner-item-row")).forEach((row, i) => {
      const n = i + 1;
      const qty = read($(".planner-qty", row).value, LIMITS.qty, "Quantity");
      const price = read($(".planner-price", row).value, LIMITS.price, "Unit price");
      const line = roundTo(qty * price, d);
      subtotal += line;
      const name = $(".planner-name", row).value.trim();
      $(".planner-line-total", row).textContent = money(line);
      $(".planner-name-print", row).textContent = name;
      $(".planner-name", row).setAttribute("aria-label", "Item " + n + " name");
      $(".planner-qty", row).setAttribute("aria-label", "Item " + n + " quantity");
      $(".planner-price", row).setAttribute("aria-label", "Item " + n + " unit price");
      $(".planner-remove", row).setAttribute("aria-label", "Remove " + (name || "item " + n));
    });
    subtotal = roundTo(subtotal, d);
    const taxRate = read(taxInput.value, LIMITS.pct, "Tax");
    const contingencyRate = read(contingencyInput.value, LIMITS.pct, "Contingency");
    const tax = roundTo(subtotal * taxRate / 100, d);
    const contingency = roundTo((subtotal + tax) * contingencyRate / 100, d);
    const total = roundTo(subtotal + tax + contingency, d);
    $("#planner-subtotal").textContent = money(subtotal);
    $("#planner-tax-total").textContent = money(tax);
    $("#planner-contingency-total").textContent = money(contingency);
    $("#planner-grand-total").textContent = money(total);
    announceTotal(total);
    updateArea();
    if (warningBox) {
      warningBox.textContent = Array.from(warnings).join(" ");
      warningBox.hidden = warnings.size === 0;
    }
  }
  itemsBody.addEventListener("input", () => { announceEnabled = true; calculate(); });
  itemsBody.addEventListener("click", (event) => {
    const remove = event.target.closest(".planner-remove");
    if (!remove) return;
    announceEnabled = true;
    const rows = Array.from(itemsBody.querySelectorAll(".planner-item-row"));
    const current = remove.closest("tr");
    const index = rows.indexOf(current);
    if (rows.length <= 1) {
      $(".planner-name", current).value = "";
      $(".planner-qty", current).value = 1;
      $(".planner-price", current).value = 0;
    } else {
      current.remove();
    }
    calculate();
    const left = Array.from(itemsBody.querySelectorAll(".planner-item-row"));
    const target = left[Math.min(Math.max(index, 0), left.length - 1)];
    if (target) $(".planner-name", target).focus();
  });
  $("#planner-add").addEventListener("click", () => {
    announceEnabled = true;
    itemsBody.appendChild(createRow("", 1, 0));
    calculate();
    $(".planner-name", itemsBody.lastElementChild).focus();
  });
  [currency, taxInput, contingencyInput, lengthInput, widthInput, unitInput].forEach((input) => {
    const handler = () => { announceEnabled = true; calculate(); };
    input.addEventListener("input", handler);
    input.addEventListener("change", handler);
  });
  $("#planner-print").addEventListener("click", () => window.print());
  $("#planner-reset").addEventListener("click", () => {
    announceEnabled = true;
    itemsBody.innerHTML = "";
    itemsBody.append(createRow("Storage unit", 1, 0), createRow("Furniture", 1, 0));
    currency.value = "USD"; lengthInput.value = ""; widthInput.value = ""; unitInput.value = "ft";
    taxInput.value = 0; contingencyInput.value = 10; calculate();
  });
  calculate();
})();
