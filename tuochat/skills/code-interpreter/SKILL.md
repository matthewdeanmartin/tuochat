______________________________________________________________________

## name: code-interpreter description: Execute JavaScript or Lua code in a sandboxed environment.

# Code Interpreter

When the user asks you to compute, transform data, or demonstrate logic, write a fenced code block in JavaScript or Lua. The host will execute it in a sandbox and optionally attach the output.

## How to write executable code

Use a fenced code block with language tag `js` or `lua`. Prefix with `Path: [sandbox]`.

````
Path: [sandbox]
```js
// your code here
````

```

## Language rules

{javascript}

{lua}

## General constraints

- One fenced block per response. First matching block is executed.
- Keep code short and focused. No libraries, no imports.
- Use `input` for any data the user provides.
- Always call `emit(value)` exactly once with your answer.
- Use `console.log()` / `print()` for intermediate output.
- Timeout: 500ms. Memory: 64MB. Max output: 256KB.
```
