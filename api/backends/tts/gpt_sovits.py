"""GPT-SoVITS TTS — HTTP API 语音克隆（V2 端点）

仅支持 api_v2.py（POST /tts）。

voice_config 参数:
  reference_audio: 参考音频路径（必填，服务器本地路径或 URL）
  aux_ref_audio_paths: 辅助参考音频路径列表（可选，多人音色融合）
  prompt_text: 参考音频对应的文本（可选，提升音色一致性）
  prompt_lang: 参考音频语言（默认同 text language）
  speed_factor: 语速因子（默认 1.0）
  top_k: top-k 采样（默认 15）
  top_p: nucleus 采样（默认 1.0）
  temperature: 温度（默认 1.0）
  batch_size: 批大小（默认 1）
  batch_threshold: 批次拆分阈值（默认 0.75）
  split_bucket: 是否分桶（默认 True）
  fragment_interval: 音频片段间隔（默认 0.3）
  seed: 随机种子，-1 为随机（默认 -1）
  parallel_infer: 是否并行推理（默认 True）
  repetition_penalty: 重复惩罚（默认 1.35）
  sample_steps: VITS V3 采样步数（默认 32）
  super_sampling: V3 超采样（默认 False）
  streaming_mode: 流式模式 0/1/2/3 或 bool（默认 False）
  overlap_length: 流式语义 token 重叠长度（默认 2）
  min_chunk_length: 流式最小 chunk 长度（默认 16）
  media_type: 输出格式 wav/ogg/aac/raw（默认 wav）
  text_split_method: 文本分割方法（默认 cut5）
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path

from api.registry import BackendMeta, registry
from infra.http_pool import get_client

logger = logging.getLogger(__name__)

# GPT-SoVITS 参考音频要求 3–10 秒，超过时自动裁剪到目标时长
_REF_MAX_DURATION = 10.0
_REF_TARGET_DURATION = 8.0
_REF_TRIM_START = 0.5  # 跳过开头可能的静音


def upload_audio(api_url: str, file_path: str | Path, filename: str | None = None) -> str:
    """上传音频到 GPT-SoVITS /upload_refer，返回服务器路径。失败返回空串。

    共享函数：GptSovits 后端和 Web 路由共用，消除重复上传逻辑。
    """
    from infra.http_pool import get_client
    file_path = Path(file_path)
    if not filename:
        filename = file_path.name
    try:
        client = get_client(timeout=30)
        with open(file_path, "rb") as f:
            resp = client.post(
                f"{api_url.rstrip('/')}/upload_refer",
                files={"file": (filename, f.read())},
                params={"name": filename},
            )
        if resp.status_code == 200:
            server_path = resp.json().get("path", "")
            if server_path:
                return server_path
        logger.warning(f"上传参考音频失败 (HTTP {resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"上传参考音频异常: {e}")
    return ""


class GptSovits:
    """GPT-SoVITS TTS 后端（V2 API: POST /tts）"""

    def __init__(self, config: dict):
        self._url = config.get("api_url", "").rstrip("/")
        if not self._url:
            raise ValueError(
                "GPT-SoVITS api_url 未配置，请在 system.yaml 的 models.gpt_sovits.api_url 中设置\n"
                "示例: http://127.0.0.1:9880"
            )
        # 参考音频目录：纯文件名自动拼接此前缀（GPT-SoVITS API 要求绝对路径）
        # 可在 system.yaml 的 models.gpt_sovits.refs_dir 中覆盖
        self._refs_dir = config.get("refs_dir", "/workspace/refs").rstrip("/")
        self._timeout = config.get("timeouts", {}).get("tts", 60)
        self._client = get_client(timeout=self._timeout)
        self._fast_client = get_client(timeout=3)

    @property
    def name(self) -> str:
        return "gpt-sovits"

    # ── 参考音频预处理 ──────────────────────────────────────────

    @staticmethod
    def _get_audio_duration(path: str) -> float | None:
        """获取音频时长（秒），失败返回 None"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return None

    @staticmethod
    def _trim_audio(input_path: str, output_path: str,
                    start: float = _REF_TRIM_START,
                    duration: float = _REF_TARGET_DURATION) -> bool:
        """用 ffmpeg 裁剪音频，返回是否成功"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", input_path,
                 "-ss", str(start), "-t", str(duration),
                 "-acodec", "pcm_s16le", output_path],
                capture_output=True, text=True, timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _prepare_ref_audio(self, local_path: Path) -> Path:
        """检查并裁剪参考音频：超过 _REF_MAX_DURATION 则自动裁剪，返回可直接上传的临时文件。

        原始文件不会被修改，裁剪结果写入临时文件。
        """
        duration = self._get_audio_duration(str(local_path))
        if duration is None:
            logger.warning(f"无法获取音频时长，使用原始文件: {local_path}")
            return local_path
        if duration <= _REF_MAX_DURATION:
            return local_path

        # 超出时长 → 自动裁剪
        tmp = tempfile.NamedTemporaryFile(suffix=local_path.suffix, delete=False)
        tmp_path = tmp.name
        tmp.close()

        ok = self._trim_audio(str(local_path), tmp_path)
        if not ok:
            Path(tmp_path).unlink(missing_ok=True)
            logger.warning(f"音频裁剪失败，使用原始文件: {local_path}")
            return local_path

        # 校验裁剪结果
        new_dur = self._get_audio_duration(tmp_path)
        logger.info(
            f"✂️ 参考音频自动裁剪: {duration:.1f}s → {new_dur:.1f}s\n"
            f"  原始: {local_path}\n"
            f"  裁剪: {tmp_path}"
        )
        return Path(tmp_path)

    # ── 路径解析 + 自动上传 ─────────────────────────────────────

    # 上传结果缓存：本地绝对路径 → 服务器路径（避免同一文件重复上传）
    _upload_cache: dict[str, str] = {}

    # list_refers 缓存：避免重复请求
    _refs_info_cache: tuple[float, list[dict]] | None = None  # (timestamp, files)

    def _get_refs_info(self) -> list[dict]:
        """获取服务器上的参考音频列表（带 30s 缓存）"""
        import time
        now = time.time()
        if self._refs_info_cache and (now - self._refs_info_cache[0]) < 30:
            return self._refs_info_cache[1]
        try:
            resp = self._fast_client.get(f"{self._url}/list_refers")
            if resp.status_code == 200:
                files = resp.json().get("files", [])
                self._refs_info_cache = (now, files)
                return files
        except Exception:
            pass
        return []

    @staticmethod
    def _find_local_ref_copy(basename: str) -> Path | None:
        """在项目 assets 目录中搜索本地音频副本。

        策略：
        1. 先按 basename 精确匹配
        2. 若未匹配，从 basename 提取可能的角色名（如 "路飞_ref.wav"→"路飞"），
           查找 assets/characters/{角色名}/voice/ref.wav
        """
        import glob as _glob
        from infra.config.resolver import get_root
        candidate_dirs = [get_root()]
        for root in candidate_dirs:
            # 策略 1: 精确匹配 basename
            pattern = str(root / "projects" / "*" / "assets" / "characters" / "*" / "voice" / basename)
            for match in _glob.glob(pattern):
                p = Path(match)
                if p.is_file():
                    return p

            # 策略 2: 从服务器文件名推断角色名 → 查找 ref.wav
            # 常见模式: {角色名}_ref.wav, {角色名}-ref.wav
            stem = Path(basename).stem
            for sep in ("_ref", "-ref", "_reference"):
                if stem.endswith(sep):
                    char_name = stem[:-len(sep)]
                    if char_name:
                        ref_pattern = str(
                            root / "projects" / "*" / "assets" / "characters"
                            / char_name / "voice" / "ref.wav"
                        )
                        for match in _glob.glob(ref_pattern):
                            p = Path(match)
                            if p.is_file():
                                return p
                    break  # 只尝试第一个匹配的分隔符
        return None

    def _do_upload(self, upload_file: Path, source_path: str,
                   overwrite_name: str | None = None) -> str:
        """上传音频到 GPT-SoVITS 服务器，返回服务器路径。失败返回空串。"""
        ext = upload_file.suffix
        if overwrite_name:
            fname = overwrite_name
        else:
            path_hash = hashlib.md5(source_path.encode()).hexdigest()[:8]
            fname = f"auto_{Path(source_path).stem}_{path_hash}{ext}"
        server_path = upload_audio(self._url, upload_file, fname)
        if not server_path:
            logger.warning(f"自动上传参考音频失败: {source_path}")
        return server_path

    def _resolve_path(self, path: str) -> str:
        """归一化音频路径 → GPT-SoVITS 服务器可访问的路径"""
        if not path:
            return path
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            # 短文件名 → 拼接 refs_dir
            return f"{self._refs_dir}/{path}"

        # 本地服务器：绝对路径直接可用
        if self._url.startswith(("http://127.0.0.1", "http://localhost")):
            return path

        # ── 远程服务器场景 ──
        # 已在 refs_dir 下的路径：检查服务器端是否超长，尝试查找本地副本并裁剪上传
        if path.startswith(self._refs_dir + "/"):
            return self._resolve_refs_dir_path(path)

        # 如果路径不在本地存在 → 可能是服务器路径，直接返回
        local_file = Path(path)
        if not local_file.is_file():
            return path

        # 命中缓存 → 直接返回之前的上传结果
        if path in self._upload_cache:
            return self._upload_cache[path]

        # ── 本地文件 + 远程服务器 → 自动裁剪并上传 ──
        upload_file = self._prepare_ref_audio(local_file)
        is_tmp = upload_file != local_file
        try:
            server_path = self._do_upload(upload_file, path)
            if server_path:
                self._upload_cache[path] = server_path
                logger.info(
                    f"✅ 已自动上传参考音频到 GPT-SoVITS 服务器:\n"
                    f"  本地: {path}\n"
                    f"  服务器: {server_path}"
                )
                return server_path
        finally:
            if is_tmp:
                upload_file.unlink(missing_ok=True)

        # 上传失败，返回原路径（让后续 TTS 调用报出明确错误）
        return path

    def _resolve_refs_dir_path(self, server_path: str) -> str:
        """处理已在 refs_dir 下的路径：检查服务器端文件是否超长，
        若超长则尝试查找本地副本进行裁剪并覆盖上传。
        """
        basename = Path(server_path).name

        # 1. 检查服务器端文件大小（通过 list_refers 缓存）
        refs = self._get_refs_info()
        server_info = None
        for r in refs:
            if r.get("path") == server_path or r.get("name") == basename:
                server_info = r
                break

        # 粗略估算：44100Hz 16-bit mono ≈ 88KB/s，10s ≈ 880KB
        # 使用宽松阈值 500KB 作为"需要检查"的信号
        _SIZE_HINT_THRESHOLD = 500_000
        server_size = server_info.get("size", 0) if server_info else 0

        if server_size > 0 and server_size <= _SIZE_HINT_THRESHOLD:
            # 文件不大，应该没问题，直接使用
            return server_path

        # 2. 查找本地副本
        local_file = self._find_local_ref_copy(basename)
        if local_file is None:
            if server_size > _SIZE_HINT_THRESHOLD:
                logger.warning(
                    f"⚠️ 服务器参考音频可能超长:\n"
                    f"  {server_path} ({server_size/1024:.0f}KB)\n"
                    f"  GPT-SoVITS 要求参考音频在 3-10 秒内。\n"
                    f"  未找到本地副本，无法自动裁剪。建议将角色 YAML 的\n"
                    f"  reference_audio 改为本地文件路径。"
                )
            return server_path

        # 3. 本地副本存在 → 裁剪并覆盖上传到服务器
        upload_file = self._prepare_ref_audio(local_file)
        is_tmp = upload_file != local_file
        try:
            server_result = self._do_upload(upload_file, server_path,
                                            overwrite_name=basename)
            if server_result:
                self._upload_cache[server_path] = server_result
                logger.info(
                    f"✅ 已自动裁剪并覆盖上传服务器参考音频:\n"
                    f"  服务器: {server_path}\n"
                    f"  本地源: {local_file}\n"
                    f"  结果: {server_result}"
                )
                return server_result
        finally:
            if is_tmp:
                upload_file.unlink(missing_ok=True)

        # 上传失败，回退到原路径
        return server_path

    def synthesize(self, text: str, output: str, *,
                   voice_config: dict | None = None, emotion: str = "neutral",
                   language: str = "zh") -> str:
        voice_config = voice_config or {}
        ref_audio = voice_config.get("reference_audio", "")
        if not ref_audio:
            raise ValueError(
                "GPT-SoVITS 需要 reference_audio（参考音频路径）。\n"
                "请在角色配置的 voice.reference_audio 中设置。\n"
                "路径为 GPT-SoVITS 服务器上的本地文件路径或 HTTP URL。"
            )

        # 归一化路径 → GPT-SoVITS 服务器可访问的路径
        # - 短文件名: 拼接 refs_dir（如 "ref.wav" → "/workspace/refs/ref.wav"）
        # - HTTP URL: 直接使用
        # - 绝对路径: 仅当 refs_dir 未配置时保留原路径（本地部署场景）
        #   远程服务器 + 本地绝对路径 = 无法访问，需用户手动将音频上传到服务器
        ref_audio = self._resolve_path(ref_audio)

        # 辅助音频同样归一化
        aux_paths = voice_config.get("aux_ref_audio_paths") or []
        if aux_paths:
            aux_paths = [self._resolve_path(p) for p in aux_paths if p]

        Path(output).parent.mkdir(parents=True, exist_ok=True)
        if emotion != "neutral":
            logger.debug(f"GPT-SoVITS 不支持 emotion 参数，已忽略 (emotion={emotion})")

        # ── 构造 payload，覆盖全部 API 参数 ──────────────────────
        payload = {
            # 必填
            "text": text,
            "text_lang": language,
            "ref_audio_path": ref_audio,

            # 参考音频文本
            "prompt_text": voice_config.get("prompt_text", ""),
            "prompt_lang": voice_config.get("prompt_lang", language),

            # 多参考音频融合
            "aux_ref_audio_paths": aux_paths,

            # 采样控制
            "top_k": int(voice_config.get("top_k", 15)),
            "top_p": float(voice_config.get("top_p", 1.0)),
            "temperature": float(voice_config.get("temperature", 1.0)),
            "repetition_penalty": float(voice_config.get("repetition_penalty", 1.35)),

            # 随机种子
            "seed": int(voice_config.get("seed", -1)),

            # 文本分割
            "text_split_method": voice_config.get("text_split_method", "cut5"),

            # 批处理
            "batch_size": int(voice_config.get("batch_size", 1)),
            "batch_threshold": float(voice_config.get("batch_threshold", 0.75)),
            "split_bucket": bool(voice_config.get("split_bucket", True)),

            # 语速与片段间隔
            "speed_factor": float(voice_config.get("speed_factor", 1.0)),
            "fragment_interval": float(voice_config.get("fragment_interval", 0.3)),

            # 推理模式
            "parallel_infer": bool(voice_config.get("parallel_infer", True)),

            # VITS V3 模型
            "sample_steps": int(voice_config.get("sample_steps", 32)),
            "super_sampling": bool(voice_config.get("super_sampling", False)),

            # 输出格式与流式
            "media_type": voice_config.get("media_type", "wav"),
            "streaming_mode": voice_config.get("streaming_mode", False),

            # 流式模式专属
            "overlap_length": int(voice_config.get("overlap_length", 2)),
            "min_chunk_length": int(voice_config.get("min_chunk_length", 16)),
        }
        # ─────────────────────────────────────────────────────────

        endpoint = f"{self._url}/tts"

        with self._client.stream("POST", endpoint, json=payload) as r:
            if r.status_code in (400, 422):
                error_body = b"".join(r.iter_bytes())
                try:
                    import json
                    err = json.loads(error_body)
                    detail = err.get("message") or err.get("detail") or err.get("error") or error_body.decode()
                    raise RuntimeError(
                        f"GPT-SoVITS 合成失败 (HTTP {r.status_code}): {detail}\n"
                        f"  ref_audio_path: {ref_audio}\n"
                        f"  text_lang: {language}\n"
                        f"  text: {text[:50]}..."
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise RuntimeError(f"GPT-SoVITS 合成失败 (HTTP {r.status_code}): {error_body[:200]}")
            r.raise_for_status()
            content = b"".join(r.iter_bytes())

        if len(content) < 100:
            raise RuntimeError(f"GPT-SoVITS 返回音频过小 ({len(content)} bytes)，可能合成失败")

        from infra.config import atomic_write_bytes
        atomic_write_bytes(output, content)
        return output

    def health_check(self) -> tuple[bool, str]:
        from api.backends import http_health_check
        return http_health_check(self._url, self._fast_client, "GPT-SoVITS", path="/list_refers")

    def shutdown(self) -> None:
        pass


def _factory(config: dict) -> GptSovits:
    return GptSovits(config)


registry.register(BackendMeta(
    name="gpt-sovits", service_type="tts", factory=_factory,
    description="GPT-SoVITS 语音克隆（V2 API）", priority=50, tags=["api"],
))
