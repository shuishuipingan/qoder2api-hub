"""企业 VPC 的**账号级**模型套件（替代原 QD_CN_VPC_ENDPOINT 全局套件）。

判据：
  1. QD_CN_VPC_ENDPOINT 不再生效：设了也只留一条 WARN，区域端点保持公网；
  2. 解析规则保持不变（实例名 / 三种官方域名；拒绝路径、端口、凭据、query）；
  3. 实例名能从账号 domain 反推（老账号升级路径）；
  4. SSRF 白名单只登记**账号显式配置**的实例，未登记的 vpc 域名照旧按
     公网规则校验（解析到内网 -> 拒绝）。

    python tests/_test_vpc_endpoint.py
"""
import json
import os
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _suite_head import ROOT, bootstrap, check, declare_suite, finish  # noqa: E402

os.environ.pop("QD_CN_VPC_ENDPOINT", None)
P, A = bootstrap()
declare_suite(__file__, ["qoder_accounts.py", "qoder_proxy.py"])

print("\n[vpc] 1) 解析：实例名与三种官方域名")
CASES = {
    "acme": ("acme", "https://acme.vpc.qoder.com.cn",
             "https://acme-openapi.vpc.qoder.com.cn",
             "https://acme-gateway.vpc.qoder.com.cn"),
    "ACME.VPC.QODER.COM.CN": ("acme", "https://acme.vpc.qoder.com.cn",
                              "https://acme-openapi.vpc.qoder.com.cn",
                              "https://acme-gateway.vpc.qoder.com.cn"),
    "https://acme-openapi.vpc.qoder.com.cn/": (
        "acme", "https://acme.vpc.qoder.com.cn",
        "https://acme-openapi.vpc.qoder.com.cn",
        "https://acme-gateway.vpc.qoder.com.cn"),
    "acme-gateway.vpc.qoder.com.cn": (
        "acme", "https://acme.vpc.qoder.com.cn",
        "https://acme-openapi.vpc.qoder.com.cn",
        "https://acme-gateway.vpc.qoder.com.cn"),
}
for value, expected in CASES.items():
    got = A.parse_vpc_endpoint(value)
    actual = ((got or {}).get("instance"), (got or {}).get("website"),
              (got or {}).get("openapi"), (got or {}).get("gateway"))
    check("解析 %r" % value, actual == expected, actual)

check("空值 = 未配置（返回 None）", A.parse_vpc_endpoint("") is None)

print("\n[vpc] 2) 解析：拒绝部分重定向输入")
BAD = (
    "  acme", "acme  ", "acme\n", "acme:8443",
    "acme/path", "acme?x=1", "acme#frag",
    "other.example.com", "acme.vpc.qoder.com.cn.evil.test",
    "ftp://acme", "u:p@acme.vpc.qoder.com.cn",
    "acme..vpc.qoder.com.cn", "-acme", "acme-",
)
for value in BAD:
    try:
        A.parse_vpc_endpoint(value)
        ok = False
    except ValueError:
        ok = True
    check("拒绝 %r" % value, ok)

print("\n[vpc] 3) 未配置账号：CN 行为就是公网")
check("CN openapi 是公网",
      A.get_realm_config("cn")["openapi"] == "https://openapi.qoder.com.cn")
check("CN gateway 是单一官方主机",
      A.gateway_candidates("cn") == ["https://gateway.qoder.com.cn"])
check("CN openapi 候选不含 VPC 域",
      not any("vpc.qoder.com.cn" in c for c in A.openapi_candidates("cn")))
check("未登记时 is_configured_vpc_host 为 False",
      not A.is_configured_vpc_host("acme-openapi.vpc.qoder.com.cn"))


def run_py(code, env_extra):
    env = dict(os.environ)
    env.pop("QD_CN_OPENAPI", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [ROOT] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.update(env_extra)
    out = subprocess.check_output([sys.executable, "-c", code],
                                  cwd=ROOT, env=env, text=True,
                                  stderr=subprocess.STDOUT, timeout=60)
    return out.strip().splitlines()[-1]


print("\n[vpc] 4) 子进程：QD_CN_VPC_ENDPOINT 已失效（只告警，不改端点）")
CODE = r'''
import json
import qoder_accounts as A
cn = A.get_realm_config("cn")
print(json.dumps({
    "deprecated": A.VPC_ENV_DEPRECATED,
    "openapi": cn["openapi"], "gateway": cn["gateway"],
    "website": cn["website"], "domain": cn["domain"],
    "gateway_candidates": A.gateway_candidates("cn"),
}, ensure_ascii=False))
'''
data = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": "acme"}))
check("检测到旧变量仍被设置", data["deprecated"] is True, data["deprecated"])
check("openapi 仍是公网（变量不再生效）",
      data["openapi"] == "https://openapi.qoder.com.cn", data["openapi"])
check("gateway 仍是公网",
      data["gateway"] == "https://gateway.qoder.com.cn", data["gateway"])
check("website 仍是公网", data["website"] == "https://qoder.com.cn",
      data["website"])
check("domain 仍是公网", data["domain"] == "qoder.com.cn", data["domain"])
check("候选不含实例域",
      data["gateway_candidates"] == ["https://gateway.qoder.com.cn"],
      data["gateway_candidates"])

plain = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": ""}))
check("未设置变量时没有告警", plain["deprecated"] is False, plain["deprecated"])

bad_env = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": "bad host"}))
check("非法旧值也不会让进程起不来", bad_env["deprecated"] is True,
      bad_env["deprecated"])
check("非法旧值同样不改端点",
      bad_env["gateway"] == "https://gateway.qoder.com.cn", bad_env["gateway"])

print("\n[vpc] 5) 从账号 domain 反推实例")
DERIVE = {
    "acme.vpc.qoder.com.cn": "acme",
    "acme-gateway.vpc.qoder.com.cn": "acme",
    "acme-openapi.vpc.qoder.com.cn": "acme",
    "ACME.VPC.QODER.COM.CN": "acme",
    "qoder.com.cn": "",
    "": "",
    "-acme.vpc.qoder.com.cn": "",
    "acme.vpc.qoder.com.cn.evil.test": "",
}
for domain, want in DERIVE.items():
    got = A._vpc_instance_from_domain(domain)
    check("domain %r -> %r" % (domain, want), got == want, got)

print("\n[vpc] 6) SSRF：只有账号登记的实例被放行")
parsed = A.register_vpc_hosts("acme")
check("登记成功", (parsed or {}).get("instance") == "acme", parsed)
check("三个专属域被放行",
      all(A.is_configured_vpc_host(h) for h in (
          "acme.vpc.qoder.com.cn", "acme-openapi.vpc.qoder.com.cn",
          "acme-gateway.vpc.qoder.com.cn")))
check("别的实例没有被连带放行",
      not A.is_configured_vpc_host("other-openapi.vpc.qoder.com.cn"))

_real_gai = socket.getaddrinfo


def _fake_gai(host, port, *a, **k):
    if str(host).endswith("vpc.qoder.com.cn"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.8.7", port))]
    return _real_gai(host, port, *a, **k)


socket.getaddrinfo = _fake_gai
try:
    check("已登记实例解析到内网仍然放行",
          A.validate_public_http_url(
              "https://acme-openapi.vpc.qoder.com.cn/api/v1/x").startswith(
                  "https://acme-openapi"))
    try:
        A.validate_public_http_url("https://evil-openapi.vpc.qoder.com.cn/x")
        blocked = False
    except ValueError:
        blocked = True
    check("未登记的 vpc 域名解析到内网 -> 拒绝", blocked)
finally:
    socket.getaddrinfo = _real_gai

print("\n[vpc] 7) 审查补充：冲突配置与 DNS label 边界")
for value in ("a" * 56, "a" * 63, "acme:", "acme?", "acme.vpc.qoder.com.cn:"):
    try:
        A.parse_vpc_endpoint(value)
        ok = False
    except ValueError:
        ok = True
    check("拒绝边界输入 %r" % value, ok)
longest = A.parse_vpc_endpoint("a" * 55)
check("55 字符实例的 gateway label 恰为 63 字符",
      len(longest["gateway"].split("//", 1)[1].split(".")[0]) == 63)
conflict = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": "acme",
                                    "QD_CN_OPENAPI": "https://openapi.qoder.com.cn"}))
check("VPC 优先于旧 OPENAPI 覆盖", conflict["openapi_candidates"] ==
      ["https://acme-openapi.vpc.qoder.com.cn"], conflict)

print("\n[vpc] 8) fake-IP IPv6 映射与私网混合解析")
CODE_FAKE = r'''
import ipaddress, json, socket
import qoder_accounts as A
import qoder_proxy as P
results = {}
for label, ips in (
    ("fake", ["198.18.0.45", "::ffff:0:c612:2d", "::ffff:198.18.0.45"]),
    ("private", ["198.18.0.45", "10.20.30.40"]),
    ("mapped_private", ["::ffff:0:a00:1"]),
):
    socket.getaddrinfo = lambda host, port, **kw: [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
        for ip in ips]
    for name, mod in (("accounts", A), ("proxy", P)):
        try:
            mod.validate_public_http_url("https://fixture.invalid/path")
            results[name + "_" + label] = True
        except ValueError:
            results[name + "_" + label] = False
print(json.dumps(results))
'''
fake = json.loads(run_py(CODE_FAKE, {"QD_CN_VPC_ENDPOINT": "acme"}))
for name in ("accounts", "proxy"):
    check(name + " 接受 IPv4/mapped/translated fake-IP", fake[name + "_fake"])
    check(name + " 拒绝 fake-IP 混入私网", not fake[name + "_private"])
    check(name + " 拒绝 translated 私网地址", not fake[name + "_mapped_private"])

print("\n[vpc] 9) 旧额度缓存、跨区诊断与重定向隔离（离线）")
CODE_ISOLATION = r'''
import json, tempfile, urllib.request, urllib.error
from unittest import mock
import qoder_accounts as A
account = A.Account({"uid": "fixture", "realm": "cn", "accessToken": "fixture-token"})
seen = []
def fake_http(url, **kwargs):
    seen.append(url)
    return {}
with tempfile.TemporaryDirectory() as root:
    A.save_credits_source(root, "cn", "https://openapi.qoder.com.cn", "/api/v2/quota/usage")
    with mock.patch.object(A, "http_json", side_effect=fake_http):
        stale = account._fetch_credits_via_source(root, {"host": "https://openapi.qoder.com.cn", "path": "/api/v2/quota/usage"})
        account.probe_credits_endpoints(root, limit=2)
        before = len(seen)
        hint = account._other_realm_quota_hint()
        other = A.Account({"uid": "other", "realm": "intl", "accessToken": "other-token"})
        other._other_realm_quota_hint()
        no_cross = len(seen) == before
handler = A._VpcRedirectHandler()
req = urllib.request.Request("https://acme-openapi.vpc.qoder.com.cn/start", headers={"Authorization": "Bearer fixture-token"})
redirects = {}
for label, url in (
    ("own", "https://acme.vpc.qoder.com.cn/next"),
    ("public", "https://openapi.qoder.com.cn/next"),
    ("other", "https://other.vpc.qoder.com.cn/next"),
    ("http", "http://acme.vpc.qoder.com.cn/next"),
    ("port", "https://acme.vpc.qoder.com.cn:8443/next"),
):
    try:
        handler.redirect_request(req, None, 302, "Found", {}, url)
        redirects[label] = True
    except urllib.error.HTTPError:
        redirects[label] = False
print(json.dumps({"seen": seen, "stale": stale, "no_cross": no_cross,
                  "hint": hint, "redirects": redirects, "dirs": A.cli_auth_dirs("cn"),
                  "intl": A.get_realm_config("intl")["gateway"]}))
'''
isolation = json.loads(run_py(CODE_ISOLATION, {"QD_CN_VPC_ENDPOINT": "acme"}))
check("旧公网额度来源缓存不再出站", isolation["stale"] is None and
      isolation["seen"] and all(url.startswith("https://acme-openapi.vpc.qoder.com.cn/")
                                for url in isolation["seen"]), isolation)
check("VPC 模式关闭双向跨区域令牌探测", isolation["no_cross"] and isolation["hint"] == "")
for label, allowed in isolation["redirects"].items():
    check("redirect " + label, allowed == (label == "own"), allowed)
check("VPC CLI 凭据目录优先且保留旧目录", len(isolation["dirs"]) == 2 and
      "/.vpc/acme/.auth" in isolation["dirs"][0].replace("\\", "/") and
      isolation["dirs"][1].replace("\\", "/").endswith("/.qoder-cn/.auth"), isolation["dirs"])
check("INTL 默认网关保持公网", "vpc.qoder.com.cn" not in isolation["intl"])
with open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8") as fh:
    inference_source = fh.read()
check("VPC 推理同样使用隔离重定向 opener",
      "resp = qoder_accounts._opener_for_request().open(req, timeout=600)" in inference_source)

finish()
