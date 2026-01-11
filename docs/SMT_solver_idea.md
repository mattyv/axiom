ESBMC Verification Integration for Claude Code
1. Project Configuration (CLAUDE.md)

Add this to your CLAUDE.md file so Claude knows how to invoke the verifier. This configuration uses the Clang frontend for native C++20 support.

Markdown
## Verification Commands
- **Run Formal Verification (File):** `esbmc <file> --std c++20 --overflow-check --memory-leak-check --unwind 10`
- **Run Formal Verification (Function):** `esbmc <file> --function <func_name> --std c++20 --incremental-bmc`
- **Full Project Scan:** `lsverifier -r -f --std c++20`

## Verification Guidelines
- Use ESBMC to verify memory safety, pointer validity, and arithmetic overflows.
- For C++20, ensure the Clang frontend is active (default in v7.x+).
- If verification fails, examine the "Counterexample" trace provided in the terminal.
2. Custom Skill Definition (.claude/skills/verify-cpp.md)

Create this file to give Claude the "reasoning" logic for when to use the SMT solver.

Markdown
---
name: verify-cpp-logic
description: Formally verify C++20 code for memory safety and logical correctness using ESBMC SMT solver.
---

# Instructions
When the user asks to "check" or "verify" C++ code, or after generating complex pointer/concurrency logic:
1. **Identify Entry Points:** Determine the function or file that needs verification.
2. **Execute ESBMC:** Run `esbmc {file} --std c++20 --overflow-check --memory-leak-check`.
3. **Parse Output:** - If `VERIFICATION SUCCESSFUL`: Confirm the code is formally safe within the given bounds.
   - If `VERIFICATION FAILED`: Read the "Counterexample" or "Violation" trace.
4. **Self-Correct:** Use the counterexample (the specific state where the assertion failed) to fix the bug and re-run verification.

# C++20 Specifics
- Use `--std c++20` to support concepts, coroutines, and modern STL.
- If using headers, ensure `-I` paths are included or use `compile_commands.json`.
3. Usage Reference (Common Flags)

Provide this table to Claude if it needs to tune the SMT solver performance:

Flag	Purpose	Recommended for C++20
--std c++20	Enables Clang-based C++20 parsing.	Required
--overflow-check	Detects signed/unsigned integer overflows.	Recommended
--memory-leak-check	Finds dynamic memory that wasn't freed.	Recommended
--unwind N	Sets the loop unwinding limit (default is often too low).	Set to 5 or 10
--floatbv	Use bit-vector theory for floating point accuracy.	Use for math code
--k-induction	Uses induction to prove properties for any loop depth.	Use for complex loops
How to use this with Claude Code

Place the files: Put CLAUDE.md in your project root and the skill in .claude/skills/.

Initialize: Run claude in your terminal.

Command Claude: > "Hey Claude, rewrite the buffer_manager.cpp using C++20 spans, then verify it with ESBMC to make sure I didn't introduce any out-of-bounds issues."

Why this works

Claude Code is a terminal-based agent. By defining ESBMC in CLAUDE.md, you grant the agent the "permission" and "syntax" to use the SMT solver as a tool. Since ESBMC outputs diagnostics in a compiler-like format (file:line: error), Claude can naturally "read" the verification failures just like it reads build errors.

Would you like me to generate a specific GitHub Action workflow so these ESBMC checks run automatically on every push?

ESBMC: Formal Verification for C++ This video demonstrates how ESBMC uses SMT solvers to find deep bugs in C++ code, which helps in understanding how Claude will interpret the counterexample traces.


The "Counterexample" Doc for Claude Code
To make Claude Code effective with ESBMC, you need to teach it how to read a Counterexample Trace. When ESBMC fails, it doesn't just say "Bug found"; it outputs the exact values of variables that caused the crash.

Copy this into a file named ESBMC_GUIDE.md and tell Claude Code: "Read ESBMC_GUIDE.md and follow its loop for all C++ tasks."

Markdown
# ESBMC Formal Verification Loop for Claude

You are tasked with writing "Correct-by-Construction" C++20 code. You must use ESBMC as your logical judge.

### The Verification Loop
1. **Implement:** Write the C++20 code with `assert()` or `__ESBMC_assert()` for critical logic.
2. **Verify:** Run `esbmc {file} --std c++20 --overflow-check --pointer-check`.
3. **Analyze Failure:** If verification fails, look for the **"Counterexample Trace"** in the output.
   - Look for: `State X: variable == VALUE`
   - This is the exact state that breaks your code.
4. **Refine:** Do not just "try something else." Use the trace values to understand the edge case you missed (e.g., "I forgot that `int_min` divided by `-1` overflows").
5. **Repeat:** Re-verify until you see `VERIFICATION SUCCESSFUL`.

### ESBMC "Superpowers" to Use
- **Assumptions:** Use `__ESBMC_assume(x > 0);` to tell the solver about constraints you know are true.
- **Assertions:** Use `__ESBMC_assert(condition, "Error Msg");` for properties you want to prove.
- **K-Induction:** If you have complex loops, use the `--k-induction` flag to prove the loop is safe for *any* number of iterations.

### Example Counterexample Handling
If ESBMC says:
`Violation of 'division by zero' at line 10, state: y = 0`
**Your Fix:** Add a guard `if (y != 0)` or an assumption `__ESBMC_assume(y != 0)`.
Why this is "Un-fuck-up-able"

By giving Claude Code this specific guide, you are changing its behavior from "Probabilistic" (guessing what code looks right) to "Deterministic" (only accepting code that satisfies the SMT solver).

Would you like me to show you how to set up a "Pre-commit Hook" that prevents you from even committing code unless ESBMC gives it a green light?
