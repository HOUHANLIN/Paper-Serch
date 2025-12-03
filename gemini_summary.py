"""
命令行工具：通过 `google-genai` 调用 Gemini 模型，对任意文本生成总结。
你可以在此基础上生成针对文献的 AI 总结，并将生成的内容写入
`pubmed_bibtex.py` 产出的 BibTeX 条目中的 `annote` 字段。

依赖安装：
    pip install -r requirements.txt

运行前请在 .env 中配置：
    GEMINI_API_KEY=你的_API_Key
    GEMINI_MODEL=gemini-2.5-flash   # 或其他可用模型
    GEMINI_TEMPERATURE=0            # 可选
"""

import argparse
import os
from typing import Optional

from google import genai
from google.genai import types


def generate(
    prompt: str,
    model: str,
) -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Environment variable GEMINI_API_KEY is not set. "
            "Please export your Gemini API key before running this script."
        )

    client = genai.Client(api_key=api_key)

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
    ]

    # 温度从环境变量获取，尽量避免在脚本中写死配置
    temperature_str = os.environ.get("GEMINI_TEMPERATURE", "0")
    try:
        temperature = float(temperature_str)
    except ValueError:
        temperature = 0.0

    generate_content_config = types.GenerateContentConfig(temperature=temperature)

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        if chunk.text:
            print(chunk.text, end="", flush=True)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gemini 命令行客户端：从 --prompt 或标准输入读取文本，并流式输出模型结果。"
        )
    )
    parser.add_argument(
        "--prompt",
        "-p",
        help="提示词文本；若省略，则从标准输入读取。",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="模型名称；若为空则使用环境变量 GEMINI_MODEL。",
    )
    parser.add_argument(
        # 占位，无其它参数
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.prompt:
        prompt = args.prompt
    else:
        # 将标准输入的全部内容读入作为提示词
        prompt = ""
        for line in os.sys.stdin:
            prompt += line
        if not prompt.strip():
            raise SystemExit(
                "No prompt provided. Use --prompt or pipe text via stdin."
            )

    model = args.model or os.environ.get("GEMINI_MODEL")
    if not model:
        raise SystemExit(
            "错误: 未指定模型名称。请通过 --model 传入，或在 .env / 环境变量中设置 GEMINI_MODEL。"
        )

    generate(prompt=prompt, model=model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
