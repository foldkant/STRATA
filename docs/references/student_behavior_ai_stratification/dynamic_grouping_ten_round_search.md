# 学生动态分组十轮检索记录

> 日期：2026-07-20  
> 用途：支持 STRATA 课堂和项目动态分组设计。  
> 性质：设计导向补充检索，不是 PRISMA 系统综述，不改变现有 105 篇正式证据库数量。

## 1. 检索方法

- OpenAlex 用于候选发现。
- Crossref 用于核验报告中新增候选的 DOI、题名、期刊和年份。
- 优先选择 K-12、协作学习、计算机支持协作学习、算法分组和共享调节研究。
- 高等教育和通用团队研究不直接外推到中学课堂。
- 医疗、纯优化算法、生成式 AI 和与教育无关的团队研究已排除。
- 元数据候选在全文双人复核前不引用具体样本、效应量或显著性结果。

## 2. 十轮检索问题

| 轮次 | 问题 | 主要检索式 |
| --- | --- | --- |
| DG-R1 | 分组前是否必须定义协作任务 | `cooperative learning group formation systematic review classroom education` |
| DG-R2 | 同层与异层组何时适用 | `homogeneous heterogeneous ability grouping collaborative learning students` |
| DG-R3 | 分组应使用哪些多维证据 | `dynamic group formation learning analytics classroom collaborative learning` |
| DG-R4 | 人数、角色和协作脚本如何设计 | `collaborative learning role assignment scripts shared regulation systematic review` |
| DG-R5 | 多久换组以及如何保护稳定性 | `group stability regrouping repeated collaboration classroom students` |
| DG-R6 | 算法应使用聚类、机器学习还是约束优化 | `algorithmic group formation constraints fairness education collaborative learning` |
| DG-R7 | 如何避免身份、机会和公平伤害 | `ability grouping collaborative learning equity student perspectives` |
| DG-R8 | 如何区分小组产出和个人贡献 | `collaborative learning analytics individual contribution group assessment` |
| DG-R9 | 教师如何确认并在课堂执行 | `teacher decision making group formation learning analytics classroom` |
| DG-R10 | 如何比较动态分组教学效果 | `group composition randomized experiment education peer effects interference classroom` |

## 3. 新增候选

| DOI | 用途 | 状态 |
| --- | --- | --- |
| `10.1007/s11528-022-00823-9` | 协作/合作学习历史与设计 | Crossref 已核验，全文待复核 |
| `10.1007/s11423-019-09729-5` | 协作认知负荷 | Crossref 已核验，全文待复核 |
| `10.1111/ssm.12427` | 同质与异质合作组比较 | Crossref 已核验，全文待复核 |
| `10.1109/access.2021.3120557` | 动态分组工程方案 | Crossref 已核验，不能单独证明教学效果 |
| `10.1016/j.lcsi.2021.100539` | 学生角色配置 | Crossref 已核验，全文待复核 |
| `10.3389/feduc.2020.00111` | 协作中的动机和情绪调节 | Crossref 已核验，全文待复核 |
| `10.1007/s11412-023-09386-0` | 自动小组分析和反馈 | Crossref 已核验，全文待复核 |
| `10.1111/bjet.12917` | 学习科学与机器学习桥接 | Crossref 已核验，全文待复核 |
| `10.17275/per.22.97.9.4` | 合作学习元分析候选 | Crossref 已核验，全文待复核 |

Lechuga & Doroudi (`10.1007/s40593-022-00309-y`)、Liang et al. (`10.1080/10494820.2022.2121730`) 和 Vallès-Català & Palau (`10.1371/journal.pone.0280604`) 已在现有目录或前轮候选中，因此未重复生成元数据。

候选 RIS 文件保存在[动态分层与分组候选文献目录](metadata/dynamic_stratification_candidates/README.md)。

## 4. 证据限制

- 合作学习总体有效不代表任何自动分组策略有效。
- 算法可以生成分组不代表生成的组具有教学效果。
- 同质/异质结果依赖任务、年龄、学科、支架和持续时间。
- 组内学生相互影响，不能把个人观测当作完全独立。
- 正式论文前仍需 ERIC、PsycINFO、Scopus 和 Web of Science 的系统检索、双人筛选和质量评价。
