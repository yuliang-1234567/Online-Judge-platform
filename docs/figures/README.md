# 图源与原图存档

| 图 | 唯一维护源 | 已确认修正 |
| --- | --- | --- |
| 总体架构 | [architecture.md](architecture.md) | 任务从Redis取；Beat投递维护任务；可信Worker访问daemon |
| 提交时序 | [submission-sequence.md](submission-sequence.md) | 鉴权→限流→参数校验→在途上限，与正文一致 |
| 状态机 | [submission-state.md](submission-state.md) | 保留既有拓扑，仅转成Mermaid |
| ER | [er.md](er.md) | input_size/output_size；限制快照；追踪/幂等分离 |

reference/中的四张PNG是v1.1原件，只用于历史对照，不再编辑。设计主本链接上述图源，不复制第二份Mermaid。

重绘限时半天，只修已确认差异；未完成项记录后不阻塞阶段06。当前已写出四份图源，WSL无Node/npm，运行时预览未执行，不能声称渲染验收通过。静态链接、围栏和字段核对结果记录在修订说明。
