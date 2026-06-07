# TODO

> 2026-06-07 后期合成逻辑链审查遗留项。

## 后期合成（post/production.py）审查 — 2026-06-07

### 🔴 P1：SRT 时间轴与拼接视频时间轴不同步

- **文件：** `post/subtitle.py:33-34` vs `infra/transitions.py:82`
- **问题：** SRT 用 `clip_duration()` 计算时间轴（整数 2-8），拼接视频用 `probe()` 获取的实际文件时长。两者来源不同，随镜头数量累积产生字幕漂移。
- **修复方向：** SRT 生成应读取各镜头视频的实际时长（probe），而非依赖分镜表的 duration 字段。

### 🔴 P1：BGM 总时长与实际视频总时长不一致

- **文件：** `post/production.py:82`
- **问题：** `total_dur = sum(float(s.get("duration", 4)) for s in shots)` 使用分镜原始 duration，未经 `clip_duration` 夹紧，也未使用实际视频时长。BGM 比视频短时，`mix_audio` 的 `-shortest` 会截断成片。
- **修复方向：** BGM 时长应基于拼接后视频的实际时长（probe concat 输出），或至少使用 `clip_duration` 夹紧后的值。

### 🟡 P2：无音频流视频导致 mix_audio 失败

- **文件：** `infra/ffmpeg.py:147`
- **问题：** `mix_audio` 的 filter_complex 硬编码 `[0:a]`，如果视频无音频流会直接报错。当前被上层 catch 降级跳过，但静音视频在制作中不算罕见。
- **修复方向：** 检测视频是否有音频流，无音频时用 `-f lavfi -i anullsrc` 补一条静音流，或用 `-map 0:v` 只取视频流。

### 🟡 P2：`_collect_videos` 排序键和目录匹配不够健壮

- **文件：** `post/production.py:34`
- **问题：** `re.search(r'\d+', p.name)` 只取第一个数字序列；`s*` glob 可能匹配非镜头目录。
- **修复方向：** 使用更严格的 shot 目录命名规范或正则匹配，如 `s\d+`；或从分镜表读取 shot_id 列表反向查找。

### 🟢 P3：`_rename_final` 残留文件风险

- **文件：** `post/production.py:105-107`
- **问题：** `copy2` 成功但 `unlink` 失败时，源文件残留。`_cleanup_and_update_db` 最终会清理，但磁盘紧张时中间状态可能有问题。
- **修复方向：** unlink 失败时记录 warning 日志而非静默 pass。
