(() => {
  "use strict";

  const benchmarkSection = document.querySelector("#benchmark");
  const benchmarkButtons = Array.from(
    benchmarkSection ? benchmarkSection.querySelectorAll("[data-filter]") : []
  );
  const benchmarkRows = Array.from(
    benchmarkSection ? benchmarkSection.querySelectorAll(".benchmark-table tbody tr") : []
  );
  const benchmarkCount = document.querySelector("#benchmark-count");
  const form = document.querySelector("#migration-form");
  const serviceSelect = document.querySelector("#service");
  const serviceLinks = Array.from(document.querySelectorAll("[data-service]"));
  const painInput = document.querySelector("#pain");
  const painCount = document.querySelector("#pain-count");
  const usecaseError = document.querySelector("#usecase-error");
  const usecaseFieldset = document.querySelector("#usecase-fieldset");
  const briefResult = document.querySelector("#brief-result");
  const briefOutput = document.querySelector("#brief-output");
  const copyButton = document.querySelector("#copy-brief");
  const copyStatus = document.querySelector("#copy-status");
  const year = document.querySelector("#current-year");

  if (year) {
    year.textContent = String(new Date().getFullYear());
  }

  benchmarkButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const selectedFilter = button.dataset.filter;

      benchmarkButtons.forEach((candidate) => {
        candidate.setAttribute("aria-pressed", String(candidate === button));
      });

      let visibleRows = 0;
      benchmarkRows.forEach((row) => {
        const isVisible = selectedFilter === "all" || row.dataset.category === selectedFilter;
        row.hidden = !isVisible;
        if (isVisible) visibleRows += 1;
      });

      if (benchmarkCount) {
        benchmarkCount.textContent = `显示 ${visibleRows} / ${benchmarkRows.length} 项`;
      }
    });
  });

  serviceLinks.forEach((link) => {
    link.addEventListener("click", () => {
      if (serviceSelect) serviceSelect.value = link.dataset.service || "";
    });
  });

  if (!form || !painInput || !briefResult || !briefOutput || !copyButton) return;

  const selectedValues = (name) =>
    Array.from(form.querySelectorAll(`input[name="${name}"]:checked`)).map((input) => input.value);

  const selectedValue = (name) => {
    const control = form.elements.namedItem(name);
    if (control instanceof RadioNodeList) return control.value;
    return control ? control.value : "";
  };

  const testRecipes = {
    "代码与仓库任务": "选取 20—30 个有现成回归测试的真实 issue；记录补丁、测试通过率、轮次与人工介入。",
    "长文档与检索": "按 32K、128K、256K 与目标上限分桶；同时测试信息召回、跨段推理与干扰项鲁棒性。",
    "图像、截图与表格": "固定原图与缩放策略；逐字段核对中文 OCR、表格关系和多图引用，保留视觉输入。",
    "工具调用与 Agent": "首轮仅测动作意图、只读边界与 JSON 合规；真实调用、失败恢复和完整轨迹需另建隔离执行评测。",
    "通用对话与写作": "构建匿名化盲测对；由至少两名评审按任务 rubric 独立评分并记录分歧。",
    "结构化抽取": "固定 JSON Schema 与字段判定；分别统计解析成功率、字段准确率和幻觉字段率。"
  };

  const serviceScopes = {
    "模型迁移体检 · ¥9,800": [
      "最多 50 条脱敏业务样本，比较当前基线与 V4.1-Flash 两个 model-endpoint pair。",
      "材料、门槛和 API 额度齐备后 3 个工作日交付。",
      "包含原始 JSONL、汇总报告、迁移 / 路由 / 暂缓建议和 60 分钟线上复盘。"
    ],
    "企业迁移试点 · ¥39,800 起": [
      "最多 200 条脱敏样本，可增加定制评分规则和多个业务轨道。",
      "包含质量、延迟、token 用量与成本估算门槛，以及影子流量、任务路由和回退计划。",
      "不包含生产环境变更、私有化部署、第三方 API / GPU 和差旅费用。"
    ],
    "持续回归监控 · ¥6,800 / 月起": [
      "固定最多 100 条回归样本，默认覆盖两个 model-endpoint pair。",
      "每月最多两次约定运行，交付变化摘要、失败样本和可比性检查。",
      "新增数据轨道、实时告警和生产系统集成另行确认范围。"
    ],
    "只使用公开评测基线": [
      "自行运行 3 条 smoke 与 12 条中文业务合成样本。",
      "包含开源 CLI、评分器、结果 Schema 和方法文档。",
      "不包含业务数据定制、人工复核或迁移结论。"
    ]
  };

  const buildBrief = () => {
    const service = selectedValue("service");
    const project = selectedValue("project").trim() || "未命名项目";
    const baseline = selectedValue("baseline");
    const volume = selectedValue("volume");
    const context = selectedValue("context");
    const deployment = selectedValue("deployment");
    const usecases = selectedValues("usecase");
    const metrics = selectedValues("metric");
    const pain = selectedValue("pain").trim() || "未填写";
    const decisionMetrics = metrics.length
      ? metrics
      : ["任务质量", "token 用量与单位任务成本估算", "长任务稳定性"];
    const serviceScope = serviceScopes[service] || [];
    const generatedAt = new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(new Date());

    const recipes = usecases.map((usecase, index) => `${index + 1}. ${usecase}：${testRecipes[usecase]}`);
    const deploymentCheck = deployment.includes("本地") || deployment.includes("私有云")
      ? "部署前置：先验证目标硬件与推理框架能否加载，并记录显存、首 token 延迟、吞吐和 30 分钟稳定性；不要先承诺生产容量。"
      : "服务前置：官方 deepseek-flash API 可用于首轮实测；仍需保存端点版本、区域、限流、运行时价格与数据条款，并保留当前基线作为回退。";
    const longContextCheck = context.includes("128K") || context.includes("波动")
      ? "长上下文门槛：配置字段为 1,048,576，但参考实现默认 4K、交互模式覆盖为 64K；必须用目标框架逐级验证，不把标称长度视为可用长度。"
      : "上下文门槛：先覆盖当前典型长度，再用更长输入做压力测试；分别报告质量与延迟。";

    return [
      "# V41 FlashLab 采购与迁移评估简报",
      "",
      `生成时间：${generatedAt}`,
      `项目代号：${project}`,
      "",
      "## 拟采购方案",
      `- 服务方案：${service}`,
      ...serviceScope.map((item) => `- ${item}`),
      "- 所选价格为页面标价；适用范围、税费、排期、API 费用和付款节点以双方书面确认单为准。",
      "",
      "## 业务约束",
      `- 当前基线：${baseline}`,
      `- 每日请求量：${volume}`,
      `- 典型输入：${context}`,
      `- 部署约束：${deployment}`,
      `- 决策指标：${decisionMetrics.join("、")}`,
      `- 当前问题：${pain}`,
      "",
      "## 首轮对照实验",
      ...recipes,
      "",
      "## 必做前置检查",
      `- ${deploymentCheck}`,
      `- ${longContextCheck}`,
      "- 固定模型提交版本、推理参数、依赖、硬件与随机种子。",
      "- 同预算运行当前基线；保存输入、完整输出、每次 attempt、错误和评分明细。",
      "- 结果至少重复两次；失败与超时样例不得从汇总中删除。",
      "- 客户提供脱敏样本、合法可用的端点与 API 额度，并确认数据处理边界。",
      "",
      "## 建议决策门槛",
      ...decisionMetrics.map((metric) => `- ${metric}：在测试前写出可量化阈值，并由业务负责人确认。`),
      "- 只有关键门槛全部通过且回退路径演练成功，才进入小流量试点。",
      "",
      "## 证据边界",
      "- 官方报告披露 552B backbone 与 196B Engram，并给出约 8B 预填充 / 16B 解码激活参数口径。",
      "- 对 checkpoint 文件的独立审计约为 763.2B 逻辑权重（含 Engram 与 DSpark）；HF API 的 484.6B 是量化存储元素计数，不能直接当参数量。",
      "- 官方配置还披露 FP8 / 专家 FP4、1,048,576 最大位置配置和视觉编码器。",
      "- 参考推理实现默认 4K、交互模式 64K；接入时还需显式核对 pad token 配置。",
      "- 上述字段不是质量、速度、实际账单成本或可部署性的独立证明。",
      "- 成本仅依据约定价目和记录到的 token 用量估算；缓存计费、失败请求和供应商账单差异必须另行披露。",
      "- V41 FlashLab 为独立评测服务，与 DeepSeek 无隶属或背书关系。",
      "- 本简报由浏览器本地生成，未提交或保存表单内容。"
    ].join("\n");
  };

  const validateUsecases = () => {
    const valid = selectedValues("usecase").length > 0;
    usecaseError.textContent = valid ? "" : "请至少选择一个优先验证场景。";
    usecaseFieldset.setAttribute("aria-invalid", String(!valid));
    return valid;
  };

  form.querySelectorAll('input[name="usecase"]').forEach((input) => {
    input.addEventListener("change", validateUsecases);
  });

  painInput.addEventListener("input", () => {
    painCount.textContent = String(painInput.value.length);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    copyStatus.textContent = "";

    const usecasesValid = validateUsecases();
    const controlsValid = form.checkValidity();

    if (!controlsValid) form.reportValidity();
    if (!usecasesValid) {
      form.querySelector('input[name="usecase"]').focus();
    }
    if (!controlsValid || !usecasesValid) return;

    briefOutput.textContent = buildBrief();
    briefResult.hidden = false;
    briefResult.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "nearest"
    });
  });

  form.addEventListener("reset", () => {
    window.requestAnimationFrame(() => {
      painCount.textContent = "0";
      usecaseError.textContent = "";
      usecaseFieldset.setAttribute("aria-invalid", "false");
      briefOutput.textContent = "";
      copyStatus.textContent = "";
      briefResult.hidden = true;
    });
  });

  const fallbackCopy = (text) => {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.setAttribute("readonly", "");
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    document.body.appendChild(textArea);
    textArea.select();
    const copied = document.execCommand("copy");
    textArea.remove();
    return copied;
  };

  copyButton.addEventListener("click", async () => {
    const brief = briefOutput.textContent;
    if (!brief) return;

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(brief);
      } else if (!fallbackCopy(brief)) {
        throw new Error("copy failed");
      }
      copyStatus.textContent = "已复制到剪贴板。";
      copyButton.textContent = "已复制";
      window.setTimeout(() => {
        copyButton.textContent = "复制简报";
      }, 1800);
    } catch {
      copyStatus.textContent = "自动复制失败，请在上方简报中全选复制。";
      briefOutput.focus();
    }
  });
})();
