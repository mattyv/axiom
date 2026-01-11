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
