import { Tracer } from "./tracer.js";

/**
 * Wrap an async or sync function so each invocation emits TOOL_CALL/TOOL_RESULT
 * events through the supplied tracer.
 */
export function wrapTool<TArgs extends unknown[], TResult>(
  tracer: Tracer,
  toolName: string,
  fn: (...args: TArgs) => Promise<TResult> | TResult,
): (...args: TArgs) => Promise<TResult> {
  return (...args: TArgs): Promise<TResult> =>
    tracer.toolCall(toolName, { args }, () => fn(...args));
}
