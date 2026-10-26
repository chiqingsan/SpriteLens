/* 设置页分区导航：点击平滑定位，滚动时同步高亮。 */
(function () {
  "use strict";
  var page = document.getElementById("page-capture");
  if (!page) { return; }
  var nav = page.querySelector(".settings-nav");
  if (!nav) { return; }

  var links = Array.prototype.slice.call(nav.querySelectorAll("a[href^='#']"));
  var targets = links.map(function (link) {
    return document.getElementById(link.getAttribute("href").slice(1));
  });
  if (!links.length) { return; }

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var activeIndex = -1;
  var ticking = false;
  var clickLock = 0;

  function isVisible() {
    return page.clientHeight > 0 && page.offsetParent !== null;
  }

  function contentTop(target) {
    var pageRect = page.getBoundingClientRect();
    return target.getBoundingClientRect().top - pageRect.top + page.scrollTop;
  }

  function setActive(index) {
    if (index === activeIndex) { return; }
    activeIndex = index;
    links.forEach(function (link, i) {
      if (i === index) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  function sync() {
    ticking = false;
    if (!isVisible()) { return; }
    if (Date.now() < clickLock) { return; }
    var threshold = page.scrollTop + Math.min(page.clientHeight * 0.3, 200);
    var active = 0;
    for (var i = 0; i < targets.length; i += 1) {
      var target = targets[i];
      if (target && contentTop(target) <= threshold) { active = i; }
    }
    var atBottom = page.scrollTop + page.clientHeight >= page.scrollHeight - 2;
    setActive(atBottom ? targets.length - 1 : active);
  }

  function requestSync() {
    if (ticking) { return; }
    ticking = true;
    window.requestAnimationFrame(sync);
  }

  links.forEach(function (link, index) {
    link.addEventListener("click", function (event) {
      var target = targets[index];
      if (!target) { return; }
      event.preventDefault();
      page.scrollTo({
        top: Math.max(0, contentTop(target) - 16),
        behavior: reduced.matches ? "auto" : "smooth",
      });
      clickLock = Date.now() + 800;
      setActive(index);
    });
  });

  page.addEventListener("scroll", requestSync, { passive: true });
  window.addEventListener("resize", requestSync);

  /* 切到设置页时（display:none → 显示）补一次定位，避免隐藏时误判为“已到底”。 */
  if (window.MutationObserver) {
    new MutationObserver(function () {
      if (page.classList.contains("active")) { requestSync(); }
    }).observe(page, { attributes: true, attributeFilter: ["class"] });
  }
  sync();
})();
