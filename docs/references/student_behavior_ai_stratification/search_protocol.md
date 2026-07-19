# STRATA 学生行为与动态分层证据库检索协议

> 检索日期：2026-07-18  
> 用途：支持平台研究设计、变量定义和后续正式系统检索。  
> 当前性质：设计导向的范围性证据库，不是已完成 PRISMA 双人筛选的系统综述。

## 1. 检索问题

检索围绕以下设计问题展开：

1. 数字学习轨迹能够为学习投入、自我调节和协作提供什么证据，效度边界是什么？
2. 形成性评价、分析性量规、自评、互评和反馈应如何设计与验证？
3. 学习分析和机器学习如何预测未来掌握、支持需要和成长，同时控制教学机会、嵌套结构和标签泄漏？
4. 动态分组、差异化教学和自适应支架有哪些可复用证据？
5. 教师在环、人本设计、算法公平、隐私和审计需要哪些治理机制？

## 2. 数据源与路由

- 发现：OpenAlex，覆盖 Crossref、期刊、会议和机构仓储元数据。
- DOI 核验：Crossref `/works/{doi}`，核对标题、发表年、来源和文献类型。
- 开放全文：仅使用 OpenAlex `best_oa_location` 或其他标记为开放获取的合法位置。
- 引文导出：Crossref 元数据生成 BibTeX 和 RIS。

正式投稿前建议在学校或合作机构可访问的 Scopus、Web of Science、ERIC 和 PsycINFO 中按同一概念块执行补充检索，并由两名研究者独立筛选。

## 3. 概念块与示例检索式

| 概念块 | 示例关键词 |
| --- | --- |
| 学习投入 | `student engagement AND (learning analytics OR educational technology)` |
| 自我调节与轨迹 | `self-regulated learning AND (trace data OR temporal OR multimodal OR learning analytics)` |
| 测量效度 | `(trace data OR log data) AND validity AND learning` |
| 形成性评价 | `formative assessment AND (rubric OR feedback OR peer assessment OR AI)` |
| 预测分析 | `predictive learning analytics AND (student performance OR risk OR calibration)` |
| 差异化与分组 | `(differentiated instruction OR adaptive scaffolding OR algorithmic grouping) AND education` |
| 人机协同 | `(human-in-the-loop OR hybrid intelligence OR human-centred) AND learning analytics` |
| 公平治理 | `(algorithmic fairness OR audit OR ethics) AND (education OR learning analytics)` |

2026 年更新额外使用了：

- `self-regulated learning analytics trace data student`
- `predictive learning analytics student performance calibration fairness`
- `adaptive differentiated instruction artificial intelligence secondary school`
- `human-centred learning analytics teacher AI`

## 4. 纳入与排除

纳入条件：

- 与至少一个检索问题直接相关的实证研究、系统/范围综述、元分析或高相关方法框架。
- 教育或学习场景明确，能够支持变量、测量、模型、干预或治理设计。
- DOI 可由 Crossref 核验；经典基础文献可早于近五年窗口。
- 近年补充优先 2022-2026 年，另保留 2021 年高相关研究以连接五年前证据。

排除条件：

- 只泛谈 AI、机器学习或数字化教育，不能映射到本项目设计决策。
- 仅依据学习风格等争议性固定类型进行个性化，且缺少可验证学习结果。
- DOI/标题/来源无法核验，或只有非正规全文来源。
- 与教育无关、仅使用相似关键词的医学、商业、工程预测研究。

## 5. 当前结果

- 唯一 DOI：105。
- 2021-2026 年：72 篇。
- 当前日期向前五个完整发表年度 2022-2026：63 篇。
- 合法开放全文并通过 `%PDF` 文件签名验证：47 篇。
- 仅元数据：58 篇。
- BibTeX：105 条；RIS：105 条。

稳定编号和主题映射见 `papers_manifest.csv`，全文状态和合法来源见 `oa_download_report.csv`。

## 6. 证据使用规则

- 文献支持的是设计原则和待检验假设，不自动证明 STRATA 的量规、模型或干预有效。
- 只有元数据的文献在阅读全文前不用于转述精确效应、样本和统计结果。
- 预测性能证据不能替代干预效果证据；相关行为不能解释为因果机制。
- 高等教育证据迁移到中学场景时必须明确人群边界，并通过本地前瞻性研究验证。
- 正式系统综述需保存完整数据库检索式、命中数、去重记录、双人筛选、排除理由和流程图。
