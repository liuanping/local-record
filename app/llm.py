"""LLM 客户端：对本地 llama-server（OpenAI 兼容 API）的封装。

提供健康检查与 chat 调用，以及三个业务封装：
摘要（summarize）、问答（ask）、时间定位（locate）。
"""
from __future__ import annotations

from typing import List

import httpx

from .logger import get_logger
from .utils import fmt_time

log = get_logger(__name__)


class LLMClient:
    def __init__(self, cfg: dict):
        server = cfg["llama_server"]
        self.base_url = f"http://{server['host']}:{server['port']}"
        self.max_new_tokens = int(server.get("max_new_tokens", 4096))
        # 上下文总量（要和 llama-server 的 -c 一致），用于给提示词留预算
        self.ctx_size = int(server.get("ctx_size", 16384))
        # 思维链开关（config.yaml: llama_server.enable_thinking）
        # 实测本机：关 29.9s / 开 71.1s，摘要质量提升有限 → 默认关
        self.enable_thinking = bool(server.get("enable_thinking", False))
        # 输出上限 4096 token 时，最长可能要生成好几分钟（本机 ~8 token/s），
        # 所以读超时给足；连不上时仍然 3 秒就报错
        self.timeout = httpx.Timeout(1800.0, connect=3.0)

    def _fit_to_context(self, user: str) -> str:
        """把过长的提示词裁进上下文预算（保留头尾，中间省略）。

        不裁的话，转写一长，llama-server 会因为超出 n_ctx 直接报错，
        用户看到的就是"生成失败"。宁可少喂一点也别失败。
        """
        budget = max(512, self.ctx_size - self.max_new_tokens - 256)
        if len(user) <= budget:
            return user
        keep = max(256, budget - 80)
        head_len = int(keep * 0.6)
        tail_len = keep - head_len
        omitted = len(user) - head_len - tail_len
        log.warning("提示词过长（%d 字 > 预算 %d 字），保留头尾、中间省略 %d 字",
                    len(user), budget, omitted)
        return (f"{user[:head_len]}\n\n"
                f"……（中间省略 {omitted} 字，转写过长）……\n\n{user[-tail_len:]}")

    def is_ready(self) -> bool:
        """快速健康检查（不抛异常）。"""
        try:
            r = httpx.get(f"{self.base_url}/v1/models", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, system: str, user: str) -> str:
        """单轮对话，返回模型回复文本。"""
        user = self._fit_to_context(user)
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.max_new_tokens,
            "temperature": 0.3,
            # 思维链由 config.yaml 的 llama_server.enable_thinking 控制（默认关）。
            # 关的原因：本机 CPU 推理下开 CoT 会先烧掉大量 token（实测 29.9s → 71.1s，
            # 摘要质量提升有限；4B 上更极端，32 token 全被思考吃掉、content 为空）。
            # 老版 llama-server 不认该参数会返回 400，已在下方降级重试。
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            r = client.post("/v1/chat/completions", json=payload)
            if r.status_code == 400 and "chat_template_kwargs" in payload:
                # 老版 llama-server 不认 chat_template_kwargs：去掉重试
                payload.pop("chat_template_kwargs")
                r = client.post("/v1/chat/completions", json=payload)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                # 兜底：thinking 未被禁用时取推理内容
                content = (msg.get("reasoning_content") or "").strip()
            return content

    # ---------------- 业务封装 ----------------

    @staticmethod
    def _transcript_text(segments: List[dict]) -> str:
        """把分段列表（{text,start,end}）格式化为带编号与时间戳的文本。"""
        lines = [f"[{i}] {fmt_time(s['start'])} {s['text']}"
                 for i, s in enumerate(segments, 1)]
        return "\n".join(lines)

    def summarize(self, segments: List[dict], template: str) -> str:
        if not segments:
            return "（还没有转写内容，先录一段再问吧）"
        return self.chat("你是本地录音转写助手。",
                         template.format(transcript=self._transcript_text(segments)))

    def ask(self, question: str, segments: List[dict], template: str) -> str:
        if not segments:
            return "（还没有转写内容，先录一段再问吧）"
        return self.chat(
            "你是本地录音转写助手。",
            template.format(transcript=self._transcript_text(segments),
                            question=question))

    def locate(self, question: str, segments: List[dict], template: str) -> str:
        """时间定位：让模型返回 [编号] 起始时间 文本，供 UI 高亮跳转。"""
        if not segments:
            return "（还没有转写内容，先录一段再问吧）"
        return self.chat(
            "你是本地录音转写助手。",
            template.format(transcript=self._transcript_text(segments),
                            question=question))

    # ---------------- OCR 文本的 LLM 处理 ----------------

    def summarize_ocr(self, text: str, template: str) -> str:
        if not text.strip():
            return "（还没有 OCR 内容，先识别一张图片或 PDF 吧）"
        return self.chat("你是本地 OCR 助手。", template.format(text=text))

    def ask_ocr(self, question: str, text: str, template: str) -> str:
        if not text.strip():
            return "（还没有 OCR 内容，先识别一张图片或 PDF 吧）"
        return self.chat(
            "你是本地 OCR 助手。",
            template.format(text=text, question=question))


def parse_locate_result(text: str) -> List[int]:
    """从时间定位结果里提取段落编号 [n]，供 UI 定位到对应转写行。"""
    import re
    return [int(m) for m in re.findall(r"\[(\d+)\]", text)]
