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
  const formatter = () => new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency.value === "other" ? "USD" : currency.value,
    maximumFractionDigits: 2
  });
  const number = (value) => {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  };
  const percent = (value) => Math.min(100, number(value));
  const money = (value) => {
    try { return formatter().format(value); }
    catch (_) { return value.toFixed(2) + " " + currency.value; }
  };
  function createRow(name = "", qty = 1, price = 0) {
    const row = document.createElement("tr");
    row.className = "planner-item-row";
    row.innerHTML = `<td><input class="planner-name" aria-label="Item name" placeholder="Item name"></td>
      <td><input class="planner-qty" aria-label="Quantity" type="number" min="0" step="any"></td>
      <td><input class="planner-price" aria-label="Unit price" type="number" min="0" step="any"></td>
      <td class="planner-line-total">—</td><td><button type="button" class="planner-remove" aria-label="Remove item">×</button></td>`;
    $(".planner-name", row).value = name;
    $(".planner-qty", row).value = qty;
    $(".planner-price", row).value = price;
    return row;
  }
  function updateArea() {
    const length = number(lengthInput.value), width = number(widthInput.value), unit = unitInput.value;
    const area = length * width;
    if (!(length > 0 && width > 0)) {
      $("#planner-area").textContent = "Enter length and width to calculate the floor area.";
      return;
    }
    const sq = unit === "ft" ? "sq ft" : "m²";
    const alternate = unit === "ft" ? area * 0.09290304 : area / 0.09290304;
    const alternateUnit = unit === "ft" ? "m²" : "sq ft";
    $("#planner-area").textContent = `Floor area: ${area.toLocaleString(undefined, {maximumFractionDigits: 2})} ${sq} (about ${alternate.toLocaleString(undefined, {maximumFractionDigits: 2})} ${alternateUnit}).`;
  }
  function calculate() {
    let subtotal = 0;
    itemsBody.querySelectorAll(".planner-item-row").forEach((row) => {
      const line = number($(".planner-qty", row).value) * number($(".planner-price", row).value);
      subtotal += line;
      $(".planner-line-total", row).textContent = money(line);
      $(".planner-remove", row).setAttribute("aria-label", "Remove " + ($(".planner-name", row).value.trim() || "item"));
    });
    const tax = subtotal * percent(taxInput.value) / 100;
    const contingency = (subtotal + tax) * percent(contingencyInput.value) / 100;
    $("#planner-subtotal").textContent = money(subtotal);
    $("#planner-tax-total").textContent = money(tax);
    $("#planner-contingency-total").textContent = money(contingency);
    $("#planner-grand-total").textContent = money(subtotal + tax + contingency);
    updateArea();
  }
  itemsBody.addEventListener("input", calculate);
  itemsBody.addEventListener("click", (event) => {
    const remove = event.target.closest(".planner-remove");
    if (!remove) return;
    const rows = itemsBody.querySelectorAll(".planner-item-row");
    if (rows.length <= 1) {
      const row = rows[0];
      $(".planner-name", row).value = "";
      $(".planner-qty", row).value = 1;
      $(".planner-price", row).value = 0;
    } else remove.closest("tr").remove();
    calculate();
  });
  $("#planner-add").addEventListener("click", () => {
    itemsBody.appendChild(createRow("", 1, 0));
    $(".planner-name", itemsBody.lastElementChild).focus();
    calculate();
  });
  [currency, taxInput, contingencyInput, lengthInput, widthInput, unitInput].forEach((input) => {
    input.addEventListener("input", calculate);
    input.addEventListener("change", calculate);
  });
  $("#planner-print").addEventListener("click", () => window.print());
  $("#planner-reset").addEventListener("click", () => {
    itemsBody.innerHTML = "";
    itemsBody.append(createRow("Storage unit", 1, 0), createRow("Furniture", 1, 0));
    currency.value = "USD"; lengthInput.value = ""; widthInput.value = ""; unitInput.value = "ft";
    taxInput.value = 0; contingencyInput.value = 10; calculate();
  });
  calculate();
})();
