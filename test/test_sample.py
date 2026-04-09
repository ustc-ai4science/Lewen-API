import requests
import json

# 设置请求头，包含 API Key
headers = {"X-API-Key": "lw-d7ea4e41519dc1cd03b322d0faa8fb9b"}

# 发送 GET 请求
r1 = requests.get(
    "http://172.16.100.204:4000/paper/search",
    params={"query": "Paper search agent", "limit": 50, "retrieval": "dense"},
    headers=headers
)

# r2 = requests.get(
#     f"http://172.16.100.204:4000/paper/2501.10120",
#     headers=headers
# )
# r3 = requests.get(
#     f"http://172.16.100.204:4000/paper/search/title",
#     params={"query": "PaSa: An LLM Agent for Comprehensive Academic Paper Search"},
#     headers=headers
# )
print(json.dumps(r1.json()))
# print(json.dumps(r2.json()))
# print(json.dumps(r3.json()))