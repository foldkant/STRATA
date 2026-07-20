# 动态分层五轮补充检索记录

> 检索日期：2026-07-20  
> 用途：补充核查 STRATA 动态内容分层、层级迁移和实证研究设计。  
> 性质：设计导向的补充检索，不是 PRISMA 系统综述，也不改变现有 105 篇正式证据库的数量。

候选文献的参考文献管理文件保存在[动态分层候选 RIS 目录](metadata/dynamic_stratification_candidates/README.md)。

## 1. 数据源与方法

- 先复核现有 105 篇证据库、47 篇已验证开放全文和现有 30 轮设计报告。
- 补充发现使用 OpenAlex，优先 2020-2026 年的系统综述、元分析、K-12 实证研究和方法论文。
- 2026-07-20 通过 Crossref REST API 逐条核验关键候选的 DOI、题名、期刊和出版年份；OpenAlex 引用次数仅用于发现，不作为证据质量判断。
- 以 DOI 去重；与医学等非教育领域有关的方法论文只用于随机试验或序贯设计方法，不用于推断教育效果。
- 新发现且尚未纳入正式证据库的论文只作为候选。正式论文引用具体效应、样本和统计结果前，仍需获取全文并由两名研究者复核。

## 2. 五轮检索问题

### 第一轮：测量与跨层可比性

检索式：

- `item response theory anchor items test equating differential item functioning educational assessment`
- `personalized adaptive assessment measurement comparability common items student mastery`

审查问题：不同层级学生完成不同题目后，是否还能直接比较原始得分与完成率；共同题、锚题、IRT、DIF 和题目漂移需要达到什么条件。

### 第二轮：时间过程与层级迁移

检索式：

- `knowledge tracing dynamic student mastery estimation uncertainty calibration education`
- `adaptive learning temporal personalized scaffolding self regulated learning dashboard`
- `longitudinal within person student learning analytics dynamic change`

审查问题：夜间更新是否等于夜间变层；如何区分学生间差异和同一学生自身变化；如何使用不确定性、连续证据、冷却期和滞回规则避免频繁跳层。

### 第三轮：预测与教学效果

检索式：

- `cluster randomized trial adaptive learning personalized instruction school education`
- `stepped wedge cluster randomized education digital learning intervention`
- `sequential multiple assignment randomized trial education adaptive intervention`
- `dynamic treatment regime education personalized learning causal`

审查问题：如何证明动态分层改善学习，而不是只证明模型可以预测；集群随机、阶梯实施、SMART 和观察性历史数据分别能回答什么问题。

### 第四轮：公平、教师预期与学生权益

检索式：

- `ability grouping tracking self fulfilling prophecy student confidence teacher expectations secondary school`
- `algorithmic fairness education learning analytics K-12 human in the loop`
- `human centred learning analytics teacher decision making systematic review`
- `student autonomy adaptive learning analytics personalization`

审查问题：隐性层级能否降低污名化；固定分组、教师预期、自我实现、机会差异、教师负担和学生复核应如何监测。

### 第五轮：外部验证与长期运行

检索式：

- `student performance prediction external validation temporal calibration learning analytics`
- `concept drift student performance prediction education learning analytics`
- `K-12 learning analytics systematic review 2024 challenges`
- `adaptive learning K-12 meta analysis personalized learning outcomes`
- `prediction model reporting external validation calibration artificial intelligence`

审查问题：如何完成时间外、班级外和学校外验证；如何处理概念漂移、解释稳定性、模型校准、跨校适用性和可复现报告。

## 3. 本轮重点补充候选

以下文献已核对题名、年份和 DOI，但未全部取得并复核全文，因此暂不并入正式 R 编号。

| 文献 | DOI | 对本方案的用途 | 当前状态 |
| --- | --- | --- | --- |
| Chen et al. (2025), *Item Response Theory - A Statistical Framework for Educational and Psychological Measurement* | `10.1214/23-STS896` | IRT、测量误差和可比掌握估计 | 元数据候选 |
| Sinharay et al. (2025), *Validation for Personalized Assessments: A Threats-to-Validity Approach* | `10.1111/jedm.12434` | 个性化测量的效度威胁 | 元数据候选 |
| Wang et al. (2024), *The Efficacy of Artificial Intelligence-Enabled Adaptive Learning Systems...: A Meta-Analysis* | `10.1177/07356331241240459` | 自适应系统效果的总体证据边界 | 元数据候选 |
| Lechuga & Doroudi (2023), *Three Algorithms for Grouping Students* | `10.1007/s40593-022-00309-y` | 从个性化系统数据到课堂分组的算法桥接 | Crossref 元数据已核验 |
| Dumont & Ready (2023), *On the promise of personalized learning for educational equity* | `10.1038/s41539-023-00174-x` | 个性化学习与公平的条件 | 元数据候选 |
| Bang et al. (2022), *Efficacy of an Adaptive Game-Based Math Learning App...* | `10.1007/s10643-022-01332-3` | K-12 自适应学习实证候选 | 元数据候选 |
| van der Graaf et al. (2023), *How to design and evaluate personalized scaffolds for self-regulated learning* | `10.1007/s11409-023-09361-y` | 支架个性化和评价设计 | 元数据候选 |
| Francis et al. (2020), *The impact of tracking by attainment on pupil self-confidence over time* | `10.1080/01425692.2020.1763162` | 固定分组、自信与自我实现风险 | 元数据候选 |
| Paolucci et al. (2024), *A review of learning analytics opportunities and challenges for K-12 education* | `10.1016/j.heliyon.2024.e25767` | K-12 学习分析部署边界 | 元数据候选 |
| Raudenbush & Schwartz (2020), *Randomized Experiments in Education, with Implications for Multilevel Causal Inference* | `10.1146/annurev-statistics-031219-041205` | 班级/学校嵌套随机试验 | 元数据候选 |
| Kidwell & Almirall (2023), *Sequential, Multiple Assignment, Randomized Trial Designs* | `10.1001/jama.2022.24324` | 后续自适应干预序列研究方法 | 方法候选，非教育效果证据 |
| Hodgen et al. (2022), *The achievement gap: The impact of between-class attainment grouping on pupil attainment and educational equity over time* | `10.1002/berj.3838` | 固定分组的成绩和公平风险 | Crossref 元数据已核验 |
| Zanellati et al. (2024), *Hybrid Models for Knowledge Tracing: A Systematic Literature Review* | `10.1109/TLT.2023.3348690` | 时序掌握估计的方法范围 | Crossref 元数据已核验 |
| Alfredo et al. (2024), *Human-centred learning analytics and AI in education: A systematic literature review* | `10.1016/j.caeai.2024.100215` | 教师在环与人本设计 | 已纳入现有证据库 R46，开放全文已验证 |
| Jovanovic et al. (2021), *Students matter the most in learning analytics* | `10.1016/j.compedu.2021.104251` | 教学条件与外部适用性 | 已纳入现有证据库 R50，开放全文已验证 |
| Kapoor et al. (2024), *REFORMS: Consensus-based Recommendations for Machine-learning-based Science* | `10.1126/sciadv.adk3452` | 机器学习比较、泄漏与可复现报告 | Crossref 元数据已核验；通用方法证据 |

说明：Lechuga 与 Doroudi 的 DOI 字符串含 2022，但 Crossref 登记的期刊出版年为 2023；记录引用时以期刊元数据为准。候选表不等于正式纳入表，未取得并双人复核全文的候选不引用具体效应量。

## 4. 与现有证据库的主要连接

- 测量与知识追踪：R26-R27、R35、R38、R83、R89-R93。
- 时间过程与支架：R08、R40-R45、R64-R65、R71-R75、R99、R105。
- 差异化教学和算法分组：R19-R23、R63、R66、R69-R70、R82。
- 教师在环、公平和权益：R33-R34、R46-R62、R74、R79、R83-R84、R97-R98、R102-R104。
- 预测验证、泄漏和漂移：R24-R25、R67-R68、R85-R88、R94-R95、R100-R101。

## 5. 检索边界

- OpenAlex 的排序用于发现，不代表证据质量排序。
- 引用次数不作为纳入或模型选择依据。
- 高等教育证据不能直接外推到中学课堂。
- 算法分组研究证明可实施，不等于证明同层、异层或动态内容带一定有效。
- 正式投稿前仍需在 ERIC、PsycINFO、Scopus 和 Web of Science 复检，并保存完整命中数、去重、双人筛选和排除理由。
