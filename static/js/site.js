(() => {
  "use strict";

  const $ = (selector, root = document) =>
    root.querySelector(selector);

  const $$ = (selector, root = document) =>
    Array.from(root.querySelectorAll(selector));

  /* ==========================================
     MOBILE NAVIGATION
     ========================================== */

  const navToggle = $("#nav-toggle");
  const nav = $("#primary-navigation");

  function closeNavigation() {
    if (!navToggle || !nav) return;

    navToggle.setAttribute("aria-expanded", "false");
    navToggle.setAttribute("aria-label", "Open menu");
    nav.classList.remove("is-open");
    document.body.classList.remove("nav-open");
  }

  function openNavigation() {
    if (!navToggle || !nav) return;

    navToggle.setAttribute("aria-expanded", "true");
    navToggle.setAttribute("aria-label", "Close menu");
    nav.classList.add("is-open");
    document.body.classList.add("nav-open");
  }

  if (navToggle && nav) {
    navToggle.addEventListener("click", () => {
      const isOpen =
        navToggle.getAttribute("aria-expanded") === "true";

      if (isOpen) {
        closeNavigation();
      } else {
        openNavigation();
      }
    });

    $$(".site-nav-link", nav).forEach((link) => {
      link.addEventListener("click", () => {
        closeNavigation();
      });
    });

    /* Close menu when clicking outside it */
    document.addEventListener("click", (event) => {
      if (
        !nav.contains(event.target) &&
        !navToggle.contains(event.target)
      ) {
        closeNavigation();
      }
    });

    /* Close menu with Escape */
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeNavigation();

        if (document.activeElement === navToggle) {
          navToggle.blur();
        }
      }
    });

    /* Restore desktop state when resizing */
    window.addEventListener("resize", () => {
      if (window.innerWidth > 780) {
        closeNavigation();
      }
    });
  }

  /* ==========================================
     HOMEPAGE SEARCH
     ========================================== */

  const searchInput = $("#post-search");
  const clearButton = $("#post-search-clear");
  const cards = $$(".home-post-card");
  const filters = $$(".category-filter");
  const resultCount = $("#filter-result-count");
  const noResults = $("#no-results");

  let activeCategory = "all";

  const normalize = (value) =>
    (value || "")
      .toString()
      .trim()
      .toLowerCase();

  function applyFilters() {
    if (!cards.length) return;

    const query = normalize(
      searchInput ? searchInput.value : ""
    );

    let visible = 0;

    cards.forEach((card) => {
      const haystack = [
        card.dataset.searchTitle,
        card.dataset.searchDescription,
        card.dataset.searchCategory,
        card.dataset.searchTags,
      ].join(" ");

      const category = normalize(
        card.dataset.searchCategory
      );

      const categoryOK =
        activeCategory === "all" ||
        category.includes(activeCategory);

      const queryOK =
        !query || normalize(haystack).includes(query);

      const show = categoryOK && queryOK;

      card.hidden = !show;

      if (show) {
        visible++;
      }
    });

    if (resultCount) {
      resultCount.textContent =
        `${visible} article${visible === 1 ? "" : "s"}`;
    }

    if (noResults) {
      noResults.hidden = visible !== 0;
    }

    if (clearButton) {
      clearButton.hidden = !query;
    }
  }

  filters.forEach((button) => {
    button.addEventListener("click", () => {
      activeCategory = normalize(
        button.dataset.category
      );

      filters.forEach((item) => {
        const selected = item === button;

        item.classList.toggle("is-active", selected);
        item.setAttribute(
          "aria-pressed",
          String(selected)
        );
      });

      applyFilters();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", applyFilters);

    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        searchInput.value = "";
        applyFilters();
        searchInput.blur();
      }
    });
  }

  if (clearButton && searchInput) {
    clearButton.addEventListener("click", () => {
      searchInput.value = "";
      applyFilters();
      searchInput.focus();
    });
  }

  /* ==========================================
     READING PROGRESS
     ========================================== */

  const progress = $("#reading-progress");

  function updateProgress() {
    if (!progress) return;

    const scrollTop =
      window.scrollY ||
      document.documentElement.scrollTop ||
      0;

    const documentHeight =
      document.documentElement.scrollHeight;

    const viewportHeight = window.innerHeight;
    const maxScroll = documentHeight - viewportHeight;

    const percentage =
      maxScroll > 0
        ? Math.min(
            100,
            Math.max(0, (scrollTop / maxScroll) * 100)
          )
        : 0;

    progress.style.width = `${percentage}%`;
  }

  /* ==========================================
     BACK TO TOP
     ========================================== */

  const backToTop = $("#back-to-top");

  function updateTopButton() {
    if (!backToTop) return;

    const scrollTop =
      window.scrollY ||
      document.documentElement.scrollTop ||
      0;

    backToTop.hidden = scrollTop < 500;
  }

  if (backToTop) {
    backToTop.addEventListener("click", () => {
      window.scrollTo({
        top: 0,
        behavior: "smooth",
      });
    });
  }

  /* ==========================================
     SCROLL HANDLER
     ========================================== */

  let ticking = false;

  function handleScroll() {
    if (ticking) return;

    window.requestAnimationFrame(() => {
      updateProgress();
      updateTopButton();
      ticking = false;
    });

    ticking = true;
  }

  window.addEventListener("scroll", handleScroll, {
    passive: true,
  });

  /* ==========================================
     MOBILE LINK BEHAVIOR
     ========================================== */

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");

    if (!link) return;

    const href = link.getAttribute("href");

    if (!href) return;

    /* Ignore anchors and external links */
    if (
      href.startsWith("#") ||
      /^(https?:|mailto:|tel:)/i.test(href)
    ) {
      return;
    }

    /* Only relevant on mobile */
    if (window.innerWidth > 780 || !nav) {
      return;
    }

    closeNavigation();
  });

  /* ==========================================
     INITIAL STATE
     ========================================== */

  applyFilters();
  updateProgress();
  updateTopButton();
})();
