// Közös helper minden oldalhoz: nav aktív állapot + API + escape.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) { let d = {}; try { d = await r.json(); } catch (e) {} throw new Error((d.issues || []).join("; ") || d.error || ("HTTP " + r.status)); }
  return r.json().catch(() => ({}));
}
// Aktív menüpont jelölése az aktuális fájlnév alapján.
(function () {
  const page = location.pathname === "/" ? "/index.html" : location.pathname;
  const norm = page === "/" ? "/index.html" : page;
  document.querySelectorAll(".topbar nav a").forEach((a) => {
    const href = a.getAttribute("href");
    if (href === location.pathname || href === norm || (location.pathname === "/" && href === "/")) a.classList.add("active");
  });
})();
