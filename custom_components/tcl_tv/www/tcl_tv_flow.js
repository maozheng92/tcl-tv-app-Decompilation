/**
 * TCL TV options dialog: keep one-click menu rows, put Save at the bottom
 * right and Back at the bottom left.
 */
const DOMAIN = "tcl_tv";
const HIDDEN_MENU = {
  init: ["save"],
  sources: ["save", "sources_done"],
  source_seq_kind: ["source_seq_kind_back"],
};

function isZh(hass) {
  const lang = String(
    hass?.language || hass?.locale?.language || ""
  ).toLowerCase();
  return lang.startsWith("zh");
}

function labels(hass) {
  return isZh(hass)
    ? { save: "保存", back: "返回" }
    : { save: "Save", back: "Back" };
}

function deepQuery(root, selector) {
  const out = [];
  const visit = (node) => {
    if (!node) return;
    const start = node.shadowRoot || node;
    if (start.querySelectorAll) {
      try {
        start.querySelectorAll(selector).forEach((el) => out.push(el));
      } catch (_err) {
        /* ignore invalid selector on this node */
      }
      if (start.querySelectorAll) {
        start.querySelectorAll("*").forEach((el) => {
          if (el.shadowRoot) visit(el);
        });
      }
    }
  };
  visit(root);
  return out;
}

function menuItemId(el) {
  return el.step || el.value || el.getAttribute?.("value") || "";
}

function hideMenuItems(dialog, stepId) {
  const hidden = new Set(HIDDEN_MENU[stepId] || []);
  if (!hidden.size) return;
  const hideSave = hidden.has("save");
  const hideBack =
    hidden.has("sources_done") || hidden.has("source_seq_kind_back");
  for (const menu of deepQuery(dialog, "step-flow-menu")) {
    const items = deepQuery(
      menu,
      "ha-list-item-button, ha-md-list-item, mwc-list-item, ha-list-item"
    );
    for (const el of items) {
      const id = menuItemId(el);
      const text = (el.textContent || "").replace(/\s+/g, " ").trim();
      const byLabel =
        (hideSave && (text === "保存" || text === "Save")) ||
        (hideBack && (text === "返回" || text === "Back"));
      if (hidden.has(id) || byLabel) {
        el.style.display = "none";
        el.hidden = true;
      }
    }
  }
}

function continueFlow(dialog, data) {
  const step = dialog._step;
  const params = dialog._params;
  if (!step || !params?.flowConfig?.handleFlowStep) return;
  dialog.dispatchEvent(
    new CustomEvent("flow-update", {
      bubbles: true,
      composed: true,
      detail: {
        stepPromise: params.flowConfig.handleFlowStep(
          dialog.hass,
          step.flow_id,
          data
        ),
      },
    })
  );
}

function makeButton(text, { primary, onClick }) {
  const el = document.createElement("ha-button");
  el.slot = primary ? "primaryAction" : "secondaryAction";
  el.setAttribute("data-tcl-tv", primary ? "save" : "back");
  if (!primary) {
    el.setAttribute("appearance", "plain");
  }
  el.textContent = text;
  el.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    onClick();
  });
  return el;
}

function findFooter(dialog) {
  return (
    dialog.shadowRoot?.querySelector("ha-dialog-footer") ||
    deepQuery(dialog, "ha-dialog-footer")[0] ||
    null
  );
}

function findDialogShell(dialog) {
  return (
    dialog.shadowRoot?.querySelector("ha-dialog, ha-wa-dialog, ha-md-dialog") ||
    deepQuery(dialog, "ha-dialog, ha-wa-dialog, ha-md-dialog")[0] ||
    dialog.shadowRoot ||
    dialog
  );
}

function layoutFooter(footer, { back, save }) {
  const inner = footer.shadowRoot?.querySelector("footer") || footer;
  if (!inner?.style) return;
  if (back && save) inner.style.justifyContent = "space-between";
  else if (back && !save) inner.style.justifyContent = "flex-start";
  else inner.style.justifyContent = "flex-end";
  inner.style.width = "100%";
}

function clearInjected(dialog) {
  const root = dialog.shadowRoot || dialog;
  root.querySelectorAll?.("[data-tcl-tv-footer]").forEach((el) => el.remove());
  for (const footer of deepQuery(dialog, "ha-dialog-footer")) {
    footer.querySelectorAll("[data-tcl-tv]").forEach((el) => el.remove());
  }
}

function wantsSave(step) {
  return step.step_id === "init" || step.step_id === "sources";
}

function wantsBack(step) {
  return step.step_id !== "init";
}

function backPayload(step) {
  if (step.type === "menu") {
    if (step.step_id === "sources") return { next_step_id: "sources_done" };
    if (step.step_id === "source_seq_kind") {
      return { next_step_id: "source_seq_kind_back" };
    }
    return { next_step_id: "back" };
  }
  return { go_back: true };
}

function savePayload(step) {
  if (step.type === "menu") return { next_step_id: "save" };
  return {};
}

function injectFooter(dialog, step) {
  const text = labels(dialog.hass);
  const showSave = wantsSave(step);
  const showBack = wantsBack(step);
  if (!showSave && !showBack) return;

  let footer = findFooter(dialog);
  if (!footer && step.type === "menu") {
    footer = document.createElement("ha-dialog-footer");
    footer.setAttribute("slot", "footer");
    footer.setAttribute("data-tcl-tv-footer", "1");
    findDialogShell(dialog).appendChild(footer);
  }
  if (!footer) return;

  footer.querySelectorAll("[data-tcl-tv]").forEach((el) => el.remove());
  if (showBack) {
    footer.appendChild(
      makeButton(text.back, {
        primary: false,
        onClick: () => continueFlow(dialog, backPayload(step)),
      })
    );
  }
  if (showSave) {
    footer.appendChild(
      makeButton(text.save, {
        primary: true,
        onClick: () => continueFlow(dialog, savePayload(step)),
      })
    );
  }
  layoutFooter(footer, { back: showBack, save: showSave });
}

function enhance(dialog) {
  const params = dialog._params;
  const step = dialog._step;
  if (!params || params.domain !== DOMAIN) return;
  if (params.flowConfig?.flowType && params.flowConfig.flowType !== "options_flow") {
    return;
  }
  if (!step || dialog._loading) return;

  hideMenuItems(dialog, step.step_id);

  const key = `${step.flow_id}:${step.step_id}:${step.type}`;
  const marked = deepQuery(dialog, `[data-tcl-tv-key="${key}"]`)[0];
  const hasButtons = deepQuery(dialog, "[data-tcl-tv]").length > 0;
  if (dialog._tclTvUiKey === key && marked && hasButtons) return;

  if (dialog._tclTvUiKey !== key) {
    clearInjected(dialog);
  }
  dialog._tclTvUiKey = key;
  injectFooter(dialog, step);
  deepQuery(dialog, "[data-tcl-tv]").forEach((el) => {
    el.setAttribute("data-tcl-tv-key", key);
  });
  const footer = findFooter(dialog);
  if (footer) footer.setAttribute("data-tcl-tv-key", key);
}

function scan() {
  document.querySelectorAll("dialog-data-entry-flow").forEach(enhance);
}

setInterval(scan, 300);
const observer = new MutationObserver(scan);
observer.observe(document.body, { childList: true, subtree: true });
scan();
