/* Theme (Light / Dark / System) and the avatar menu.
   Loaded synchronously in <head> so the theme is applied before first paint (no flash).
   "System" removes data-theme so the prefers-color-scheme tokens in tokens.css apply.
   ?theme=dark|light|system overrides and is remembered. Storage is optional: every access is
   wrapped so the page renders correctly when localStorage is unavailable. */

(function () {
  // UI label for the financial space (data model: Workspace). Owner still confirming the term.
  var PROFILE_LABEL = "Switch profile";
  var KEY = "foresight-theme";
  var CHOICES = ["light", "dark", "system"];

  function read() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function write(v) {
    try { localStorage.setItem(KEY, v); } catch (e) { /* storage unavailable */ }
  }
  function apply(choice) {
    var root = document.documentElement;
    if (choice === "light" || choice === "dark") root.setAttribute("data-theme", choice);
    else root.removeAttribute("data-theme");
    root.dataset.themeChoice = choice;
  }

  var fromUrl = null;
  try { fromUrl = new URLSearchParams(location.search).get("theme"); } catch (e) { /* no-op */ }
  var choice = CHOICES.indexOf(fromUrl) >= 0 ? fromUrl : read();
  if (CHOICES.indexOf(choice) < 0) choice = "system";
  if (fromUrl && CHOICES.indexOf(fromUrl) >= 0) write(fromUrl);
  apply(choice);

  function setChoice(next) {
    choice = next;
    write(next);
    apply(next);
    syncRadios();
    window.dispatchEvent(new CustomEvent("fs:themechange", { detail: next }));
  }

  // System preference changes repaint charts too.
  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      if (choice === "system") window.dispatchEvent(new CustomEvent("fs:themechange", { detail: "system" }));
    });
  } catch (e) { /* older browsers */ }

  function themeGroup(idPrefix) {
    var labels = { light: "Light", dark: "Dark", system: "System" };
    return '<div class="theme-group" role="radiogroup" aria-label="Theme">' +
      CHOICES.map(function (c) {
        return '<button type="button" role="radio" class="theme-opt" data-theme-choice="' + c +
          '" id="' + idPrefix + "-" + c + '">' + labels[c] + "</button>";
      }).join("") + "</div>";
  }

  function syncRadios() {
    document.querySelectorAll(".theme-opt").forEach(function (b) {
      var on = b.dataset.themeChoice === choice;
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    });
  }

  function wireRadios(root) {
    root.querySelectorAll(".theme-group").forEach(function (group) {
      group.addEventListener("click", function (e) {
        var b = e.target.closest(".theme-opt");
        if (b) setChoice(b.dataset.themeChoice);
      });
      group.addEventListener("keydown", function (e) {
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].indexOf(e.key) < 0) return;
        e.preventDefault();
        var step = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1;
        var next = CHOICES[(CHOICES.indexOf(choice) + step + CHOICES.length) % CHOICES.length];
        setChoice(next);
        var btn = group.querySelector('[data-theme-choice="' + next + '"]');
        if (btn) btn.focus();
      });
    });
  }

  function buildMenus() {
    // Avatar menu on signed-in pages.
    document.querySelectorAll(".topbar .user").forEach(function (user, i) {
      var id = "user-menu-" + i;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "user";
      btn.setAttribute("aria-haspopup", "true");
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-controls", id);
      btn.innerHTML = user.innerHTML;
      var wrap = document.createElement("div");
      wrap.className = "user-wrap";
      var menu = document.createElement("div");
      menu.className = "user-menu";
      menu.id = id;
      menu.hidden = true;
      menu.innerHTML =
        '<p class="um-head"><strong>Amara Nwosu</strong><span>Demo profile · fictional data</span></p>' +
        '<a class="um-item" href="#">' + PROFILE_LABEL + "</a>" +
        '<a class="um-item" href="#">Settings</a>' +
        '<a class="um-item" href="#">Quality checks</a>' +
        '<div class="um-sep" role="separator"></div>' +
        '<p class="um-label" id="' + id + '-theme">Theme</p>' + themeGroup(id);
      user.replaceWith(wrap);
      wrap.appendChild(btn);
      wrap.appendChild(menu);
      function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        var open = menu.hidden;
        menu.hidden = !open;
        btn.setAttribute("aria-expanded", open ? "true" : "false");
        if (open) { var cur = menu.querySelector('[aria-checked="true"]'); if (cur) cur.focus(); }
      });
      document.addEventListener("click", function (e) { if (!wrap.contains(e.target)) close(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && !menu.hidden) { close(); btn.focus(); }
      });
    });
    // Footer control on public pages.
    document.querySelectorAll("[data-theme-footer]").forEach(function (host, i) {
      host.innerHTML = '<span class="um-label">Theme</span>' + themeGroup("theme-footer-" + i);
    });
    wireRadios(document);
    syncRadios();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", buildMenus);
  else buildMenus();
  window.FS_THEME = { set: setChoice, get: function () { return choice; } };
})();
