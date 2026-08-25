// DSH 动态 Cordis 插件: L-clone 记忆钩子（会话开始 bootstrap / 每轮结束 capture）。
//
// 已确认的事件（来自 dsh-agent-loop、dsh-session 源码）:
//   - agent/session-start : Cordis 事件, 会话建立后发出, payload { source }
//   - session/event       : 会话事件流; event.type 含 'turn/start' / 'turn/end' / 'assistant/message'
//   - turn/end payload    : { turn: number, reason: string }
//
// 激活前需用 cordis 预设的 cordis_inspect_query 确认两处（本会话是 standard 预设，无 cordis 工具）:
//   1) 执行外部命令用哪个 Host service（bash / subprocess）及其方法签名
//   2) 如何取到本轮 user+assistant 文本（session/event 的消息类型, 或 session service）
//
// 激活流程见 README.md: cordis_define → cordis_run。

return {
  apply(ctx) {
    // 会话开始 → bootstrap 注入 charter + 全局记忆
    ctx.on('agent/session-start', (payload) => {
      const subprocess = ctx.get('subprocess')
      if (subprocess === undefined) return
      // TODO(cordis_inspect_query 确认): subprocess 运行 `lclone bootstrap ""`,
      // 把 stdout 注入 agent 上下文（具体注入 service 也需确认）
    })

    // 每轮结束 → capture 沉淀 decision/note 草稿
    ctx.on('session/event', (event) => {
      if (event.type !== 'turn/end') return
      const subprocess = ctx.get('subprocess')
      if (subprocess === undefined) return
      // TODO(cordis_inspect_query 确认): 取本轮文本, 运行 `lclone capture "<text>"`
    })
  },
}
