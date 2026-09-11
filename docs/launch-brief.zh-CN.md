# DeepSeek-V4.1-Flash 上线首日技术简报

快照时间：2026-09-10（Asia/Shanghai）

## 一句话判断

V4.1-Flash 的核心卖点不是传统意义上的“小模型”，而是针对输入密集型、长时程 Agent 工作负载重新设计的大型 MoE 系统。最值得验证的是它能否在真实服务栈上兑现长上下文 KV 缓存、预填充成本和 Agent 性价比优势。

## 已由官方资料确认

- 原生支持文本与图像输入、文本输出。
- 技术报告描述 552B backbone 参数和 196B Engram 参数；每 token 在 prefill 激活 8B、decode 激活 16B。权重仓库还包含独立的 DSpark 草稿模块。
- 40 层语言网络由 20 层因果编码器和 20 层解码器组成。
- 原生上下文上限标称为 1M tokens。
- 使用 CED、CSA2、跨层 KV/索引复用、FP4 主 KV cache、SWA Bounded Replay、Single-Pass mHC、Engram 和 DSpark。
- 官方称全局 KV cache 为每 token 890 bytes，约为 V4-Flash 的四分之一；持久 KV 占用约为 V4-Flash 的八分之一。
- 预训练语料规模为 45T multimodal tokens。
- Hugging Face 权重仓库标注 MIT License，提供 48 个 safetensors 分片和最小推理实现。

## 容易误读的地方

### “484.6B”不是逻辑参数总量

Hugging Face API 显示的约 484.6B 是 safetensors 的物理 tensor-element 计数。大量 FP4 expert 权重以 I8 打包，每个 I8 承载两个 FP4 值，因此这个字段会少计逻辑参数。按权重形状审计并排除量化 scale 后，仓库约含 763.2B 逻辑权重：约 552.1B backbone、196.9B Engram 和 14.2B DSpark；这与报告的主要口径吻合。48 个分片的索引总大小约 510.3 GB（475.2 GiB）。即使每 token 激活参数较少，权重存储和多机部署仍是主要门槛。

### “Flash”不等于消费级本地模型

这里的 Flash 指向激活规模、预填充和 KV cache 效率，不代表完整权重能放进消费级显卡。部署预算应使用权重索引、逻辑形状、目标量化、冗余副本和推理引擎开销共同估算。

### “1M 上下文”不等于任意端点都支持 1M

模型配置和报告给出 1M 上限，但推理引擎、硬件、服务商限制、视觉 token、超时与计费策略都会改变实际可用长度。必须对每个 model-endpoint pair 单独验证。

### 官方榜单不等于你的 Agent 表现

技术报告明确展示了不同 Agent scaffold 和 reasoning effort 会改变 token 消耗与通过率。在部分实验里，提高 reasoning effort 会显著增加轨迹长度，但准确率并非处处单调提升。迁移评测必须固定 scaffold、工具定义和预算。

## 上线首日仍未验证

- 主流推理框架的生产级兼容性和吞吐。
- 第三方服务商的准确模型版本、上下文上限与定价。
- 1M 上下文下的首 token 延迟、召回稳定性和真实成本。
- FP4 KV 与不同量化/内核组合对质量的影响。
- 官方 benchmark 在独立环境中的可复现程度。
- 中文企业文档、真实代码库和办公自动化任务上的相对优势。

## 当前最快的实测入口

DeepSeek 官方 API 已经上线，OpenAI-compatible model id 为 `deepseek-flash`。官方页面当前列出：1M context、最大 384K 输出、视觉、工具调用、JSON 输出、Responses API 与 Anthropic-compatible API。

上线日峰值价格为每百万 token：cache hit $0.006、cache miss $0.30、output $1.20；非峰时段半价。价格和峰谷时段可能调整，因此公开报告应保存评测时的价格快照，不能只在事后套用当前价格。

Thinking 默认开启。官方托管 API 暴露 `low`、`high`、`max`，而 checkpoint 的 `encoding.py` 还包含不同的内部数值映射与 `xhigh` 标签。对比时必须记录使用的是官方 API 语义还是本地 prompt encoder，不能只写一个含混的 “high”。

## 工具链状态

截至本快照，官方仓库提供的是 TP8 最小推理参考实现，不是完整 serving engine。Transformers、vLLM 与 SGLang 所查主干尚未注册 `deepseek_v41` / `DeepseekV41ForCausalLM`。因此首轮业务评测优先走官方 API；自托管兼容性应作为独立工程轨道，不应把 V4 的支持状态直接套到 V4.1。

官方参考路径约需下载 510.3 GB 权重并转换成 TP8 checkpoint。官方示例使用 8 个 GPU 进程，但这不构成“8×80GB 是最低配置”的官方保证；KV、激活、临时 workspace、转换期内存与源/目标权重共存都需要额外预算。

## 第一批值得公开的实验

1. 同一端点从 32K 递增到 1M 的多位置检索与跨段推理曲线。
2. 固定 Agent scaffold，对 reasoning effort 25/40/60/80/100 做质量、输出 token 和成本曲线。
3. 真实仓库修复任务，公开补丁、测试结果、轨迹和失败类型。
4. 中文表格、合同、财报图表和产品截图的多模态任务。
5. 相同业务样本与当前生产模型进行盲评，而非只对比官方榜单。

## 信息来源

- DeepSeek-AI, *DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache Compression*, 2026-09-10: <https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/2bc89ac599031fa673cab993f1df02fc4a98c673/DeepSeek_V41_Tech_Report.pdf>
- Hugging Face 模型仓库与配置：<https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash>
- Hugging Face 模型元数据 API：<https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4.1-Flash>
- DeepSeek API 模型与价格：<https://api-docs.deepseek.com/quick_start/pricing>
- DeepSeek API Thinking Mode：<https://api-docs.deepseek.com/guides/thinking_mode>

本简报是独立整理，不代表 DeepSeek。文中的“官方称”均应视为待独立复现的厂商声明。
