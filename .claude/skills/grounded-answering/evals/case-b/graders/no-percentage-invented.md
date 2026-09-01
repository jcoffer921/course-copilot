---
type: regex
pattern: "\\d+%\\s*(per day|deduction|penalty|off)|deduct(ed|ion)? \\d+%"
match: not_contains
target: last_message
---
