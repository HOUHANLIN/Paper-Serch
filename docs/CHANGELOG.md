# 变更记录

## Unreleased
- 自动工作流改为 SSE：新增 `POST /api/auto_workflow_stream`，方向完成即可返回分组结果与进度事件。
- 工作流“并发”语义调整：前端并发设置用于控制 PubMed HTTP 请求并发（方向本身不限制并发）。
- PubMed 增强：对 `429/5xx/超时/连接失败` 增加重试与指数退避，错误信息更可操作。
- AI 摘要增强：按文章并发 summarize（一次调用总结一篇文章），默认不限制并发；支持 `AI_SUMMARY_CONCURRENCY` 覆盖。
- UI 调整：“获取可用模型列表”按钮移动到对应 Provider 的“模型名称”下方；工作流并发设置归入高级参数。

## 0.5.0
- 初始版本：Flask Web 检索、PubMed 数据源、BibTeX 导出、可选 AI 中文摘要与建议。

