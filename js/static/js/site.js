(function () {
  "use strict";

  // ============================================
  // Reading Progress Bar
  // ============================================

  var progressBar = document.getElementById(
    "reading-progress"
  );

  var article = document.querySelector(
    ".post-content"
  );

  function updateProgress() {

    if (!progressBar) {
      return;
    }

    if (!article) {
      progressBar.style.width = "0%";
      return;
    }

    var rect = article.getBoundingClientRect();
    var articleTop = rect.top + window.scrollY;
    var articleHeight = rect.height;

    var scrollTop = window.scrollY;
    var windowHeight = window.innerHeight;

    var scrolled = scrollTop - articleTop;
    var total = articleHeight - windowHeight;

    if (total <= 0) {
      progressBar.style.width = "100%";
      return;
    }

    var percent = (scrolled / total) * 100;

    if (percent < 0) {
      percent = 0;
    }

    if (percent > 100) {
      percent = 100;
    }

    progressBar.style.width = percent + "%";

  }

  if (progressBar) {

    window.addEventListener(
      "scroll",
      updateProgress,
      { passive: true }
    );

    window.addEventListener(
      "resize",
      updateProgress
    );

    updateProgress();

  }


  // ============================================
  // Back to Top Button
  // ============================================

  var backToTop = document.getElementById(
    "back-to-top"
  );

  function updateBackToTop() {

    if (!backToTop) {
      return;
    }

    if (window.scrollY > 600) {
      backToTop.hidden = false;
    } else {
      backToTop.hidden = true;
    }

  }

  if (backToTop) {

    backToTop.addEventListener(
      "click",
      function () {
        window.scrollTo({
          top: 0,
          behavior: "smooth"
        });
      }
    );

    window.addEventListener(
      "scroll",
      updateBackToTop,
      { passive: true }
    );

    updateBackToTop();

  }

})();
