# 学生行为分析与 AI 动态分层文献目录

本目录服务于 [STRATA 学生行为分析、过程性评价与 AI 隐性动态分层设计报告](../../student_behavior_ai_stratification_design.md)。检索日期为 2026-07-18，元数据通过 OpenAlex 发现并由 Crossref DOI 记录核验。当前共收录 105 篇，其中 72 篇发表于 2021-2026 年；按当前日期向前五个完整发表年度 2022-2026 计算为 63 篇。第 16-30 轮新增 23 篇，重点补充测量公平、预测泄漏与偏倚、外部验证、AI 题目效度、解释稳定性、因果识别、概念漂移、K-12 仪表板、教师数据素养、隐私与学生自主性。文献库用于设计与验证规划，不构成已完成的系统综述。

## 文件说明

- `papers/`：可合法公开获取且已通过 `%PDF` 文件签名验证的全文，共 47 篇。
- `references.bib`：105 条合并 BibTeX 记录。
- `references.ris`：105 条合并 RIS 记录，可导入 EndNote、Zotero 等。
- `metadata/individual/`：Crossref 为每个 DOI 生成的独立 BibTeX/RIS 记录。
- `papers_manifest.csv`：稳定文献编号、引用键、DOI 和主题。
- `oa_download_report.csv`：OpenAlex 开放获取状态、下载结果、来源 URL 和失败原因。
- `refs.txt`：可重复执行的 DOI 输入清单。
- `refs_recent_2021_2025.txt`：本轮新增近五年文献的 DOI 输入清单。
- `refs_2026.txt`：2026 年新增且经 Crossref 核验的 DOI 输入清单。
- `refs_rounds_16_30.txt`：第 16-30 轮科学审查新增 23 篇文献的 DOI 输入清单。
- `refs_evaluation_stratification_grouping_rounds_11_30.txt`：评价、状态/模型训练与分组新增反证的 62 条唯一 DOI 补充清单；独立于原 105 条主库计数。
- `evaluation_stratification_grouping_rounds_11_30_search.md`：本轮研究问题、概念块、检索回退、纳入排除、核心来源和正式系统检索缺口记录。
- `download_open_access_papers.ps1`：只下载 OpenAlex 标记为开放获取的 PDF，并验证文件签名。
- `search_protocol.md`：检索问题、概念块、纳入排除标准、当前计数和证据使用边界。

`metadata_only` 表示已核验元数据，但当前没有合法直链、开放页面拒绝自动下载或出版社只返回 HTML。它不表示论文不存在，也不表示可从非正规来源下载。开放获取状态以后可能变化，可重新运行脚本。

## 核心文献

| 编号 | 文献与 DOI | 在方案中的作用 | 本地全文 |
| --- | --- | --- | --- |
| R01 | Fredricks et al. (2004), *School Engagement: Potential of the Concept, State of the Evidence*. `10.3102/00346543074001059` | 行为、情感、认知投入框架 | 元数据 |
| R02 | Henrie et al. (2015), *Measuring student engagement in technology-mediated learning: A review*. `10.1016/j.compedu.2015.09.005` | 技术环境投入测量边界 | 元数据 |
| R03 | Bond et al. (2020), *Mapping research in student engagement and educational technology in higher education*. `10.1186/s41239-019-0176-8` | 投入指标证据图谱 | [PDF](papers/03_Bond2020.pdf) |
| R04 | Dixson (2015), *Measuring Student Engagement in the Online Course: The Online Student Engagement Scale*. `10.24059/olj.v19i4.561` | 自报告投入量表参照 | [PDF](papers/04_Dixson2015.pdf) |
| R05 | Panadero (2017), *A Review of Self-regulated Learning: Six Models and Four Directions for Research*. `10.3389/fpsyg.2017.00422` | 自我调节学习构念 | [PDF](papers/05_Panadero2017.pdf) |
| R06 | Wong et al. (2018), *Supporting Self-Regulated Learning in Online Learning Environments and MOOCs*. `10.1080/10447318.2018.1543084` | 在线 SRL 支持综述 | 元数据 |
| R07 | Cerezo et al. (2019), *Process mining for self-regulated learning assessment in e-learning*. `10.1007/s12528-019-09225-y` | 用行为序列识别 SRL | [PDF](papers/07_Cerezo2019.pdf) |
| R08 | Saint et al. (2022), *Temporally-focused analytics of self-regulated learning*. `10.1016/j.caeai.2022.100060` | SRL 时间过程分析 | 元数据 |
| R09 | Gašević et al. (2016), *Learning analytics should not promote one size fits all*. `10.1016/j.iheduc.2015.10.002` | 教学情境对预测的影响 | [PDF](papers/09_Gasevic2016.pdf) |
| R10 | Sedrakyan et al. (2020), *Linking learning behavior analytics and learning science concepts*. `10.1016/j.chb.2018.05.004` | 行为数据与学习科学连接 | 元数据 |
| R11 | Chi & Wylie (2014), *The ICAP Framework*. `10.1080/00461520.2014.965823` | 认知投入活动层级 | 元数据 |
| R12 | Black & Wiliam (1998), *Assessment and Classroom Learning*. `10.1080/0969595980050102` | 形成性评价基础 | 元数据 |
| R13 | Shute (2008), *Focus on Formative Feedback*. `10.3102/0034654307313795` | 反馈设计原则 | 元数据 |
| R14 | Jonsson & Svingby (2007), *The use of scoring rubrics*. `10.1016/j.edurev.2007.05.002` | 评价标准信效度综述 | 元数据 |
| R15 | Panadero & Jonsson (2013), *The use of scoring rubrics for formative assessment purposes revisited*. `10.1016/j.edurev.2013.01.002` | 评价标准用于形成性评价 | 元数据 |
| R16 | Panadero et al. (2023), *Effects of Rubrics on Academic Performance, Self-Regulated Learning, and Self-Efficacy*. `10.1007/s10648-023-09823-4` | 评价标准效果元分析 | [PDF](papers/16_PanaderoEtAl2023.pdf) |
| R17 | Double et al. (2019), *The Impact of Peer Assessment on Academic Performance*. `10.1007/s10648-019-09510-3` | 互评效果元分析 | [PDF](papers/17_Double2019.pdf) |
| R18 | Wisniewski et al. (2020), *The Power of Feedback Revisited*. `10.3389/fpsyg.2019.03087` | 教育反馈元分析 | [PDF](papers/18_Wisniewski2020.pdf) |
| R19 | Deunk et al. (2018), *Effective differentiation Practices*. `10.1016/j.edurev.2018.02.002` | 差异化教学认知效果 | 元数据 |
| R20 | Smale-Jacobse et al. (2019), *Differentiated Instruction in Secondary Education*. `10.3389/fpsyg.2019.02366` | 中学差异化教学证据 | [PDF](papers/20_SmaleJacobse2019.pdf) |
| R21 | Kulik & Fletcher (2016), *Effectiveness of Intelligent Tutoring Systems*. `10.3102/0034654315581420` | 智能辅导效果元分析 | 元数据 |
| R22 | Kim et al. (2017), *Effectiveness of Computer-Based Scaffolding in Problem-Based Learning*. `10.1007/s10648-017-9419-1` | 计算机支架元分析 | [PDF](papers/22_KimBellandWalker2017.pdf) |
| R23 | Létourneau et al. (2025), *AI-driven intelligent tutoring systems in K-12 education*. `10.1038/s41539-025-00320-7` | K-12 智能辅导新综述 | [PDF](papers/23_Letourneau2025.pdf) |
| R24 | Alyahyan & Düştegör (2020), *Predicting academic success in higher education*. `10.1186/s41239-020-0177-7` | 预测建模最佳实践 | [PDF](papers/24_AlyahyanDustegor2020.pdf) |
| R25 | Romero & Ventura (2020), *Educational data mining and learning analytics: An updated survey*. `10.1002/widm.1355` | EDM/LA 方法综述 | [PDF](papers/25_RomeroVentura2020.pdf) |
| R26 | Abdelrahman et al. (2023), *Knowledge Tracing: A Survey*. `10.1145/3569576` | 知识追踪方法谱系 | 元数据 |
| R27 | Corbett & Anderson (1995), *Knowledge tracing: Modeling the acquisition of procedural knowledge*. `10.1007/BF01099821` | Bayesian Knowledge Tracing 基础 | 元数据 |
| R28 | Ifenthaler & Yau (2020), *Utilising learning analytics to support study success*. `10.1007/s11423-020-09788-z` | 学习分析干预综述 | [PDF](papers/28_IfenthalerYau2020.pdf) |
| R29 | Araka et al. (2020), *Measurement and intervention tools for self-regulated learning*. `10.1186/s41039-020-00129-5` | SRL 测量与干预工具 | [PDF](papers/29_Araka2020.pdf) |
| R30 | Heikkinen et al. (2022), *Supporting self-regulated learning with learning analytics interventions*. `10.1007/s10639-022-11281-4` | LA 支持 SRL 综述 | [PDF](papers/30_Heikkinen2022.pdf) |
| R31 | Barredo Arrieta et al. (2020), *Explainable Artificial Intelligence*. `10.1016/j.inffus.2019.12.012` | XAI 分类与责任边界 | [PDF](papers/31_BarredoArrieta2020.pdf) |
| R32 | Lundberg et al. (2020), *From local explanations to global understanding with explainable AI for trees*. `10.1038/s42256-019-0138-9` | 树模型 SHAP 解释 | 元数据 |
| R33 | Nguyen et al. (2022), *Ethical principles for artificial intelligence in education*. `10.1007/s10639-022-11316-w` | 教育 AI 伦理原则 | [PDF](papers/33_Nguyen2022.pdf) |
| R34 | Buckingham Shum et al. (2019), *Human-Centred Learning Analytics*. `10.18608/jla.2019.62.1` | 人本、教师在环设计 | [PDF](papers/34_BuckinghamShum2019.pdf) |
| R35 | Siddiq et al. (2016), *Assessment instruments for primary and secondary school students' ICT literacy*. `10.1016/j.edurev.2016.05.002` | ICT 素养测量综述 | 元数据 |
| R36 | Polit et al. (2007), *The content validity index*. `10.1002/nur.20147` | 内容效度指数方法 | 元数据 |
| R37 | McNeish (2018), *Thanks coefficient alpha, we'll take it from here*. `10.1037/met0000144` | 反思仅使用 alpha | 元数据 |
| R38 | Putnick & Bornstein (2016), *Measurement invariance conventions and reporting*. `10.1016/j.dr.2016.06.004` | 跨群体测量不变性 | 元数据 |
| R39 | Koo & Li (2016), *Selecting and Reporting Intraclass Correlation Coefficients*. `10.1016/j.jcm.2016.02.012` | 评分者一致性报告 | 元数据 |
| R40 | Lim et al. (2023), *Effects of real-time analytics-based personalized scaffolds on students' self-regulated learning*. `10.1016/j.chb.2022.107547` | 实时分析支架与 SRL 干预设计 | [PDF](papers/40_Lim2022.pdf) |
| R41 | Molenaar et al. (2023), *Measuring self-regulated learning and the role of AI: Five years of research using multimodal multichannel data*. `10.1016/j.chb.2022.107540` | 多通道 SRL 测量及 AI 边界 | 元数据 |
| R42 | Fan et al. (2022), *Towards investigating the validity of measurement of self-regulated learning based on trace data*. `10.1007/s11409-022-09291-1` | 行为轨迹作为 SRL 测量证据的效度检验 | [PDF](papers/42_Fan2022TraceValidity.pdf) |
| R43 | Giannakos & Cukurova (2023), *The role of learning theory in multimodal learning analytics*. `10.1111/bjet.13320` | 多模态分析与学习理论对齐 | 元数据 |
| R44 | Ouhaichi et al. (2023), *Research trends in multimodal learning analytics: A systematic mapping study*. `10.1016/j.caeai.2023.100136` | 多模态学习分析证据版图与研究缺口 | 元数据 |
| R45 | Worsley et al. (2021), *A New Era in Multimodal Learning Analytics: Twelve Core Commitments to Ground and Grow MMLA*. `10.18608/jla.2021.7361` | 多模态数据采集、推断和反馈治理原则 | [PDF](papers/45_Worsley2021.pdf) |
| R46 | Alfredo et al. (2024), *Human-centred learning analytics and AI in education: A systematic literature review*. `10.1016/j.caeai.2024.100215` | 人本学习分析、教师在环和界面需求 | [PDF](papers/46_Alfredo2024.pdf) |
| R47 | Paulsen & Lindsay (2024), *Learning analytics dashboards are increasingly becoming about learning and not just analytics - A systematic review*. `10.1007/s10639-023-12401-4` | 教师仪表板从展示数据转向支持行动 | [PDF](papers/47_PaulsenLindsay2024.pdf) |
| R48 | Susnjak et al. (2022), *Learning analytics dashboard: a tool for providing actionable insights to learners*. `10.1186/s41239-021-00313-7` | 可行动洞察和仪表板评价框架 | [PDF](papers/48_Susnjak2022.pdf) |
| R49 | Silvola et al. (2021), *Expectations for supporting student engagement with learning analytics: An academic path perspective*. `10.1016/j.compedu.2021.104192` | 学习分析支持投入的利益相关者需求 | 元数据 |
| R50 | Jovanovic et al. (2021), *Students matter the most in learning analytics: The effects of internal and instructional conditions in predicting academic success*. `10.1016/j.compedu.2021.104251` | 在预测中显式控制教学条件和学生差异 | [PDF](papers/50_Jovanovic2021.pdf) |
| R51 | Darvishi et al. (2024), *Impact of AI assistance on student agency*. `10.1016/j.compedu.2023.104967` | AI 辅助对学生能动性的影响与边界 | [PDF](papers/51_Darvishi2023Agency.pdf) |
| R52 | Cavalcanti et al. (2021), *Automatic feedback in online learning environments: A systematic literature review*. `10.1016/j.caeai.2021.100027` | 自动反馈类型、证据及设计限制 | 元数据 |
| R53 | Darvishi et al. (2022), *Incorporating AI and learning analytics to build trustworthy peer assessment systems*. `10.1111/bjet.13233` | 可信互评、异常评价和 AI 支持 | 元数据 |
| R54 | Hopfenbeck et al. (2023), *Challenges and opportunities for classroom-based formative assessment and AI*. `10.3389/feduc.2023.1270700` | 课堂形成性评价与 AI 的机会和风险 | [PDF](papers/54_Hopfenbeck2023.pdf) |
| R55 | Topping et al. (2025), *Enhancing peer assessment with artificial intelligence*. `10.1186/s41239-024-00501-1` | AI 支持互评的近期证据与风险 | [PDF](papers/55_Topping2025.pdf) |
| R56 | Holmes et al. (2022), *Ethics of AI in Education: Towards a Community-Wide Framework*. `10.1007/s40593-021-00239-1` | 教育 AI 伦理框架 | [PDF](papers/56_Holmes2021.pdf) |
| R57 | Akgun & Greenhow (2021), *Artificial intelligence in education: Addressing ethical challenges in K-12 settings*. `10.1007/s43681-021-00096-7` | K-12 场景的隐私、公平与责任 | 元数据 |
| R58 | Kizilcec & Lee (2022), *Algorithmic fairness in education*. `10.4324/9780429329067-10` | 教育算法公平的概念和评价边界 | 元数据 |
| R59 | Jiang & Pardos (2021), *Towards Equity and Algorithmic Fairness in Student Grade Prediction*. `10.1145/3461702.3462623` | 成绩预测中的群体公平审计 | 元数据 |
| R60 | Simbeck (2023), *They shall be fair, transparent, and robust: auditing learning analytics systems*. `10.1007/s43681-023-00292-7` | 学习分析系统审计框架 | [PDF](papers/60_Simbeck2023.pdf) |
| R61 | Cukurova (2024), *The interplay of learning, analytics and artificial intelligence in education: A vision for hybrid intelligence*. `10.1111/bjet.13514` | 教师与 AI 混合智能决策 | 元数据 |
| R62 | Mosqueira-Rey et al. (2022), *Human-in-the-loop machine learning: a state of the art*. `10.1007/s10462-022-10246-w` | 人在环机器学习方法与审计 | [PDF](papers/62_MosqueiraRey2022.pdf) |
| R63 | Lin et al. (2023), *Artificial intelligence in intelligent tutoring systems toward sustainable education: a systematic review*. `10.1186/s40561-023-00260-y` | 自适应学习、隐私与部署条件 | [PDF](papers/63_Lin2023ITS.pdf) |
| R64 | de Mooij et al. (2025), *A Systematic Review of Self-Regulated Learning through Integration of Multimodal Data and Artificial Intelligence*. `10.1007/s10648-025-10028-0` | 多模态 SRL 与 AI 的最新综述 | [PDF](papers/64_DeMooij2025.pdf) |
| R65 | Sharma et al. (2024), *Self-regulation and shared regulation in collaborative learning in adaptive digital learning environments*. `10.1111/bjet.13459` | 协作中的自我调节与共同调节 | 元数据 |
| R66 | Ouyang et al. (2023), *Integration of artificial intelligence performance prediction and learning analytics to improve student learning in online engineering course*. `10.1186/s41239-022-00372-4` | 预测分析与教学干预的闭环案例 | [PDF](papers/66_Ouyang2023.pdf) |
| R67 | Sghir et al. (2022), *Recent advances in Predictive Learning Analytics: A decade systematic review (2012-2022)*. `10.1007/s10639-022-11536-0` | 预测学习分析方法与评价综述 | 元数据 |
| R68 | Albreiki et al. (2021), *A Systematic Literature Review of Student Performance Prediction Using Machine Learning Techniques*. `10.3390/educsci11090552` | 学业表现预测的数据与模型综述 | 元数据 |
| R69 | Liang et al. (2022), *Algorithmic group formation and group work evaluation in a learning analytics-enhanced environment*. `10.1080/10494820.2022.2121730` | 初中场景算法分组的实施证据 | 元数据 |
| R70 | Valles-Catala & Palau (2023), *Minimum entropy collaborative groupings: A tool for an automatic heterogeneous learning group formation*. `10.1371/journal.pone.0280604` | 自动异质分组算法及比较基线 | [PDF](papers/70_VallesCatala2023.pdf) |
| R71 | Fan et al. (2022), *Improving the measurement of self-regulated learning using multi-channel data*. `10.1007/s11409-022-09304-z` | 多通道数据增量效度和融合评价 | [PDF](papers/71_Fan2022Multichannel.pdf) |
| R72 | Cloude et al. (2022), *System design for using multimodal trace data in modeling self-regulated learning*. `10.3389/feduc.2022.928632` | SRL 轨迹数据架构与标准化处理 | [PDF](papers/72_Cloude2022.pdf) |
| R73 | Jin et al. (2023), *Supporting students' self-regulated learning in online learning using artificial intelligence applications*. `10.1186/s41239-023-00406-5` | AI 支持 SRL 的系统综述 | [PDF](papers/73_Jin2023.pdf) |
| R74 | Molenaar (2022), *Towards hybrid human-AI learning technologies*. `10.1111/ejed.12527` | 人机混合学习技术的责任分工 | 元数据 |
| R75 | Azevedo et al. (2022), *Lessons Learned and Future Directions of MetaTutor*. `10.3389/fpsyg.2022.813632` | 多通道数据、自适应支架和长期系统经验 | [PDF](papers/75_Azevedo2022.pdf) |
| R76 | Seufert (2026), *Transforming Self-regulated Learning - Multimodal Insights and Future Directions*. `10.1007/s10648-026-10119-6` | SRL 动态、多模态与可行动支架的最新研究议程 | [PDF](papers/76_Seufert2026.pdf) |
| R77 | Wong et al. (2026), *Student engagement profiles in a mobile app: Links to self-regulated learning and performance*. `10.1007/s11423-026-10586-2` | 行为投入类型与 SRL/表现的关系及非固定标签边界 | [PDF](papers/77_Wong2026Engagement.pdf) |
| R78 | Futterer et al. (2026), *Enhancing School Students' Self-Regulated Learning through Generative AI Support: A Randomized Controlled Trial*. `10.1007/s10648-026-10133-8` | 中学生 GenAI-SRL 支持的随机对照证据和有限效果 | [PDF](papers/78_Futterer2026.pdf) |
| R79 | Brunner & Karlen (2026), *Teacher judgments of student self-regulated learning - Examining the effect of student and teacher characteristics*. `10.1007/s11409-026-09469-x` | 教师 SRL 判断的偏差来源，支持弱标签定位 | [PDF](papers/79_BrunnerKarlen2026.pdf) |
| R80 | Yilmaz et al. (2026), *Supporting online learners' regulation skills with the help of learning analytics and generative artificial intelligence*. `10.1007/s11423-026-10595-1` | 学习分析驱动的人类/GenAI 反馈比较 | [PDF](papers/80_Yilmaz2026.pdf) |
| R81 | Lamsa et al. (2026), *Self-Regulated Learning, Multimodal Data, and Analysis Grid*. `10.1007/s10648-025-10113-4` | SRL 多模态数据与分析网格的测量框架 | [PDF](papers/81_Lamsa2026.pdf) |
| R82 | Paavilainen et al. (2026), *Implementing learning design with learning analytics to scaffold the regulation of collaboration in primary education*. `10.1186/s40561-026-00453-1` | 基础教育协作调节的学习设计与分析支架 | [PDF](papers/82_Paavilainen2026.pdf) |
| R83 | Jacobs & Wallach (2021), *Measurement and Fairness*. `10.1145/3442188.3445901` | 区分测量公平与算法结果公平 | 元数据 |
| R84 | Caton & Haas (2024), *Fairness in Machine Learning: A Survey*. `10.1145/3616865` | 公平定义、指标冲突与审计边界 | 元数据 |
| R85 | Kapoor & Narayanan (2023), *Leakage and the reproducibility crisis in machine-learning-based science*. `10.1016/j.patter.2023.100804` | 数据泄漏、非独立样本和可复现风险 | 元数据 |
| R86 | Van Calster et al. (2023), *There is no such thing as a validated prediction model*. `10.1186/s12916-023-02779-w` | 验证结论的场景、总体和时间边界 | 元数据 |
| R87 | Collins et al. (2024), *TRIPOD+AI statement: updated guidance for reporting clinical prediction models that use regression or machine learning methods*. `10.1136/bmj-2023-078378` | 预测模型透明报告的可迁移原则 | 元数据 |
| R88 | Moons et al. (2025), *PROBAST+AI: an updated quality, risk of bias, and applicability assessment tool for prediction models using regression or artificial intelligence methods*. `10.1136/bmj-2024-082505` | 预测模型偏倚风险与适用性审查 | 元数据 |
| R89 | Järvelä & Hadwin (2024), *Triggers for self-regulated learning: A conceptual framework for advancing multimodal research about SRL*. `10.1016/j.lindif.2024.102526` | SRL 触发条件、时间过程和多模态研究框架 | 元数据 |
| R90 | Salibašić Glamočić et al. (2021), *Maintaining item banks with the Rasch model: An example from wave optics*. `10.1103/physrevphyseducres.17.010105` | 题库维护、链接、项目漂移与 Rasch 方法 | 元数据 |
| R91 | Hao et al. (2024), *Transforming Assessment: The Impacts and Implications of Large Language Models and Generative AI*. `10.1111/emip.12602` | 生成式 AI 对评价效度和安全的影响 | 元数据 |
| R92 | Kaldaras et al. (2024), *Developing valid assessments in the era of generative artificial intelligence*. `10.3389/feduc.2024.1399377` | AI 时代评价主张与效度证据 | 元数据 |
| R93 | Arslan et al. (2024), *Opportunities and challenges of using generative AI to personalize educational assessment*. `10.3389/frai.2024.1460651` | 个性化 AI 评价的机会、风险与验证要求 | 元数据 |
| R94 | Tiukhova et al. (2024), *Explainable Learning Analytics: Assessing the stability of student success prediction models by means of explainable AI*. `10.1016/j.dss.2024.114229` | 学习分析解释的稳定性与可信展示 | 元数据 |
| R95 | Weidlich et al. (2022), *Causal Inference and Bias in Learning Analytics*. `10.18608/jla.2022.7577` | 学习分析中的混杂、选择偏倚与因果边界 | 元数据 |
| R96 | Possaghi et al. (2025), *Integrating multi-modal learning analytics dashboard in K-12 education: insights for enhancing orchestration and teacher decision-making*. `10.1186/s40561-025-00410-4` | K-12 多模态看板、课堂编排和教师决策 | 元数据 |
| R97 | Francis et al. (2023), *Student Privacy and Learning Analytics*. `10.18608/jla.2023.7975` | 学生隐私、治理和学习分析边界 | 元数据 |
| R98 | Prinsloo et al. (2022), *The answer is (not only) technological: Considering student data privacy in learning analytics*. `10.1111/bjet.13216` | 超越技术控制的制度性隐私治理 | 元数据 |
| R99 | Blume & Schmiedek (2024), *It counts in every single lesson: Between- and within-person associations of teaching quality and student self-regulation*. `10.1016/j.learninstruc.2024.101908` | 区分学生间差异与学生自身纵向变化 | 元数据 |
| R100 | Sonnleitner et al. (2025), *Evaluation of early student performance prediction given concept drift*. `10.1016/j.caeai.2025.100369` | 时间外推、概念漂移和模型再验证 | 元数据 |
| R101 | Michos et al. (2023), *Teachers' data literacy for learning analytics: a central predictor for digital data use in upper secondary schools*. `10.1007/s10639-023-11772-y` | 教师数据素养与分析工具实际使用 | 元数据 |
| R102 | Kaveri et al. (2023), *Supporting Student Agency with a Student-Facing Learning Analytics Dashboard*. `10.18608/jla.2023.7729` | 学生端看板与能动性支持 | 元数据 |
| R103 | Mohseni et al. (2024), *Visual Learning Analytics for Educational Interventions in Primary and Secondary Schools*. `10.18608/jla.2024.8309` | 中小学可视学习分析和教学干预 | 元数据 |
| R104 | Weydner-Volkmann & Bär (2024), *Student autonomy and Learning Analytics: Philosophical Considerations for Designing Feedback Tools*. `10.18608/jla.2024.8313` | 反馈工具中的学生自主性与规范边界 | 元数据 |
| R105 | Park et al. (2022), *Adaptive or adapted to: Sequence and reflexive thematic analysis to understand learners' self-regulated learning in an adaptive learning analytics dashboard*. `10.1111/bjet.13287` | 自适应看板中的 SRL 过程与学生体验 | 元数据 |

## 使用边界

- 设计文档中的观点是对文献的工程化综合，不等于论文已经验证了 STRATA 的评价标准或模型。
- 正式写作引用某项结果前，作者需要阅读对应全文；只有元数据的条目不能仅凭摘要转述细节。
- 未来加入文献时先更新 `refs.txt` 和 `papers_manifest.csv`，重新生成引用文件和 OA 报告，避免手工引用漂移。
