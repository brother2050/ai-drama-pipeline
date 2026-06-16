// AI 短剧工作台 v2 — 国际化字典
const I18N = {
  // 通用
  'app.title': { zh: '🎬 AI 短剧工作台 v2', en: '🎬 AI Drama Studio v2' },
  'btn.save': { zh: '保存', en: 'Save' },
  'btn.cancel': { zh: '取消', en: 'Cancel' },
  'btn.close': { zh: '关闭', en: 'Close' },
  'btn.delete': { zh: '🗑', en: '🗑' },
  'btn.edit': { zh: '✏', en: '✏' },
  'btn.add': { zh: '新建', en: 'New' },
  'btn.confirm': { zh: '确认', en: 'Confirm' },

  // 侧边栏（纯文字，图标由 NAV_ICONS 控制）
  'nav.dashboard': { zh: '仪表盘', en: 'Dashboard' },
  'nav.characters': { zh: '角色管理', en: 'Characters' },
  'nav.scenes': { zh: '场景管理', en: 'Scenes' },
  'nav.storyboard': { zh: '分镜表', en: 'Storyboard' },
  'nav.pipeline': { zh: '生产管线', en: 'Pipeline' },
  'nav.projects': { zh: '项目管理', en: 'Projects' },
  'nav.settings': { zh: '系统设置', en: 'Settings' },

  // 仪表盘
  'dash.title': { zh: '📊 系统状态', en: '📊 System Status' },
  'dash.infra': { zh: '基础设施', en: 'Infrastructure' },
  'dash.ai_tools': { zh: 'AI 工具', en: 'AI Tools' },
  'dash.gpu_tools': { zh: 'GPU 工具', en: 'GPU Tools' },
  'dash.available': { zh: '可用', en: 'Available' },
  'dash.unavailable': { zh: '不可用', en: 'Unavailable' },
  'dash.welcome_desc': { zh: '从剧本到成片，AI 全流程驱动', en: 'From script to final video, AI-powered' },
  'dash.conn_fail': { zh: '❌ 连接失败', en: '❌ Connection Failed' },
  'dash.setup_title': { zh: '需要启动服务', en: 'Services Required' },
  'dash.setup_desc': { zh: '以下必选服务未运行，请在终端中启动：', en: 'The following required services are not running. Start them in your terminal:' },
  'dash.setup_hint': { zh: '启动后刷新页面即可。遇到问题？查看 README 的「快速开始」章节。', en: 'Refresh this page after starting them. See the Quick Start section in README for help.' },
  'dash.ai_gen': { zh: 'AI 生成', en: 'AI Generate' },
  'dash.stat_projects': { zh: '项目', en: 'Projects' },
  'dash.stat_shots': { zh: '镜头', en: 'Shots' },
  'dash.stat_tools': { zh: '工具就绪', en: 'Tools Ready' },
  'dash.stat_episode': { zh: '当前集', en: 'Episode' },
  'dash.quick_actions': { zh: '快速入口', en: 'Quick Actions' },
  'dash.qe_storyboard': { zh: '编辑分镜剧本', en: 'Edit storyboard' },
  'dash.qe_characters': { zh: '管理角色配置', en: 'Manage characters' },
  'dash.qe_scenes': { zh: '管理场景配置', en: 'Manage scenes' },
  'dash.qe_pipeline': { zh: '生产管线执行', en: 'Production pipeline' },
  'dash.qe_projects': { zh: '切换/新建项目', en: 'Switch/create projects' },
  'dash.qe_settings': { zh: '系统配置调整', en: 'System settings' },

  // 工作台
  'wb.shots_count': { zh: '个镜头', en: 'shots' },
  'wb.batch_tts': { zh: '🎤 批量 TTS', en: '🎤 Batch TTS' },
  'wb.batch_frame': { zh: '🎨 批量首帧', en: '🎨 Batch Frame' },
  'wb.batch_video': { zh: '🎬 批量视频', en: '🎬 Batch Video' },
  'wb.batch_lipsync': { zh: '👄 批量口型', en: '👄 Batch LipSync' },
  'wb.batch_label': { zh: '批量', en: 'Batch' },
  'wb.force_overwrite': { zh: '强制覆盖', en: 'Force Overwrite' },
  'wb.no_shots': { zh: '暂无分镜', en: 'No shots yet' },
  'wb.no_shots_hint': { zh: '先在分镜表添加镜头', en: 'Add shots in Storyboard first' },
  'wb.go_edit': { zh: '去编辑', en: 'Go Edit' },
  'wb.no_resource': { zh: '暂无资源', en: 'No resources' },
  'wb.esc_hint': { zh: '点击空白处关闭 · ESC 键退出', en: 'Click to close · ESC to exit' },
  'wb.loading': { zh: '⏳ 加载...', en: '⏳ Loading...' },

  // 编辑
  'edit.shot_title': { zh: '✏ 编辑镜头', en: '✏ Edit Shot' },
  'edit.scene': { zh: '场景', en: 'Scene' },
  'edit.characters': { zh: '角色', en: 'Characters' },
  'edit.action': { zh: '动作', en: 'Action' },
  'edit.dialogue': { zh: '台词', en: 'Dialogue' },
  'edit.camera': { zh: '运镜', en: 'Camera' },
  'edit.shot_type': { zh: '景别', en: 'Shot Type' },
  'edit.duration': { zh: '时长', en: 'Duration' },
  'edit.emotion': { zh: '情绪', en: 'Emotion' },
  'edit.language': { zh: '语言', en: 'Language' },
  'edit.outfit': { zh: '服装', en: 'Outfit' },
  'edit.outfit_ph': { zh: '对应角色配置中的 outfits key', en: 'Outfit key from character config' },

  // 批量
  'batch.confirm': { zh: '批量执行 {step}？共 {n} 个镜头', en: 'Batch {step}? {n} shots total' },
  'batch.cancelled': { zh: '已取消', en: 'Cancelled' },
  'batch.done': { zh: '批量完成', en: 'Batch Complete' },

  // 提示
  'toast.saved': { zh: '✅ 已保存', en: '✅ Saved' },
  'toast.deleted': { zh: '✅ 已删除', en: '✅ Deleted' },
  'toast.created': { zh: '已创建', en: 'Created' },
  'toast.switched': { zh: '已切换', en: 'Switched' },
  'toast.cancelled': { zh: '批量已取消', en: 'Batch Cancelled' },
  'toast.timeout': { zh: '轮询超时，任务可能仍在执行中。可在终端运行 celery -A pipeline.celery_app inspect active 查看，或刷新任务面板', en: 'Polling timeout, task may still be running. Run celery -A pipeline.app inspect active or refresh the task panel' },
  'toast.task_done': { zh: '完成', en: 'Done' },
  'toast.task_fail': { zh: '失败', en: 'Failed' },
  'toast.input_outline': { zh: '请输入至少 10 字的剧情大纲', en: 'Please enter at least 10 characters' },
  'toast.input_desc': { zh: '请输入描述', en: 'Please enter a description' },
  'toast.input_at_least_one': { zh: '请至少输入一个', en: 'Please enter at least one' },
  'toast.select_first': { zh: '请先选择要操作的项目', en: 'Please select items first' },
  'toast.fill_name': { zh: '请先填写名称', en: 'Please fill in the name first' },
  'toast.select_chars': { zh: '请至少选择一个角色', en: 'Please select at least one character' },
  'toast.portrait_done': { zh: '✅ 定妆照已生成', en: '✅ Portrait generated' },
  'toast.scene_img_done': { zh: '✅ 场景图已生成', en: '✅ Scene image generated' },
  'toast.upload_done': { zh: '✅ 图片已上传', en: '✅ Image uploaded' },
  'toast.tts_preview_done': { zh: '✅ TTS 试听完成', en: '✅ TTS preview done' },
  'toast.task_cancelled': { zh: '任务已取消', en: 'Task cancelled' },
  'toast.cancel_fail': { zh: '取消失败', en: 'Cancel failed' },
  'toast.batch_delete_done': { zh: '批量删除完成: {done} 成功, {fail} 失败', en: 'Batch delete: {done} done, {fail} failed' },
  'toast.gen_done': { zh: '✅ 已生成', en: '✅ Generated' },
  'toast.gen_count': { zh: '✅ 已生成 {n} 个镜头', en: '✅ Generated {n} shots' },
  'toast.outfit_done': { zh: '✅ 服装「{key}」参考图已生成', en: '✅ Outfit "{key}" image generated' },
  'toast.outfits_batch_done': { zh: '✅ 服装批量生成完成: {done}/{total}', en: '✅ Outfits batch: {done}/{total}' },
  'toast.lora_done': { zh: '✅ LoRA 训练完成: {id}', en: '✅ LoRA trained: {id}' },
  'toast.lora_batch_done': { zh: '批量训练完成: {done}成功 {fail}失败', en: 'Batch training: {done} done, {fail} failed' },
  'toast.already_generated': { zh: '✅ 已{label}', en: '✅ {label}' },
  'confirm.delete_shot': { zh: '确认删除镜头 {id}？', en: 'Delete shot {id}?' },
  'confirm.delete_char': { zh: '确认删除角色 {id}？', en: 'Delete character {id}?' },
  'confirm.delete_scene': { zh: '确认删除场景 {id}？', en: 'Delete scene {id}?' },
  'confirm.batch': { zh: '批量执行 {step}？共 {n} 个镜头', en: 'Batch {step}? {n} shots' },

  // 角色
  'char.title': { zh: '角色', en: 'Characters' },
  'char.none': { zh: '暂无', en: 'None' },
  'char.name': { zh: '姓名', en: 'Name' },
  'char.gender': { zh: '性别', en: 'Gender' },
  'char.appearance': { zh: '外观', en: 'Appearance' },
  'char.operations': { zh: '操作', en: 'Actions' },
  'char.edit_title': { zh: '✏ 编辑角色', en: '✏ Edit Character' },

  // 场景
  'scene.title': { zh: '场景', en: 'Scenes' },
  'scene.none': { zh: '暂无', en: 'None' },
  'scene.name': { zh: '名称', en: 'Name' },
  'scene.desc': { zh: '描述', en: 'Description' },
  'scene.lighting': { zh: '光照', en: 'Lighting' },
  'scene.operations': { zh: '操作', en: 'Actions' },
  'scene.edit_title': { zh: '✏ 编辑场景', en: '✏ Edit Scene' },
  'scene.gen_image': { zh: '🎨 AI 生成场景图', en: '🎨 AI Generate Scene Image' },

  // 分镜表
  'sb.title': { zh: '分镜表', en: 'Storyboard' },
  'sb.shot_id': { zh: '镜号', en: 'Shot#' },
  'sb.none': { zh: '暂无', en: 'None' },
  'sb.added': { zh: '已添加', en: 'Added' },
  'sb.timeline': { zh: '时间轴', en: 'Timeline' },
  'sb.empty_desc': { zh: '添加镜头或使用 AI 从大纲生成', en: 'Add shots or generate from outline with AI' },

  // 项目
  'proj.title': { zh: '项目', en: 'Projects' },
  'proj.current': { zh: '当前', en: 'Current' },
  'proj.name': { zh: '名称', en: 'Name' },
  'proj.path': { zh: '路径', en: 'Path' },
  'proj.status': { zh: '状态', en: 'Status' },

  // 设置
  'set.env': { zh: '环境', en: 'Environment' },
  'set.config': { zh: '配置', en: 'Configuration' },
  'set.tts': { zh: 'TTS', en: 'TTS' },
  'set.comfyui': { zh: 'ComfyUI', en: 'ComfyUI' },
  'set.lipsync': { zh: 'LipSync', en: 'LipSync' },
  'set.backend': { zh: '后端', en: 'Backend' },
  'set.address': { zh: '地址', en: 'Address' },
  'set.os': { zh: 'OS', en: 'OS' },
  'set.python': { zh: 'Python', en: 'Python' },

  // 运镜/景别/情绪
  'camera.fixed': { zh: '固定', en: 'Fixed' },
  'camera.push_in': { zh: '缓慢推近', en: 'Slow Push In' },
  'camera.pan': { zh: '跟随平移', en: 'Follow Pan' },
  'camera.handheld': { zh: '手持晃动', en: 'Handheld' },
  'camera.orbit': { zh: '环绕', en: 'Orbit' },
  'camera.top': { zh: '俯视', en: 'Top Down' },
  'camera.bottom': { zh: '仰视', en: 'Low Angle' },

  'shot.closeup': { zh: '特写', en: 'Close-up' },
  'shot.medium_close': { zh: '近景', en: 'Medium Close' },
  'shot.medium': { zh: '中景', en: 'Medium' },
  'shot.over_shoulder': { zh: '过肩', en: 'Over Shoulder' },
  'shot.full': { zh: '全身', en: 'Full Body' },
  'shot.wide': { zh: '全景', en: 'Wide' },
  'shot.extreme_wide': { zh: '远景', en: 'Extreme Wide' },
  'shot.two_shot': { zh: '双人全景', en: 'Two-Shot' },
  'shot.side_closeup': { zh: '侧面特写', en: 'Side Close-up' },
  'shot.back_closeup': { zh: '背面特写', en: 'Back Close-up' },

  'emo.neutral': { zh: '平静', en: 'Neutral' },
  'emo.happy': { zh: '开心', en: 'Happy' },
  'emo.sad': { zh: '悲伤', en: 'Sad' },
  'emo.angry': { zh: '愤怒', en: 'Angry' },
  'emo.worried': { zh: '担心', en: 'Worried' },
  'emo.surprised': { zh: '惊讶', en: 'Surprised' },
  'emo.calm': { zh: '冷静', en: 'Calm' },
  'emo.determined': { zh: '坚定', en: 'Determined' },

  // 仪表盘补充

  // 通用补充
  'common.loading': { zh: '⏳ 加载...', en: '⏳ Loading...' },
  'common.error': { zh: '❌', en: '❌' },
  'common.none': { zh: '暂无', en: 'None' },
  'common.operations': { zh: '操作', en: 'Actions' },
  'common.switch': { zh: '切换', en: 'Switch' },
  'common.current': { zh: '当前', en: 'Current' },
  'common.name': { zh: '名称', en: 'Name' },
  'common.path': { zh: '路径', en: 'Path' },
  'common.status': { zh: '状态', en: 'Status' },

  // 管线补充
  'wb.no_storyboard': { zh: '暂无分镜', en: 'No storyboard' },
  'wb.add_shots_first': { zh: '先在分镜表添加镜头', en: 'Add shots in Storyboard first' },
  'wb.go_edit_btn': { zh: '去编辑', en: 'Go Edit' },
  'wb.gen_portraits': { zh: '定妆照', en: 'Portraits' },
  'wb.gen_scene_images': { zh: '场景图', en: 'Scene Images' },
  'wb.prepare': { zh: '🔧 准备阶段', en: '🔧 Prepare' },
  'wb.prepare_hint': { zh: '批量翻译角色/场景/分镜（生产前运行一次）', en: 'Batch translate characters/scenes/storyboard (run once before produce)' },
  'wb.bible': { zh: '📖 角色圣经', en: '📖 Bible' },
  'wb.bible_hint': { zh: '为角色补全性格/说话风格/人际关系等（生产前运行一次）', en: 'Fill in character personality/speech/relationships (run once before produce)' },
  'wb.post_process': { zh: '后期合成', en: 'Post' },
  'wb.run_all': { zh: '一键全流程', en: 'Run All' },
  'wb.tools': { zh: '工具', en: 'Tools' },
  'wb.flow_title': { zh: '生产流程', en: 'Production Flow' },
  'wb.post_short': { zh: '后期', en: 'Post' },
  'wb.portrait_short': { zh: '定妆照', en: 'Portrait' },
  'wb.scene_short': { zh: '场景图', en: 'Scene' },
  // 质量检查
  'quality.title': { zh: '质量检查提醒', en: 'Quality Check Warning' },
  'quality.has_warnings': { zh: '发现质量问题，请查看详情', en: 'Quality issues found, please check details' },
  'quality.hint': { zh: '请在角色/场景编辑页补全缺失的英文翻译和 prompt 后再执行生产', en: 'Please complete missing English translations and prompts in the character/scene editor before production' },

  // 角色补充
  'char.not_found': { zh: '角色不存在', en: 'Character not found' },
  'char.gender.male': { zh: '男', en: 'Male' },
  'char.gender.female': { zh: '女', en: 'Female' },
  'char.outfits': { zh: '服装', en: 'Outfits' },
  'char.voice': { zh: '语音', en: 'Voice' },
  'char.voice_desc': { zh: '声音描述', en: 'Voice Description' },
  'char.voice_ref_audio': { zh: '参考音频路径', en: 'Reference Audio Path' },
  'char.voice_aux_refs': { zh: '辅助参考音频', en: 'Auxiliary Reference Audio' },
  'char.voice_speaker': { zh: '说话人', en: 'Speaker' },
  'char.voice_ref_id': { zh: '参考 ID', en: 'Reference ID' },
  'char.voice_prompt_text': { zh: '提示文本', en: 'Prompt Text' },
  'char.voice_prompt_lang': { zh: '提示语言', en: 'Prompt Lang' },
  'char.voice_speed': { zh: '语速', en: 'Speed' },
  'char.voice_seed': { zh: '音色种子', en: 'Voice Seed' },
  'char.voice_clone_seed': { zh: '克隆种子', en: 'Clone Seed' },
  'char.voice_prompt': { zh: '控制标签', en: 'Control Tags' },
  'char.voice_params': { zh: '语音参数', en: 'Voice Parameters' },
  'char.personality': { zh: '性格', en: 'Personality' },
  'char.outfit_desc': { zh: '服装描述', en: 'Outfit Description' },

  // 场景补充
  'scene.not_found': { zh: '场景不存在', en: 'Scene not found' },

  // 项目补充
  'proj.created': { zh: '已创建', en: 'Created' },
  'proj.switched': { zh: '已切换', en: 'Switched' },
  'proj.input_name': { zh: '名称:', en: 'Name:' },
  'proj.create_title': { zh: '新建短剧项目', en: 'New Drama Project' },
  'proj.name_ph': { zh: '输入项目名称', en: 'Enter project name' },
  'proj.style': { zh: '视觉风格', en: 'Visual Style' },
  'proj.genre': { zh: '题材类型', en: 'Genre' },
  'proj.confirm_delete': { zh: '确认删除项目 {name}？', en: 'Delete project {name}?' },
  'proj.deleted': { zh: '项目已删除', en: 'Project deleted' },

  // 设置补充
  'set.saved': { zh: '✅ 已保存', en: '✅ Saved' },
  'set.optional': { zh: '选填', en: 'Optional' },
  'set.llm': { zh: 'LLM', en: 'LLM' },
  'set.llm_enabled': { zh: '启用', en: 'Enabled' },
  'set.llm_model': { zh: '模型', en: 'Model' },
  'set.test': { zh: '测试连接', en: 'Test' },
  'set.tts_api_key': { zh: 'API Key', en: 'API Key' },
  'set.tts_test': { zh: '🎤 试听', en: '🎤 Preview' },
  'set.tts_test_text': { zh: '试听文本', en: 'Preview Text' },
  'set.tts_test_hint': { zh: '输入文本，测试 TTS 合成效果', en: 'Enter text to test TTS synthesis' },
  'set.tts_params': { zh: 'TTS 参数', en: 'TTS Parameters' },
  'set.tts_speaker': { zh: '说话人', en: 'Speaker' },
  'set.tts_ref_audio': { zh: '参考音频', en: 'Reference Audio' },
  'set.tts_ref_id': { zh: '参考 ID', en: 'Reference ID' },
  'set.tts_voice_desc': { zh: '声音描述', en: 'Voice Description' },
  'set.tts_prompt_text': { zh: '提示文本', en: 'Prompt Text' },

  // 训练
  'set.image_backend': { zh: '生图后端', en: 'Image Backend' },
  'set.video_backend': { zh: '视频后端', en: 'Video Backend' },
  'set.training': { zh: 'LoRA 训练', en: 'LoRA Training' },
  'set.training_timeout': { zh: '训练超时(秒)', en: 'Train Timeout(s)' },
  'set.training_poll': { zh: '轮询间隔(秒)', en: 'Poll Interval(s)' },

  // LoRA 训练面板
  'train.title': { zh: '🏋 LoRA 训练', en: '🏋 LoRA Training' },
  'train.desc': { zh: '用角色定妆照训练专属 LoRA 模型，提升角色一致性', en: 'Train a dedicated LoRA model with character portraits for better consistency' },
  'train.status': { zh: 'LoRA 状态', en: 'LoRA Status' },
  'train.trained': { zh: '已训练', en: 'Trained' },
  'train.not_trained': { zh: '未训练', en: 'Not Trained' },
  'train.trigger': { zh: '触发词', en: 'Trigger Word' },
  'train.trigger_hint': { zh: '留空自动生成（如 ohwx 角色名）', en: 'Leave empty to auto-generate (e.g. ohwx character name)' },
  'train.steps': { zh: '训练步数', en: 'Steps' },
  'train.lr': { zh: '学习率', en: 'Learning Rate' },
  'train.rank': { zh: 'Rank', en: 'Rank' },
  'train.resolution': { zh: '分辨率', en: 'Resolution' },
  'train.start': { zh: '🚀 开始训练', en: '🚀 Start Training' },
  'train.force': { zh: '覆盖已有 LoRA', en: 'Overwrite existing LoRA' },
  'train.progress': { zh: '训练中...', en: 'Training...' },
  'train.done': { zh: '训练完成', en: 'Training Complete' },
  'train.failed': { zh: '训练失败', en: 'Training Failed' },
  'train.no_portrait': { zh: '请先生成定妆照', en: 'Generate portrait first' },
  'train.size': { zh: '大小', en: 'Size' },
  'train.batch': { zh: '🏋 批量训练 LoRA', en: '🏋 Batch Train LoRA' },
  'train.batch_desc': { zh: '选择要训练的角色（有定妆照的才能训练）', en: 'Select characters to train (needs portrait)' },
  'train.batch_done': { zh: '批量训练完成: {done}成功 {fail}失败', en: 'Batch done: {done} OK {fail} failed' },

  // 批量补充
  'batch.cancel_btn': { zh: '⏹ 取消', en: '⏹ Cancel' },
  'batch.close_btn': { zh: '关闭', en: 'Close' },
  'batch.progress': { zh: '{step}...', en: '{step}...' },
  'batch.complete': { zh: '批量完成: {done}成功 {skip}跳过 {fail}失败', en: 'Batch done: {done} OK {skip} skip {fail} fail' },
  'batch.concurrent': { zh: '并发数', en: 'Concurrency' },

  // 步骤名
  'step.tts': { zh: 'TTS', en: 'TTS' },
  'step.first_frame': { zh: '首帧', en: 'Frame' },
  'step.video': { zh: '视频', en: 'Video' },
  'step.lipsync': { zh: '口型同步', en: 'LipSync' },

  // 撤销/重做
  'undo.no_action': { zh: '没有可{label}的操作', en: 'Nothing to {label}' },
  'undo.undo': { zh: '撤销', en: 'Undo' },
  'undo.redo': { zh: '重做', en: 'Redo' },

  // 分镜表补充
  'sb.saved': { zh: '✅ 已保存', en: '✅ Saved' },
  'sb.deleted': { zh: '✅ 已删除', en: '✅ Deleted' },
  'sb.emotion': { zh: '情绪', en: 'Emotion' },
  'sb.action_en': { zh: '动作(英)', en: 'Action(EN)' },
  'sb.dialogue_en': { zh: '台词(英)', en: 'Dialogue(EN)' },
  'sb.unsaved_confirm': { zh: '分镜表有未保存的修改，确定离开？', en: 'Unsaved changes in storyboard. Leave anyway?' },

  // 集数
  'ep.input': { zh: '集数:', en: 'Episode #:' },
  'ep.invalid': { zh: '集数无效', en: 'Invalid episode' },
  'ep.switched': { zh: '已切换到第 {ep} 集', en: 'Switched to episode {ep}' },

  // 通用补充
  'common.id_invalid': { zh: 'ID 格式不合法', en: 'Invalid ID format' },

  // 管线 - 单镜头执行结果
  'wb.shot_done': { zh: '完成', en: 'Done' },
  'wb.shot_skip': { zh: '跳过', en: 'Skipped' },
  'wb.shot_fail': { zh: '失败', en: 'Failed' },
  'wb.shot_err': { zh: '出错', en: 'Error' },
  'wb.shot_timeout': { zh: '超时', en: 'Timeout' },

  // 管线 - 批量完成
  'wb.batch_done': { zh: '✅ 完成', en: '✅ Done' },
  'wb.batch_cancelled': { zh: '⏹ 已取消', en: '⏹ Cancelled' },
  'wb.batch_ok': { zh: '✅', en: '✅' },
  'wb.batch_skip': { zh: '⏭', en: '⏭' },
  'wb.batch_fail': { zh: '❌', en: '❌' },

  // 空状态引导
  'char.empty_hint': { zh: '点击上方按钮创建第一个角色', en: 'Click the button above to create your first character' },
  'char.empty_desc': { zh: '角色用于分镜表中的角色配置，支持 AI 生成', en: 'Characters are used in storyboard, supports AI generation' },
  'scene.empty_hint': { zh: '点击上方按钮创建第一个场景', en: 'Click the button above to create your first scene' },
  'scene.empty_desc': { zh: '场景用于分镜表中的场景配置，支持 AI 生成', en: 'Scenes are used in storyboard, supports AI generation' },

  // 配乐/字幕
  'wb.gen_music': { zh: '配乐', en: 'Music' },
  'wb.gen_subtitle': { zh: '字幕', en: 'Subtitle' },
  'wb.music_duration': { zh: '时长(秒)', en: 'Duration(s)' },
  'wb.music_mood': { zh: '情绪', en: 'Mood' },

  // 2.1 灵感输入
  'dash.inspire_placeholder': { zh: '输入你的剧情灵感，例如：\n"林夏独自在家等顾辰来过生日，等了很久他都没回消息..."', en: 'Enter your story idea, e.g.:\n"Lin Xia waits alone at home for Gu Chen to arrive for her birthday..."' },
  'dash.inspire_btn': { zh: '🚀 AI 生成分镜', en: '🚀 AI Generate Storyboard' },
  'dash.inspire_hint': { zh: '输入一句话，AI 自动生成完整分镜表', en: 'One sentence → AI generates a full storyboard' },
  'dash.inspire_advanced': { zh: '⚙ 高级选项', en: '⚙ Advanced' },
  'dash.inspire_ep': { zh: '集数', en: 'Episode' },
  'dash.inspire_dur': { zh: '目标时长(秒)', en: 'Target Duration(s)' },
  'dash.inspire_append': { zh: '追加到现有分镜表', en: 'Append to existing storyboard' },

  // 2.3 缩略图骨架屏
  'wb.thumb_loading': { zh: '加载中...', en: 'Loading...' },

  // 2.5 编辑面板增强
  'edit.char_count': { zh: '{count} 字', en: '{count} chars' },
  'edit.next_shot': { zh: '▶ 下一个镜头', en: '▶ Next Shot' },
  'edit.prev_shot': { zh: '◀ 上一个镜头', en: '◀ Prev Shot' },
  'edit.select_char': { zh: '选择角色...', en: 'Select character...' },
  'edit.select_scene': { zh: '选择场景...', en: 'Select scene...' },

  // 2.2 图片上传
  'char.upload_img': { zh: '📷 上传定妆照', en: '📷 Upload Portrait' },
  'scene.upload_img': { zh: '📷 上传参考图', en: '📷 Upload Reference' },
  'common.upload_hint': { zh: '点击或拖拽上传', en: 'Click or drag to upload' },
  'common.uploading': { zh: '上传中...', en: 'Uploading...' },

  // 3.1 拖拽排序
  'sb.drag_hint': { zh: '💡 拖拽行可调整镜头顺序', en: '💡 Drag rows to reorder shots' },
  'sb.reordered': { zh: '✅ 顺序已更新', en: '✅ Order updated' },

  // 3.2 导入/导出
  'sb.import': { zh: '导入', en: 'Import' },
  'sb.export': { zh: '导出', en: 'Export' },
  'sb.import_title': { zh: '导入分镜', en: 'Import Storyboard' },
  'sb.import_mode': { zh: '导入模式', en: 'Import Mode' },
  'sb.import_merge': { zh: '合并（追加）', en: 'Merge (Append)' },
  'sb.import_overwrite': { zh: '覆盖（替换）', en: 'Overwrite (Replace)' },
  'sb.import_file': { zh: '选择文件', en: 'Select File' },
  'sb.import_done': { zh: '✅ 已导入 {n} 个镜头', en: '✅ Imported {n} shots' },
  'sb.export_done': { zh: '✅ 已导出 {n} 个镜头', en: '✅ Exported {n} shots' },
  'sb.import_parse_err': { zh: '文件解析失败', en: 'File parse error' },

  // 3.3 引用计数
  'char.ref_count': { zh: '被 {n} 个镜头引用', en: 'Referenced by {n} shots' },
  'scene.ref_count': { zh: '被 {n} 个镜头引用', en: 'Referenced by {n} shots' },
  'char.confirm_delete_ref': { zh: '此角色被 {n} 个镜头引用，确认删除？', en: 'This character is referenced by {n} shots. Delete anyway?' },
  'scene.confirm_delete_ref': { zh: '此场景被 {n} 个镜头引用，确认删除？', en: 'This scene is referenced by {n} shots. Delete anyway?' },

  // 3.4 配置预设
  'set.presets': { zh: '⚡ 快速配置', en: '⚡ Quick Presets' },
  'set.preset_local': { zh: '🏠 本地 ComfyUI', en: '🏠 Local ComfyUI' },
  'set.preset_cloud': { zh: '☁ 云端 SiliconFlow', en: '☁ Cloud SiliconFlow' },
  'set.preset_ollama': { zh: '🦙 Ollama 本地', en: '🦙 Ollama Local' },
  'set.preset_applied': { zh: '✅ 预设已应用', en: '✅ Preset applied' },

  // 3.5 成片预览
  'wb.final_preview': { zh: '🎬 成片预览', en: '🎬 Final Preview' },
  'wb.no_final': { zh: '尚未生成成片', en: 'No final video yet' },
  'wb.no_final_hint': { zh: '运行「一键全流程」后可在此预览', en: 'Run "Run All" to generate the final video' },
  'wb.download': { zh: '⬇ 下载', en: '⬇ Download' },

  // 4.1 对话式编辑
  'chat.title': { zh: '💬 对话编辑', en: '💬 Chat Edit' },
  'chat.placeholder': { zh: '用自然语言编辑分镜，例如：\n"把第3个镜头的台词改成..."', en: 'Edit storyboard with natural language, e.g.:\n"Change shot 3 dialogue to..."' },
  'chat.send': { zh: '发送', en: 'Send' },
  'chat.thinking': { zh: '🧠 AI 思考中...', en: '🧠 AI thinking...' },
  'chat.success': { zh: '✅ 已执行', en: '✅ Done' },
  'chat.error': { zh: '❌ 执行失败', en: '❌ Failed' },
  'chat.empty': { zh: '请输入指令', en: 'Please enter a command' },

  // 4.2 主体库
  'nav.assets': { zh: '主体库', en: 'Assets' },
  'asset.title': { zh: '主体库', en: 'Asset Library' },
  'asset.desc': { zh: '全局共享的角色和场景，可跨项目复用', en: 'Global shared characters and scenes, reusable across projects' },
  'asset.copy_to_proj': { zh: '复制到当前项目', en: 'Copy to Project' },
  'asset.copied': { zh: '✅ 已复制到当前项目', en: '✅ Copied to current project' },
  'asset.empty': { zh: '主体库为空', en: 'Asset library is empty' },
  'asset.empty_hint': { zh: '在角色/场景管理中添加到主体库', en: 'Add assets from Character/Scene management' },
  'asset.add_to_lib': { zh: '添加到主体库', en: 'Add to Library' },

  // 4.3 多剧集管理
  'ep.title': { zh: '📺 集数管理', en: '📺 Episode Manager' },
  'ep.shots': { zh: '镜头', en: 'Shots' },
  'ep.duration': { zh: '时长', en: 'Duration' },
  'ep.status': { zh: '状态', en: 'Status' },
  'ep.status_none': { zh: '未开始', en: 'Not Started' },
  'ep.status_progress': { zh: '进行中', en: 'In Progress' },
  'ep.status_done': { zh: '已完成', en: 'Completed' },
  'ep.batch_gen': { zh: '🚀 全集生成', en: '🚀 Generate All' },
  'ep.batch_export': { zh: '📤 全集导出', en: '📤 Export All' },
  'ep.confirm_delete': { zh: '确认删除第 {ep} 集？将删除该集所有分镜和生成产物，不可恢复。', en: 'Delete episode {ep}? All shots and generated files will be permanently removed.' },
  'ep.deleted': { zh: '已删除第 {ep} 集（{n} 个镜头）', en: 'Episode {ep} deleted ({n} shots)' },
  'ep.confirm_clear': { zh: '确认清空第 {ep} 集的生成产物？分镜表保留，仅删除音频/图片/视频。', en: 'Clear outputs for episode {ep}? Storyboard will be kept, only generated files will be removed.' },
  'ep.cleared': { zh: '已清空第 {ep} 集产物（{n} 个文件）', en: 'Episode {ep} outputs cleared ({n} files)' },
  'ep.clear_outputs': { zh: '清空产物', en: 'Clear Outputs' },

  // 批量删除
  'btn.batch_delete': { zh: '🗑 批量删除', en: '🗑 Batch Delete' },
  'btn.select_all': { zh: '全选', en: 'Select All' },
  'btn.deselect_all': { zh: '取消全选', en: 'Deselect All' },
  'confirm.batch_delete_chars': { zh: '确认删除选中的 {n} 个角色？此操作不可撤销。', en: 'Delete {n} selected characters? This cannot be undone.' },
  'confirm.batch_delete_scenes': { zh: '确认删除选中的 {n} 个场景？此操作不可撤销。', en: 'Delete {n} selected scenes? This cannot be undone.' },
  'confirm.batch_delete_shots': { zh: '确认删除选中的 {n} 个镜头？此操作不可撤销。', en: 'Delete {n} selected shots? This cannot be undone.' },
  'toast.batch_deleted': { zh: '✅ 已删除 {n} 个', en: '✅ Deleted {n}' },
  'toast.batch_delete_done': { zh: '批量删除完成: {done} 成功 {fail} 失败', en: 'Batch delete: {done} OK {fail} failed' },
  'common.selected': { zh: '已选 {n} 个', en: '{n} selected' },

  // 4.4 实时协作指示
  'worker.running': { zh: '🔧 Worker 运行中', en: '🔧 Worker Running' },
  'worker.idle': { zh: '💤 Worker 空闲', en: '💤 Worker Idle' },
  'worker.tasks': { zh: '{n} 个任务', en: '{n} tasks' },
  'worker.offline': { zh: '⛔ Worker 离线', en: '⛔ Worker Offline' },

  // TaskPanel 任务面板
  'task.title': { zh: '⏳ 任务', en: '⏳ Tasks' },
  'task.pending': { zh: '排队中', en: 'Pending' },
  'task.running': { zh: '执行中', en: 'Running' },
  'task.done': { zh: '完成', en: 'Done' },
  'task.failed': { zh: '失败', en: 'Failed' },
  'task.cancelled': { zh: '已取消', en: 'Cancelled' },
  'task.timeout': { zh: '超时', en: 'Timeout' },
  'task.empty': { zh: '暂无任务', en: 'No tasks' },
  'task.recent_done': { zh: '最近完成', en: 'Recent' },
  'task.cancel': { zh: '取消', en: 'Cancel' },
  'task.waiting': { zh: '等待中...', en: 'Waiting...' },
  'task.submitted': { zh: '已提交，等待 Worker 处理...', en: 'Submitted, waiting for worker...' },
  'task.processing': { zh: '任务执行中...', en: 'Processing...' },
  'task.toggle': { zh: '展开/收起', en: 'Expand/Collapse' },
  'task.n_running': { zh: '{n} 个任务运行中', en: '{n} tasks running' },

  // Seko 影视策划
  'nav.seko': { zh: '影视策划', en: 'Seko Proposal' },
  'seko.title': { zh: '🎬 影视策划案', en: '🎬 Seko Proposal' },
  'seko.desc': { zh: '基于 Seko AI 一键生成影视策划案，包含故事梗概、美术风格、角色/场景设计、分镜剧本', en: 'AI-powered proposal generation: story, art style, characters, scenes, storyboard' },
  'seko.api_key_unset': { zh: '⚠ 请先在系统设置中配置 SEKO_API_KEY', en: '⚠ Please set SEKO_API_KEY in Settings first' },
  'seko.new_proposal': { zh: '📝 新建策划案', en: '📝 New Proposal' },
  'seko.prompt_label': { zh: '故事描述', en: 'Story Description' },
  'seko.prompt_ph': { zh: '输入你的故事想法，例如：\n"一个程序员穿越到古代用代码拯救世界"', en: 'Enter your story idea, e.g.:\n"A programmer travels back in time to save the ancient world with code"' },
  'seko.submit_btn': { zh: '🚀 生成策划案', en: '🚀 Generate Proposal' },
  'seko.submitting': { zh: '提交中...', en: 'Submitting...' },
  'seko.submitted': { zh: '✅ 策划案已提交，任务ID: {id}', en: '✅ Proposal submitted, task ID: {id}' },
  'seko.submit_fail': { zh: '❌ 提交失败', en: '❌ Submission failed' },
  'seko.task_list': { zh: '📋 任务列表', en: '📋 Task List' },
  'seko.no_tasks': { zh: '暂无任务，提交策划案后在此查看进度', en: 'No tasks yet. Submit a proposal to track progress here' },
  'seko.status_RUNNING': { zh: '⏳ 处理中', en: '⏳ Running' },
  'seko.status_OK': { zh: '✅ 成功', en: '✅ OK' },
  'seko.status_FAIL': { zh: '❌ 失败', en: '❌ Failed' },
  'seko.check_btn': { zh: '🔄 查询状态', en: '🔄 Check Status' },
  'seko.checking': { zh: '查询中...', en: 'Checking...' },
  'seko.download_btn': { zh: '⬇ 下载图片', en: '⬇ Download Images' },
  'seko.modify_btn': { zh: '✏ 修改', en: '✏ Modify' },
  'seko.modify_title': { zh: '修改策划案', en: 'Modify Proposal' },
  'seko.modify_ph': { zh: '输入修改指令，例如：\n"把主角改成女性，背景改成赛博朋克"', en: 'Enter modification, e.g.:\n"Change protagonist to female, set in cyberpunk world"' },
  'seko.modify_submit': { zh: '提交修改', en: 'Submit Modification' },
  'seko.result_title': { zh: '📄 策划案结果', en: '📄 Proposal Result' },
  'seko.downloaded': { zh: '✅ 已下载 {n} 张图片', en: '✅ Downloaded {n} images' },
  'seko.task_added': { zh: '任务已添加到列表', en: 'Task added to list' },
  'seko.import_btn': { zh: '📥 导入项目', en: '📥 Import to Project' },
  'seko.import_confirm': { zh: '确认将策划案导入当前项目？', en: 'Import this proposal into the current project?' },
  'seko.import_desc': { zh: '将导入角色、场景、分镜，并在后台下载图片', en: 'Imports characters, scenes, storyboard and downloads images in background' },
  'seko.import_mode_title': { zh: '📥 导入方式', en: '📥 Import Mode' },
  'seko.import_mode_desc': { zh: '输入新项目名 → 创建新项目并导入\n留空 → 导入到当前项目', en: 'Enter name → create new project & import\nLeave empty → import to current project' },
  'seko.import_mode_ph': { zh: '留空 = 导入当前项目', en: 'Empty = import to current project' },
  'seko.import_creating': { zh: '正在创建项目并导入...', en: 'Creating project and importing...' },
  'seko.import_switch_hint': { zh: '已创建项目', en: 'Project created' },
  'seko.import_submitting': { zh: '正在提交导入任务...', en: 'Submitting import task...' },
  'seko.import_submitted': { zh: '✅ 导入任务已提交', en: '✅ Import task submitted' },
  'seko.import_done': { zh: '✅ 导入完成！', en: '✅ Import complete!' },
  'seko.import_fail': { zh: '❌ 导入失败', en: '❌ Import failed' },
  'seko.import_timeout': { zh: '⏰ 导入任务超时，请稍后查看结果', en: '⏰ Import task timed out, check results later' },

  // 短剧管理
  'drama.title': { zh: '短剧管理', en: 'Drama Manager' },
  'drama.new': { zh: '新建短剧', en: 'New Drama' },
  'drama.list': { zh: '短剧列表', en: 'Dramas' },
  'drama.switch_to': { zh: '切换为当前', en: 'Switch To' },
  'drama.prepare': { zh: '准备阶段', en: 'Prepare' },
  'drama.prepare_done': { zh: '✅ 准备阶段完成', en: '✅ Prepare done' },
  'drama.status': { zh: '项目状态', en: 'Project Status' },
  'drama.st_chars': { zh: '角色', en: 'Characters' },
  'drama.st_scenes': { zh: '场景', en: 'Scenes' },
  'drama.st_shots': { zh: '总镜头', en: 'Total Shots' },
};

// 当前语言（默认中文）
let _lang = localStorage.getItem('drama_lang') || 'zh';

// 导航图标映射（与 i18n 文字分离，避免重复）
const NAV_ICONS = {
  'nav.dashboard': '📊',
  'nav.characters': '👤',
  'nav.scenes': '🏔',
  'nav.storyboard': '📝',
  'nav.pipeline': '🎬',
  'nav.projects': '📂',
  'nav.settings': '⚙',
  'nav.seko': '🎬',
  'nav.assets': '📦',
};

function setLang(lang) {
  _lang = lang;
  localStorage.setItem('drama_lang', lang);
  applyI18n();
}

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const entry = I18N[key];
    if (entry) {
      const icon = NAV_ICONS[key];
      const text = entry[_lang] || entry.zh || key;
      el.textContent = icon ? `${icon} ${text}` : text;
    }
  });
}

function t(key, params = {}) {
  const entry = I18N[key];
  let text = entry ? (entry[_lang] || entry.zh || key) : key;
  // 替换参数 {name} → value
  for (const [k, v] of Object.entries(params)) {
    text = text.replaceAll(`{${k}}`, v);
  }
  return text;
}

// ── Module: i18n ──
Drama.i18n = { t, setLang, applyI18n, I18N, NAV_ICONS };
window.t = t;
window.setLang = setLang;
window.applyI18n = applyI18n;
