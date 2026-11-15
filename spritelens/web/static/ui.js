/* 原生壳的键盘与筛选面板交互；详情抽屉/焦点陷阱已由 Vue 页面（PetDetailPanel）自有实现。 */
(function () {
  "use strict";

  document.addEventListener("keydown", function (event) {
    if (event.target.closest("[data-vue-page]")) { return; }
    var item = event.target.closest("[role='button'][tabindex='0']");
    if (item && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault(); item.click();
    }
  });

  document.getElementById("btn-pet-filters").addEventListener("click", function () {
    var expanded = this.getAttribute("aria-expanded") !== "true";
    this.setAttribute("aria-expanded", String(expanded));
    document.getElementById("pet-filters").classList.toggle("filters-open", expanded);
  });
  document.getElementById("btn-close-pet-filters").addEventListener("click", function () {
    var button = document.getElementById("btn-pet-filters");
    button.click();
    button.focus({ preventScroll: false });
  });
})();
