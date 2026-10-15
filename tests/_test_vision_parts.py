# -*- coding: utf-8 -*-
"""图片入站映射（vision）—— 上游到底从哪个字段取图。

背景（2026-10-15 实测，探针 _output/vision_upstream_probe.py 三变体）：
  · 只写 body.image_urls + chat_context.imageUrls（本仓改动前的行为）
      → 模型答「没有收到任何图片」，prompt_tokens 与纯文本一致（2618 vs 2613）
  · 图片写进 messages[].content 的 OpenAI parts
      → 模型正确数出 3 苹果 / 1 梨 / 卡片 7423，prompt_tokens 2618→3388
  · 两处都写
      → prompt_tokens 仍是 3388（上游忽略 image_urls，**不会重复计费**）
所以修复面只有一处：带图且目标模型 is_vl 时，content 保留 parts 列表；
image_urls 继续照写（官方模板形态不变，且实测无害）。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _suite_head import *  # noqa: F401,F403
declare_suite(__file__, ["qoder_proxy.py", "qoder_anthropic.py"])

P, A = bootstrap()

URL_A = "data:image/png;base64,AAA"
URL_B = "https://example.com/x.png"
Q = "图里有几个苹果？"


def _user_msg(content):
    return {"role": "user", "content": content}


def _body(model_key, messages):
    return P.build_qoder_body({"model": model_key, "messages": messages},
                              None, model_key, realm="cn")


def _last(body):
    return body["messages"][-1]


def _parts(body):
    c = _last(body)["content"]
    return c if isinstance(c, list) else []


print("[vision] 图片入站映射")
print()

# ---- 1. 命门：视觉模型 -> parts ----
b = _body("qfmodel", [_user_msg([{"type": "text", "text": Q},
                                 {"type": "image_url",
                                  "image_url": {"url": URL_A}}])])
check("#V-1 【命门】qfmodel(is_vl) 带图 -> content 是 parts 列表（改动前是字符串，图被丢掉）",
      isinstance(_last(b)["content"], list), _last(b))
check("#V-2 parts 里 text 与 image_url 各一、URL 逐字节不变",
      [p.get("type") for p in _parts(b)] == ["text", "image_url"]
      and _parts(b)[1]["image_url"]["url"] == URL_A, _parts(b))
check("#V-3 image_urls 与 chat_context.imageUrls 照旧写入（官方模板形态不变）",
      b.get("image_urls") == [URL_A]
      and (b["chat_context"].get("imageUrls") or []) == [URL_A], b.get("image_urls"))
check("#V-4 文本部分仍是原句（没有被 parts 化流程吃掉）",
      _parts(b)[0]["text"] == Q, _parts(b))

# ---- 2. 非视觉模型 / 纯文本：行为逐字不变 ----
b2 = _body("mmodel", [_user_msg([{"type": "text", "text": Q},
                                 {"type": "image_url",
                                  "image_url": {"url": URL_A}}])])
check("#V-5 非视觉模型(is_vl=false) -> content 仍是字符串（改动前行为，不新增上游拒答面）",
      isinstance(_last(b2)["content"], str), _last(b2))
b3 = _body("qfmodel", [_user_msg(Q)])
check("#V-6 视觉模型 + 纯文本请求 -> content 仍是字符串（无图不引入 parts）",
      isinstance(_last(b3)["content"], str), _last(b3))

# ---- 3. 下游取文本的两处不能拿到 list ----
check("#V-7 chat_context.text.text 取到的是文本而非 list（回归 prompt 的 list 分支）",
      (b["chat_context"].get("text") or {}).get("text") == Q,
      b["chat_context"].get("text"))
check("#V-8 business.name 同样只含文本",
      Q in str((b.get("business") or {}).get("name") or ""),
      (b.get("business") or {}).get("name"))

# ---- 4. 多图 / 无文本 / 多轮 ----
bm = _body("qfmodel", [_user_msg([{"type": "image_url", "image_url": {"url": URL_A}},
                                  {"type": "image_url", "image_url": {"url": URL_B}}])])
check("#V-9 无文本、两张图 -> parts 只含两个 image_url 且顺序保留",
      [p.get("type") for p in _parts(bm)] == ["image_url", "image_url"]
      and _parts(bm)[1]["image_url"]["url"] == URL_B, _parts(bm))
check("#V-10 无文本时 image_urls 也收齐两张（与 parts 同源）",
      bm.get("image_urls") == [URL_A, URL_B], bm.get("image_urls"))
bt = _body("qfmodel", [_user_msg([{"type": "text", "text": "第一轮看图"},
                                  {"type": "image_url",
                                   "image_url": {"url": URL_A}}]),
                       {"role": "assistant", "content": "三个"},
                       _user_msg("第二个问题")])
check("#V-11 多轮：历史轮的图保留 parts，当前轮纯文本不受影响",
      isinstance(bt["messages"][1]["content"], list)
      and bt["messages"][3]["content"] == "第二个问题",
      [m.get("content") for m in bt["messages"][1:2]])
check("#V-12 历史轮图片仍进 image_urls（跨轮重放时上游拿得到）",
      bt.get("image_urls") == [URL_A], bt.get("image_urls"))

# ---- 5. system 抽取不受影响 ----
bs = _body("qfmodel", [{"role": "system", "content": "只看图说话"},
                       _user_msg([{"type": "text", "text": Q},
                                  {"type": "image_url",
                                   "image_url": {"url": URL_A}}])])
check("#V-13 带 system + 图：system 仍被抽成模板替换源，图仍在 parts",
      bs["messages"][0] == {"role": "system", "content": "只看图说话"}
      and isinstance(_last(bs)["content"], list), bs["messages"][0])

# ---- 6. flatten_messages 单元层：vision 开关与 images 收集 ----
sys_t, flat, imgs = P.flatten_messages(
    [_user_msg([{"type": "text", "text": Q},
                {"type": "image_url", "image_url": {"url": URL_A}}])], vision=True)
check("#V-14 flatten(vision=True) -> content 为 list 且 images 仍照旧收集（两条路同源）",
      isinstance(flat[0]["content"], list) and imgs == [URL_A], (flat, imgs))
sys_t2, flat2, imgs2 = P.flatten_messages(
    [_user_msg([{"type": "text", "text": Q},
                {"type": "image_url", "image_url": {"url": URL_A}}])])
check("#V-15 flatten(默认 vision=False) -> 与改动前逐字一致（str + 仍收集 images）",
      isinstance(flat2[0]["content"], str) and imgs2 == [URL_A], (flat2, imgs2))
_, flat3, _ = P.flatten_messages([{"role": "weird", "content": [
    {"type": "image_url", "image_url": {"url": URL_A}}]}], vision=True)
check("#V-16 未知角色降级为 user 时也不丢图（parts 同样保留）",
      flat3[0]["role"] == "user" and isinstance(flat3[0]["content"], list), flat3)

# ---- 7. 另外两条入口最终汇到同一 flatten ----
rchat = P.responses_to_chat({"model": "qfmodel", "input": [
    {"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": Q},
        {"type": "input_image", "image_url": URL_A}]}]})
br = _body("qfmodel", rchat["messages"])
check("#V-17 Responses 入口 input_image -> 出站同样是 parts（三入口共用一次修复）",
      isinstance(_last(br)["content"], list)
      and URL_A in [p.get("image_url", {}).get("url") for p in _parts(br)],
      (rchat["messages"], _parts(br)))

import qoder_anthropic as AN
achat = AN.messages_to_chat({"model": "qfmodel", "max_tokens": 64, "messages": [
    {"role": "user", "content": [
        {"type": "text", "text": Q},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "AAA"}}]}]},
    catalog_meta=P.catalog_meta_for("qfmodel", "cn"))
ba = _body("qfmodel", achat["messages"])
check("#V-18 Anthropic image(base64) 块 -> 桥接成 data URL 后出站仍是 parts",
      isinstance(_last(ba)["content"], list)
      and "data:image/png;base64,AAA" in json.dumps(_last(ba)["content"]),
      achat["messages"])

finish()
