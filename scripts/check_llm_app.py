"""走 app 真实链路的 LLM 自检（配置 → llama-server → LLM 摘要）。

用法::

    .venv\\Scripts\\python.exe scripts\\check_llm_app.py           # 用 config.yaml 的模型与参数
    .venv\\Scripts\\python.exe scripts\\check_llm_app.py --no-start # 只发请求（服务已在跑）

和 :mod:`scripts.bench_llm` 的区别：bench 是"跑分"（自己也拼 prompt），
本脚本用的是 **app 自己的类**（``app.llama_server.LlamaServer`` +
``app.llm.LLMClient`` + config 里的 prompt 模板），所以能验证：

* config.yaml 的 ``model.filename`` / ``extra_args`` 等改动真的被应用读到；
* 加载耗时与摘要质量就是用户在界面上会得到的那个；
* 摘要 prompt 模板与分段格式（[编号] HH:MM:SS 文本）能正常喂给模型。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config as config_mod  # noqa: E402
from app.llama_server import LlamaServer  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.paths import storage_dir  # noqa: E402

# 带时间戳的真实会议转写（与界面上传出的分段格式一致）
SEGMENTS = [
    {"text": "大家好，今天我们过一下这个季度的交付情况。", "start": 3.2, "end": 9.0},
    {"text": "第一个模块已经完成了联调，测试用例覆盖了百分之八十五。", "start": 18.6, "end": 26.0},
    {"text": "第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。", "start": 35.1, "end": 43.0},
    {"text": "我们计划把风险同步给采购，下周三之前给出替代方案。", "start": 52.4, "end": 60.0},
    {"text": "第三个模块按原计划下周上线，需要运维配合灰度发布。", "start": 71.8, "end": 79.0},
    {"text": "另外客服反馈了两个线上问题，优先级比较高，本周内要修。", "start": 89.0, "end": 97.0},
    {"text": "人力方面，小王下周休假三天，排期要往前挪一挪。", "start": 108.0, "end": 115.0},
    {"text": "预算还剩百分之二十，主要用于压测环境的扩容。", "start": 125.0, "end": 132.0},
    {"text": "下周一上午十点开复盘会，请大家提前把数据准备好。", "start": 142.0, "end": 150.0},
    {"text": "好，今天就到这里，散会。", "start": 160.0, "end": 165.0},
]


def main() -> int:
    cfg = config_mod.load_config()
    print(f"模型: {cfg['model']['filename']}")
    print(f"llama_server.extra_args: {cfg['llama_server'].get('extra_args')}")
    print(f"ctx_size: {cfg['llama_server'].get('ctx_size')}")

    server = None
    started = False
    if "--no-start" not in sys.argv:
        server = LlamaServer(cfg, storage_dir())
        t0 = time.monotonic()
        server.start()

        def on_progress(frac: float) -> None:
            pct = int(frac * 100)
            if pct % 25 < 3:
                print(f"  加载中 {pct}%  ({time.monotonic() - t0:.0f}s)", flush=True)

        try:
            ok = server.wait_until_ready(on_progress=on_progress)
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] 加载失败: {type(e).__name__}: {e}")
            return 1
        started = ok
        print(f"就绪，用时 {time.monotonic() - t0:.1f}s")
    else:
        print("（--no-start：假定服务已在运行）")

    try:
        client = LLMClient(cfg)
        print(f"健康检查 /v1/models: {client.is_ready()}")
        t1 = time.monotonic()
        summary = client.summarize(SEGMENTS, cfg["prompts"]["summarize"])
        dt = time.monotonic() - t1
        print(f"\n摘要耗时 {dt:.1f}s（{len(summary)} 字）：\n{'-'*66}")
        print(summary)
        print("-" * 66)

        t2 = time.monotonic()
        answer = client.ask("这周的交付风险有哪些？", SEGMENTS, cfg["prompts"]["qa"])
        print(f"\n问答耗时 {time.monotonic() - t2:.1f}s：\n{'-'*66}")
        print(answer)
        print("-" * 66)

        bad = (not summary.strip()) or ("还没有转写内容" in summary)
        print("\n[PASS] 真实链路可用" if not bad else "\n[FAIL] 摘要为空")
        return 0 if not bad else 1
    finally:
        if server is not None and started:
            server.stop()
            print("llama-server 已停止")


if __name__ == "__main__":
    sys.exit(main())
