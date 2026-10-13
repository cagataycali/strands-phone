/* Copy pills, the content fade on instant navigation, and the "On this page" bar. Vanilla, ~40 lines. */
(() => {
  function wire(root) {
    root.querySelectorAll(".sr-copy[data-clipboard-text]").forEach((b) => {
      if (b.__wired) return; b.__wired = true;
      b.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(b.dataset.clipboardText); } catch { /* no clipboard */ }
        b.classList.add("is-copied"); const t = b.textContent; b.textContent = "copied";
        setTimeout(() => { b.classList.remove("is-copied"); b.textContent = t; }, 1200);
      });
    });
    const inner = root.querySelector(".md-content__inner");
    if (inner) { inner.classList.remove("sr-enter"); void inner.offsetWidth; inner.classList.add("sr-enter"); }
  }
  function toc() {
    const nav = document.querySelector(".md-nav--secondary"); if (!nav) return;
    const a = nav.querySelector(".md-nav__link--active"); if (!a) return;
    const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
    nav.style.setProperty("--sr-toc-y", `${r.top - n.top}px`); nav.style.setProperty("--sr-toc-h", `${r.height}px`);
  }
  const boot = () => { wire(document); toc(); };
  if (window.document$) window.document$.subscribe(boot); else document.addEventListener("DOMContentLoaded", boot);
  document.addEventListener("scroll", () => requestAnimationFrame(toc), { passive: true });
})();
