import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('courses', '0029_alter_classroomgroupcollaboration_storage_quota_mb'),
        ('school', '0009_school_is_synthetic'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ResearchProtocolVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version_no', models.PositiveIntegerField()),
                ('stage', models.CharField(choices=[('E1', '内容与可用性研究'), ('E2', '回顾性测量与预测验证'), ('E3', '前瞻性影子运行'), ('E4', '有限咨询试点'), ('E5', '冻结政策集群试验'), ('E6', '外部独立确认')], max_length=2)),
                ('design_type', models.CharField(choices=[('blind_review', '独立盲评'), ('cognitive_interview', '认知访谈'), ('retrospective', '回顾性验证'), ('shadow', '影子运行'), ('consultation', '有限咨询试点'), ('cluster_trial', '平行集群试验'), ('stepped_wedge', '阶梯楔形集群试验'), ('external_confirmation', '外部独立确认')], max_length=32)),
                ('protocol', models.JSONField(default=dict)),
                ('policy_snapshot', models.JSONField(blank=True, default=dict)),
                ('policy_hash', models.CharField(blank=True, db_index=True, max_length=64)),
                ('ethics_approval_ref', models.CharField(blank=True, max_length=160)),
                ('ethics_approved_at', models.DateField(blank=True, null=True)),
                ('preregistration_ref', models.CharField(blank=True, max_length=255)),
                ('preregistered_at', models.DateTimeField(blank=True, null=True)),
                ('consent_required', models.BooleanField(default=True)),
                ('consent_plan', models.TextField(blank=True)),
                ('content_hash', models.CharField(db_index=True, editable=False, max_length=64)),
                ('registered_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('registered_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='registered_research_protocols', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-version_no', '-id'],
            },
        ),
        migrations.CreateModel(
            name='ResearchCohortAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('arm', models.CharField(choices=[('experiment', '实验组'), ('control', '对照组'), ('observational', '观察组'), ('external_confirmation', '外部确认组')], max_length=24)),
                ('allocation_method', models.CharField(choices=[('random', '随机分配'), ('stratified_random', '分层随机分配'), ('stepped_wedge', '阶梯楔形分配'), ('matched', '匹配分配'), ('observational', '观察性纳入')], max_length=24)),
                ('allocation_unit_code', models.CharField(max_length=96)),
                ('development_site', models.BooleanField(default=True)),
                ('prior_policy_access', models.BooleanField(default=False)),
                ('content_hash', models.CharField(db_index=True, editable=False, max_length=64)),
                ('assigned_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('assigned_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='research_cohort_assignments', to=settings.AUTH_USER_MODEL)),
                ('class_group', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='research_cohort_assignments', to='school.classgroup')),
                ('protocol', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cohort_assignments', to='research.researchprotocolversion')),
            ],
            options={
                'ordering': ['class_group__name', 'id'],
            },
        ),
        migrations.CreateModel(
            name='ResearchRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('run_code', models.CharField(max_length=96)),
                ('mode', models.CharField(choices=[('blind_review', '独立盲评'), ('cognitive_interview', '认知访谈'), ('retrospective', '回顾性验证'), ('shadow', '影子运行'), ('consultation', '有限咨询'), ('cluster_trial', '集群试验'), ('external_confirmation', '外部确认')], max_length=32)),
                ('status', models.CharField(choices=[('planned', '计划中'), ('active', '实施中'), ('paused', '已暂停'), ('closed', '已结束'), ('data_locked', '数据已锁定')], default='planned', max_length=16)),
                ('decision_effect', models.BooleanField(default=False)),
                ('automatic_action_enabled', models.BooleanField(default=False)),
                ('planned_start', models.DateTimeField(blank=True, null=True)),
                ('planned_end', models.DateTimeField(blank=True, null=True)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('activated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='activated_research_runs', to=settings.AUTH_USER_MODEL)),
                ('closed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='closed_research_runs', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_research_runs', to=settings.AUTH_USER_MODEL)),
                ('protocol', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='runs', to='research.researchprotocolversion')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='ResearchExposureRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('observed_on', models.DateField()),
                ('actual_exposure', models.CharField(choices=[('assigned', '按方案实施'), ('not_delivered', '未实施'), ('crossover', '交叉暴露'), ('partial', '部分实施'), ('unknown', '暂不确定')], max_length=24)),
                ('contamination_detected', models.BooleanField(default=False)),
                ('implementation_fidelity', models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True)),
                ('opportunity_summary', models.JSONField(blank=True, default=dict)),
                ('note', models.TextField(blank=True)),
                ('content_hash', models.CharField(db_index=True, editable=False, max_length=64)),
                ('recorded_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cohort_assignment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exposure_records', to='research.researchcohortassignment')),
                ('recorded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='research_exposure_records', to=settings.AUTH_USER_MODEL)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='exposure_records', to='research.researchrun')),
            ],
            options={
                'ordering': ['observed_on', 'cohort_assignment_id'],
            },
        ),
        migrations.CreateModel(
            name='ResearchDataLock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision_as_of', models.DateTimeField()),
                ('data_cutoff', models.DateTimeField()),
                ('dataset_manifest', models.JSONField(default=dict)),
                ('variable_dictionary', models.JSONField(default=list)),
                ('row_count', models.PositiveIntegerField(default=0)),
                ('missingness_summary', models.JSONField(blank=True, default=dict)),
                ('exclusion_summary', models.JSONField(blank=True, default=dict)),
                ('dataset_hash', models.CharField(max_length=64)),
                ('content_hash', models.CharField(db_index=True, editable=False, max_length=64)),
                ('locked_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('locked_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='research_data_locks', to=settings.AUTH_USER_MODEL)),
                ('run', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='data_lock', to='research.researchrun')),
            ],
            options={
                'ordering': ['-locked_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='ResearchStudy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=64)),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('draft', '草稿'), ('registered', '已登记'), ('active', '实施中'), ('closed', '已结束'), ('archived', '已归档')], default='draft', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('course', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='research_studies', to='courses.course')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_research_studies', to=settings.AUTH_USER_MODEL)),
                ('current_protocol', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='current_for_studies', to='research.researchprotocolversion')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='research_studies', to='school.school')),
                ('subject', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='research_studies', to='courses.subject')),
                ('updated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='updated_research_studies', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddField(
            model_name='researchprotocolversion',
            name='study',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='protocol_versions', to='research.researchstudy'),
        ),
        migrations.CreateModel(
            name='ResearchAnalysisRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('analysis_key', models.CharField(max_length=96)),
                ('status', models.CharField(choices=[('completed', '已完成'), ('failed', '失败并保留')], max_length=16)),
                ('parameters', models.JSONField(default=dict)),
                ('software_versions', models.JSONField(default=dict)),
                ('result_summary', models.JSONField(blank=True, default=dict)),
                ('failure_detail', models.TextField(blank=True)),
                ('content_hash', models.CharField(db_index=True, editable=False, max_length=64)),
                ('completed_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='completed_research_analysis_runs', to=settings.AUTH_USER_MODEL)),
                ('data_lock', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='analysis_runs', to='research.researchdatalock')),
            ],
            options={
                'ordering': ['-completed_at', '-id'],
                'constraints': [models.UniqueConstraint(fields=('data_lock', 'analysis_key'), name='uniq_research_analysis_key')],
            },
        ),
        migrations.CreateModel(
            name='ResearchGateDecision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gate', models.CharField(choices=[('ethics', '伦理审批'), ('preregistration', '预注册'), ('consent', '知情与退出安排'), ('instrument_review', '评价工具审查'), ('rater_training', '评分者培训'), ('data_governance', '数据治理'), ('data_quality', '数据质量'), ('power_analysis', '功效分析'), ('teacher_training', '教师培训'), ('safety_monitoring', '安全监测'), ('policy_freeze', '政策冻结'), ('allocation', '集群分配方案'), ('external_independence', '外部独立性')], max_length=32)),
                ('sequence_no', models.PositiveIntegerField()),
                ('decision', models.CharField(choices=[('approved', '通过'), ('conditional', '有条件通过'), ('rejected', '不通过')], max_length=16)),
                ('evidence_ref', models.CharField(max_length=255)),
                ('note', models.TextField(blank=True)),
                ('content_hash', models.CharField(db_index=True, editable=False, max_length=64)),
                ('decided_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('decided_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='research_gate_decisions', to=settings.AUTH_USER_MODEL)),
                ('protocol', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='gate_decisions', to='research.researchprotocolversion')),
            ],
            options={
                'ordering': ['gate', '-sequence_no', '-id'],
                'indexes': [models.Index(fields=['protocol', 'gate', 'decided_at'], name='research_re_protoco_cd1d49_idx')],
                'constraints': [models.UniqueConstraint(fields=('protocol', 'gate', 'sequence_no'), name='uniq_research_gate_sequence')],
            },
        ),
        migrations.AddIndex(
            model_name='researchcohortassignment',
            index=models.Index(fields=['protocol', 'arm'], name='research_re_protoco_0ecd28_idx'),
        ),
        migrations.AddConstraint(
            model_name='researchcohortassignment',
            constraint=models.UniqueConstraint(fields=('protocol', 'class_group'), name='uniq_research_protocol_class_group'),
        ),
        migrations.AddConstraint(
            model_name='researchcohortassignment',
            constraint=models.UniqueConstraint(fields=('protocol', 'allocation_unit_code'), name='uniq_research_allocation_unit_code'),
        ),
        migrations.AddIndex(
            model_name='researchrun',
            index=models.Index(fields=['protocol', 'status', 'created_at'], name='research_re_protoco_1ab7a2_idx'),
        ),
        migrations.AddConstraint(
            model_name='researchrun',
            constraint=models.UniqueConstraint(fields=('protocol', 'run_code'), name='uniq_research_run_code'),
        ),
        migrations.AddIndex(
            model_name='researchexposurerecord',
            index=models.Index(fields=['run', 'observed_on'], name='research_re_run_id_271bd7_idx'),
        ),
        migrations.AddConstraint(
            model_name='researchexposurerecord',
            constraint=models.UniqueConstraint(fields=('run', 'cohort_assignment', 'observed_on'), name='uniq_research_exposure_day'),
        ),
        migrations.AddIndex(
            model_name='researchstudy',
            index=models.Index(fields=['school', 'status', 'created_at'], name='research_re_school__1dc4fb_idx'),
        ),
        migrations.AddConstraint(
            model_name='researchstudy',
            constraint=models.UniqueConstraint(fields=('school', 'code'), name='uniq_research_study_code_school'),
        ),
        migrations.AddIndex(
            model_name='researchprotocolversion',
            index=models.Index(fields=['stage', 'design_type', 'registered_at'], name='research_re_stage_b81588_idx'),
        ),
        migrations.AddConstraint(
            model_name='researchprotocolversion',
            constraint=models.UniqueConstraint(fields=('study', 'version_no'), name='uniq_research_protocol_version_no'),
        ),
        migrations.AddConstraint(
            model_name='researchprotocolversion',
            constraint=models.UniqueConstraint(fields=('study', 'content_hash'), name='uniq_research_protocol_content_hash'),
        ),
    ]
