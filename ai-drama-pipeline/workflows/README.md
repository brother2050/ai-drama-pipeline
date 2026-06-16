# ComfyUI 工作流模板

将 ComfyUI 导出的 API 格式 JSON 工作流放在此目录。

## 需要的文件

| 文件名 | 用途 | 对应后端 |
|--------|------|---------|
| `01_first_frame_sd15.json` | SD1.5 首帧生成 | `image_backend: sd15` |
| `01_first_frame_flux.json` | Flux 首帧生成 | `image_backend: flux` |
| `02_img2video.json` | AnimateDiff 视频生成 | `video_backend: animatediff` |
| `03_img2video_cogvideo.json` | CogVideoX 视频生成 | `video_backend: cogvideox` |

## 如何获取

1. 在 ComfyUI 中搭建工作流
2. 点击 **Save (API Format)** 导出 JSON
3. 重命名后放入此目录

## 节点命名约定

工作流中的节点会被自动识别：
- `LoadImage` / `LoadImageFromPath` / `ImageLoad` → 角色参考图注入
- `CLIPTextEncode` → Prompt 自动注入
- `IPAdapterAdvanced` → 角色一致性权重调整
- `KSampler` → 采样参数调整
