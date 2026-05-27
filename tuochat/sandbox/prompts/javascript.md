## JavaScript Sandbox Rules

Write plain JavaScript only. The following constraints are absolute:

- **No imports**: `require()`, `import`, dynamic `import()` are unavailable.
- **No network**: `fetch`, `XMLHttpRequest`, `WebSocket` do not exist.
- **No timers**: `setTimeout`, `setInterval`, `requestAnimationFrame` are unavailable.
- **No filesystem**: No `fs`, no file access of any kind.

### Available API

- `input` — read-only structured data provided by the host.
- `console.log(...)` — captured to stdout (max 200 lines / 64 KB).
- `emit(value)` — set the final result. Call **exactly once**. Error if called twice.
- `fail(message)` — signal an explicit failure.

### Output rules

- Call `emit(value)` exactly once with your final answer.
- Only these types may be emitted: `null`, `boolean`, `number`, `string`, `Array`, plain `Object` with string keys.
- Maximum result size: 256 KB JSON.

### Example

```js
const nums = input.numbers;
const sum = nums.reduce((a, b) => a + b, 0);
console.log("sum is", sum);
emit(sum);
```
