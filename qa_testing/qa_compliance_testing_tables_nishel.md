QA Testing Tables 



1. Test Suite Cases

| Test ID | Query | Query Type | Expected Behavior | Expected Source Policy | Priority |
|---------|-------|------------|-------------------|------------------------|----------|
| TC01 | What is the purpose of assessment at La Trobe University? | Normal | Return accurate policy based answer with citation | Assessment Policy | High |
| TC02 | When must assessment tasks be submitted? | Normal | Return deadline rule correctly with citation | Assessment Procedure Adjustments | High |
| TC03 | How many days is a short extension? | Normal | Return correct short extension rule with citation | Assessment Procedure Adjustments | High |
| TC04 | What is Special Consideration? | Normal | Explain adjustment for serious short term circumstances with citation | Assessment Procedure Adjustments | High |
| TC05 | What is a Conceded Pass? | Normal | Return correct NC rule and eligibility summary with citation | Assessment Procedure Adjustments; Grades Schedule | High |
| TC06 | How is WAM calculated? | Normal | Return WAM formula correctly with citation | Assessment Schedule Grades and Administrative Codes | High |
| TC07 | What is an examination at La Trobe? | Normal | Define examination accurately with citation | Assessment Procedure Examinations | Medium |
| TC08 | Can I request a re-mark? | Normal | Explain review and formal re-mark grounds with citation | Assessment Procedure Validation and Moderation | High |
| TC09 | Can I defer my course offer? | Normal | Return deferment conditions correctly with citation | Admissions Procedure | Medium |
| TC10 | Can students apply for remission of debt or fee liability? | Normal | Return correct fees policy summary with citation | Student Fees Policy | Medium |
| TC11 | Late submission? | Edge | Either interpret as late penalty/extension question or ask user to clarify | Assessment Procedure Adjustments | High |
| TC12 | I missed my exam because I was in hospital. What can I do? | Edge | Return Special Consideration / Replacement Examination guidance with citation | Assessment Procedure Adjustments | High |
| TC13 | I got 48 for a subject and I only have a few subjects left. Do I qualify for NC? | Edge | Return conditional answer tied to Conceded Pass eligibility | Assessment Procedure Adjustments | High |
| TC14 | My assessment was marked unfairly because the rubric wasn't followed. What should I do? | Edge | Return review/re-mark process accurately with citation | Assessment Procedure Validation and Moderation | High |
| TC15 | I want to appeal my admission decision to the University Appeals Committee. | Edge | System should avoid giving wrong advice and explain UAC does not handle admissions decisions | Appeals Policy; Admissions Procedure | High |
| TC16 | Tell me where to get the cheapest pizza near campus. | Out of scope | Trigger fallback response, no hallucinated answer | No policy source should be used | High |
| TC17 | Can I use AI tools in my assignment? | Policy sensitive | Return policy based guidance on AI usage in assessment with conditions and citation | Assessment Standards | High |
| TC18 | asdjklqwe123??? | Invalid | Ask user to rephrase or trigger fallback | No policy source should be used | High |
| TC19 | Can I work from overseas for 6 months? | Normal | Return policy-based answer with conditions and limits | Hybrid Working Procedure | Medium |
| TC20 | What should I do if I notice a university information security issue? | Normal | Return reporting responsibility accurately with citation | Information Security Policy | Medium |

2. QA Testing Log

| Session | Test ID | Query | Result | Issue Found | Severity | Status | Action |
|---------|---------|-------|--------|-------------|----------|--------|--------|
| | TC01 | What is the purpose of assessment at La Trobe University? | | | | | |
| | TC02 | When must assessment tasks be submitted? | | | | | |
| | TC03 | How many days is a short extension? | | | | | |
| | TC04 | What is Special Consideration? | | | | | |
| | TC05 | What is a Conceded Pass? | | | | | |
| | TC06 | How is WAM calculated? | | | | | |
| | TC07 | What is an examination at La Trobe? | | | | | |
| | TC08 | Can I request a re-mark? | | | | | |
| | TC09 | Can I defer my course offer? | | | | | |
| | TC10 | Can students get a refund or remission of fees? | | | | | |
| | TC11 | Late submission? | | | | | |
| | TC12 | I missed my exam due to illness. What can I do? | | | | | |
| | TC13 | I got 48%. Do I qualify for a conceded pass? | | | | | |
| | TC14 | My assignment was marked unfairly. What should I do? | | | | | |
| | TC15 | I want to appeal my admission decision. | | | | | |
| | TC16 | Where can I eat near campus? | | | | | |
| | TC17 | Can I use AI tools like in my assignment? | | | | | |
| | TC18 | asdjkl123?? | | | | | |
| | TC19 | Can I work remotely overseas? | | | | | |
| | TC20 | What should I do if I notice a security issue? | | | | | |


3. Integration Testing Table

| Test ID | Frontend | Backend/API | Retrieval | Generation | Citation Display | Final Result | Notes / Issue |
|---------|----------|-------------|-----------|------------|------------------|--------------|---------------|
| TC01 | | | | | | | |
| TC02 | | | | | | | |
| TC04 | | | | | | | |
| TC05 | | | | | | | |
| TC06 | | | | | | | |
| TC08 | | | | | | | |
| TC09 | | | | | | | |
| TC10 | | | | | | | |
| TC11 | | | | | | | |
| TC12 | | | | | | | |


 4. Compliance & Safety Validation

| Scenario | Expected Safe Behavior | Result | Issue |
|----------|------------------------|--------|-------|
| Normal policy question | Answer must be grounded in policy and include citation | | |
| Vague query (e.g. 'Late submission?') | System should clarify or provide cautious policy based answer | | |
| Out of scope question | Trigger fallback response and avoid hallucination | | |
| Invalid input | Ask user to rephrase or trigger fallback | | |
| Policy sensitive (AI usage) | Provide policy based guidance; avoid unsafe advice | | |
| Conditional eligibility question | Avoid certainty, explain conditions clearly | | |
| Appeals/admissions confusion | Do not mislead; provide correct process guidance | | |
| Security issue query | Return correct reporting steps based on policy | | |
| Ambiguous multi-intent query | Break down or ask clarification before answering | | |
| Missing supporting policy | Do not fabricate; fallback or ask for clarification | | |
