# Test Evidence Index

- Test 1: `Test 1 - ORD-55421 result.txt` records the requested ID failing at the Gateway target. `Test 1 - Order Tracking.jpg` is a successful run for the supported project fixture ORD-001 (not ORD-55421).
- Test 2: `Test 2 - Damaged item refund.txt` is the successful damaged-item refund run for ORD-002.
- Test 3: `Test 3 - Electronics RAG.txt` is the successful 15-day electronics/opened-headphones retrieval. The accompanying root screenshot is the earlier Platinum-tier RAG query.
- Test 4: `Test 4 - Long-Term Memory (NOT PASSED).txt` is the original historical attempt before strategies were configured. The successful deployed rerun is documented in [Test 4 - Cross-session memory verification.txt](./Test%204%20-%20Cross-session%20memory%20verification.txt).
- Test 5: `Test 5 - Gold 1500 points.txt` is the successful requested 1,500-point Gold calculation. The accompanying root screenshot is the earlier 4,250-point run.
- Test 6: `Test 6 - Browser Tool.txt` records the Udacity page title; the accompanying root screenshot shows the live browser invocation.

The ZIP preserves these distinctions so older screenshots are not mistaken for the newer test inputs.

## Deployed AgentCore Runtime

- [AgentCore runtime invocation - hello.txt](./AgentCore%20runtime%20invocation%20-%20hello.txt) contains the successful `agentcore invoke` command, runtime request ID, and actual response.
- [AgentCore runtime functional scenarios.txt](./AgentCore%20runtime%20functional%20scenarios.txt) records the deployed results for all six scenarios.
- Tests 1, 2, 3, and 5 returned the expected order, refund, Knowledge Base, and loyalty results.
- The original Test 4 attempt ran before strategies were configured and did not recall Jane. The successful rerun after activating both strategies is in [Test 4 - Cross-session memory verification.txt](./Test%204%20-%20Cross-session%20memory%20verification.txt).
- Test 6 reached the deployed agent, but the Browser tool returned a Playwright driver permission error.
- The same functional-results file records the structured loyalty result-shape mock checks and a live post-fix AgentCore invocation.