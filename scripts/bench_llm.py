"""LLM 基准测试：加载耗时 / 预填充 / 生成速度 / 内存占用（可对比不同 GGUF）。

用法::

    .venv\\Scripts\\python.exe scripts\\bench_llm.py                    # 测 config.yaml 里的模型
    .venv\\Scripts\\python.exe scripts\\bench_llm.py --list             # 列出候选 gguf
    .venv\\Scripts\\python.exe scripts\\bench_llm.py --all              # 逐个测（storage/models + build/models-test）
    .venv\\Scripts\\python.exe scripts\\bench_llm.py <任意路径.gguf>       # 测指定文件
    .venv\\Scripts\\python.exe scripts\\bench_llm.py <m.gguf> --server-args "-ctk q8_0 -ctv q8_0 -fa on"

    # 换用别的 llama-server（例如升级新版先试跑，确认没问题再覆盖 storage/）：
    $env:LLAMA_SERVER = "build\\llama-b11274\\llama-server.exe"
    .venv\\Scripts\\python.exe scripts\\bench_llm.py --all

测试内容与 app 一致（同样的 llama-server 参数、app 的摘要 prompt 模板风格）：
1. **冷启动耗时**：从拉起进程到 /v1/models 返回 200；
2. **真实摘要任务**：给一段中文会议转写做摘要，记录预填充/生成 tok/s、首字延迟、总耗时；
3. **进程峰值内存**（PeakWorkingSet64）——内存紧时模型会被换页，速度会掉，这里能看出来；
4. 顺带打印 GGUF 元数据（架构/层数/KV heads/模板），架构不被支持时一眼可见。

注意：每测完一个模型会自动停掉 llama-server，不会残留进程。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODELS_DIR = ROOT / "storage" / "models"
# 可用环境变量 LLAMA_SERVER 指向别的 llama-server（升级新版时先试跑，别急着覆盖）
SERVER = Path(os.environ.get(
    "LLAMA_SERVER",
    str(ROOT / "storage" / "bin" / "llama-server" / "llama-server.exe")))
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

# 与 app 的 prompts.summarize 同风格的真实任务（一段中文会议转写）
TRANSCRIPT = """[1] 00:00:03 大家好，今天我们过一下这个季度的交付情况。
[2] 00:00:18 第一个模块已经完成了联调，测试用例覆盖了百分之八十五。
[3] 00:00:35 第二个模块遇到一点阻塞，主要卡在第三方的接口联调上。
[4] 00:00:52 我们计划把风险同步给采购，下周三之前给出替代方案。
[5] 00:01:11 第三个模块按原计划下周上线，需要运维配合灰度发布。
[6] 00:01:29 另外客服反馈了两个线上问题，优先级比较高，本周内要修。
[7] 00:01:48 人力方面，小王下周休假三天，排期要往前挪一挪。
[8] 00:02:05 预算还剩百分之二十，主要用于压测环境的扩容。
[9] 00:02:22 下周一上午十点开复盘会，请大家提前把数据准备好。
[10] 00:02:40 好，今天就到这里，散会。"""

PROMPT = ("你是本地录音转写助手。下面是录音转写文本（每段带时间戳与编号）：\n"
          f"{TRANSCRIPT}\n"
          "请用中文输出一段简洁摘要（300 字以内），并分点列出关键信息。")


def list_models() -> list[Path]:
    out = [p.resolve() for p in sorted(MODELS_DIR.glob("*.gguf"))]
    extra = ROOT / "build" / "models-test"
    if extra.is_dir():
        out += [p.resolve() for p in sorted(extra.glob("*.gguf"))]
    return out


def start_server(model: Path, port: int = 8099,
                 extra: list[str] | None = None) -> tuple[subprocess.Popen, float]:
    """按 app 的参数启动 llama-server，返回 (进程, 冷启动秒数)。

    ``extra`` 用于追加参数，例如 KV 量化 + flash attention：
    ``["-ctk", "q8_0", "-ctv", "q8_0", "-fa", "on"]``
    """
    args = [str(SERVER), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
            "-c", str(CFG["llama_server"].get("ctx_size", 8192)),
            "-ngl", str(CFG["llama_server"].get("gpu_layers", 0))]
    threads = int(CFG["llama_server"].get("threads", 0))
    if threads > 0:
        args += ["-t", str(threads)]
    args += [str(a) for a in CFG["llama_server"].get("extra_args", [])]
    args += list(extra or [])
    tag_new = "-new" if "b11274" in str(SERVER) else ""
    log = ROOT / "build" / f"bench-{model.stem}{tag_new}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log, "w", encoding="utf-8", errors="replace")
    t0 = time.monotonic()
    proc = subprocess.Popen(args, cwd=str(SERVER.parent), stdout=fh, stderr=fh,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server 退出（code={proc.returncode}），见 {log}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=2.0).status_code == 200:
                return proc, time.monotonic() - t0
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError("等待就绪超时")


def stop_server(proc: subprocess.Popen, port: int) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)


def peak_working_set(proc: subprocess.Popen) -> int:
    """进程峰值工作集（字节）——内存不够时会被换页，速度会掉。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Id {proc.pid}).PeakWorkingSet64"],
            capture_output=True, text=True, timeout=20)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0


def run_prompt(port: int, max_tokens: int = 160) -> dict:
    payload = {
        "messages": [{"role": "system", "content": "你是本地录音转写助手。"},
                     {"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.monotonic()
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=600.0) as c:
        r = c.post("/v1/chat/completions", json=payload)
        if r.status_code == 400 and "chat_template_kwargs" in payload:
            payload.pop("chat_template_kwargs")
            r = c.post("/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
    wall = time.monotonic() - t0
    t = data.get("timings", {}) or {}
    text = (data["choices"][0]["message"].get("content") or "").strip()
    return {
        "wall": wall,
        "prompt_n": t.get("prompt_n", 0),
        "prefill_tps": t.get("prompt_per_second", 0.0),
        "gen_n": t.get("predicted_n", 0),
        "decode_tps": t.get("predicted_per_second", 0.0),
        "ttft": (t.get("prompt_ms", 0)
                 + t.get("predicted_ms", 0) / max(1, t.get("predicted_n", 1))) / 1000.0,
        "sample": text,
    }


def bench(model: Path, port: int = 8099, extra: list[str] | None = None,
          tag: str = "") -> dict | None:
    size_gb = model.stat().st_size / (1024 ** 3)
    label = f"{model.name}{(' [' + tag + ']') if tag else ''}"
    print(f"\n{'='*78}\n模型: {label}  ({size_gb:.2f} GB)"
          f"\nllama-server: {SERVER}\n{'='*78}", flush=True)
    # 先看 GGUF 元数据：架构/预分词不被支持的话，加载必然失败，先给出可读结论
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from gguf_meta import describe
        info = describe(model)
        print(f"  GGUF: arch={info['architecture']} ctx={info['ctx_length']} "
              f"layers={info['block_count']} kv_heads={info['kv_heads']} "
              f"模板={'有' if info['has_chat_template'] else '无'}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  GGUF 元数据读取失败: {type(e).__name__}: {e}", flush=True)

    proc = None
    try:
        proc, load_s = start_server(model, port, extra)
        print(f"  冷启动到就绪: {load_s:.1f}s", flush=True)
        res = run_prompt(port)
        res.update(model=model.name, tag=tag, size_gb=size_gb, load_s=load_s,
                   peak_ws=peak_working_set(proc),
                   server=f"{SERVER.name} @ {SERVER.parent.name}")
        print(f"  预填充: {res['prefill_tps']:.1f} tok/s ({res['prompt_n']} tok)"
              f" | 生成: {res['decode_tps']:.2f} tok/s ({res['gen_n']} tok)"
              f" | 首字 {res['ttft']:.1f}s | 总耗时 {res['wall']:.1f}s", flush=True)
        print(f"  峰值内存: {res['peak_ws']/1024**3:.2f} GB", flush=True)
        print("  ---- 输出 ----")
        for line in res["sample"].splitlines()[:16]:
            print("  " + line)
        return res
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {e}")
        log = ROOT / "build" / f"bench-{model.stem}.log"
        if log.is_file():
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-6:]
            print("  ---- llama-server 日志尾部 ----")
            for line in tail:
                print("  " + line)
        return None
    finally:
        if proc is not None:
            stop_server(proc, port)
            time.sleep(1.0)


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--list" in args:
        for m in list_models():
            print(f"{m.name}  ({m.stat().st_size/1024**3:.2f} GB)")
        return 0

    # --server-args "-ctk q8_0 -ctv q8_0 -fa on" → 追加给 llama-server 的参数
    extra: list[str] = []
    tag = ""
    if "--server-args" in args:
        i = args.index("--server-args")
        extra = args[i + 1].split()
        tag = args[i + 1]
        args = args[:i] + args[i + 2:]

    names = [a for a in args if not a.startswith("--")]
    if "--all" in args:
        targets = list_models()
    elif names:
        # 支持「storage/models 下的文件名」或「任意路径」；必须 resolve()：
        # llama-server 的 cwd 是它自己的目录，相对路径会解析错位
        targets = [(Path(n) if Path(n).is_file() else MODELS_DIR / n).resolve()
                   for n in names]
    else:
        targets = [(MODELS_DIR / CFG["model"]["filename"]).resolve()]

    missing = [t for t in targets if not t.is_file()]
    if missing:
        print(f"找不到模型: {[str(m) for m in missing]}")
        return 1
    if not SERVER.is_file():
        print(f"找不到 llama-server: {SERVER}")
        return 1

    results = [r for r in (bench(m, extra=extra, tag=tag) for m in targets) if r]
    if len(results) > 1:
        print(f"\n{'='*78}\n汇总（tok/s 越大越快，内存越小越好）\n{'='*78}")
        print(f"{'模型':<40}{'体积':>7}{'冷启动':>9}{'预填充':>11}{'生成':>10}{'峰值内存':>10}")
        for r in sorted(results, key=lambda x: x["size_gb"]):
            name = r["model"] + (f" [{r['tag']}]" if r["tag"] else "")
            print(f"{name:<40}{r['size_gb']:>6.2f}G{r['load_s']:>8.1f}s"
                  f"{r['prefill_tps']:>9.1f}t/s{r['decode_tps']:>8.2f}t/s"
                  f"{r['peak_ws']/1024**3:>9.2f}G")
    out = ROOT / "build" / "bench-llm-results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
