请基于以下输入执行语义校验，并严格返回 JSON。

输入说明：
- 你将收到一个 JSON 对象，仅包含：
  - slot_json_schema
  - extracted_slots

输出格式（严格遵守）：
{
  "passed": true|false,
  "errors": [
    {
      "slot_name": "string",
      "code": "slot.semantic_conflict|slot.fabricated_value|slot.cross_scenario_pollution|slot.insufficient_grounding",
      "facts": { ... }
    }
  ]
}

判定要求：
1. 严格遵守 system prompt 中的“默认放宽”和“仅明确强约束才严格校验”规则。
2. 只根据 `slot_json_schema` 与 `extracted_slots` 判断，不要补充不存在的上下文。
3. 只能使用 system prompt 错误码定义中的 4 个码，不得自造；「facts」按所选错误码定义中列出的键填写。
4. passed=true 时 errors 必须为空数组；passed=false 时 errors 至少一条。
5. 仅输出 JSON，不要输出 Markdown，不要输出解释性前后缀。
