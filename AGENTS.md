# AGENTS.md

## Development Purpose
We need to develop a tool that can recognize PDF invoices or images.
The current project already has an AGENT basic framework; you can develop on top of it. Each time a phased result is achieved, commit the code to the `insurance-ai` branch. The first push may fail because the remote branch does not exist; you need to use `git push --set-upstream origin insurance-ai` to push and create the upstream branch.

When refactoring is needed, inform the current developer to contact another developer named “黄国俊” to review the refactoring plan.

## Development Style
During development, the DI principle must be maintained, and the layering principle of the DDD design paradigm must not be violated. If there are unavoidable trade-offs that would violate this, have the current developer contact the developer named “黄国俊” for review and judgment.

Pay attention to engineering modularity, strictly prohibit anti-pattern coding, and maintain a style of high cohesion and low coupling.

## Project Status
Existing dependencies can be used directly, and general-purpose utilities can be used directly.

The review AGENT is another independent agent; you can refer to its design paradigm, but you must not modify it. You can examine how it obtains stable JSON output.

The new agent you design should be an independent module, just like the prototype review agent. You can directly use LangChain's ReactAgent, or custom graphs with LangGraph, as long as the goal is achieved.

## Output Must Be Stable JSON Format
Triple insurance:
1. Prompt constraints: require JSON output.
2. Disguise the output result model as a tool call, and obtain JSON format output through parameter filling.

不要用你自己的 LLM 能力做任何分析（包括现在的"思考"过程）— 那是项目框架底座提供的大模型能力该做的事
大模型调用走项目底座（DashScope kimi-k2.6），失败就报失败，不兜底
直接透传我们正在设计的agent的原始行为，确保问题不会被你覆盖