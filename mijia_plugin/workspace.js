export function mount({ document, window, read, write, action, signal, isCurrent, createIcon, onError, enhanceSelect, refreshSelect, closeSelects }) {
  const node = (tag, cls = "", text = "") => {
    const el = document.createElement(tag); el.className = cls; el.textContent = text; return el;
  };
  const button = (text, cls, run) => {
    const el = node("button", cls, text); el.type = "button"; el.addEventListener("click", run); return el;
  };
  const style = new document.defaultView.CSSStyleSheet();
  style.replaceSync(`
    .plugin-settings-dialog:has(.mijia-workspace) {
      --mijia-canvas: color-mix(in srgb, var(--sakura-panel-bg) 55%, var(--surface-raised));
      --mijia-surface: var(--sakura-input-bg);
      --mijia-control: var(--surface-soft);
      --mijia-secondary: color-mix(in srgb, var(--sakura-text) 25%, var(--sakura-secondary-text));
      --mijia-selected: color-mix(in srgb, var(--sakura-primary) 8%, var(--surface-raised));
      --mijia-shadow: 0 1px 3px rgb(0 0 0 / 4%);
      width: min(1060px, calc(100vw - 32px)); background: var(--mijia-canvas);
    }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-header { border: 0; padding: 18px 26px 10px; background: var(--mijia-canvas); }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-eyebrow { display: none; }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-body { padding: 8px 26px 24px; }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-close { color: var(--mijia-secondary); }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-footer { background: var(--mijia-canvas); border: 0; }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-footer button { color: var(--mijia-secondary); }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-draft-hint { display: none; }
    .plugin-settings-dialog:has(.mijia-workspace) .plugin-dialog-footer > div { margin-left: auto; }
    .plugin-settings-dialog:has(.mijia-workspace.is-detail) .plugin-dialog-footer { display: none; }
    .plugin-settings-dialog:has(.mijia-workspace) .connection-status { padding: 0; border: 0; background: transparent; }
    .plugin-settings-dialog:has(.mijia-workspace) .connection-status:not(.is-linking) .connection-status-icon,
    .plugin-settings-dialog:has(.mijia-workspace) .connection-status:not(.is-linking) h3 { display: none; }
    .plugin-settings-dialog:has(.mijia-workspace) .connection-status .plugin-setting-actions button { background: var(--mijia-surface); color: var(--mijia-secondary); font-size: 13px; }
    .plugin-settings-dialog:has(.mijia-workspace) .connection-status .plugin-status { color: var(--mijia-secondary); }
    .plugin-contribution:has(.mijia-workspace) > .plugin-contribution-title { display: none; }
    .plugin-settings:has(.mijia-workspace) > .plugin-contribution + .plugin-contribution { margin-top: 12px; }
    .mijia-workspace { color: var(--sakura-text); font-size: 14px; line-height: 1.6; min-width: 0; }
    .mijia-workspace [hidden] { display: none !important; }
    .mijia-workspace button { font: inherit; box-shadow: none; }
    .mijia-workspace button:focus-visible { outline: 2px solid var(--sakura-primary); outline-offset: 3px; }
    .mijia-top, .mijia-tools, .mijia-tabs, .mijia-rooms { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .mijia-top { justify-content: space-between; gap: 14px; padding: 10px 0 4px; }
    .mijia-tabs button, .mijia-rooms button { min-width: 0; border: 0; background: transparent; color: var(--mijia-secondary); padding: 8px 14px; border-radius: 9px; }
    .mijia-tabs button[aria-pressed="true"], .mijia-rooms button[aria-pressed="true"] { background: var(--tint-soft); color: var(--sakura-text); font-weight: 600; }
    .mijia-tools { flex: 1; justify-content: flex-end; }
    .mijia-search { display: flex; align-items: center; gap: 8px; width: min(250px, 100%); min-width: 0; padding: 0 12px; border-radius: 10px; background: var(--mijia-surface); }
    .mijia-search .sakura-icon { width: 16px; height: 16px; flex: none; color: var(--mijia-secondary); }
    .mijia-search input { appearance: none; width: 100%; min-width: 0; height: 40px; padding: 8px 0; border: 0; outline: 0; border-radius: 0; box-shadow: none; background: transparent; color: var(--sakura-text); font: inherit; }
    .mijia-search input::placeholder { color: var(--mijia-secondary); }
    .mijia-search:focus-within { outline: 2px solid var(--sakura-primary); outline-offset: 2px; }
    .mijia-tools .custom-select { width: 150px; min-width: 0; }
    .mijia-tools .custom-select__trigger { min-height: 40px; border: 0; background: var(--mijia-surface); color: var(--mijia-secondary); border-radius: 10px; }
    .mijia-rooms { padding: 14px 0; }
    .mijia-caption { margin: 4px 0 18px; color: var(--mijia-secondary); font-size: 13px; }
    .mijia-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(205px, 1fr)); gap: 12px; min-height: 180px; align-content: start; }
    .mijia-card { display: grid; grid-template-columns: 64px minmax(0, 1fr); grid-template-rows: auto auto; align-items: center; gap: 18px 12px; width: 100%; min-width: 0; min-height: 150px; padding: 20px 18px 16px; text-align: left; color: var(--sakura-text); border: 1px solid color-mix(in srgb, var(--hairline) 50%, transparent); background: var(--mijia-surface); border-radius: var(--radius-md); cursor: pointer; }
    .mijia-workspace .mijia-card { box-shadow: var(--mijia-shadow); }
    .mijia-workspace .mijia-card:hover { background: var(--mijia-selected); border-color: var(--sakura-primary); box-shadow: var(--mijia-shadow); }
    .mijia-card.is-offline { color: var(--mijia-secondary); }
    .mijia-card.is-offline .mijia-art { opacity: .45; }
    .mijia-art { display: grid; place-items: center; width: 64px; height: 64px; color: var(--sakura-muted-text); }
    .mijia-art img { width: 100%; height: 100%; object-fit: contain; }
    .mijia-art > .sakura-icon { width: 30px; height: 30px; }
    .mijia-card-copy { min-width: 0; }
    .mijia-card strong { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 15px; line-height: 1.5; font-weight: 600; overflow-wrap: anywhere; }
    .mijia-location { display: block; color: var(--mijia-secondary); font-size: 13px; margin-top: 4px; overflow-wrap: anywhere; }
    .mijia-card-foot { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--mijia-secondary); }
    .mijia-online { display: inline-flex; align-items: center; gap: 6px; }
    .mijia-online::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: #26855c; }
    .mijia-grant { padding: 3px 9px; border-radius: 6px; background: var(--mijia-control); }
    .mijia-empty { grid-column: 1 / -1; text-align: center; color: var(--sakura-secondary-text); padding: 40px 12px; }
    .mijia-detail { max-width: 780px; margin: 14px auto 0; padding: 28px 30px; border: 1px solid color-mix(in srgb, var(--hairline) 50%, transparent); border-radius: var(--radius-md); background: var(--mijia-surface); box-shadow: var(--mijia-shadow); }
    .mijia-workspace.is-detail .mijia-top { position: sticky; top: -8px; z-index: 2; padding: 12px 0; background: var(--mijia-canvas); }
    .mijia-workspace .mijia-back { display: inline-flex; align-items: center; gap: 9px; min-height: 44px; padding: 10px 16px; border: 1px solid var(--sakura-border); border-radius: var(--radius-sm); background: var(--mijia-surface); color: var(--sakura-text); font-size: 14px; font-weight: 600; }
    .mijia-workspace .mijia-back:hover { border-color: var(--sakura-primary); background: var(--mijia-selected); }
    .mijia-back .sakura-icon { width: 18px; height: 18px; transform: rotate(180deg); }
    .mijia-identity { display: flex; align-items: center; gap: 24px; padding: 0 0 30px; }
    .mijia-identity .mijia-art { width: 104px; height: 104px; padding: 10px; flex: none; }
    .mijia-identity h3 { font-size: 23px; margin: 0 0 6px; line-height: 1.4; overflow-wrap: anywhere; }
    .mijia-identity p { margin: 4px 0 0; color: var(--mijia-secondary); overflow-wrap: anywhere; }
    .mijia-permissions { border: 0; margin: 0 0 22px; padding: 0; }
    .mijia-permissions legend { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
    .mijia-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .mijia-option { position: relative; display: block; cursor: pointer; }
    .mijia-option input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; z-index: 1; cursor: pointer; }
    .mijia-option span { display: block; padding: 12px 8px; background: var(--mijia-control); border-radius: 9px; text-align: center; }
    .mijia-option input:checked + span { background: var(--mijia-selected); color: var(--sakura-text); font-weight: 600; box-shadow: inset 0 0 0 1.5px var(--sakura-primary); }
    .mijia-option input:focus-visible + span { outline: 2px solid var(--sakura-primary); outline-offset: 2px; }
    .mijia-alias { display: grid; gap: 8px; max-width: 360px; }
    .mijia-alias input { font: inherit; padding: 10px 12px; border: 1px solid var(--sakura-border); border-radius: var(--radius-sm); background: var(--surface-raised); color: var(--sakura-text); box-shadow: none; }
    .mijia-alias input:focus { outline: 2px solid var(--sakura-primary); outline-offset: 2px; }
    .mijia-inspection { margin-top: 28px; }
    .mijia-inspection > button { background: var(--mijia-surface); color: var(--sakura-text); font-weight: 600; }
    .mijia-scene-toggle { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px; margin-bottom: 12px; border-radius: 12px; background: var(--mijia-control); }
    .mijia-scene-toggle input { appearance: none; width: 38px; height: 22px; margin: 0; border: 0; border-radius: 99px; padding: 3px; background: var(--sakura-muted-text); cursor: pointer; }
    .mijia-scene-toggle input::after { content: ""; display: block; width: 16px; height: 16px; border-radius: 50%; background: var(--sakura-input-bg); transform: none; }
    .mijia-scene-toggle input:checked { background: var(--sakura-primary); }
    .mijia-scene-toggle input:checked::after { transform: translateX(16px); }
    .mijia-values { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px 18px; }
    .mijia-values dt { color: var(--mijia-secondary); }
    .mijia-values dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
    .mijia-state h4 { margin: 18px 0 8px; font-size: 13px; }
    @media(max-width: 650px) {
      .mijia-tools { flex-basis: 100%; justify-content: stretch; }
      .mijia-search { flex: 1; width: 0; }
      .mijia-grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
      .mijia-detail { padding: 20px 18px; }
      .mijia-identity { gap: 14px; }
      .mijia-identity .mijia-art { width: 66px; height: 66px; }
      .mijia-options { gap: 6px; }
    }
  `);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, style];
  const root = node("div", "mijia-workspace");
  const top = node("div", "mijia-top"), tabs = node("div", "mijia-tabs"), tools = node("div", "mijia-tools");
  const back = button("", "mijia-back", () => {
    const id = selected; selected = null; invalidate(); render();
    content.querySelector(`[data-id="${CSS.escape(id)}"]`)?.focus();
  });
  const backLabel = node("span"); back.append(createIcon(document, "arrow-right"), backLabel);
  const home = node("select"); home.setAttribute("aria-label", "家庭");
  const search = node("input"); search.type = "search"; search.placeholder = "搜索设备、房间或别名"; search.setAttribute("aria-label", "搜索设备或场景");
  const searchBox = node("div", "mijia-search"); searchBox.append(createIcon(document, "search"), search);
  tools.append(home, searchBox); top.append(back, tabs, tools); enhanceSelect(home);
  const rooms = node("div", "mijia-rooms"), caption = node("p", "mijia-caption"), content = node("div");
  root.append(top, rooms, caption, content);
  const modes = { hidden: "不开放", read: "仅查询", control: "允许控制" };
  let page = "devices", room = "", selected = null, generation = 0, signature = "", reading = false;
  const art = new Map();
  const current = () => !signal.aborted && isCurrent();
  const items = () => read(page === "devices" ? "items" : "sceneItems") || [];
  const grantField = () => page === "devices" ? "grants" : "sceneGrants";
  const grants = () => read(grantField()) || {};
  const invalidate = () => { generation++; };
  const setGrant = (id, patch) => write(grantField(), { ...grants(), [id]: { ...grants()[id], ...patch } });
  const image = item => {
    const box = node("span", "mijia-art"); art.set(item.id, { box, src: null }); updateImage(item); return box;
  };
  function updateImage(item) {
    const entry = art.get(item.id); if (!entry || entry.src === (item.image || "")) return;
    entry.src = item.image || "";
    const fallback = () => entry.box.replaceChildren(createIcon(document, page === "scenes" ? "layers" : "puzzle"));
    if (!item.image) { fallback(); return; }
    const img = node("img"); img.alt = ""; img.src = item.image; img.addEventListener("error", fallback, { once: true });
    entry.box.replaceChildren(img);
  }
  function selectPage(next) { page = next; selected = null; room = ""; search.value = ""; invalidate(); render(); }
  const devicesTab = button("设备", "", () => selectPage("devices"));
  const scenesTab = button("场景", "", () => selectPage("scenes")); tabs.append(devicesTab, scenesTab);
  function render() {
    closeSelects(root);
    art.clear(); content.replaceChildren();
    root.classList.toggle("is-detail", selected !== null);
    back.hidden = selected === null; tabs.hidden = selected !== null;
    backLabel.textContent = page === "devices" ? "返回设备列表" : "返回场景列表";
    devicesTab.textContent = `设备 ${(read("items") || []).length}`; scenesTab.textContent = `场景 ${(read("sceneItems") || []).length}`;
    devicesTab.setAttribute("aria-pressed", String(page === "devices")); scenesTab.setAttribute("aria-pressed", String(page === "scenes"));
    const oldHome = home.value, homes = [...new Set((read("items") || []).map(i => i.home).filter(Boolean))];
    home.replaceChildren();
    for (const value of ["", ...homes]) { const option = node("option", "", value || "全部家庭"); option.value = value; home.append(option); }
    home.value = homes.includes(oldHome) ? oldHome : "";
    refreshSelect(home); home.closest(".custom-select").hidden = page === "scenes"; search.placeholder = page === "devices" ? "搜索设备、房间或别名" : "搜索场景";
    const availableRooms = [...new Set(items().filter(i => !home.value || i.home === home.value).map(i => i.room).filter(Boolean))];
    if (!availableRooms.includes(room)) room = "";
    rooms.replaceChildren(); rooms.hidden = page !== "devices" || selected !== null;
    for (const name of ["", ...availableRooms]) {
      const tab = button(name || "全部房间", "", () => { room = name; invalidate(); render(); });
      tab.setAttribute("aria-pressed", String(room === name)); rooms.append(tab);
    }
    tools.hidden = selected !== null; caption.hidden = selected !== null;
    const item = items().find(i => i.id === selected);
    if (selected && !item) { selected = null; invalidate(); render(); return; }
    if (item) { renderDetail(item); return; }
    const query = search.value.trim().toLocaleLowerCase();
    const filtered = items().filter(i => (page === "scenes" || ((!home.value || i.home === home.value) && (!room || i.room === room)))
      && [i.label, i.description, grants()[i.id]?.alias].join(" ").toLocaleLowerCase().includes(query));
    caption.textContent = page === "devices" ? `${filtered.length} 台设备 · 选择设备，设置桌宠权限或查看状态。` : `${filtered.length} 个场景 · 选择允许桌宠执行的米家手动场景。`;
    const grid = node("div", "mijia-grid"); content.append(grid);
    if (!filtered.length) grid.append(node("p", "mijia-empty", items().length ? "没有找到匹配项，试试其他名称或房间。" : page === "devices" ? "暂无设备，请刷新设备列表。" : "暂无手动场景。可在米家 App 中创建后刷新。"));
    for (const item of filtered) {
      const card = button("", `mijia-card${item.online === false ? " is-offline" : ""}`, () => { selected = item.id; invalidate(); render(); back.focus(); });
      card.dataset.id = item.id; card.title = item.label;
      const copy = node("span", "mijia-card-copy"); copy.append(node("strong", "", item.label), node("span", "mijia-location", item.description));
      const foot = node("span", "mijia-card-foot");
      foot.append(node("span", item.online === true ? "mijia-online" : "", page === "scenes" ? "手动场景" : item.online === false ? "离线" : item.online === true ? "在线" : "状态未知"), node("span", "mijia-grant"));
      card.append(image(item), copy, foot); grid.append(card);
    }
    updateGrants();
  }
  function renderDetail(item) {
    const detail = node("section", "mijia-detail"); detail.setAttribute("aria-label", item.label);
    const identity = node("div", "mijia-identity"), text = node("div");
    text.append(node("h3", "", item.label), node("p", "", item.description));
    if (page === "devices") text.append(node("p", "", item.online === false ? "离线" : item.online === true ? "在线" : "在线状态未知"));
    identity.append(image(item), text); detail.append(identity);
    if (page === "devices") {
      const field = node("fieldset", "mijia-permissions"), options = node("div", "mijia-options"); field.append(node("legend", "", "桌宠权限"), options);
      for (const [value, label] of Object.entries(modes)) {
        const option = node("label", "mijia-option"), radio = node("input"); radio.type = "radio"; radio.name = "mijia-permission"; radio.value = value;
        radio.addEventListener("change", () => { if (radio.checked) setGrant(item.id, { mode: value }); });
        option.append(radio, node("span", "", label)); options.append(option);
      }
      detail.append(field, node("p", "mijia-caption", "不开放的设备仍可手动读取状态。权限修改会在应用设置后生效。"));
      const label = node("label", "mijia-alias", "别名"), input = node("input"); input.type = "text"; input.placeholder = "例如：床头灯";
      input.addEventListener("input", () => setGrant(item.id, { alias: input.value })); label.append(input); detail.append(label);
      const inspection = node("div", "mijia-inspection"), state = node("div", "mijia-state"); state.setAttribute("aria-live", "polite");
      const readButton = button("读取状态", "secondary-button", () => inspect(item, readButton, state));
      readButton.disabled = reading; inspection.append(readButton, state); detail.append(inspection);
    } else {
      const label = node("label", "mijia-scene-toggle"), input = node("input"); input.type = "checkbox";
      input.addEventListener("change", () => setGrant(item.id, { allowed: input.checked }));
      label.append(node("span", "", "允许桌宠执行"), input); detail.append(label, node("p", "mijia-caption", "授权场景会开放其中的全部动作，包括未单独开放的设备。"));
    }
    content.append(detail); updateGrants();
  }
  function updateGrants() {
    for (const card of content.querySelectorAll(".mijia-card")) {
      const value = grants()[card.dataset.id] || {};
      card.querySelector(".mijia-grant").textContent = page === "devices" ? modes[value.mode || "hidden"] : value.allowed ? "允许执行" : "不开放";
    }
    if (!selected) return;
    const value = grants()[selected] || {};
    for (const radio of content.querySelectorAll('input[type="radio"]')) radio.checked = radio.value === (value.mode || "hidden");
    const alias = content.querySelector(".mijia-alias input"); if (alias && document.activeElement !== alias) alias.value = value.alias || "";
    const allowed = content.querySelector('input[type="checkbox"]'); if (allowed) allowed.checked = Boolean(value.allowed);
  }
  async function inspect(item, control, target) {
    if (reading) return;
    reading = true; control.disabled = true; control.textContent = "正在读取…"; target.replaceChildren();
    const ticket = generation, request = { id: item.id, requestId: window.crypto.randomUUID() };
    const active = () => current() && ticket === generation;
    try {
      let result = await action("read", { request });
      while (active()) {
        const value = result.values.result;
        if (value.state !== "running") {
          if (value.message) target.append(node("p", "", value.message));
          const renderRows = (parent, rows) => {
            let group, list;
            for (const row of rows) {
              if (!list || group !== row.group) { group = row.group; if (group) parent.append(node("h4", "", group)); list = node("dl", "mijia-values"); parent.append(list); }
              list.append(node("dt", "", row.label), node("dd", "", row.value));
            }
          };
          renderRows(target, (value.rows || []).filter(row => !row.secondary));
          const secondary = (value.rows || []).filter(row => row.secondary);
          if (secondary.length) { const more = node("details"); more.append(node("summary", "", `其他状态（${secondary.length}）`)); renderRows(more, secondary); target.append(more); }
          break;
        }
        await new Promise(resolve => window.setTimeout(resolve, 250));
        if (active()) result = await action("read_status", { request });
      }
    } catch (error) { if (active()) { target.textContent = error.message; onError(error); } }
    finally {
      reading = false;
      if (current()) { const next = content.querySelector(".mijia-inspection button"); if (next) { next.disabled = false; next.textContent = "读取状态"; } }
    }
  }
  home.addEventListener("change", () => { room = ""; invalidate(); render(); });
  search.addEventListener("input", () => { invalidate(); render(); });
  root.addEventListener("keydown", event => {
    if (selected !== null && event.key === "Enter" && event.target.tagName === "INPUT") event.preventDefault();
  });
  function update() {
    const connected = read("visible");
    if (!connected) { selected = null; invalidate(); }
    const next = JSON.stringify([connected, (read("items") || []).map(({ image, ...item }) => item), read("sceneItems")]);
    if (next !== signature) { signature = next; invalidate(); render(); }
    else { items().forEach(updateImage); updateGrants(); }
  }
  update();
  return { element: root, update, cancel() { invalidate(); closeSelects(root); }, dispose() { invalidate(); closeSelects(root); document.adoptedStyleSheets = document.adoptedStyleSheets.filter(s => s !== style); root.remove(); } };
}
