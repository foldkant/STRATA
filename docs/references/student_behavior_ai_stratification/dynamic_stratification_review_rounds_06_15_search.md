# 动态分层第 6-15 轮检索记录

> 日期：2026-07-20  
> 目的：为第 6-15 轮科学核查补充检索。  
> 说明：这不是 PRISMA 系统综述，不改变现有 105 篇正式证据库的数量。

## 1. 检索与筛选

使用 OpenAlex 进行候选发现，使用 Crossref REST API 核验写入报告的 DOI、题名、期刊和年份。检索结果中的医疗、纯算法、生成式 AI 和高等教育论文，如果不能直接约束中学学习分析设计，只保留为排除记录或方法提醒。

现有 105 篇证据库继续作为主要来源。新增候选在全文双人复核前不引用具体样本量、效应量或显著性结论。

## 2. 十轮问题与检索式

| 轮次 | 核查问题 | 检索式 |
| --- | --- | --- |
| R06 | 行为数据到底测量了什么构念 | `criterion referenced mastery standard setting classification consistency educational assessment`；`learning analytics construct validity behavioral trace engagement proxy education` |
| R07 | 不同版本、不同题目是否可比 | `adaptive assessment common anchor items test equating longitudinal measurement comparability` |
| R08 | IRT/BKT/知识追踪适合承担什么 | `knowledge tracing calibration uncertainty model evaluation student mastery` |
| R09 | 行为代理是否有增量效度 | `learning analytics construct validity behavioral trace engagement proxy education`；`temporally focused analytics self regulated learning systematic review` |
| R10 | 如何区分学生间差异和学生内变化 | `within person longitudinal learning analytics temporal validation repeated measures students` |
| R11 | 什么时候模型应拒绝判断 | `prediction model calibration uncertainty applicability validation education`；`selective prediction abstention uncertainty calibration` |
| R12 | 内容带与课堂分组是否应分开 | `dynamic ability grouping differentiated instruction secondary school equity attainment` |
| R13 | 如何证明分层教学产生效果 | `personalized adaptive learning cluster randomized trial school education intervention`；`adaptive learning randomized controlled trial K-12 personalized instruction` |
| R14 | 教师在环是否会产生自动化偏差 | `teacher decision making predictive learning analytics dashboard secondary school`；`teacher algorithmic advice student assessment artificial intelligence decision making trust` |
| R15 | 如何做时间外、班级外和学校外验证 | `external validation transportability concept drift student performance prediction learning analytics` |

## 3. 本轮写入报告的新增候选

| 编号 | DOI | 主要用途 | 状态 |
| --- | --- | --- | --- |
| C1 | `10.1080/10705511.2023.2191292` | 测量不变性分级审查 | Crossref 已核验，全文待复核 |
| C2 | `10.1146/annurev-statistics-042720-104044` | 教育测量方法边界 | Crossref 已核验，全文待复核 |
| C3 | `10.1109/TLT.2020.2999970` | 学习分析构念操作化 | Crossref 已核验，全文待复核 |
| C4 | `10.1016/j.intell.2022.101688` | DIF 与时间链接 | Crossref 已核验，全文待复核 |
| C5 | `10.1080/02671522.2020.1836517` | 中学成就分组实施 | Crossref 已核验，全文待复核 |
| C6 | `10.1002/berj.3802` | 学生对能力分组的理解 | Crossref 已核验，全文待复核 |
| C7 | `10.1093/jopart/muac007` | 自动化偏差方法提醒 | Crossref 已核验；非教育效果证据 |

候选 RIS 文件和前五轮候选合并保存在[动态分层候选文献目录](metadata/dynamic_stratification_candidates/README.md)。

## 4. 证据使用限制

- OpenAlex 排序和引用次数不代表证据质量。
- Crossref 核验只能确认出版元数据，不能代替全文阅读。
- 教育测量方法不能直接证明动态分层提高成绩。
- 其他国家、其他学段和高等教育证据不能直接外推到小榄中学。
- 正式 SCI 写作前仍需在 ERIC、PsycINFO、Scopus 和 Web of Science 执行可复现检索、双人筛选和质量评价。
