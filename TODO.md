# TODO

> 2026-06-07 后期合成逻辑链审查遗留项。

## 后期合成（post/production.py）审查 — 2026-06-07

### ~~🔴 P1：SRT 时间轴与拼接视频时间轴不同步~~ ✅ 已修复 (8b426bd)

- **文件：** `post/subtitle.py:33-34` vs `infra/transitions.py:82`
- **问题：** SRT 用 `clip_duration()` 整数，拼接视频用 `probe()` 实际时长。
- **修复：** `generate_srt` 新增 `video_durations` 参数；`run_post` 探测各镜头视频实际时长传入。

### ~~🔴 P1：BGM 总时长与实际视频总时长不一致~~ ✅ 已修复 (8b426bd)

- **文件：** `post/production.py:82`
- **问题：** BGM 用分镜原始 duration，`-shortest` 可能截断成片。
- **修复：** BGM 时长改为 probe 拼接视频的实际时长，回退 shot.duration。

### ~~🟡 P2：无音频流视频导致 mix_audio 失败~~ ✅ 已修复 (8b426bd)

- **文件：** `infra/ffmpeg.py:147`
- **问题：** `mix_audio` 硬编码 `[0:a]`，无音频流视频直接报错。
- **修复：** 检测视频是否有音频流，无音频时直接将 BGM 作为唯一音频流混合。

### 🟡 P2：`_collect_videos` 排序键和目录匹配不够健壮

- **文件：** `post/production.py:34`
- **状态：** 经评估非实际问题。`s*` glob + 数值排序符合项目约定，误匹配目录会被静默跳过。
- **结论：** YAGNI，不修改。

### ~~🟢 P3：`_rename_final` 残留文件风险~~ ✅ 已修复 (8b426bd)

- **文件：** `post/production.py:105-107`
- **修复：** unlink 失败记 warning 日志。
