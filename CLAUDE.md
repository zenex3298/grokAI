# Claude Instructions

## Scalability
To ensure the model stays on track and maintains strict adherence to long-term goals without deviation, consider these prompts:

1. **Strict Alignment with Long-Term Vision**  
"Before making any changes, verify that the proposed modification directly aligns with the long-term project vision. No changes should be made if they introduce unnecessary complexity, redundancy, or misalignment with the core architecture."

2. **Justification for Every Line of Code**  
"Every line of code must have a clear, justified purpose that contributes to the overall project structure. If a change does not have a specific, documented rationale tied to project goals, it should not be made."

3. **Minimal, Tested, and Validated Additions Only**  
"No new code should be added unless it has been rigorously tested, reviewed, and proven necessary. Avoid speculative coding, temporary fixes, or features that are not validated by real needs or use cases."

4. **No Shortcuts or Unnecessary Dependencies**  
"Ensure that no shortcuts, workarounds, or unnecessary dependencies are introduced. Every solution must be maintainable, modular, and scalable in the long term. If a quick fix is required, document it and plan a proper implementation within the project roadmap."

5. **Preserve Code Simplicity and Clarity**  
"Every change should improve or maintain the clarity and simplicity of the codebase. If a proposed modification makes the system harder to understand or maintain, reconsider the approach or refactor the existing implementation instead."

6. **Consistency with Existing Architecture and Documentation**  
"Before implementing changes, ensure that they are consistent with the existing architecture and documentation. If discrepancies arise, update documentation first before modifying the code to maintain alignment across the project."

7. **Continuous Review and Feedback Process**  
"No change should be merged without thorough review and feedback from at least one other contributor. Regularly revisit previous decisions to ensure ongoing alignment with the project's goals."

8. **Prioritize Stability Over Speed**  
"Never prioritize speed at the expense of stability. Every change must be evaluated for its impact on the system's reliability, maintainability, and long-term integrity before implementation."

9. **Reject Features That Do Not Fit the Core Purpose**  
"Every feature or enhancement must pass a strict 'core purpose test.' If it does not directly support the fundamental objectives of the project, it should be deferred or rejected outright."

10. **Track All Changes and Revisit Past Decisions**  
"Every modification must be documented with a clear rationale and linked to a long-term strategy. Regularly review past decisions to ensure they still align with the evolving project vision."

By applying these prompts consistently, you can ensure the model remains disciplined, avoids unnecessary deviation, and stays fully aligned with the long-term objectives of the project.

## Understand FIRST
Why am I getting this error? I don't want solutions, I want to thoroughly understand the problem and look at the entire codebase and readme files to understand WHY this is the problem and dig deep to understand the ROOT problem and not move on until we FULLY comprehend the CORE issue.

## Create Log Files for Feedback
Requirements:

A separate log file must be created for each core functionality (e.g., starting services, placing orders, verifying responses, etc.).

Each log file should:

Include timestamps

Clearly label the section/function being executed

Log all standard output and error output

The script should create a main log directory (e.g., logs/YYYY-MM-DD_HH-MM-SS/) for each run and save all component logs inside it.

If any part fails, the script should continue running remaining steps but clearly mark failures in the logs.