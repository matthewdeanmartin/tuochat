## Lua Sandbox Rules

Write plain Lua only. The following constraints are absolute:

- **No modules**: `require`, `package`, `dofile`, `loadfile` are removed.
- **No OS access**: `os`, `io`, `debug` are removed.
- **No coroutines**: `coroutine` is removed.
- **No GC control**: `collectgarbage` is removed.

### Available API

- `input` — read-only structured data provided by the host (table or scalar).
- `print(...)` — captured to stdout (max 200 lines / 64 KB).
- `emit(value)` — set the final result. Call **exactly once**. Error if called twice.
- `fail(message)` — signal an explicit failure.

### Allowed globals

Arithmetic, `string`, `table` (subset), `math` (subset), `ipairs`, `pairs`, `type`, `tostring`, `tonumber`, `select`, `unpack`, `print`, `emit`, `input`.

### Output rules

- Call `emit(value)` exactly once with your final answer.
- Only these types may be emitted: `nil`, `boolean`, `number`, `string`, tables (arrays or string-keyed maps).
- Maximum result size: 256 KB JSON.

### Example

```lua
local nums = input.numbers
local sum = 0
for _, v in ipairs(nums) do
  sum = sum + v
end
print("sum is", sum)
emit(sum)
```
