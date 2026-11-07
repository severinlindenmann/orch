// Admin portal row "Icon and colour" (relay + publish). Shown inside the workspace editor.
// Editable while the workspace has not chosen its own look; afterwards read only (409 text from the contract).
"use strict";
(function () {
  const L = window.OrchLook;
  const LOCKED = "This workspace chooses its own icon.";
  function row(ws, patch) {
    const box = document.createElement("div");
    box.className = "look-row";
    box.setAttribute("data-look-row", "");
    const label = document.createElement("div");
    label.className = "look-label";
    label.textContent = "Icon and colour";
    const note = document.createElement("p");
    note.className = "look-note";
    note.setAttribute("role", "status");
    const body = document.createElement("div");
    box.append(label, body, note);
    function locked() {
      body.replaceChildren(L.badge(ws.name, ws.icon, ws.color, 40));
      body.setAttribute("aria-disabled", "true");
      note.textContent = LOCKED + " Chosen in the workspace's dashboard.";
    }
    if (ws.look_by === "workspace") {
      locked();
      return box;
    }
    const p = L.picker({
      name: ws.name, icon: ws.icon, color: ws.color,
      onChange: async (v) => {
        try {
          await patch({ icon: v.icon, color: v.color });
          ws.icon = v.icon; ws.color = v.color; ws.look_by = "admin";
          note.textContent = "Saved.";
        } catch (e) {
          if (e && e.status === 409) { ws.look_by = "workspace"; locked(); } else note.textContent = (e && e.message) || "Could not save.";
        }
      },
    });
    p.addEventListener("keydown", (ev) => { if (ev.key === "Enter") ev.preventDefault(); });
    body.appendChild(p);
    return box;
  }
  window.OrchLookAdmin = { row };
})();
