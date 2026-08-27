// L-clone 待确认决策提醒 (DSH 客户端 bundle)
// 每 5 秒轮询 lclone web 的 /api/pending, 有 pending 就在 DSH 界面右上角注入横幅,
// 点击横幅跳转到 lclone web 的「待确认」处理页。无需任何宿主服务注入, 只用浏览器全局 API。
window.__ModuleLoader__.load({
  id: "lclone-memory-dsh",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;

    function apply(ctx) {
      const PENDING_URL = "http://127.0.0.1:8000/api/pending";
      const WEB_URL = "http://127.0.0.1:8000/";
      let banner = null;
      let last = -1;

      function render(n) {
        if (banner) { banner.remove(); banner = null; }
        if (n <= 0) return;
        banner = document.createElement("div");
        banner.id = "lclone-pending-banner";
        banner.style.cssText =
          "position:fixed;top:14px;right:14px;z-index:2147483647;" +
          "background:#fbbf24;color:#241d08;padding:11px 16px;border-radius:11px;" +
          "box-shadow:0 8px 28px rgba(0,0,0,.35);" +
          "font:600 13px/1.4 system-ui;cursor:pointer;" +
          "display:flex;align-items:center;gap:10px;";
        banner.innerHTML = `⏳ 待确认决策 <b style="font-size:16px">${n}</b> 条 · 点此处理`;
        banner.onclick = () => window.open(WEB_URL, "_blank");
        const x = document.createElement("span");
        x.textContent = "✕";
        x.style.cssText = "opacity:.6;font-weight:400;";
        x.onclick = (e) => { e.stopPropagation(); banner.remove(); banner = null; };
        banner.appendChild(x);
        document.body.appendChild(banner);
      }

      async function check() {
        try {
          const r = await (await fetch(PENDING_URL)).json();
          const n = (r.items || []).length;
          if (n !== last) { last = n; render(n); }
        } catch (e) { /* lclone web 未启动, 忽略 */ }
      }

      check();
      const timer = setInterval(check, 1500);  // 1.5s 近即时刷新, 决策进 pending 立刻弹横幅
      return () => clearInterval(timer);
    }

    exports.apply = apply;
    return module.exports;
  }
});
