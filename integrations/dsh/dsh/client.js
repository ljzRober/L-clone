// L-clone 大脑看板 (DSH 客户端 UI bundle): 侧边栏「大脑看板」按钮 → 中心区全屏 iframe 记忆工作台。
//
// 格式照已验证先例:
//   - bundle 外壳: window.__ModuleLoader__.load({ id: <包名>, factory })  (dshmarket 同款)
//   - 侧边栏按钮 DOM 注入 + MutationObserver 自愈:  @linxin666/dsh-client-ui-task-board 同款
//   - 面板切换用 html data-attribute + CSS (对话子树保持挂载, 不丢状态): task-board 同款
//   - 与其他面板(taskboard/ssh)互斥: dsh-panel-activate CustomEvent 协议
//
// 零依赖: 不引 React, 纯原生 DOM + 内联 CSS (theme 变量 --dsw-alias-* 自适应深浅色)。
// 安装: dsh plugin --profile web add <本目录绝对路径> (与 host 端 index.js 同包, 双面包)。

window.__ModuleLoader__.load({
  id: "lclone-memory-dsh",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    // ---- 常量 ----
    const PANEL_NAME = "lclone";
    const ACTIVE_ATTR = "data-dsh-lclone-active";
    const ENTRY_SELECTOR = "[data-dsh-lclone-entry]";
    const OTHER_ACTIVE_ATTR = "data-dsh-ssh-active";
    const ACTIVATE_EVENT = "dsh-panel-activate";
    const HEALTH_ENDPOINT = "/api/lclone-health";
    let DASHBOARD_URL = "http://127.0.0.1:8000"; // 后端基址; 会从 /api/lclone-health 的 webUrl 更新(支持服务器部署)
    let DOCS_URL = "https://github.com/ljzRober/L-clone"; // 文档链接; 会从 health 的 docsUrl 更新
    // 决策确认 (本变更): 客户端轮询 host 代理路由, 弹窗 + 角标呈现待确认决策, 不进主 agent。
    const DECISIONS_ENDPOINT = "/api/lclone-decisions";
    const REVIEW_ENDPOINT = "/api/lclone-review";
    const DECISION_POLL_MS = 4000;

    // 中心对话列 / 侧边栏 shell 的 DOM 选择器 (task-board 验证过的壳选择器)
    const CONVERSATION_COLUMN_SELECTOR = '[data-pane="conversation"], [class*="centerCol"]';
    const SIDEBAR_COLUMN_SELECTOR = '[data-pane="sidebar"], [class*="sidebarCol"]';
    const SIDEBAR_ROW_SELECTOR =
      '[class*="sessionRow"], [class*="projectRow"], [class*="searchResultRow"], [class*="searchResultWorkspace"], [class*="newSession"]';

    // ---- 内联 CSS (主题变量自适应; 底部 footer 紧凑图标按钮; 焦点环; reduced-motion) ----
    const CSS = `
/* 给中心对话列建立定位上下文, 使 absolute 看板容器能铺满 (task-board 同款, 缺了会白屏) */
[data-pane=conversation],[class*=centerCol]{position:relative}
[data-dsh-lclone-entry]{box-sizing:border-box;width:100%;height:36px;color:var(--dsw-alias-label-secondary,#6b7280);cursor:pointer;white-space:nowrap;background:0 0;border:none;border-radius:8px;justify-content:flex-start;align-items:center;gap:8px;padding:0 10px;font-family:var(--dsw-font-family);font-size:13px;display:flex}
[data-dsh-frame][data-sidebar-collapsed] [data-dsh-lclone-entry]{border-radius:50%;justify-content:center;width:36px;height:36px;margin:0 auto 12px;padding:0}
[data-dsh-frame][data-sidebar-collapsed] [data-dsh-lclone-entry] .lclone-entry-label{display:none}
[data-dsh-lclone-entry]:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}
[data-dsh-lclone-entry][data-active]{background:var(--dsw-alias-interactive-bg-active);color:var(--dsw-alias-label-primary);font-weight:600}
[data-dsh-lclone-entry]:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:2px}
[data-dsh-lclone-entry] .lclone-entry-icon{flex:none;justify-content:center;align-items:center;width:24px;height:24px;display:inline-flex}
[data-dsh-lclone-entry] .lclone-entry-icon svg{width:18px;height:18px;display:block}
[data-dsh-lclone-entry] .lclone-entry-label{min-width:0;text-overflow:ellipsis;overflow:hidden;text-align:left}
[data-dsh-lclone-view]{z-index:60;background:var(--dsw-alias-bg-base);display:none;flex-direction:column;position:absolute;inset:0}
html[data-dsh-lclone-active]:not([data-dsh-ssh-active]) [data-dsh-lclone-view]{display:flex}
html[data-dsh-lclone-active]:not([data-dsh-ssh-active]) [data-pane=conversation]>:not([data-dsh-lclone-view]),html[data-dsh-lclone-active]:not([data-dsh-ssh-active]) [class*=centerCol]>:not([data-dsh-lclone-view]){display:none!important}
.lclone-board-bar{box-sizing:border-box;flex:none;height:44px;border-bottom:1px solid var(--dsw-alias-border-l2);align-items:center;gap:8px;padding:0 12px;display:flex}
.lclone-board-back{color:var(--dsw-alias-label-secondary);cursor:pointer;white-space:nowrap;background:0 0;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;align-items:center;gap:4px;padding:4px 10px;font-size:12px;font-family:inherit;display:inline-flex}
.lclone-board-back:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}
.lclone-board-back:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:2px}
/* 刷新按钮: 主色填充 + 图标, 显眼 (区别于 ghost 的返回会话) */
.lclone-board-refresh{color:var(--dsw-alias-label-primary-foreground);cursor:pointer;white-space:nowrap;background:var(--dsw-alias-button-info-fill);border:none;border-radius:8px;align-items:center;gap:5px;padding:5px 12px;font-size:12px;font-family:inherit;display:inline-flex}
.lclone-board-refresh:hover{background:var(--dsw-alias-button-info-hover);opacity:.92}
.lclone-board-refresh:active{transform:translateY(1px)}
.lclone-board-refresh:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:2px}
.lclone-board-refresh svg{width:13px;height:13px;display:block}
@media (prefers-reduced-motion:reduce){.lclone-board-refresh{transition:none}}
.lclone-board-title{min-width:0;color:var(--dsw-alias-label-primary);text-overflow:ellipsis;white-space:nowrap;flex:1;margin:0;font-size:13px;font-weight:600;overflow:hidden}
.lclone-board-status{flex:none;align-items:center;gap:6px;color:var(--dsw-alias-label-tertiary);font-size:12px;display:inline-flex}
.lclone-board-dot{width:8px;height:8px;border-radius:50%;flex:none}
.lclone-board-dot[data-state=online]{background:var(--dsw-alias-state-success-primary,#0f6b3a)}
.lclone-board-dot[data-state=offline]{background:var(--dsw-alias-state-error-primary,#d93025)}
.lclone-board-frame{box-sizing:border-box;min-width:0;min-height:0;border:0;flex:1;width:100%;display:block}
.lclone-board-offline{box-sizing:border-box;flex:1;align-items:center;justify-content:center;color:var(--dsw-alias-label-secondary);gap:12px;padding:24px;font-size:13px;text-align:center;flex-direction:column;display:flex}
.lclone-board-offline code{color:var(--dsw-alias-label-primary);font-family:var(--dsw-font-markdown-code-block-small);background:var(--dsw-alias-markdown-code-block);border:1px solid var(--dsw-alias-border-l1);border-radius:6px;padding:2px 6px}
@media (prefers-reduced-motion:reduce){[data-dsh-lclone-entry]{transition:none}}
/* 侧边栏入口的待确认角标 (决策确认) */
[data-dsh-lclone-entry]{position:relative}
[data-dsh-lclone-entry] .lclone-entry-badge{position:absolute;top:-5px;right:-5px;box-sizing:border-box;min-width:16px;background:var(--dsw-alias-state-error-primary,#d93025);color:#fff;border:2px solid var(--dsw-alias-bg-base,#fff);border-radius:9px;padding:0 4px;font-size:10px;line-height:14px;font-weight:600;text-align:center;pointer-events:none}
/* 决策确认弹窗 (非侵入, 右下角), 主题变量自适应深浅色 */
[data-dsh-lclone-decision-toast]{position:fixed;right:16px;bottom:16px;z-index:70;box-sizing:border-box;width:min(360px,calc(100vw - 32px));max-height:60vh;overflow:auto;background:var(--dsw-alias-bg-base,#151517);border:1px solid var(--dsw-alias-border-l2,#ffffff1f);border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.18);padding:12px 14px;display:flex;flex-direction:column;gap:8px;font-family:var(--dsw-font-family);color:var(--dsw-alias-label-primary,#f9fafb);animation:dshLcloneToastIn .18s ease-out}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-head{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--dsw-alias-label-secondary)}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-head .dot{width:7px;height:7px;border-radius:50%;background:var(--dsw-alias-state-business-primary,#2264d1);flex:none}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-item{display:flex;flex-direction:column;gap:6px;border-top:1px solid var(--dsw-alias-border-l1);padding-top:8px}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-body{font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-word;color:inherit;opacity:.92}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-actions{display:flex;gap:8px;flex-wrap:wrap}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-actions button{flex:1;min-width:64px;padding:6px 10px;font-size:12px;font-family:inherit;border:1px solid var(--dsw-alias-border-l2,#c9cfd6);border-radius:8px;background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.14));color:var(--dsw-alias-label-primary,#1a1d21);cursor:pointer}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-actions button:hover{background:var(--dsw-alias-interactive-bg-hover,rgba(127,127,127,.24))}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-actions button:focus-visible{outline:2px solid var(--dsw-alias-state-business-primary);outline-offset:2px}
[data-dsh-lclone-decision-toast] .dsh-lclone-dt-actions button.dsh-lclone-dt-keep{background:var(--dsw-alias-button-info-fill);color:var(--dsw-alias-label-primary-foreground);border:none}
@keyframes dshLcloneToastIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){[data-dsh-lclone-decision-toast]{animation:none}}
@media (max-width:520px){[data-dsh-lclone-decision-toast]{right:12px;left:12px;bottom:12px;width:auto}}`;

    const tagId = "lclone-memory-dsh/dashboard.css";
    if (typeof document !== "undefined" && document.querySelector('style[data-plugin-css="' + tagId + '"]') === null) {
      const tag = document.createElement("style");
      tag.dataset.plugin = "lclone-memory-dsh";
      tag.dataset.pluginCss = tagId;
      tag.textContent = CSS;
      document.head.appendChild(tag);
    }

    // ---- 图标 (18px 导航 glyph 尺寸, stroke 风格与其他入口一致) ----
    const ICON =
      '<svg viewBox="0 0 16 16" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.5c1.6 0 2.8 1.1 2.8 2.6 0 1.2-.7 2.2-1.8 2.9.8.4 1.4 1.1 1.7 1.9.3.9.2 1.8-.2 2.4.4.2.6.5.6.9v.4H8.6C7.3 13.7 6 13.4 4.9 12.5 3.7 11.5 3 10 3 8.5 3 5.2 5.2 2.5 8 2.5z"/><path d="M8 2.5V1M5.5 4.2 4.4 3.1M10.5 4.2l1.1-1.1"/></svg>';

    // ---- 控制器: 面板开关状态 ----
    function createController() {
      let open = false;
      const subs = new Set();
      return {
        isOpen: () => open,
        toggle: () => {
          open = !open;
          for (const fn of subs) fn();
        },
        close: () => {
          if (!open) return;
          open = false;
          for (const fn of subs) fn();
        },
        subscribe: (fn) => {
          subs.add(fn);
          return () => subs.delete(fn);
        },
      };
    }

    // ---- 侧边栏导航区入口按钮 (与 task-board/ssh/技能中心同区, 可见) ----
    // task-board 同款: 挂到 side 根 (logoRow 的 parentElement = hHd-Xa_root),
    // 折叠态由 CSS [data-sidebar-collapsed] 收敛为图标; 挂 footArea 会被 display:none 隐藏。
    function sidebarShell() {
      const column = document.querySelector(SIDEBAR_COLUMN_SELECTOR);
      if (column === null) return void 0;
      return column.querySelector('[class*="logoRow"]')?.parentElement ?? column;
    }

    function placeEntry(shell, entry) {
      if (shell === void 0) return false;
      if (entry.parentElement === shell) return true;
      // 插到技能中心入口之后 (占据其相邻位置; 支持展开/折叠形态)
      const family = Array.from(shell.children).filter((el) => el instanceof HTMLElement);
      const skillEntry = family.find(
        (el) => el.matches('[data-dsh-skill-explorer-entry], [class*="cBrkua_entry"]')
      );
      const lastNavBtn = family.filter((el) => el.matches('button, [data-dsh-taskboard-entry], [data-dsh-ssh-entry], [data-dsh-skill-explorer-entry]')).pop();
      const anchor = skillEntry !== void 0 ? skillEntry.nextElementSibling : (lastNavBtn !== void 0 ? lastNavBtn.nextElementSibling : void 0);
      shell.insertBefore(entry, anchor ?? null);
      return true;
    }

    function createEntry(controller) {
      const entry = document.createElement("button");
      entry.type = "button";
      entry.setAttribute("data-dsh-lclone-entry", "");
      entry.setAttribute("data-dsh-plugin", "lclone-memory-dsh");
      entry.setAttribute("data-dsh-part", "sidebar-entry");
      entry.setAttribute("aria-label", "大脑看板");
      entry.setAttribute("title", "大脑看板 (L-clone 记忆工作台)");
      // 图标 + 文字 (与 task-board/ssh/技能中心同级对齐); 折叠态由 CSS 只显图标
      entry.innerHTML =
        '<span class="lclone-entry-icon">' + ICON + '</span><span class="lclone-entry-label">大脑看板</span>';
      // 待确认决策角标 (决策确认): 初始隐藏, 由 mountDecisionConfirm 更新
      const badge = document.createElement("span");
      badge.className = "lclone-entry-badge";
      badge.dataset.dshLcloneBadge = "";
      badge.style.display = "none";
      entry.appendChild(badge);
      controller.entryRef = entry;
      entry.addEventListener("click", (event) => {
        event.preventDefault();
        controller.toggle();
      });
      return entry;
    }

    function mountSidebarEntry(controller) {
      if (typeof document !== "undefined" && document.querySelector(ENTRY_SELECTOR) !== null) return () => {};
      const entry = createEntry(controller);
      let shell;
      let placed = false;
      let shellObserver;
      const tryPlace = () => {
        if (shell !== void 0 && !shell.isConnected) {
          shellObserver.disconnect();
          shell = void 0;
          placed = false;
        }
        if (placed) {
          if (document.body.contains(entry)) return;
          shellObserver.disconnect();
          shell = void 0;
          placed = false;
        }
        shell ??= sidebarShell();
        if (shell === void 0) return;
        placed = placeEntry(shell, entry);
        if (placed) {
          shellObserver.observe(shell, { childList: true, subtree: true });
        }
      };
      const waitObserver = new MutationObserver(() => {
        tryPlace();
      });
      waitObserver.observe(document.body, { childList: true, subtree: true });
      shellObserver = new MutationObserver(() => {
        if (shell === void 0 || !shell.isConnected) {
          placed = false;
          tryPlace();
          return;
        }
        if (!shell.contains(entry)) placed = placeEntry(shell, entry);
      });
      const syncActive = () => {
        if (controller.isOpen()) entry.dataset.active = "true";
        else delete entry.dataset.active;
      };
      const unsubActive = controller.subscribe(syncActive);
      tryPlace();
      syncActive();
      return () => {
        waitObserver.disconnect();
        shellObserver.disconnect();
        unsubActive();
        entry.remove();
      };
    }

    // ---- 全屏看板面板 (中心列注入 iframe) ----
    function mountBoard(controller) {
      let container;
      let iframe;
      let statusDot;
      let offlineHint;
      let skillHint;
      let docsLinkEl;
      const ensure = () => {
        if (container !== void 0) return;
        const column = document.querySelector(CONVERSATION_COLUMN_SELECTOR);
        if (column === void 0 || column === null) return; // 对话列未挂载: 静默等待, 由 waitObserver 重试
        container = document.createElement("div");
        container.dataset.dshLcloneView = "";
        container.dataset.dshPlugin = "lclone-memory-dsh";

        const bar = document.createElement("div");
        bar.className = "lclone-board-bar";

        const back = document.createElement("button");
        back.type = "button";
        back.className = "lclone-board-back";
        back.textContent = "← 返回会话";
        back.addEventListener("click", () => controller.close());

        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.className = "lclone-board-refresh";
        refresh.innerHTML =
          '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2v3h-3"/></svg><span>刷新</span>';
        refresh.addEventListener("click", () => {
          if (iframe !== void 0) {
            iframe.src = DASHBOARD_URL; // reload iframe 重新拉取看板数据
          }
          refreshHealth();
        });

        const title = document.createElement("span");
        title.className = "lclone-board-title";
        title.textContent = "外置大脑 · 记忆工作台";

        const status = document.createElement("span");
        status.className = "lclone-board-status";
        statusDot = document.createElement("span");
        statusDot.className = "lclone-board-dot";
        statusDot.dataset.state = "unknown";
        const statusText = document.createElement("span");
        statusText.textContent = "检测中…";
        status.appendChild(statusDot);
        status.appendChild(statusText);

        bar.appendChild(back);
        bar.appendChild(refresh);
        bar.appendChild(title);
        bar.appendChild(status);

        iframe = document.createElement("iframe");
        iframe.className = "lclone-board-frame";
        iframe.src = DASHBOARD_URL;
        iframe.title = "L-clone 记忆工作台";

        offlineHint = document.createElement("div");
        offlineHint.className = "lclone-board-offline";
        offlineHint.style.display = "none";
        const hintTitle = document.createElement("div");
        hintTitle.style.fontWeight = "600";
        hintTitle.textContent = "L-clone 后台服务未启动，记忆工作台无法显示。";
        const hintCmd = document.createElement("div");
        hintCmd.style.marginTop = "6px";
        hintCmd.textContent = "请先启动后台服务：";
        const hintCode = document.createElement("code");
        hintCode.textContent = "python -m lclone web（或 lclone serve start 后台常驻）";
        const hintRemote = document.createElement("div");
        hintRemote.style.marginTop = "6px";
        hintRemote.textContent = "部署在服务器上时，用 LCLONE_WEB_URL 指向后台地址。";
        docsLinkEl = document.createElement("a");
        docsLinkEl.href = DOCS_URL;
        docsLinkEl.target = "_blank";
        docsLinkEl.rel = "noopener noreferrer";
        docsLinkEl.textContent = "查看使用文档 →";
        docsLinkEl.style.display = "inline-block";
        docsLinkEl.style.marginTop = "8px";
        docsLinkEl.style.color = "var(--dsw-alias-state-business-primary,#4f8cff)";
        offlineHint.appendChild(hintTitle);
        offlineHint.appendChild(hintCmd);
        offlineHint.appendChild(hintCode);
        offlineHint.appendChild(hintRemote);
        offlineHint.appendChild(docsLinkEl);

        skillHint = document.createElement("div");
        skillHint.className = "lclone-board-offline";
        skillHint.style.display = "none";
        const skillText = document.createElement("span");
        skillText.textContent = "记忆 skill 未安装，自动记忆(读侧 bootstrap)不生效。请运行：";
        const skillCode = document.createElement("code");
        skillCode.textContent = "lclone integrate --target skill";
        skillHint.appendChild(skillText);
        skillHint.appendChild(skillCode);

        container.appendChild(bar);
        container.appendChild(offlineHint);
        container.appendChild(skillHint);
        container.appendChild(iframe);
        column.appendChild(container);
      };

      const applyActive = () => {
        if (controller.isOpen()) {
          document.documentElement.removeAttribute(OTHER_ACTIVE_ATTR);
          document.documentElement.setAttribute(ACTIVE_ATTR, "");
          document.dispatchEvent(new CustomEvent(ACTIVATE_EVENT, { detail: PANEL_NAME }));
          refreshHealth();
        } else {
          document.documentElement.removeAttribute(ACTIVE_ATTR);
        }
      };

      const onOtherActivate = (event) => {
        if (event.detail !== PANEL_NAME && controller.isOpen()) controller.close();
      };
      const onClickSidebarRow = (event) => {
        if (!controller.isOpen()) return;
        const target = event.target;
        if (target === null) return;
        if (target.closest(SIDEBAR_ROW_SELECTOR) !== null) controller.close();
      };

      // 健康探测: 同源 host 路由 (host 端 index.js 注册), 无 CORS 问题
      let healthTimer = null;
      const refreshHealth = () => {
        if (statusDot === void 0) return;
        fetch(HEALTH_ENDPOINT, { headers: { accept: "application/json" } })
          .then((response) => {
            if (!response.ok) throw new Error("bad status " + response.status);
            return response.json();
          })
          .then((body) => {
            const online = body && body.ok === true;
            const skillOk = body && body.skill !== false;
            if (body && typeof body.webUrl === "string" && body.webUrl) DASHBOARD_URL = body.webUrl.replace(/\/+$/, "");
            if (body && typeof body.docsUrl === "string" && body.docsUrl) DOCS_URL = body.docsUrl;
            statusDot.dataset.state = online ? "online" : "offline";
            if (offlineHint !== void 0) offlineHint.style.display = online ? "none" : "flex";
            if (skillHint !== void 0) skillHint.style.display = skillOk ? "none" : "flex";
            if (iframe !== void 0) {
              iframe.style.display = online ? "block" : "none";
              if (online && iframe.getAttribute("src") !== DASHBOARD_URL) iframe.src = DASHBOARD_URL;
            }
            if (docsLinkEl !== void 0) docsLinkEl.href = DOCS_URL;
          })
          .catch(() => {
            statusDot.dataset.state = "offline";
            if (offlineHint !== void 0) offlineHint.style.display = "flex";
            if (iframe !== void 0) iframe.style.display = "none";
          });
      };

      const waitObserver = new MutationObserver(() => {
        ensure();
      });
      waitObserver.observe(document.body, { childList: true, subtree: true });

      document.addEventListener("click", onClickSidebarRow, true);
      document.addEventListener(ACTIVATE_EVENT, onOtherActivate);
      const unsubscribe = controller.subscribe(applyActive);
      ensure();
      applyActive();
      if (controller.isOpen()) healthTimer = setInterval(refreshHealth, 30000);

      return () => {
        document.removeEventListener("click", onClickSidebarRow, true);
        document.removeEventListener(ACTIVATE_EVENT, onOtherActivate);
        waitObserver.disconnect();
        unsubscribe();
        if (healthTimer !== null) clearInterval(healthTimer);
        document.documentElement.removeAttribute(ACTIVE_ATTR);
        container?.remove();
        container = void 0;
        iframe = void 0;
        statusDot = void 0;
        offlineHint = void 0;
        skillHint = void 0;
        docsLinkEl = void 0;
      };
    }

    // ---- 决策确认: 轮询待确认决策, 弹窗保留/删除, 侧边栏角标 (不进主 agent) ----
    function mountDecisionConfirm(controller) {
      // seen: 用户已处理(保留/删除)或「稍后」消失的决策 id, 避免重复提醒同一批
      const seen = new Set();
      let renderedIds = []; // 当前弹窗里正在展示的决策 id 列表 (仅集合变化时才重建, 避免每轮夺焦点)
      let toastEl;
      let timer;

      function refreshBadge(n) {
        let entry = controller.entryRef;
        if (entry === void 0 || entry === null) entry = document.querySelector(ENTRY_SELECTOR);
        if (entry === void 0 || entry === null) return;
        let badge = entry.querySelector("[data-dsh-lclone-badge]");
        if (badge === null) {
          badge = document.createElement("span");
          badge.className = "lclone-entry-badge";
          badge.dataset.dshLcloneBadge = "";
          entry.appendChild(badge);
        }
        const label = n + " 条待确认";
        badge.setAttribute("aria-label", label);
        badge.title = label;
        badge.textContent = n > 99 ? "99+" : String(n);
        badge.style.display = n > 0 ? "inline-block" : "none";
      }

      function closeToast() {
        if (toastEl !== void 0) {
          toastEl.remove();
          toastEl = void 0;
        }
        renderedIds = [];
      }

      function renderToast(items) {
        if (toastEl === void 0) {
          toastEl = document.createElement("div");
          toastEl.dataset.dshLcloneDecisionToast = "";
          toastEl.dataset.dshPlugin = "lclone-memory-dsh";
          toastEl.setAttribute("role", "status");
          toastEl.setAttribute("aria-live", "polite");
          // 挂到主题作用域内的对话列, 让 --dsw-alias-bg-elevated 正确解析成深/浅色背景,
          // 否则浮动到 document.body 会回退成白底 + 白色文字(不可见)。
          const toastHost = document.querySelector(CONVERSATION_COLUMN_SELECTOR) || document.body;
          toastHost.appendChild(toastEl);
        }
        toastEl.innerHTML = "";
        const head = document.createElement("div");
        head.className = "dsh-lclone-dt-head";
        head.innerHTML = '<span class="dot"></span><span>新增 ' + items.length + " 条待确认决策</span>";
        toastEl.appendChild(head);
        for (const it of items) {
          const item = document.createElement("div");
          item.className = "dsh-lclone-dt-item";
          const body = document.createElement("div");
          body.className = "dsh-lclone-dt-body";
          body.textContent = it.content || "(无内容)";
          item.appendChild(body);
          const actions = document.createElement("div");
          actions.className = "dsh-lclone-dt-actions";
          const mkBtn = (label, cls, act) => {
            const b = document.createElement("button");
            b.textContent = label;
            if (cls) b.className = cls;
            b.addEventListener("click", act);
            return b;
          };
          actions.appendChild(mkBtn("保留", "dsh-lclone-dt-keep", () => review(it.id, "keep")));
          actions.appendChild(mkBtn("删除", "", () => review(it.id, "delete")));
          actions.appendChild(mkBtn("稍后", "", () => { seen.add(it.id); poll(); }));
          item.appendChild(actions);
          toastEl.appendChild(item);
        }
        renderedIds = items.map((it) => it.id);
      }

      async function poll() {
        try {
          const r = await fetch(DECISIONS_ENDPOINT, { headers: { accept: "application/json" } });
          if (!r.ok) throw new Error("bad status " + r.status);
          const body = await r.json();
          const items = (body && body.items) || [];
          refreshBadge(items.length);
          const fresh = items.filter((it) => !seen.has(it.id));
          const sig = fresh.map((it) => it.id).join(",");
          if (sig !== renderedIds.join(",")) {
            if (fresh.length > 0) renderToast(fresh);
            else closeToast();
          }
        } catch (e) {
          // web 服务离线: 无法读取待确认, 清角标 + 关弹窗, 等恢复后再轮询
          refreshBadge(0);
          closeToast();
        }
      }

      async function review(id, action) {
        let ok = false;
        try {
          const r = await fetch(REVIEW_ENDPOINT, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ id, action }),
          });
          const body = await r.json().catch(() => ({}));
          ok = r.ok && body.ok === true;
        } catch (e) { ok = false; }
        // 仅在后端确认成功时才标记已处理; 失败则留在 seen 之外, 下一轮 poll 重新弹窗
        if (ok) seen.add(id);
        poll();
      }

      // 页面隐藏时暂停轮询(省资源且避免后台无意义刷新), 可见后再启动
      const onVisibility = () => {
        if (document.hidden) {
          if (timer !== void 0) clearInterval(timer);
        } else {
          if (timer !== void 0) clearInterval(timer);
          timer = setInterval(poll, DECISION_POLL_MS);
          poll();
        }
      };
      document.addEventListener("visibilitychange", onVisibility);

      timer = setInterval(poll, DECISION_POLL_MS);
      poll();

      return () => {
        if (timer !== void 0) clearInterval(timer);
        document.removeEventListener("visibilitychange", onVisibility);
        closeToast();
      };
    }

    // ---- apply: 挂载入口 (HMR 重载时通过 ctx.effect 释放后可重新挂) ----
    const APPLIED_FLAG = "lcloneMemoryDashboardApplied";

    function apply(ctx) {
      // 同一页面内防重复挂载 (热重载 bundle 会重新 apply, 靠 effect 释放标记)
      if (globalThis[APPLIED_FLAG] === true) return;
      globalThis[APPLIED_FLAG] = true;
      ctx.effect(() => {
        const controller = createController();
        const disposers = [];
        try {
          disposers.push(mountSidebarEntry(controller));
          disposers.push(mountBoard(controller));
          disposers.push(mountDecisionConfirm(controller));
        } catch (error) {
          console.error("[lclone-memory-dsh] mount failed:", error);
          return () => {
            globalThis[APPLIED_FLAG] = void 0;
          };
        }
        return () => {
          for (const dispose of disposers.splice(0)) {
            try {
              dispose();
            } catch {}
          }
          globalThis[APPLIED_FLAG] = void 0;
        };
      }, "lclone-memory-dsh: dashboard mount");
    }

    exports.apply = apply;
    exports.inject = [];
    return module.exports;
  },
});
