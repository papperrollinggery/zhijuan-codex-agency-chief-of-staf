# User Experience

只在 Durable 生命周期需要阶段状态，或 visualization 能显著降低理解成本时读取本文件。Direct/Focused 不必读取。

## 前台原则

用户应先看到项目结果，而不是编排过程：

1. 当前得到什么。
2. 关键判断或真实风险。
3. 下一项内容动作。
4. 唯一需要用户决定的问题（若有）。

不要展示内部档位、Profile、模型 ID、reasoning、task/thread schema、packet、hash、receipt、sandbox、JSON/YAML 或原始工具回值；只有用户明确要求技术证据时才在结论后给最少必要原文。

## 生命周期状态

Durable 生命周期按真实阶段选择一行：

```text
任务已接管｜需求讨论中
任务已接管｜正在创建执行清单
任务已接管｜正在启动执行对话
任务已接管｜团队执行中
任务已接管｜正在验证
任务已接管｜正在归档
```

这行必须是该阶段第一条用户可见文本；不能先发准备说明、纠正消息或工具更新。宿主若强制 Skill 使用公告，把公告放在同一条消息的第二行。Discussion 若没有用户明确指定要核对的资料，不读取 source task、历史、memory、项目或 Git，直接基于当前输入问唯一决定性问题。

Direct/Focused 不要求固定接管句、隐藏 marker 或模式标签。宿主要求工具前更新时，用一句自然语言说明目标和第一项项目动作即可。

进度由实际事件驱动：新结果、artifact、验证、失败、阻塞、重要取舍或需要用户决定。没有新信息时不重复状态，不发送虚构百分比。

最终先给结果，再给关键产物、验证范围和残余风险；状态只用 `已验证`、`未验证`、`验证失败`。

## Visualization 价值门

默认使用文字。只有一个视图比短列表或表格更容易理解真实关系时才 visualization，例如复杂依赖、空间布局、多个方案的重复字段对比或当前图片审阅。

以下情况不用 visualization：单一事实、简单状态、普通三步计划、一句确认、缺少真实数据的趋势、没有当前图片的视觉审核。步骤多本身不是使用理由。

确需使用时选择最小 surface：

| 信息关系 | 首选 | 降级 |
|---|---|---|
| 多阶段依赖 | 阶段路径 | Markdown 步骤 |
| 重复字段方案比较 | 表格或选择卡 | 简短对比表 |
| 一项变化影响多个下游 | 影响图 | Mermaid |
| 当前图片/页面审阅 | 图片预览 | 图片链接加编号意见 |
| 有单位、维度和来源的数值 | 图表 | 数据表 |

使用本 Skill 自带 surface 时，从 [assets/visualizations/surface-registry.json](../assets/visualizations/surface-registry.json) 选型，用 `scripts/validate_visualization_data.py` 校验真实 payload，再用 `scripts/render_visualization.py` 生成同源 fallback 和 manifest。不得填演示值、伪造数值或让模型二次抄写 fallback。

图片必须是已打开并确认版本的当前文件；hash 只证明字节绑定，不证明用户已经看到。只有宿主返回绑定当前 thread、surface、文件与 hash 的 mount/readback，才能声称视图已显示；否则直接给文字降级并诚实标为未验证。

视图只帮助理解，不能替代授权、完成证据、验收或外部写入确认。宿主已有更合适的 visualization Skill 时按当前安装版规则使用，不写死缓存路径或版本。

## 选择与人话

只有偏好会改变结果时才提问，一次一个问题，最多三个互斥选项，推荐项在前。

把后台状态翻译成人话：

- 工具失败：这一步没有成功，正在换可验证路径。
- 需要输入：需要你决定一件会改变结果的事。
- 证据绑定：已核对当前产物与验证结果一致。
- worker active：已安排独立处理，主任务继续推进。
- stale/hash mismatch：依据已经变化，需要重新核对。

不要复述对结果无影响的内部否定动作。
