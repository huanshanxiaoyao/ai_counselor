# Manual Smoke Scripts

这些脚本用于人工排查与联调，不纳入 `pytest` 自动回归。

## 目录

- `llm_provider_smoke.py`：依次调用多个 provider，验证基础连通性。
- `doubao_smoke.py`：验证豆包 API 与模型可用性。
- `models_config_check.py`：打印当前 provider / model 配置，便于人工核对。
- `roundtable_interactive.py`：讨论室交互式回归脚本（容器内执行）。

## 运行方式

在项目根目录执行：

```bash
python tests/manual/llm_provider_smoke.py
python tests/manual/doubao_smoke.py
python tests/manual/models_config_check.py
```

交互式讨论室脚本建议在容器内执行：

```bash
docker exec -i ai_counselor-backend-1 python /app/tests/manual/roundtable_interactive.py
```

## 注意事项

- 请先准备好 `.env` 与相关 API Key。
- 这些脚本可能写入数据库，运行前请确认环境（本地/测试/线上）。
