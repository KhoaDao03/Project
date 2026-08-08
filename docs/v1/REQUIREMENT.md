# Personal AI Assistant

## Software Requirements Specification

**Working product name:** Elly Research Assistant  
**Document version:** 1.0  
**Status:** Baseline candidate - owner approval required for listed open questions  
**Date:** 2026-08-03  
**Project owner:** Khoa Dao

---

# 1. Document Control

| Field | Value |
|---|---|
| Project name | Personal AI Assistant; working release name: Jarvis Research Assistant |
| Document title | Software Requirements Specification |
| Version | 1.0 |
| Status | Baseline candidate |
| Date | 2026-08-03 |
| Project owner | Document requester; legal/name attribution TBD |
| Intended audience | Project owner, requirements and product reviewers, software architects, security reviewers, implementers, testers, and future AI-assisted coding sessions |
| Purpose | Define the authoritative, testable requirements for Version 1 and separate them from future ideas and recommendations. |
| Source of truth | After owner approval, this document supersedes the supplied notes and conversation for Version 1 scope. Changes must update the document version, decision log, affected requirement statuses, and traceability matrix. |

**Source material summary.** The source consists of project notes and prior AI-assisted discussion about a local-first, Jarvis-inspired personal assistant. It includes: a locally hosted Ollama generalist; application-controlled orchestration; prompt-defined coding and research specialists using one configurable OpenAI API model; on-demand web search and selected-page reading; RAG; evidence and citations; explicit uncertainty and abstention; privacy modes; basic memory and startup continuity; resource guardrails; execution logging; and deferred voice, vision, crawling, computer control, and fine-tuning.

## 1.1 Classification and normative language

- **Confirmed requirement:** explicitly accepted for Version 1 by the owner through the statement that the requirements are good for V1.
- **Confirmed constraint:** a fixed boundary or technical choice accepted for V1.
- **Assumption:** a working belief needed to interpret the source; owner confirmation remains advisable.
- **Recommendation:** reviewer guidance, not binding unless later approved.
- **Open question:** an unresolved choice that must not be inferred as approved.
- **Future idea:** intentionally deferred capability.
- **Explicit non-goal:** capability V1 must not provide.
- **Must:** mandatory. **Should:** preferred but not required for V1 acceptance. **May:** optional.

# 2. Executive Summary

The product is a local-first personal AI assistant that accepts text requests, uses a medium-sized model through Ollama for ordinary conversation and coordination, and delegates narrowly scoped research or coding tasks to prompt-defined specialists when they add value. The application, not a language model, controls tool execution, cloud calls, permissions, limits, and audit records.

The product addresses the gap between convenient cloud assistants and a private, extensible assistant whose evidence, uncertainty, actions, and resource use are visible to its owner. V1 is intended for a single technically capable owner running the assistant on a personal computer. It must support multi-turn text interaction, current-information research with citations, RAG over selected evidence, two specialist roles, optional cloud escalation, basic continuity, bounded execution, and honest `known`, `inferred`, `unknown`, or `blocked` outcomes.

The intended V1 outcome is a dependable core that proves local-first orchestration and specialist extensibility without attempting a full autonomous Jarvis. The most important constraints are local hardware capacity (TBD), use of Ollama, one configurable OpenAI provider/model, privacy boundaries for cloud processing, strict limits on calls and context, untrusted web content, and no unrestricted computer control.

# 3. Product Vision

## 3.1 Long-term vision

Create a consistent personal assistant that can understand multimodal input, recall owner-approved context, research current information, and safely coordinate replaceable domain specialists and tools. Long-term capabilities may include voice, vision, focused crawling, computer assistance, richer memory, and specialized local or fine-tuned models.

## 3.2 Version 1 vision

Deliver a functionally small but behaviorally strict text assistant that operates locally for ordinary requests, uses bounded cloud and web capabilities when allowed, cites retrieved evidence, admits uncertainty, and records what it did.

## 3.3 Value proposition

- Private-by-default local operation for ordinary use.
- Better answers for research and coding through narrow specialist roles.
- Evidence, freshness, and provenance for current-information answers.
- Replaceable providers and specialists without rewriting the generalist.
- Explicit permission, cost, and resource boundaries.

## 3.4 Guiding principles

1. Epistemic honesty over apparent completeness.
2. Minimum sufficient context over maximum context.
3. Application-enforced policy over model self-policing.
4. Local-first processing with explicit cloud boundaries.
5. Evidence and provenance over unsupported confidence.
6. Small V1 scope with extension contracts defined early.
7. User control over memory, data sharing, and consequential actions.

## 3.5 Success definition

V1 succeeds when the owner can complete the defined text, research, and coding journeys; the assistant stays within configured limits; current claims are cited; unknowns are disclosed; cloud use follows the selected privacy mode; failures are visible; and the permanent evaluation suite passes the approved release thresholds.

## 3.6 Explicit non-goals

- Training a custom or fine-tuned model in V1.
- Always-listening audio, wake words, continuous webcam use, or live surveillance.
- General unrestricted crawling of arbitrary websites.
- Computer control, arbitrary shell execution, unrestricted filesystem access, form submission, email sending, purchasing, or trading.
- Autonomous financial decisions or presentation as a licensed professional.
- Recursive or swarm-style agent delegation.
- Permanent storage of every conversation by default.
- Semantic/vector long-term personal memory in V1.
- Multi-user or enterprise tenancy unless later approved.

# 4. Problem Definition

## 4.1 Current problem

General-purpose assistants may be cloud-dependent, opaque about evidence and tool use, inconsistent across sessions, prone to answering despite insufficient information, and difficult to extend with owner-specific specialists. A single local model may protect privacy but lack current information or specialist performance.

## 4.2 Affected user

The primary affected user is the project owner: a technically capable individual who wants a private, extensible assistant for ordinary conversation, web research, and coding assistance.

## 4.3 Current alternatives and workarounds

- Use separate local and cloud chat applications and manually move context between them.
- Search the web manually and paste excerpts into a model.
- Use separate coding or finance tools with no shared context or audit record.
- Save notes manually to approximate memory and continuity.

## 4.4 Why the problem is worth solving

A unified assistant can reduce repeated context transfer, preserve privacy for ordinary tasks, improve grounding for current questions, and create a reusable platform for later modalities and specialists. These benefits are assumptions until measured in user acceptance testing.

## 4.5 Expected improvement

Compared with the workarounds, V1 is expected to provide one interface, explicit routing, bounded cloud escalation, cited research, consistent uncertainty behavior, and a reviewable execution trail. Quantitative productivity improvement is TBD.

## 4.6 Evidence and assumptions

The problem and expected benefit are supported by the owner's stated goals and concerns. No external user research, benchmark, hardware test, or cost study was supplied. V1 is therefore treated as a single-owner validation release.

# 5. Stakeholders and Users

## 5.1 Primary Version 1 user: project owner

- **Objectives:** obtain trustworthy answers; research current topics; get coding assistance; retain useful continuity; control local/cloud processing and resource use.
- **Technical ability:** assumed intermediate software-development ability; able to install Ollama, configure API credentials, and inspect logs.
- **Permissions:** full control of local configuration, profile data, API modes, and task cancellation.
- **Responsibilities:** provide lawful input, review uncertainty and citations, approve data sharing where required, and choose unresolved budgets and hardware targets.
- **Trust level:** trusted owner, but owner input is still validated before tool or API use.
- **Primary workflows:** local conversation, web-backed research, coding specialist consultation, memory/profile review, task cancellation, and execution-log review.
- **Usability/accessibility:** keyboard-accessible text interface; readable status and error messages; additional needs TBD.

## 5.2 System administrator/operator

In V1 this is assumed to be the same person as the owner. The operator configures providers, secrets, limits, storage, logs, and model selection; monitors resource use; and performs recovery. Multi-user administration is out of scope.

## 5.3 External service providers

Ollama, the selected OpenAI API model, and the selected web-search/page-retrieval services are dependencies rather than trusted decision makers. Their output is untrusted until validated according to this specification.

## 5.4 Future users and stakeholders

Additional household users, administrators, domain reviewers, and recipients of actions are future possibilities. Their identity, access, isolation, and consent requirements are not defined for V1.

# 6. Scope

## 6.1 Version 1 - Required

- Text-based, multi-turn conversation through one owner-selected interface.
- A configurable medium-sized local generalist model served through Ollama.
- Application-controlled orchestration and policy enforcement.
- Prompt-defined research and coding specialist roles using one configurable OpenAI provider/model.
- On-demand web search and selected-page reading with evidence objects and clickable citations.
- RAG over selected web evidence and approved local/session context.
- Explicit `known`, `inferred`, `unknown`, and `blocked` result states.
- Local-only and cloud-permitted processing modes.
- Minimum-sufficient context construction with token and privacy budgets.
- Configurable rate, call, retry, timeout, concurrency, queue, cost, and task-duration limits.
- Basic session history, confirmed user profile, and startup continuity.
- Structured execution, source, approval, model-call, and error records with redaction.
- Cancellation, partial-result reporting, and clear failure behavior.
- A permanent evaluation suite of approximately 30 representative requests.

## 6.2 Version 1 - Optional

- Streaming text responses.
- An additional verification pass for selected high-impact claims.
- User-facing export of an execution trace in a portable format.
- A simple web interface if a terminal interface is selected as the required V1 surface.

## 6.3 Future Versions

- Focused allowlisted crawler with refresh scheduling.
- Long-term semantic/episodic memory and retrieval review tools.
- Speech recognition, text-to-speech, interruption, and later wake word.
- Image upload, screenshot analysis, explicit webcam frame capture, and later live vision.
- Parallel multi-specialist workflows and richer task graphs.
- Computer assistance with sandboxing and confirmation.
- Finance specialist using fresh market and filing data.
- Local or fine-tuned specialist models after evaluation evidence exists.
- Autonomous background tasks only after explicit permission and safety design.

## 6.4 Explicitly Out of Scope

The non-goals in Section 3.6 are binding V1 exclusions. V1 must not implement hidden background activity, unrestricted crawling, continuous sensing, arbitrary generated-code execution, external communications, purchases, trades, or destructive actions.

# 7. Terminology

| Term | Definition |
|---|---|
| Application orchestrator | Deterministic application service that controls routing, context, tools, providers, permissions, limits, validation, and synthesis. It is not itself a model prompt. |
| Generalist | The local Ollama-served model used for ordinary conversation, routing assistance, summarization, and final response composition. |
| Specialist | A narrow prompt-defined role, model configuration, toolchain, or later service that receives a bounded task and returns a structured result. |
| Research specialist | V1 specialist role for retrieving, evaluating, and summarizing external evidence. |
| Coding specialist | V1 specialist role for code-related reasoning within supplied context; V1 does not grant unrestricted code execution. |
| Cloud escalation | A call to the configured OpenAI provider when allowed by policy and useful for the task. |
| RAG | Retrieval-augmented generation: selection of relevant evidence for a model call. RAG is not a guarantee of truth. |
| Evidence object | Structured record containing a passage or claim plus provenance, freshness, and quality metadata. |
| Current-information question | A request whose correct answer may depend on recent facts, such as news, prices, schedules, laws, leadership, weather, or software versions. |
| Known | Outcome adequately supported by available evidence. |
| Inferred | A conclusion reasonably derived from evidence but not directly established. |
| Unknown | Relevant evidence is missing, weak, or conflicting. |
| Blocked | A needed service, source, permission, or tool was unavailable. |
| Memory | Persisted owner-approved profile or history data used for continuity. Basic V1 memory excludes semantic long-term memory. |
| Web reader | Component that retrieves selected pages after search. It is not a general crawler or browser agent. |
| Crawling | Systematic traversal and indexing of linked pages. Deferred from V1. |

**Ambiguous source terms.** "Main model," "master," "base," and "orchestrator" were sometimes used interchangeably. This SRS separates the local **generalist model** from the deterministic **application orchestrator**. "Specialized model" in V1 means a prompt-defined specialist role using a configurable cloud model, not a separately trained model. "Web crawling" in V1 is narrowed to on-demand search and selected-page reading; focused crawling is future scope.

# 8. Assumptions, Dependencies, and Constraints

## 8.1 Confirmed Assumptions

No factual assumption is fully confirmed independently of the owner's acceptance. The intended V1 is a single-owner personal system; owner confirmation is requested in OQ-01.

## 8.2 Unverified Assumptions

| ID | Assumption | If false |
|---|---|---|
| ASM-01 | One primary user operates V1. | Authentication, isolation, permissions, and storage require redesign. |
| ASM-02 | The owner's hardware can run a suitable medium-sized Ollama model. | Model size, latency targets, or local-first capability must change. |
| ASM-03 | The owner can obtain and fund OpenAI API access. | Cloud specialist functionality is unavailable; local degradation must suffice. |
| ASM-04 | A lawful web-search/retrieval provider is available. | Current-information capability is blocked or provider choice must change. |
| ASM-05 | Approximately 30 curated evaluation requests are enough for initial regression control. | Broader evaluation and release gates are required. |
| ASM-06 | Basic session history and a small confirmed profile provide enough V1 continuity. | Long-term memory may need earlier scope, increasing privacy and retrieval complexity. |
| ASM-07 | English is the initial interaction language. | Localization and multilingual evaluation become V1 requirements. |
| ASM-08 | The owner is comfortable operating a terminal or simple web UI. | UI scope and accessibility work increase. |
| ASM-09 | Specialist outputs can be made useful through prompting and evidence without fine-tuning. | Alternative models, retrieval, tools, or fine-tuning must be evaluated. |

## 8.3 Technical Constraints

- **Confirmed constraint:** the primary generalist model must be served locally through Ollama.
- **Confirmed constraint:** V1 cloud specialists use one configurable OpenAI provider/model and prompt-defined roles.
- **Confirmed constraint:** the application, not model output, enforces permissions, limits, calls, and execution.
- **Confirmed constraint:** providers, models, prompts, and specialist manifests must be replaceable through configuration/contracts.
- **Confirmed constraint:** delegation depth is one in V1; specialists do not recursively delegate.
- **Confirmed constraint:** RAG must preserve source identity and must not be represented as a truth guarantee.

## 8.4 Hardware and Infrastructure Constraints

GPU model, GPU VRAM, system RAM, CPU, operating system, primary runtime details, storage allowance, and acceptable local latency are TBD. The reference environment is expected to be Windows 11 with WSL2, but the exact Ollama placement and host/guest split still need validation. Architecture sizing must not begin with an unverified model/hardware fit.

## 8.5 Budget and Cost Constraints

V1 must enforce configurable per-request and per-day cloud cost ceilings. Exact ceilings and behavior at the daily limit are TBD. Web-provider and storage costs are also TBD.

## 8.6 Schedule or Staffing Constraints

The source implies a personal portfolio project and recommends small scope. Team size, target date, weekly capacity, and support expectations are TBD. Planning must assume a single developer until confirmed otherwise.

## 8.7 Privacy and Regulatory Constraints

Private files and sensitive data must remain local unless the user explicitly permits a specific cloud disclosure. Applicable legal/regulatory regimes and sensitive-data categories are TBD. V1 is not approved for regulated professional advice, trading, diagnosis, or legal determinations.

## 8.8 External Dependencies

- Ollama and one compatible local model.
- OpenAI API access and an available configured model.
- A web search service and selected-page retrieval/extraction capability.
- Local persistent storage for configuration, history, evidence metadata, and logs.

## 8.9 Third-Party Service Limitations

Provider model names, rate limits, context limits, pricing, availability, terms, and data-handling policies may change. Exact provider-specific values must remain configuration and be validated before implementation and release.

# 9. System Context

The V1 system boundary includes the text client, application orchestrator, policy and limit enforcement, local Ollama adapter, one OpenAI provider adapter, research and coding specialist configurations, web search/reader, RAG/context selection, basic memory/profile storage, source storage, and operational/audit records.

The owner submits text through the client. The orchestrator classifies the request, selects only necessary context, and either calls the local generalist or creates bounded specialist/web tasks. Web content and model output enter the boundary as untrusted data. The orchestrator validates structured results, applies privacy and resource policy, synthesizes the final answer, and records an audit event. The owner may cancel an active task and review stored profile/history and execution information.

No authentication provider is confirmed for V1. No external write integration, device sensor, email, calendar, trading service, general browser agent, or command runner is inside the V1 boundary. Detailed service topology, framework, database schema, and deployment architecture are intentionally not finalized here.

# 10. User Journeys and Use Cases

## UC-01 Local conversation

- **Primary actor:** Owner
- **Goal:** Hold a multi-turn text conversation without cloud use.
- **Preconditions:** Application and Ollama are available; local-only mode is selected.
- **Trigger:** Owner submits a text prompt.
- **Normal flow:** Validate input; select recent context; call the local generalist; stream or return text; store allowed session data and operational metadata.
- **Alternative flows:** Owner disables session persistence; assistant uses only current-session context.
- **Failure flows:** If Ollama fails or the task exceeds limits, report `blocked`, preserve no false success, and offer a safe retry.
- **Expected outcome:** A relevant response or an explicit unknown/blocked result without cloud traffic.
- **Related requirements:** BUS-001, BUS-002, FR-001, FR-002, AI-001, AI-010, SEC-001, NFR-002.

## UC-02 Current-information research

- **Primary actor:** Owner
- **Goal:** Receive a current answer with evidence.
- **Preconditions:** Web access is permitted and provider is configured.
- **Trigger:** Prompt depends on current information or explicitly requests research.
- **Normal flow:** Detect freshness need; search; select authoritative pages; retrieve/extract; create evidence objects; rank by relevance, reliability, and freshness; pass minimum sufficient evidence to the research specialist; validate; cite claims.
- **Alternative flows:** If the local generalist can summarize sufficient retrieved evidence, cloud escalation may be skipped.
- **Failure flows:** No relevant result, timeout, robots/terms restriction, conflict, or weak evidence produces `unknown` or `blocked` plus separate next-step suggestions.
- **Expected outcome:** Grounded answer with clickable sources and retrieval context, or honest abstention.
- **Related requirements:** FR-003, FR-004, AI-006, AI-009, AI-010, DATA-003, API-003, SEC-003, SEC-006.

## UC-03 Coding specialist consultation

- **Primary actor:** Owner
- **Goal:** Obtain concise coding analysis from the specialist role.
- **Preconditions:** Cloud mode and OpenAI access permit the call; required code/context is supplied.
- **Trigger:** Request is classified as coding-specialist work.
- **Normal flow:** Build a bounded task; remove irrelevant/sensitive context; call configured coding role; require structured concise output; validate result; synthesize with the local conversation.
- **Alternative flows:** Owner chooses local-only mode; local generalist answers with capability disclosure.
- **Failure flows:** Missing repository/code, malformed specialist response, timeout, budget exhaustion, or provider error yields partial/blocked status without fabricated analysis.
- **Expected outcome:** Concise result with assumptions, uncertainties, evidence/artifacts if any, and no unapproved execution.
- **Related requirements:** AI-003, AI-004, AI-005, AI-007, AI-008, AI-013, API-002, SEC-005.

## UC-04 Cloud permission boundary

- **Primary actor:** Owner
- **Goal:** Control whether data is sent to a cloud model.
- **Preconditions:** A request could benefit from cloud processing.
- **Trigger:** Orchestrator proposes cloud escalation.
- **Normal flow:** Apply selected mode; inspect sensitivity; minimize context; obtain confirmation when policy requires it; call provider only if allowed; log scope and result.
- **Alternative flows:** Owner explicitly requests a provider or selects local-only mode.
- **Failure flows:** Permission denial or unavailable provider returns local result, `blocked`, or a clarification; no cloud call occurs.
- **Expected outcome:** Cloud use matches the configured mode and explicit consent.
- **Related requirements:** AI-014, SEC-001, SEC-002, DATA-004, API-002.

## UC-05 Unknown or conflicting evidence

- **Primary actor:** Owner
- **Goal:** Understand what the assistant can and cannot establish.
- **Preconditions:** Evidence is missing, weak, or conflicting.
- **Trigger:** Validation cannot support a known result.
- **Normal flow:** Classify as inferred, unknown, or blocked; state what is missing; preserve disagreements; separate suggestions from claims.
- **Failure flows:** A malformed model output claims certainty; validator rejects or downgrades it and records the reason.
- **Expected outcome:** No unsupported factual answer is presented as known.
- **Related requirements:** AI-010, AI-011, AI-012, UX-001.

## UC-06 Startup continuity

- **Primary actor:** Owner
- **Goal:** Resume with consistent behavior and useful approved context.
- **Preconditions:** Versioned behavior configuration and allowed history/profile data exist.
- **Trigger:** Application starts or a new session begins.
- **Normal flow:** Load behavior configuration; load confirmed profile and compact relevant recent history within context budget; do not load secrets or all historical content.
- **Alternative flows:** Owner disables persistence or deletes/corrects a profile item.
- **Failure flows:** Corrupt or unavailable memory is isolated; assistant starts with base configuration and reports degraded continuity.
- **Expected outcome:** Consistent assistant behavior without uncontrolled memory injection.
- **Related requirements:** DATA-001, DATA-002, DATA-005, AI-006, SEC-001.

## UC-07 Cancel long-running task

- **Primary actor:** Owner
- **Goal:** Stop research or specialist work.
- **Preconditions:** Task is active.
- **Trigger:** Owner issues cancel.
- **Normal flow:** Stop pending calls where possible; do not begin new calls; mark incomplete operations; retain verified partial results; release resources.
- **Failure flows:** A third-party call cannot be canceled; ignore late results for final action and disclose that the call had already been sent.
- **Expected outcome:** No continued delegation or external action after cancellation acknowledgment.
- **Related requirements:** FR-005, FR-006, NFR-001, OPS-001.

## UC-08 Limit reached

- **Primary actor:** Owner
- **Goal:** Receive a safe result when cost, time, token, retry, or call limits are reached.
- **Preconditions:** Limit policy is configured.
- **Trigger:** Next operation would exceed a hard limit.
- **Normal flow:** Prevent the operation; return verified partial results; identify the limit category without exposing secrets; propose owner-controlled next steps.
- **Failure flows:** Limit configuration is invalid; fail closed for cloud/write operations and surface configuration error.
- **Expected outcome:** No hard limit is exceeded.
- **Related requirements:** AI-019, NFR-001, NFR-002, OPS-002.

# 11. Functional Requirements

## 11.1 Product and interface

### BUS-001 Trustworthy personal assistant core

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must provide a personal text assistant that handles ordinary requests and coordinates approved research and coding assistance.
- **Rationale:** This is the central V1 product outcome.
- **Preconditions:** Application is running and at least the local provider is healthy.
- **Inputs:** Owner text request and allowed context.
- **Expected behavior:** Interpret the request, choose a permitted path, and return a response or explicit non-success status.
- **Outputs:** Text response plus relevant status, citations, or error information.
- **Failure behavior:** Return `blocked` with the failed capability; do not claim success.
- **Dependencies:** FR-001, AI-001, AI-002.
- **Acceptance criteria:** Given a representative V1 request set, when requests are submitted, then each is answered, clarified, declined, marked unknown, or marked blocked through the defined contract.
- **Source:** Accepted V1 core vision and final mandatory scope.

### BUS-002 Local-first operation

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must use local processing for ordinary requests and must remain usable in local-only mode when cloud services are unavailable or disallowed.
- **Rationale:** Privacy and independence are core goals.
- **Preconditions:** Ollama and the configured local model are available.
- **Inputs:** Request and selected privacy mode.
- **Expected behavior:** Avoid cloud calls in local-only mode; degrade specialist-dependent tasks honestly.
- **Outputs:** Local response or explicit capability limitation.
- **Failure behavior:** If local inference fails, report `blocked`; do not silently switch to cloud.
- **Dependencies:** AI-001, AI-014, API-001.
- **Acceptance criteria:** Given local-only mode and disabled network access, when ordinary conversation requests are submitted, then no cloud request occurs and the assistant returns local responses or clear blocked results.
- **Source:** Local-first requirement and cloud-mode policy.

### BUS-003 Extensible specialist capability

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must define a stable specialist registration and result contract so a new specialist can be added without modifying existing specialist implementations or the local generalist model.
- **Rationale:** Future specialization must not require a core rewrite.
- **Preconditions:** Specialist contract is versioned.
- **Inputs:** Specialist manifest/configuration.
- **Expected behavior:** Validate and register a conforming specialist; reject invalid definitions.
- **Outputs:** Available capability metadata or validation errors.
- **Failure behavior:** Invalid specialist remains disabled and cannot receive tasks.
- **Dependencies:** AI-003, AI-007, AI-015.
- **Acceptance criteria:** Given a test specialist conforming to the documented contract, when registered, then it becomes routable without changing existing specialist or local-model code; a nonconforming specialist is rejected.
- **Source:** Owner's scalability and incremental-specialist requirement.

### FR-001 Text interaction surface

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; interface choice TBD
- **Requirement:** The system must provide one text interaction surface, either a terminal interface or a simple web interface.
- **Rationale:** V1 must prove behavior before voice or vision.
- **Preconditions:** Local application is running.
- **Inputs:** Unicode text and user commands.
- **Expected behavior:** Accept, display, cancel, and associate requests with the active session.
- **Outputs:** Responses, status, citations, and errors in readable form.
- **Failure behavior:** Invalid or empty input is rejected without a model call; oversized input is rejected with the configured limit.
- **Dependencies:** OQ-02, UX-001.
- **Acceptance criteria:** Given a running V1 installation, when the owner enters valid text, then the complete response contract is displayed; when input is empty or over limit, then no model call occurs and a corrective message appears.
- **Source:** Final V1 scope; terminal versus simple web remained optional.

### FR-002 Multi-turn session context

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must maintain bounded context within an active conversation and allow a new session to begin without inherited transient context.
- **Rationale:** Ordinary conversation requires continuity without unbounded context growth.
- **Preconditions:** An active session exists.
- **Inputs:** Ordered messages and approved tool/specialist summaries.
- **Expected behavior:** Select relevant recent context within budget and distinguish session data from persistent profile data.
- **Outputs:** Context-aware response and session record when persistence is enabled.
- **Failure behavior:** If context cannot fit, summarize or omit lower-priority items and disclose material omissions when they affect the answer.
- **Dependencies:** AI-006, DATA-001.
- **Acceptance criteria:** Given a multi-turn test and a configured context limit, when later prompts refer to earlier in-session facts, then relevant facts are used without exceeding the limit; a new session does not inherit transient facts unless retrieved as approved memory.
- **Source:** Conversation-history and bounded-context requirements.

## 11.2 Web research and recovery

### FR-003 Current-information detection and research

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must detect requests likely to depend on current information and attempt permitted web retrieval before presenting time-sensitive claims as current.
- **Rationale:** Stored model knowledge may be stale.
- **Preconditions:** Web access is configured and permitted.
- **Inputs:** User request and current date/time.
- **Expected behavior:** Classify freshness need, retrieve current evidence, and attach retrieval dates.
- **Outputs:** Cited answer or unknown/blocked result.
- **Failure behavior:** If retrieval is unavailable or insufficient, state that the latest information cannot be verified.
- **Dependencies:** API-003, DATA-003, AI-010.
- **Acceptance criteria:** Given a curated set of current and timeless questions, when processed, then current questions trigger retrieval and timeless questions do not trigger unnecessary web calls at the approved evaluation threshold.
- **Source:** Freshness-awareness and web-research requirements.

### FR-004 Search, selected-page reading, and citations

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must search for relevant pages, retrieve only selected permitted pages, extract useful content, and provide clickable citations linking claims to their sources.
- **Rationale:** V1 needs evidence without a general crawler.
- **Preconditions:** Search/reader provider is healthy and policy permits targets.
- **Inputs:** Search query, approved URLs, and retrieval policy.
- **Expected behavior:** Prefer primary/authoritative sources; deduplicate; record provenance and freshness; preserve source disagreement.
- **Outputs:** Evidence objects and cited answer.
- **Failure behavior:** Unsupported, blocked, oversized, disallowed, or unreadable content is skipped and recorded; no citation is fabricated.
- **Dependencies:** DATA-003, API-003, SEC-003, SEC-006.
- **Acceptance criteria:** Given ten approved current-information evaluation questions, when research succeeds, then each factual answer contains working citations to retrieved pages and source metadata; disallowed URLs are not fetched.
- **Source:** Web research pipeline and V1 scope.

### FR-005 Task cancellation

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must allow the owner to cancel a running model, research, or specialist task.
- **Rationale:** Long or costly operations require user control.
- **Preconditions:** A cancellable task is active.
- **Inputs:** Cancel command.
- **Expected behavior:** Stop scheduling new work, cancel supported calls, ignore late results for further action, release resources, and report completed portions.
- **Outputs:** Cancellation acknowledgment and partial-result status.
- **Failure behavior:** If an already-sent external call cannot be canceled, disclose that fact and prevent downstream actions.
- **Dependencies:** NFR-001, OPS-001.
- **Acceptance criteria:** Given a delayed multi-call task, when cancellation occurs, then no new call starts afterward and the task ends with `partial` or `blocked` plus completed work.
- **Source:** Cancellation and interruption requirement.

### FR-006 Failure and partial-result handling

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must identify failed components, retain verified partial results, avoid global success claims after partial failure, and offer bounded retry or alternatives.
- **Rationale:** Transparent degradation prevents fabricated completion.
- **Preconditions:** A component returns an error, timeout, malformed output, or limit event.
- **Inputs:** Component result and task state.
- **Expected behavior:** Classify status, retain provenance, apply retry policy, and synthesize only verified output.
- **Outputs:** Clear failure/partial result and recovery options.
- **Failure behavior:** If status cannot be determined, fail closed as `blocked`.
- **Dependencies:** AI-010, NFR-002, OPS-001.
- **Acceptance criteria:** Given injected failures at each provider boundary, when a task completes, then the failed component is named, verified partial work is preserved, and no full-success status is emitted.
- **Source:** Failure and partial-result requirement.

## 11.3 Memory and data controls

### DATA-001 Basic session history

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must support configurable storage of conversation/session history and must honor a no-save session mode.
- **Rationale:** V1 needs continuity without mandatory permanent storage.
- **Preconditions:** Local storage is available.
- **Inputs:** Messages, session metadata, persistence preference.
- **Expected behavior:** Persist only when enabled; separate transient context from persistent records.
- **Outputs:** Session records or confirmation that the session is not retained.
- **Failure behavior:** On storage failure, continue only if safe and disclose that history was not saved.
- **Dependencies:** SEC-001, DATA-005.
- **Acceptance criteria:** Given no-save mode, when a session ends, then its message content is absent from persistent history; given persistence enabled, then the session can be reloaded subject to retention policy.
- **Source:** Basic history and intentional-memory requirements.

### DATA-002 Confirmed user profile and startup continuity

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must store a small set of explicitly confirmed user preferences separately from model-derived assumptions and load only relevant profile data plus versioned assistant behavior at startup.
- **Rationale:** Consistency should not depend on loading all conversations.
- **Preconditions:** Profile storage exists and entries are valid.
- **Inputs:** Owner-confirmed preferences and behavior configuration.
- **Expected behavior:** Track source, confirmation state, sensitivity, timestamps, and optional expiry; exclude unconfirmed inference from confirmed profile.
- **Outputs:** Bounded startup context and reviewable profile.
- **Failure behavior:** Invalid/corrupt entries are skipped; base behavior still loads and degraded continuity is reported.
- **Dependencies:** AI-006, SEC-001.
- **Acceptance criteria:** Given confirmed and inferred test entries, when the assistant starts, then confirmed relevant entries may load, inferred entries do not masquerade as confirmed facts, and behavior configuration remains unchanged by memory content.
- **Source:** Startup continuity and memory refinement.

### DATA-003 Evidence and provenance records

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must represent each retrieved source passage as an evidence object containing URL, canonical URL when available, source/publisher, title, publication date when available, retrieval timestamp, source category, relevance/freshness indicators, content hash, and claim/passage text.
- **Rationale:** Citation, freshness, deduplication, and auditability require provenance.
- **Preconditions:** Content is retrieved.
- **Inputs:** Retrieved page and extraction metadata.
- **Expected behavior:** Validate fields, retain conflicts, and associate evidence with supported claims.
- **Outputs:** Stored or transient evidence object.
- **Failure behavior:** Missing optional metadata is marked unavailable; missing URL or retrieval time prevents use as cited evidence.
- **Dependencies:** FR-004, AI-009.
- **Acceptance criteria:** Given retrieved pages with duplicate, missing-date, and conflicting content, when evidence is created, then duplicates are identifiable by canonical URL/hash, missing dates are explicit, and conflicts remain separate.
- **Source:** Evidence pipeline and provenance requirement.

### DATA-004 Execution and audit records

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must record models, provider/model IDs, specialist and prompt versions, tools, sources, proposed/performed actions, approvals, errors, retries, durations, token usage when available, and estimated cloud cost.
- **Rationale:** The owner needs traceability and cost visibility.
- **Preconditions:** An execution begins.
- **Inputs:** Structured lifecycle events.
- **Expected behavior:** Append correlated records with task/session IDs and redaction.
- **Outputs:** Queryable local execution record.
- **Failure behavior:** Audit-write failure must be surfaced; high-impact actions must not proceed without a required approval record.
- **Dependencies:** SEC-007, OPS-001.
- **Acceptance criteria:** Given successful, failed, retried, and cloud-delegated tasks, when logs are inspected, then required fields and correlations exist and secrets/sensitive prompt bodies are absent according to policy.
- **Source:** Transparent execution log and auditability requirements.

### DATA-005 Review, correction, deletion, and no-store control

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The owner must be able to review, correct, and delete stored profile information and request that a conversation not be stored.
- **Rationale:** Memory must remain intentional and user-controlled.
- **Preconditions:** Stored profile or session data exists.
- **Inputs:** Review, correction, deletion, or no-store command.
- **Expected behavior:** Display applicable records, apply the requested change, and record non-sensitive audit metadata.
- **Outputs:** Updated data and confirmation.
- **Failure behavior:** If deletion/correction cannot complete, report exact scope not changed and do not claim completion.
- **Dependencies:** DATA-001, DATA-002, SEC-001.
- **Acceptance criteria:** Given a stored profile item, when the owner corrects and then deletes it, then subsequent retrieval reflects the correction and later absence; given no-store mode, conversation content is not persisted.
- **Source:** Intentional-memory control requirements.

# 12. AI and Agent Requirements

## 12.1 AI responsibilities

### AI-001 Configurable local generalist

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; exact model TBD
- **Requirement:** The system must use a configurable medium-sized model served through Ollama as the primary generalist for ordinary conversation, routing assistance, summarization, and final-response composition.
- **Rationale:** Owner selected local Ollama execution.
- **Preconditions:** Compatible model installed and hardware budget approved.
- **Inputs:** Bounded context package.
- **Expected behavior:** Produce response or structured orchestration assistance without executing tools or authorizing actions.
- **Outputs:** Model text or validated structured proposal.
- **Failure behavior:** Timeout, unavailable model, or malformed output returns `blocked` or a bounded retry; no silent cloud switch.
- **Dependencies:** API-001, OQ-03.
- **Acceptance criteria:** Given a configured supported Ollama model, when ordinary requests run, then calls use that model; swapping to another compatible model requires configuration change rather than orchestrator code change.
- **Source:** Final local model requirement.

### AI-002 Application-controlled orchestration

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The application orchestrator must control routing, tool/API invocation, context selection, privacy, permissions, limits, validation, conflict handling, and final status; model output may propose but must not authorize or directly execute operations.
- **Rationale:** Security and reliability cannot depend on prompt obedience alone.
- **Preconditions:** A request is accepted.
- **Inputs:** Request, policy, capabilities, and validated model proposals.
- **Expected behavior:** Enforce deterministic checks before every external operation.
- **Outputs:** Approved task graph and final result.
- **Failure behavior:** Invalid or policy-violating proposals are rejected and logged.
- **Dependencies:** SEC-004, SEC-005, NFR-001.
- **Acceptance criteria:** Given adversarial model output requesting an unauthorized call, when processed, then no call executes and a policy rejection is recorded.
- **Source:** Refined orchestrator responsibility.

### AI-003 V1 research and coding specialist roles

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must provide two narrow prompt-defined specialist roles: research and coding.
- **Rationale:** These roles test extensibility and are more objectively evaluable than broad specialization.
- **Preconditions:** Provider and prompts are configured.
- **Inputs:** Bounded structured task and permitted evidence/context.
- **Expected behavior:** Each role follows its declared capability, risk, context, output, timeout, and cost contract.
- **Outputs:** Structured specialist result.
- **Failure behavior:** Unsupported tasks are returned as `unknown` or rejected rather than answered outside role.
- **Dependencies:** AI-004, AI-007, BUS-003.
- **Acceptance criteria:** Given research, coding, and unrelated tasks, when routed, then each specialist accepts only in-scope tasks and returns contract-valid results; unrelated tasks are not forced into a specialist.
- **Source:** Latest final V1 list specifying two prompt-defined roles.

### AI-004 Configurable OpenAI cloud specialist provider

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed intent; exact API model ID TBD
- **Requirement:** The system must integrate one configurable OpenAI API provider/model for prompt-defined specialist calls, without hard-coding the provider or model identifier across the system.
- **Rationale:** The owner chose an OpenAI cloud model while requiring portability.
- **Preconditions:** Credentials, model access, privacy permission, and budget are valid.
- **Inputs:** Structured context package and specialist configuration.
- **Expected behavior:** Apply configured model, prompt version, token limit, reasoning setting when supported, timeout, and fallback policy.
- **Outputs:** Structured response plus usage metadata.
- **Failure behavior:** Authentication, quota, model-not-found, timeout, or malformed output produces a typed failure and permitted fallback; no fabricated result.
- **Dependencies:** API-002, OQ-04.
- **Acceptance criteria:** Given a valid configured model, when a specialist call occurs, then the configured identifier is used and usage is logged; given an invalid identifier, then a typed configuration/provider error is returned without repeated uncontrolled retries.
- **Source:** Owner specified GPT-5.6 Luna; final refinement made model configurable.

## 12.2 Orchestration and routing

### AI-005 Bounded specialist routing

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The orchestrator must call a specialist only when its declared capability adds value and must use deterministic request attributes plus validated model-assisted classification where needed.
- **Rationale:** Typical requests should not incur unnecessary cost or latency.
- **Preconditions:** Capability registry and routing rules are loaded.
- **Inputs:** Request features, attachment types if any, freshness need, privacy mode, risk, and capabilities.
- **Expected behavior:** Select local-only, research, coding, or clarification path and record the reason.
- **Outputs:** Route decision.
- **Failure behavior:** Ambiguous high-impact routing requests clarification or chooses the safer local/no-action path.
- **Dependencies:** BUS-003, AI-013, NFR-001.
- **Acceptance criteria:** Given the approved routing evaluation set, when classified, then accuracy meets the owner-approved threshold and ordinary requests do not invoke specialists unnecessarily.
- **Source:** Generalist/specialist routing requirements.

### AI-006 Minimum-sufficient context construction

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Every model call must receive the smallest sufficient context selected by task relevance, source reliability, freshness, privacy, duplication, and token budget.
- **Rationale:** Maximum context can increase cost, latency, distraction, and leakage.
- **Preconditions:** Candidate context exists.
- **Inputs:** Task, user constraints, compact history, approved profile, retrieved passages, source metadata, output schema, and budget.
- **Expected behavior:** Rank, deduplicate, truncate/summarize with provenance, reserve output space, and exclude unrelated history, secrets, and raw crawler output.
- **Outputs:** Auditable context manifest and model request.
- **Failure behavior:** If essential context cannot fit, ask for scope reduction or return blocked/partial; do not silently omit critical constraints.
- **Dependencies:** AI-009, SEC-002, NFR-001.
- **Acceptance criteria:** Given an oversized mixed-relevance context set and a fixed token budget, when packaged, then required high-priority items fit, duplicates/unrelated items are excluded, secrets are excluded, output budget remains, and the total does not exceed the configured limit.
- **Source:** Refined context-construction requirement.

### AI-013 Delegation depth and recursion limit

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** V1 must limit delegation depth to one and prevent specialists from recursively invoking other specialists or tools unless a future policy explicitly changes the limit.
- **Rationale:** Prevents loops, uncontrolled cost, and specialist chaos.
- **Preconditions:** Specialist task is created.
- **Inputs:** Parent task/depth metadata.
- **Expected behavior:** Reject nested delegation at depth greater than one.
- **Outputs:** Result or typed policy rejection.
- **Failure behavior:** Attempted recursion is stopped and logged.
- **Dependencies:** AI-002, NFR-001.
- **Acceptance criteria:** Given a specialist output requesting another specialist call, when processed in V1, then the nested call is not executed and the event is recorded.
- **Source:** Final orchestrator refinement.

## 12.3 Prompt, model, and result contracts

### AI-007 Structured specialist results

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Each specialist must return a validated structure containing at least `status`, `answer`, `key_evidence`, `sources`, `assumptions`, `uncertainties`, and `recommended_action`.
- **Rationale:** Predictable results enable validation, synthesis, retry, and audit.
- **Preconditions:** A specialist is invoked.
- **Inputs:** Specialist task and output schema.
- **Expected behavior:** Enforce schema and distinguish subjective confidence from verification/evidence state if confidence is included.
- **Outputs:** Contract-valid result.
- **Failure behavior:** One schema-correction attempt may occur if allowed; otherwise return malformed-result failure.
- **Dependencies:** AI-004, NFR-002.
- **Acceptance criteria:** Given valid, missing-field, wrong-type, and free-prose specialist responses, when validated, then only valid responses proceed; invalid responses receive at most the configured retry and cannot be presented as successful.
- **Source:** Concise specialist communication contract.

### AI-008 Concise specialist output

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Specialist outputs must be concise, task-focused, free of filler and repetition, and bounded by configured output-token and evidence-item limits.
- **Rationale:** The owner explicitly requested direct specialist output and efficient calls.
- **Preconditions:** Specialist call is constructed.
- **Inputs:** Output schema and configured limits.
- **Expected behavior:** Request only necessary fields and enforce maximum output size.
- **Outputs:** Concise structured result.
- **Failure behavior:** Truncated output is marked partial and is not treated as complete.
- **Dependencies:** AI-007, NFR-001.
- **Acceptance criteria:** Given specialist evaluation prompts, when responses are returned, then they satisfy the schema and configured token/item ceilings; truncation produces `partial` rather than `success`.
- **Source:** Owner's explicit concise-output requirement.

### AI-015 Model and prompt portability

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Each model/specialist configuration must declare provider, model ID, prompt version, supported modality, input/output limits, cost category, privacy classification, timeout, and fallback behavior.
- **Rationale:** Providers and models will change.
- **Preconditions:** Configuration is loaded.
- **Inputs:** Versioned provider and specialist configuration.
- **Expected behavior:** Validate configuration before use and record the active versions.
- **Outputs:** Active capability registry or configuration errors.
- **Failure behavior:** Invalid configurations fail closed for affected capability.
- **Dependencies:** BUS-003, API-001, API-002.
- **Acceptance criteria:** Given a model change within a compatible adapter, when configuration is updated, then the new model is used without changes to orchestration policy or specialist result handling.
- **Source:** Model/prompt portability refinement.

## 12.4 Retrieval, evidence, and uncertainty

### AI-009 Evidence-grounded RAG

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** RAG must retrieve task-relevant passages with source identity, location where available, freshness filtering for time-sensitive requests, and privacy filtering before cloud use; weak retrieval must produce insufficient-evidence status.
- **Rationale:** RAG assists grounding but does not guarantee truth.
- **Preconditions:** An approved evidence corpus or retrieved web evidence exists.
- **Inputs:** Task query, evidence candidates, thresholds, and context budget.
- **Expected behavior:** Rank by relevance, reliability, and freshness; deduplicate; preserve conflicts; separate personal memory from factual knowledge.
- **Outputs:** Selected evidence package and retrieval metadata.
- **Failure behavior:** No reliable passage yields `unknown` or `blocked`; the model is not pressured to invent an answer.
- **Dependencies:** DATA-003, AI-006, SEC-002.
- **Acceptance criteria:** Given relevant, irrelevant, stale, duplicate, conflicting, and sensitive passages, when retrieval runs, then selected passages meet configured thresholds, duplicates are removed, freshness applies when needed, conflicts remain visible, and sensitive passages are withheld from cloud calls without permission.
- **Source:** Owner required RAG to reduce hallucination; refinement clarified its limits.

### AI-010 Known/inferred/unknown/blocked behavior

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must classify material answer outcomes as `known`, `inferred`, `unknown`, or `blocked` and communicate the classification when uncertainty matters.
- **Rationale:** Saying "I don't know" before suggestions is a core owner requirement.
- **Preconditions:** Evidence and component results are available or absent.
- **Inputs:** Evidence quality, conflicts, missing information, and tool/provider status.
- **Expected behavior:** State unknown/blocked first, explain missing information briefly, and separate suggestions from established answers.
- **Outputs:** Status and response.
- **Failure behavior:** If validation cannot support `known`, downgrade rather than preserve model certainty.
- **Dependencies:** AI-011, AI-012, UX-001.
- **Acceptance criteria:** Given scenarios with strong evidence, indirect evidence, no evidence, conflicting evidence, and failed retrieval, when answered, then statuses match the approved rubric and suggestions following unknown/blocked are visibly separated.
- **Source:** Owner's explicit uncertainty requirement.

### AI-011 Non-fabrication and truthful execution reporting

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must not invent facts, citations, files, memories, tool results, or action success, and must not claim retrieval or execution that lacks a corresponding successful record.
- **Rationale:** Epistemic honesty is the highest-priority behavioral contract.
- **Preconditions:** A response is being validated.
- **Inputs:** Draft response, evidence, and execution records.
- **Expected behavior:** Remove, qualify, or reject unsupported claims.
- **Outputs:** Grounded response or abstention.
- **Failure behavior:** Validation failure returns unknown/blocked rather than unsupported content.
- **Dependencies:** DATA-003, DATA-004, AI-012.
- **Acceptance criteria:** Given adversarial prompts and injected tool failures, when a final response is produced, then it contains no nonexistent citation or success claim and accurately reports the failed operation.
- **Source:** Epistemic-honesty requirement.

### AI-012 Output validation and conflict handling

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The orchestrator must validate specialist/model output against schema, evidence, policy, and execution records; it must preserve material source or specialist disagreement and must not resolve it by unsupported majority or model confidence.
- **Rationale:** Specialists and models can be confidently wrong.
- **Preconditions:** Draft or specialist result exists.
- **Inputs:** Result, evidence links, policy rules, and conflict set.
- **Expected behavior:** Check structure and claim support; label inference; expose unresolved conflict; request clarification or verification when appropriate.
- **Outputs:** Validated result and verification status.
- **Failure behavior:** Unverifiable material claims are removed, qualified, or cause abstention.
- **Dependencies:** AI-007, AI-010, AI-011.
- **Acceptance criteria:** Given conflicting authoritative sources and an overconfident specialist answer, when validated, then the disagreement is disclosed and the answer is not labeled known unless an approved resolution rule supports it.
- **Source:** Evidence, specialist conflict, and hallucination-mitigation requirements.

## 12.5 Cloud modes, limits, and security

### AI-014 User-selectable cloud policy modes

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; default mode TBD
- **Requirement:** The system must support at least local-only and cloud-permitted modes, and must allow policy to require confirmation before sensitive data is sent externally.
- **Rationale:** The owner must control privacy/capability tradeoffs.
- **Preconditions:** Mode configuration is valid.
- **Inputs:** Selected mode, request sensitivity, and user permission.
- **Expected behavior:** Apply mode before any cloud request and disclose cloud delegation when it occurs.
- **Outputs:** Authorized cloud call or local/blocked alternative.
- **Failure behavior:** Ambiguous sensitivity or invalid mode fails closed against cloud transmission.
- **Dependencies:** SEC-001, SEC-002, API-002.
- **Acceptance criteria:** Given identical prompts under local-only and cloud-permitted modes, when processed, then cloud calls occur only under allowed conditions; sensitive sample content is not sent without required confirmation.
- **Source:** Controlled cloud escalation requirement.

### AI-019 Bounded model and tool use

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; numeric defaults proposed/TBD
- **Requirement:** The orchestrator must enforce configurable hard limits for specialist calls, tool calls, delegation depth, concurrent model calls, concurrent web requests, input/output tokens, per-call timeout, retries, cloud cost per request/day, pages/read size, local queue size, local concurrency, and total task duration.
- **Rationale:** Prevent crashes, runaway cost, loops, and resource exhaustion.
- **Preconditions:** Valid limit configuration is loaded.
- **Inputs:** Current usage and proposed operation.
- **Expected behavior:** Reserve/check budget before execution; apply queue backpressure; refuse operations that would exceed a hard limit.
- **Outputs:** Executed operation or typed limit event.
- **Failure behavior:** Missing/invalid hard-limit configuration fails closed for cloud and external operations.
- **Dependencies:** NFR-001, OPS-002, OQ-05.
- **Acceptance criteria:** Given test configurations with low limits, when requests attempt to exceed each limit class, then the excess operation is not executed, partial results remain available, and the limit event is logged.
- **Source:** API limiter and comprehensive guardrail requirement.

### AI-016 Optional high-impact verification pass

- **Priority:** Should
- **Version:** V1
- **Status:** Proposed
- **Requirement:** The system should allow a configured second verification pass for selected high-impact factual claims when budget and privacy policy permit.
- **Rationale:** Independent checking may improve reliability in finance, health, legal, or security topics.
- **Preconditions:** Verification policy, provider, and budget exist.
- **Inputs:** Claims and cited evidence.
- **Expected behavior:** Verify support rather than ask another model to repeat the answer.
- **Outputs:** Verification status and disagreements.
- **Failure behavior:** Failed verification leaves the original result qualified; it does not create certainty.
- **Dependencies:** AI-012, NFR-001.
- **Acceptance criteria:** Optional; release does not depend on it. If enabled, a test unsupported claim must be flagged.
- **Source:** Earlier recommendation; not explicitly required by owner.

# 13. Data Requirements

## 13.1 Conceptual entities

| Entity | Purpose | Key conceptual fields and relationships |
|---|---|---|
| Session | Conversation boundary | ID, timestamps, persistence mode; contains messages and tasks |
| Message | User/assistant text | Role, content or redacted reference, time, status; belongs to session |
| User profile item | Confirmed preference/fact | Content, type, source, confirmed flag, sensitivity, timestamps, expiry |
| Task | Unit of orchestration | Goal, status, route, parent/depth, budgets; belongs to session |
| Specialist definition | Versioned capability | ID, prompt version, provider/model, accepted inputs, limits, risk |
| Model call | Provider interaction | Provider/model, prompt version, token/latency/cost metadata; belongs to task |
| Tool execution | Web/read or future tool call | Tool/version, validated input summary, status, timing; belongs to task |
| Evidence object | Retrieved support | Provenance/freshness/content hash; linked to task and claims |
| Approval | User authorization | Exact proposed operation/data scope, decision, time; linked to task |
| Audit event | Operational trace | Correlation IDs, type, redacted details, time, result |

The storage technology and finalized schema are not approved. Conceptual relationships above are requirements inputs, not a database design.

## 13.2 Ownership, validation, and sources

The owner owns profile, session, approval, and locally retained evidence/log data. Provider-generated content remains untrusted data. All identifiers, timestamps, enum/status values, URLs, sizes, and configuration values must be validated at trust boundaries. Derived assumptions must not be stored as confirmed user facts.

## 13.3 Retention, deletion, backup, import/export, and migration

- Session/profile retention periods are TBD; no-save mode and profile deletion are required.
- Logs must follow a separate redacted retention policy, TBD before production.
- Backup and recovery objectives are TBD; loss of profile/history must not corrupt versioned assistant behavior.
- User-facing profile review/correction/deletion is required; full portable export is recommended.
- No legacy data migration is required for initial V1. Future schema changes must support versioned migrations.

## 13.4 Sensitive-data classification

At minimum, secrets/API keys, authentication tokens, private file contents, financial account data, health data, legal/private communications, precise identity details, and owner-designated sensitive content must be treated as sensitive. Final classification and cloud eligibility rules are open questions.

### DATA-006 Portable trace export

- **Priority:** Should
- **Version:** V1
- **Status:** Proposed
- **Requirement:** The system should allow the owner to export a redacted execution trace and source list in a portable format.
- **Rationale:** Improves debugging and AI-assisted handoff.
- **Preconditions:** Trace exists.
- **Inputs:** Task ID and export scope.
- **Expected behavior:** Export correlated events with secrets/sensitive content removed.
- **Outputs:** Portable trace file.
- **Failure behavior:** Refuse export if safe redaction cannot be assured.
- **Dependencies:** DATA-004, SEC-007.
- **Acceptance criteria:** Optional; if implemented, exported trace matches task records and contains no seeded secrets.
- **Source:** Recommendation derived from auditability; not owner-confirmed.

# 14. API and Integration Requirements

### API-001 Ollama integration

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must integrate with Ollama through a replaceable local-provider adapter supporting configured model selection, timeout, cancellation where supported, health status, and typed errors.
- **Rationale:** Ollama is the confirmed local runtime.
- **Preconditions:** Ollama endpoint is configured.
- **Inputs:** Model request and limits.
- **Expected behavior:** Validate request, invoke local model, collect timing/usage when available, and return normalized result.
- **Outputs:** Normalized model result or typed error.
- **Failure behavior:** Connection, model-missing, timeout, overload, and malformed-response errors remain distinguishable.
- **Dependencies:** AI-001, OPS-002.
- **Acceptance criteria:** Given healthy, unavailable, missing-model, timeout, and malformed test conditions, when invoked, then the adapter returns the corresponding normalized status and never silently invokes cloud fallback.
- **Source:** Confirmed Ollama requirement.

### API-002 OpenAI provider integration

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed intent; provider-specific details TBD
- **Requirement:** The system must provide one OpenAI adapter that supports configured model ID, structured specialist output, usage capture, timeout, cancellation when supported, rate-limit handling, and one bounded retry/fallback policy.
- **Rationale:** Owner selected OpenAI prompt-defined specialists.
- **Preconditions:** Valid credentials, accessible model, permission, and budget.
- **Inputs:** Bounded specialist request.
- **Expected behavior:** Authenticate without exposing secrets, enforce limits, normalize response and errors, and log metadata.
- **Outputs:** Validated normalized result and usage.
- **Failure behavior:** Authentication/quota/rate/model/timeout/schema failures are explicit; retry only when policy allows.
- **Dependencies:** AI-004, SEC-002, SEC-004, NFR-002.
- **Acceptance criteria:** Given mocked success and each major failure class, when invoked, then normalized outcomes, retry count, privacy decision, and cost/usage metadata match policy.
- **Source:** Final cloud specialist requirement.

### API-003 Web search and page-reader integration

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed capability; provider TBD
- **Requirement:** The system must integrate a search and selected-page retrieval capability with configurable authentication, request/size/page limits, timeout, rate-limit behavior, content-type checks, and source metadata extraction.
- **Rationale:** Current-information retrieval is required; unrestricted crawling is not.
- **Preconditions:** Provider and network policy are configured.
- **Inputs:** Query or validated public URL.
- **Expected behavior:** Search, rank, fetch selected pages, normalize canonical URLs, extract main content/metadata, and generate evidence objects.
- **Outputs:** Search candidates, evidence objects, and typed failures.
- **Failure behavior:** Robots/terms restriction, disallowed address, unsupported type, oversized response, timeout, rate limit, and extraction failure are explicit and safely skipped.
- **Dependencies:** FR-003, FR-004, SEC-003, SEC-006.
- **Acceptance criteria:** Given test pages for allowed HTML, private-network URL, redirect to private address, oversized file, unsupported type, timeout, and rate limit, when processed, then only allowed bounded content becomes evidence and each failure is classified.
- **Source:** On-demand web research and web-safety requirements.

### API-004 Integration fallback contract

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Each external integration must declare purpose, data scope, authentication mechanism, limits, timeout, retry eligibility, fallback, error mapping, cost category, privacy classification, and V1 necessity in configuration or documentation.
- **Rationale:** Prevents hidden provider coupling and unsafe fallback.
- **Preconditions:** Integration is enabled.
- **Inputs:** Integration configuration.
- **Expected behavior:** Validate required declarations before activation.
- **Outputs:** Active or disabled integration state.
- **Failure behavior:** Incomplete integration configuration disables the capability and reports the missing fields.
- **Dependencies:** AI-015, OPS-002.
- **Acceptance criteria:** Given an integration definition missing privacy or limit fields, when configuration loads, then it is disabled; a complete definition is activated and visible in health/config status.
- **Source:** Provider-independent integration requirements.

# 15. Security, Privacy, and Safety Requirements

### SEC-001 Local/cloud privacy boundary

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must classify candidate context by privacy level and must not transmit private files, sensitive conversation content, or profile data to a cloud provider unless the active policy and explicit consent permit the specific disclosure.
- **Rationale:** Local-first privacy is a core requirement.
- **Preconditions:** Candidate cloud call exists.
- **Inputs:** Data classification, mode, task, and approval.
- **Expected behavior:** Minimize and redact context; block unauthorized categories; log only non-sensitive decision metadata.
- **Outputs:** Approved minimized context or policy denial.
- **Failure behavior:** Unknown classification fails closed for cloud transmission.
- **Dependencies:** AI-014, SEC-002.
- **Acceptance criteria:** Given public, private, secret, and unclassified sample data under each mode, when cloud escalation is proposed, then only policy-permitted content is sent and unknown/sensitive content requires the configured confirmation or is blocked.
- **Source:** Privacy-boundary requirement.

### SEC-002 Consent for external data sharing

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; consent UX TBD
- **Requirement:** When confirmation is required, the system must show the provider, purpose, and exact categories or bounded content proposed for transmission before the user approves.
- **Rationale:** Generic confirmation is insufficient for informed consent.
- **Preconditions:** Policy requires approval.
- **Inputs:** Proposed provider call and minimized data scope.
- **Expected behavior:** Wait for explicit approval; bind approval to the exact proposal; expire or invalidate approval if the proposal materially changes.
- **Outputs:** Approval/denial record.
- **Failure behavior:** No response, denial, or changed scope means no call.
- **Dependencies:** DATA-004, AI-014.
- **Acceptance criteria:** Given a proposed cloud request requiring consent, when the user denies or the payload scope changes after approval, then no call occurs until a new exact approval is granted.
- **Source:** Controlled cloud escalation and exact-action confirmation.

### SEC-003 Untrusted external content and prompt injection

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must treat webpages, retrieved documents, model output, and tool output as untrusted data and must not follow embedded instructions that attempt to alter policy, reveal secrets, invoke tools, or exfiltrate data.
- **Rationale:** Web/RAG content can contain prompt injection.
- **Preconditions:** External content is ingested.
- **Inputs:** Extracted content and provenance.
- **Expected behavior:** Delimit content as evidence, strip/flag active instructions where feasible, and enforce all actions outside model prompts.
- **Outputs:** Sanitized evidence or rejection.
- **Failure behavior:** Suspicious content may be omitted or quarantined; task continues only with safe evidence.
- **Dependencies:** AI-002, FR-004.
- **Acceptance criteria:** Given test pages instructing the assistant to ignore policy, reveal keys, or call a tool, when researched, then none of those instructions execute and the content is treated only as quoted evidence or rejected.
- **Source:** External-content and prompt-injection requirement.

### SEC-004 Secrets management

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** API keys and authentication secrets must be stored outside prompts, model context, memory, source content, and ordinary logs, and must be redacted from errors and exports.
- **Rationale:** Secrets exposure would compromise all provider boundaries.
- **Preconditions:** Integration requires credentials.
- **Inputs:** Secret reference from approved configuration mechanism.
- **Expected behavior:** Resolve only at the adapter boundary and avoid serialization into audit content.
- **Outputs:** Authenticated request without user-visible secret.
- **Failure behavior:** Missing secret disables the integration; errors do not print secret material.
- **Dependencies:** API-002, API-003, SEC-007.
- **Acceptance criteria:** Given seeded canary secrets in configuration and provider errors, when tasks/logs/exports are inspected, then no secret value appears outside the credential mechanism.
- **Source:** API-key guardrail requirement.

### SEC-005 Least privilege and high-impact actions

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed behavioral contract
- **Requirement:** V1 tools and specialists must receive only capabilities and data necessary for their declared tasks; any future external write, communication, destructive, financial, or command action must require exact user confirmation and is disabled in V1.
- **Rationale:** A question does not authorize an action.
- **Preconditions:** A capability request is evaluated.
- **Inputs:** Tool manifest, risk class, and request.
- **Expected behavior:** Permit only V1 read-only research and model calls; reject high-impact capability requests.
- **Outputs:** Authorization result and audit event.
- **Failure behavior:** Unknown risk classification fails closed.
- **Dependencies:** AI-002, SEC-002.
- **Acceptance criteria:** Given prompts requesting email sending, trade execution, file deletion, or shell commands, when processed, then no such action occurs and the assistant explains that the capability is outside V1.
- **Source:** Permission levels and explicit non-goals.

### SEC-006 Input, URL, and retrieval safety

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must validate inputs and URLs; block local, loopback, link-local, private-network, unsupported-scheme, credential-bearing, and policy-denied targets; re-check redirects; and enforce content type and size limits.
- **Rationale:** Prevents SSRF, resource abuse, and unsafe retrieval.
- **Preconditions:** User/model supplies input or URL.
- **Inputs:** Text, URL, redirects, headers, and resolved addresses.
- **Expected behavior:** Normalize and validate before and during retrieval.
- **Outputs:** Safe request or typed rejection.
- **Failure behavior:** Validation ambiguity or DNS/address change blocks the fetch.
- **Dependencies:** API-003, NFR-001.
- **Acceptance criteria:** Given public, loopback, private IP, encoded private IP, credential URL, redirect-to-private, oversized, and unsupported-type cases, when fetched, then only the allowed bounded public case proceeds.
- **Source:** Web security and crawler safeguards.

### SEC-007 Log minimization and redaction

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Logs must exclude secrets, authentication data, raw sensitive prompts/files, unnecessary personal data, and full external content unless an explicit debug policy permits a sanitized sample.
- **Rationale:** Auditability must not create a privacy leak.
- **Preconditions:** An event is logged.
- **Inputs:** Event payload and classification.
- **Expected behavior:** Record metadata and redacted summaries sufficient for debugging.
- **Outputs:** Sanitized structured log.
- **Failure behavior:** If safe redaction cannot be determined, omit sensitive payload and record only event type/correlation/status.
- **Dependencies:** DATA-004, SEC-004.
- **Acceptance criteria:** Given seeded secrets and sensitive inputs across success/error paths, when all logs are scanned, then seeded values and raw sensitive payloads are absent while correlation and outcome remain available.
- **Source:** Auditability and sensitive-log restrictions.

# 16. Non-Functional Requirements

### NFR-001 Configurable hard resource limits

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; numeric values TBD
- **Requirement:** All limits listed in AI-019 must be externally configurable, validated at startup, and enforced before resource allocation or provider invocation.
- **Rationale:** Safe values depend on hardware, provider quotas, and owner budget.
- **Preconditions:** Configuration is loaded.
- **Inputs:** Limit values and current usage.
- **Expected behavior:** Reject invalid values; expose effective limits; enforce hard ceilings atomically where concurrency applies.
- **Outputs:** Valid configuration or startup/capability error.
- **Failure behavior:** Missing required cloud/external limits disables the affected capability.
- **Dependencies:** AI-019, OQ-05.
- **Acceptance criteria:** Given boundary and concurrent limit tests, when operations race for the final allowance, then accepted work never exceeds the configured ceiling and effective limits are observable.
- **Source:** Owner requested API limiter and crash prevention.

### NFR-002 Timeout, retry, backoff, and circuit breaking

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; values TBD
- **Requirement:** External and model calls must have timeouts, no unlimited retries, retry only eligible transient failures, use bounded backoff with jitter, and temporarily stop calls to repeatedly failing services.
- **Rationale:** Prevents hangs, retry storms, and wasted cost.
- **Preconditions:** A provider call is attempted.
- **Inputs:** Failure class, attempt count, circuit state, and deadline.
- **Expected behavior:** Apply at most the configured retry count within total task duration.
- **Outputs:** Success, retry event, open-circuit event, timeout, or final failure.
- **Failure behavior:** Unknown failure class is not retried automatically.
- **Dependencies:** API-001, API-002, API-003.
- **Acceptance criteria:** Given transient, permanent, timeout, and repeated-failure simulations, when calls execute, then only transient failures retry within limits, backoff occurs, and the circuit opens at the configured threshold.
- **Source:** Resource guardrail refinement.

### NFR-003 Local hardware fit and performance budget

- **Priority:** Must
- **Version:** V1
- **Status:** TBD - owner decision required
- **Requirement:** Before implementation acceptance, the selected local model must meet approved hardware ceilings and response-latency targets on the owner's target machine.
- **Rationale:** "Medium-sized" and "efficient" are otherwise untestable.
- **Preconditions:** Hardware inventory and candidate model are known.
- **Inputs:** Benchmark workload.
- **Expected behavior:** Measure load time, time to first token, generation throughput, peak RAM/VRAM, and stability under configured local concurrency.
- **Outputs:** Benchmark report and pass/fail.
- **Failure behavior:** A failing model is downsized/replaced or targets are revised by owner decision.
- **Dependencies:** OQ-03, AI-001.
- **Acceptance criteria:** Given the approved benchmark and thresholds, when run on target hardware, then every mandatory ceiling/latency target passes without crash or uncontrolled swapping.
- **Source:** Local medium-model and efficiency requirement; measurements not supplied.

### NFR-004 Permanent evaluation and regression suite

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed; pass thresholds TBD
- **Requirement:** The project must maintain approximately 30 versioned representative requests with expected behaviors covering conversation, routing, research grounding, citations, uncertainty, specialist output, privacy, failure, prompt injection, and limit enforcement.
- **Rationale:** Model/prompt changes require measurable regression control.
- **Preconditions:** Evaluation rubric and fixtures are approved.
- **Inputs:** Versioned prompts, fixtures, and expected assertions.
- **Expected behavior:** Run deterministically where possible, score probabilistic behavior with an approved rubric, and retain results by model/prompt version.
- **Outputs:** Evaluation report.
- **Failure behavior:** Release is blocked when mandatory thresholds fail or results cannot be reproduced sufficiently for review.
- **Dependencies:** OQ-09, Section 19.
- **Acceptance criteria:** Given the release candidate, when the suite runs, then all deterministic safety tests pass and each approved quality threshold is met; results identify model, prompt, provider, and date.
- **Source:** Final requirement for approximately 30 examples and permanent evaluations.

### NFR-005 Streaming responses

- **Priority:** Should
- **Version:** V1
- **Status:** Proposed
- **Requirement:** The text interface should display incremental local-model output while preserving cancellation and final validation/status.
- **Rationale:** Improves perceived responsiveness.
- **Preconditions:** Interface and provider support streaming.
- **Inputs:** Response stream.
- **Expected behavior:** Display provisional text clearly and reconcile with final status.
- **Outputs:** Incremental display and final result.
- **Failure behavior:** Interrupted streams are marked partial and not shown as complete.
- **Dependencies:** FR-001, FR-005.
- **Acceptance criteria:** Optional; if implemented, cancellation stops display and final state is not success after stream failure.
- **Source:** Earlier milestone recommendation; not explicitly confirmed as V1 mandatory.

### NFR-006 Maintainability and portability

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** Provider, model, specialist, prompt, tool, storage, and policy concerns must expose versioned interfaces/configuration so one implementation can be replaced without changing unrelated behavioral contracts.
- **Rationale:** Extensibility is a primary product goal.
- **Preconditions:** A component is implemented.
- **Inputs:** Contract tests and configuration.
- **Expected behavior:** Normalize provider-specific behavior at boundaries and keep policy provider-independent.
- **Outputs:** Passing contract tests.
- **Failure behavior:** Incompatible replacement is rejected before activation.
- **Dependencies:** BUS-003, AI-015, API-004.
- **Acceptance criteria:** Given test doubles for local, cloud, and web adapters, when substituted, then orchestrator contract tests pass without provider-specific changes outside the adapter/configuration boundary.
- **Source:** Avoid provider coupling and permit future specialists.

# 17. Failure Modes and Edge Cases

| Failure or edge case | Expected system behavior | User-visible outcome | Recovery | Related IDs |
|---|---|---|---|---|
| Empty/oversized input | Reject before model call | Explain valid size | Edit and resubmit | FR-001, NFR-001 |
| Missing required detail | Ask one focused question or mark unknown | State missing detail | User supplies it | AI-010 |
| Ollama unavailable/model absent | Do not switch silently to cloud | `Blocked: local model unavailable` | Start/install/reconfigure; retry | AI-001, API-001 |
| OpenAI authentication/model error | Stop bounded retry; preserve local result | `Blocked` or partial with provider class | Correct configuration or use local-only | AI-004, API-002 |
| API timeout | Apply timeout/retry policy | Partial/blocked and retry option | Manual retry or fallback if allowed | NFR-002 |
| Rate or daily cost limit | Prevent excess call | Limit reached; partial results shown | Wait, raise limit, or choose local | AI-019, NFR-001 |
| No relevant search result | Do not answer as known | `I could not find sufficient evidence` | Refine query or provide source | FR-003, AI-010 |
| Conflicting reliable sources | Preserve conflict | Explain disagreement and dates | Seek primary/newer source or owner judgment | AI-012 |
| Malformed specialist response | Validate; one allowed repair; otherwise fail | Partial/blocked | Retry once or local fallback | AI-007, NFR-002 |
| Prompt injection in webpage | Ignore instructions; quarantine/omit | Research may be partial | Use alternate source | SEC-003 |
| Private/loopback URL | Block fetch | URL is not permitted | Supply public approved source | SEC-006 |
| Network loss during research | Stop/retry within policy | Partial evidence and unavailable status | Retry when network returns | FR-006, NFR-002 |
| Duplicate request | Use correlation/idempotency where applicable; avoid duplicate costly work | Existing/in-progress result if safe | User may force a new run | DATA-004, NFR-001 |
| User cancellation | Stop new work and ignore late downstream results | Canceled; completed portions shown | Start a new request | FR-005 |
| Storage corruption | Isolate corrupt data; use base behavior | Continuity degraded | Restore backup or rebuild profile | DATA-002, OPS-004 |
| Insufficient permission | Do not perform operation | Explain required permission/data scope | User approves exact proposal or declines | SEC-002, SEC-005 |
| Sensitive data in logs | Redaction must prevent write; otherwise omit payload | Diagnostic metadata only | Review redaction policy | SEC-007 |
| Resource exhaustion/local queue full | Apply backpressure and reject excess | Busy/limit message | Wait, cancel, or lower concurrency | AI-019, NFR-001 |
| Application restart mid-task | Mark prior task interrupted; do not replay external calls automatically | Interrupted task visible | Owner explicitly retries | DATA-004, OPS-004 |
| Stale cached evidence | Do not present as current when freshness is required | Retrieval date and warning | Refresh evidence | FR-003, AI-009 |
| Specialist disagreement | Orchestrator exposes conflict; no unsupported majority | Qualified/unknown result | Verification or owner choice | AI-012 |

# 18. Observability and Operations

### OPS-001 Structured logging, metrics, and task tracing

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must emit structured, correlated records and metrics for task status, route, model/specialist/tool calls, latency, token/usage when available, estimated cost, retries, timeouts, cancellations, validation failures, and limit events.
- **Rationale:** Required for debugging, trust, evaluation, and cost control.
- **Preconditions:** Application is running.
- **Inputs:** Lifecycle events.
- **Expected behavior:** Use stable task/session correlation; support local review; apply SEC-007.
- **Outputs:** Logs, metrics, and trace summary.
- **Failure behavior:** Telemetry failure is visible and does not expose raw sensitive data; required approval audit failure blocks high-impact action.
- **Dependencies:** DATA-004, SEC-007.
- **Acceptance criteria:** Given one task exercising routing, web, specialist, retry, and cancellation, when records are reviewed, then every phase is correlated, durations/usage are present where available, and seeded secrets are absent.
- **Source:** Transparent execution logs and monitoring requirements.

### OPS-002 Configuration and health status

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must validate configuration at startup and expose health/degraded status for the application, Ollama/model, cloud provider configuration, web capability, storage, and effective resource limits without exposing secrets.
- **Rationale:** Failures must be diagnosable before a task relies on a capability.
- **Preconditions:** Application starts or configuration reloads.
- **Inputs:** Configuration and dependency probes.
- **Expected behavior:** Mark optional dependencies degraded; fail startup or disable capability for unsafe/missing mandatory configuration.
- **Outputs:** Human-readable and machine-usable status.
- **Failure behavior:** Probe failure is bounded and does not hang startup.
- **Dependencies:** API-001 through API-004, NFR-001.
- **Acceptance criteria:** Given healthy and misconfigured dependency scenarios, when startup checks run, then each capability has correct health/degraded/disabled status and no secret is displayed.
- **Source:** Failure transparency and guardrail requirements.

### OPS-003 Cost and usage monitoring

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** The system must track cloud call counts, token usage when reported, estimated cost by request and day, and remaining configured budget.
- **Rationale:** Cloud escalation must be efficient and bounded.
- **Preconditions:** Cloud provider is enabled.
- **Inputs:** Provider usage and pricing configuration.
- **Expected behavior:** Reserve estimated budget before call and reconcile after usage response.
- **Outputs:** Per-task/day totals and limit events.
- **Failure behavior:** Unknown pricing/usage must be disclosed; conservative budget policy applies.
- **Dependencies:** AI-019, DATA-004.
- **Acceptance criteria:** Given mocked usage and price data, when calls run, then totals reconcile within the approved calculation tolerance and a call exceeding remaining budget is prevented.
- **Source:** Cost-limit and efficient-call requirements.

### OPS-004 Recovery, backup, deployment, and rollback

- **Priority:** Must
- **Version:** V1
- **Status:** Assumed/TBD targets
- **Requirement:** The system must use versioned configuration and data migrations, mark interrupted tasks without replaying external calls, and provide documented local backup/restore and rollback procedures before production use.
- **Rationale:** Persistent continuity and provider changes require recoverability.
- **Preconditions:** Persistent data or a release upgrade exists.
- **Inputs:** Backup, versioned data/config, and release artifact.
- **Expected behavior:** Validate backups, migrate transactionally where feasible, and restore a previous compatible version.
- **Outputs:** Recovery/rollback result and audit event.
- **Failure behavior:** Failed migration stops activation and preserves the prior usable state.
- **Dependencies:** DATA-001, DATA-002, OQ-08.
- **Acceptance criteria:** Given a test backup and interrupted task, when restore/rollback is performed, then profile/history integrity matches the recovery objective and the interrupted external task is not automatically replayed.
- **Source:** Memory continuity and operational best-practice recommendation; exact objectives not supplied.

# 19. Testing and Quality Requirements

V1 must include:

- **Unit tests:** routing rules, policy decisions, context ranking/truncation, schemas, status classification, limits, redaction, cost calculation, and URL validation.
- **Integration tests:** Ollama adapter, OpenAI adapter using mocks/sandbox credentials, web search/reader fixtures, storage, cancellation, logging, and configuration validation.
- **End-to-end tests:** UC-01 through UC-08, including success and unsuccessful paths.
- **Security tests:** prompt injection, secret leakage, SSRF/redirect bypass, oversized input/content, invalid schemas, privilege denial, and dependency/configuration abuse.
- **Performance tests:** hardware benchmark under NFR-003, queue/backpressure, context budget, and concurrent limit enforcement.
- **Failure-injection tests:** timeout, rate limit, unavailable dependency, malformed response, network loss, storage failure, partial completion, restart, and cancellation.
- **AI evaluation tests:** correct routing; grounded claims; citation relevance; freshness; uncertainty/abstention; concise structured results; tool/provider selection; malformed tool result; prompt injection; context/privacy selection; and cost-limit enforcement.
- **Regression tests:** run for every prompt, model, provider adapter, routing policy, retrieval-ranking, or schema change.
- **User-acceptance tests:** owner executes the eight use cases and approves clarity, control, and usefulness.

Release thresholds are owner decisions. Mandatory deterministic security/policy tests must have a 100% pass rate. Statistical routing, citation, groundedness, and usability targets are TBD in OQ-09; failures must not be hidden by aggregate scores.

# 20. Version 1 Acceptance Criteria

V1 is complete only when all of the following are true:

- [ ] One text interface supports valid input, invalid-input feedback, multi-turn sessions, and cancellation. (FR-001, FR-002, FR-005)
- [ ] The configured Ollama generalist handles the approved ordinary-request set in local-only mode without cloud calls. (BUS-002, AI-001, API-001)
- [ ] Application policy prevents model output from directly authorizing tools or external operations. (AI-002, SEC-005)
- [ ] Research and coding specialist roles are registered, bounded, and return valid concise structures. (BUS-003, AI-003, AI-007, AI-008)
- [ ] The OpenAI adapter uses a verified configurable model ID and handles success, auth, quota, rate, timeout, schema, and model errors. (AI-004, API-002)
- [ ] Current-information requests trigger on-demand research and produce valid evidence/citations or explicit unknown/blocked outcomes. (FR-003, FR-004, DATA-003, API-003)
- [ ] RAG selection obeys relevance, freshness, privacy, deduplication, conflict, and token-budget rules. (AI-006, AI-009)
- [ ] Known/inferred/unknown/blocked behavior and non-fabrication pass the approved evaluation set. (AI-010, AI-011, AI-012, UX-001)
- [ ] Local-only and cloud-permitted modes enforce exact privacy and consent rules. (AI-014, SEC-001, SEC-002)
- [ ] Prompt injection, secret leakage, SSRF, and high-impact-action denial tests all pass. (SEC-003 through SEC-007)
- [ ] All configured call, token, time, retry, concurrency, queue, page/size, and cost ceilings are enforced, including concurrent boundary tests. (AI-019, NFR-001, NFR-002)
- [ ] Session history, no-save mode, confirmed profile, startup continuity, review/correction/deletion, and corrupt-memory degradation work as specified. (DATA-001, DATA-002, DATA-005)
- [ ] Execution/audit records, metrics, health, and cost monitoring are complete and redacted. (DATA-004, OPS-001, OPS-002, OPS-003)
- [ ] Partial failures, cancellation, restart interruption, and recovery procedures do not produce false success or automatic replay. (FR-006, OPS-004)
- [ ] Hardware targets and evaluation thresholds have been approved and passed. (NFR-003, NFR-004)
- [ ] All blocking open questions have an owner decision recorded in the decision log.

# 21. Requirement Traceability Matrix

Acceptance-test identifiers map to Section 20 checklist items and Section 19 suites.

| Requirement ID | Summary | Source/decision | Priority | Version | Use case | Acceptance test | Dependencies | Status |
|---|---|---|---|---|---|---|---|---|
| BUS-001 | Trustworthy assistant core | Accepted V1 core | Must | V1 | UC-01-03 | AT-01 | FR-001, AI-001 | Confirmed |
| BUS-002 | Local-first operation | Owner requirement | Must | V1 | UC-01,04 | AT-02 | AI-001, AI-014 | Confirmed |
| BUS-003 | Extensible specialists | Owner scalability goal | Must | V1 | UC-03 | AT-03 | AI-003, AI-015 | Confirmed |
| FR-001 | Text interface | Final V1 scope | Must | V1 | UC-01 | AT-01 | OQ-02 | Confirmed/TBD choice |
| FR-002 | Multi-turn context | Final V1 scope | Must | V1 | UC-01,06 | AT-01 | AI-006, DATA-001 | Confirmed |
| FR-003 | Freshness detection | Accepted refinement | Must | V1 | UC-02 | AT-06 | API-003 | Confirmed |
| FR-004 | Search/read/citations | Final V1 scope | Must | V1 | UC-02 | AT-06 | DATA-003, SEC-006 | Confirmed |
| FR-005 | Cancellation | Accepted refinement | Must | V1 | UC-07 | AT-01,14 | NFR-001 | Confirmed |
| FR-006 | Failure/partial results | Accepted refinement | Must | V1 | UC-02,03,07,08 | AT-14 | AI-010, NFR-002 | Confirmed |
| DATA-001 | Session history/no-save | Final V1 scope | Must | V1 | UC-01,06 | AT-12 | SEC-001 | Confirmed |
| DATA-002 | Confirmed profile/startup | Final V1 scope | Must | V1 | UC-06 | AT-12 | AI-006 | Confirmed |
| DATA-003 | Evidence objects | Accepted refinement | Must | V1 | UC-02 | AT-06 | FR-004 | Confirmed |
| DATA-004 | Execution/audit records | Final V1 scope | Must | V1 | All | AT-13 | SEC-007 | Confirmed |
| DATA-005 | Data review/control | Accepted privacy rule | Must | V1 | UC-06 | AT-12 | DATA-001/002 | Confirmed |
| AI-001 | Ollama generalist | Owner final addition | Must | V1 | UC-01 | AT-02 | API-001, OQ-03 | Confirmed/TBD model |
| AI-002 | Application orchestration | Accepted refinement | Must | V1 | All | AT-03 | SEC-005 | Confirmed |
| AI-003 | Research/coding roles | Latest V1 refinement | Must | V1 | UC-02,03 | AT-04 | AI-004/007 | Confirmed |
| AI-004 | OpenAI cloud model | Owner final addition | Must | V1 | UC-03,04 | AT-05 | API-002, OQ-04 | Confirmed intent/TBD ID |
| AI-005 | Bounded routing | Owner specialist design | Must | V1 | UC-01-04 | AT-04,15 | BUS-003 | Confirmed |
| AI-006 | Minimum context | Accepted refinement | Must | V1 | UC-02,03,06 | AT-07 | AI-009, SEC-002 | Confirmed |
| AI-007 | Structured result | Accepted refinement | Must | V1 | UC-02,03 | AT-04 | AI-004 | Confirmed |
| AI-008 | Concise output | Owner explicit addition | Must | V1 | UC-02,03 | AT-04 | AI-007 | Confirmed |
| AI-009 | Evidence-grounded RAG | Owner explicit addition | Must | V1 | UC-02 | AT-07 | DATA-003 | Confirmed |
| AI-010 | Four result states | Owner uncertainty rule | Must | V1 | UC-05 | AT-08 | AI-011/012 | Confirmed |
| AI-011 | Non-fabrication | Accepted core contract | Must | V1 | UC-05 | AT-08 | DATA-003/004 | Confirmed |
| AI-012 | Validation/conflicts | Accepted refinement | Must | V1 | UC-02,03,05 | AT-08 | AI-007/010 | Confirmed |
| AI-013 | Delegation depth one | Accepted refinement | Must | V1 | UC-03 | AT-03 | AI-002 | Confirmed |
| AI-014 | Cloud policy modes | Final V1 scope | Must | V1 | UC-04 | AT-09 | SEC-001/002 | Confirmed/TBD default |
| AI-015 | Model/prompt portability | Accepted refinement | Must | V1 | UC-03 | AT-03,05 | API-004 | Confirmed |
| AI-019 | Bounded calls/resources | Owner guardrail | Must | V1 | UC-08 | AT-11 | NFR-001 | Confirmed/TBD values |
| API-001 | Ollama adapter | Technical constraint | Must | V1 | UC-01 | AT-02 | AI-001 | Confirmed |
| API-002 | OpenAI adapter | Technical constraint | Must | V1 | UC-03,04 | AT-05 | AI-004 | Confirmed intent |
| API-003 | Web adapter | V1 capability | Must | V1 | UC-02 | AT-06,10 | FR-003/004 | Confirmed/TBD provider |
| API-004 | Integration declarations | Portability contract | Must | V1 | All | AT-13 | AI-015 | Confirmed |
| SEC-001 | Privacy boundary | Accepted core contract | Must | V1 | UC-04,06 | AT-09 | AI-014 | Confirmed |
| SEC-002 | Exact consent | Accepted core contract | Must | V1 | UC-04 | AT-09 | DATA-004 | Confirmed/TBD UX |
| SEC-003 | Prompt injection defense | Accepted core contract | Must | V1 | UC-02 | AT-10 | AI-002 | Confirmed |
| SEC-004 | Secrets management | Accepted guardrail | Must | V1 | UC-03,04 | AT-10 | API-002/003 | Confirmed |
| SEC-005 | Least privilege/no high impact | Accepted contract | Must | V1 | UC-03,04 | AT-03,10 | AI-002 | Confirmed |
| SEC-006 | URL/retrieval safety | Accepted web safety | Must | V1 | UC-02 | AT-10 | API-003 | Confirmed |
| SEC-007 | Log redaction | Accepted privacy rule | Must | V1 | All | AT-10,13 | DATA-004 | Confirmed |
| NFR-001 | Configurable hard limits | Owner guardrail | Must | V1 | UC-08 | AT-11 | AI-019, OQ-05 | Confirmed/TBD values |
| NFR-002 | Timeout/retry/circuit | Accepted guardrail | Must | V1 | UC-02,03,08 | AT-11 | APIs | Confirmed/TBD values |
| NFR-003 | Hardware/performance fit | Required measurability | Must | V1 | UC-01 | AT-15 | OQ-03 | TBD |
| NFR-004 | Evaluation suite | Final V1 scope | Must | V1 | All | AT-15 | OQ-09 | Confirmed/TBD thresholds |
| NFR-006 | Maintainability/portability | Owner extensibility goal | Must | V1 | UC-03 | AT-03 | BUS-003 | Confirmed |
| OPS-001 | Logs/metrics/tracing | Final V1 scope | Must | V1 | All | AT-13 | DATA-004 | Confirmed |
| OPS-002 | Config/health | Guardrail refinement | Must | V1 | UC-01-04,08 | AT-13 | APIs, NFR-001 | Confirmed |
| OPS-003 | Cost monitoring | Owner efficiency goal | Must | V1 | UC-03,04,08 | AT-13 | AI-019 | Confirmed |
| OPS-004 | Recovery/rollback | Operational recommendation | Must | V1 | UC-06,07 | AT-14 | OQ-08 | Assumed/TBD targets |
| UX-001 | Transparent response | Owner core behavior | Must | V1 | All | AT-08 | AI-010/012 | Confirmed |

# 22. Risks

| Risk ID | Risk | Likelihood | Impact | Early warning | Mitigation | Contingency | Owner | Related IDs |
|---|---|---|---|---|---|---|---|---|
| RSK-01 | Local model does not fit hardware or is too slow | Medium | High | OOM, swapping, unacceptable first-token delay | Benchmark before architecture commitment; configurable model | Use smaller/quantized model or revise targets | Project owner/technical lead | AI-001, NFR-003 |
| RSK-02 | Exact OpenAI model name/access differs from notes | Medium | High | Model-not-found or unavailable features | Validate official API model ID and capabilities | Select approved compatible model through configuration | Technical lead | AI-004, API-002 |
| RSK-03 | Prompt-defined specialists underperform | Medium | High | Low routing/grounding scores | Version prompts, schemas, tools, and evaluation set | Change model or narrow role; defer weak capability | Product/AI lead | AI-003, NFR-004 |
| RSK-04 | RAG retrieves relevant-looking but false/stale content | High | High | Citation exists but does not support claim | Primary-source ranking, freshness, claim checks, abstention | Return qualified/unknown; manual verification | AI lead | AI-009, AI-012 |
| RSK-05 | Prompt injection manipulates calls or leaks data | Medium | Critical | Web text requests policy override or secrets | Treat content as data; deterministic authorization; red-team tests | Disable affected source/tool; incident review | Security owner | SEC-003, SEC-005 |
| RSK-06 | Cloud disclosure violates owner expectations | Medium | Critical | Sensitive content appears in request trace | Default-safe modes, minimization, exact consent | Disable cloud, rotate keys, delete provider data where possible | Privacy owner | SEC-001, SEC-002 |
| RSK-07 | Cost or retry runaway | Medium | High | Rapid call count/latency growth | Hard budgets, depth one, circuit breakers, backpressure | Disable cloud/provider and return partial | Operator | AI-019, NFR-001/002 |
| RSK-08 | Web provider blocks, changes, or becomes costly | Medium | Medium | Rate limits, terms/pricing changes | Adapter boundary and provider configuration | Switch provider or operate without current verification | Technical lead | API-003, API-004 |
| RSK-09 | Memory stores wrong or sensitive inference | Medium | High | Irrelevant personalization or privacy complaint | Confirmed-profile separation and review/delete controls | Disable persistence; remove/restore data | Product/privacy owner | DATA-002, DATA-005 |
| RSK-10 | Logs become a secondary sensitive-data store | Medium | High | Raw prompts or tokens found in logs | Redaction tests, minimal metadata, retention policy | Purge affected logs; rotate secrets | Security/operator | SEC-004, SEC-007 |
| RSK-11 | V1 scope expands into voice/vision/control | High | High | Milestones include deferred modules | Enforce scope/non-goals and change control | Move additions to roadmap | Project owner | Section 6 |
| RSK-12 | Single-developer schedule slips | High | Medium | Evaluation/security work deferred | Prioritize strict core and automate tests | Reduce optional items, not safety requirements | Project owner | NFR-004 |
| RSK-13 | Provider/model change breaks regressions | High | Medium | Output schema or quality drift | Versioned adapters/prompts and permanent evaluations | Pin prior compatible configuration or roll back | Technical lead | AI-015, OPS-004 |
| RSK-14 | Owner mistakes financial-analysis output for professional advice | Medium | High | Requests for definitive trades | Role naming, uncertainty, evidence, non-execution | Decline autonomous trade/action; require external professional review | Product owner | SEC-005, AI-010 |

# 23. Decision Log

| Decision ID | Decision | Status | Rationale | Alternatives considered | Consequences | Source |
|---|---|---|---|---|---|---|
| DEC-001 | V1 is a text-first local-first personal assistant. | Confirmed | Keep V1 achievable and private. | Voice/vision first | Voice/vision deferred. | Accepted V1 scope |
| DEC-002 | Use Ollama for the primary local generalist. | Confirmed | Owner choice; local operation. | Other runtimes | Adapter must support Ollama; exact model TBD. | Final owner addition |
| DEC-003 | Separate application orchestrator from model behavior. | Confirmed | Deterministic policy and execution control. | Model directly calls/authorizes tools | More application logic, safer boundary. | Accepted refinement |
| DEC-004 | V1 includes research and coding prompt-defined roles. | Confirmed | Proves extensibility with testable roles. | One specialist; many specialists | Two roles supersede earlier one-specialist recommendation. | Latest final V1 list |
| DEC-005 | Use one configurable OpenAI cloud provider/model for V1 specialists. | Confirmed intent | Owner choice with portability. | Local-only or multiple providers | Access/model ID must be validated; avoid hard-coding. | Final owner addition |
| DEC-006 | Use on-demand search and selected-page reading, not general crawling. | Confirmed | Current facts with manageable risk/scope. | Full crawler or browser agent | Focused crawler deferred. | Accepted refinement |
| DEC-007 | Use RAG as evidence retrieval, not a truth guarantee. | Confirmed | Reduce unsupported output while preserving abstention. | Prompt-only answers | Requires provenance and retrieval evaluation. | Owner RAG requirement plus refinement |
| DEC-008 | Use `known`, `inferred`, `unknown`, and `blocked` outcomes. | Confirmed | Owner prioritizes "I don't know." | Unqualified prose answer | Responses and tests need explicit status rubric. | Owner requirement |
| DEC-009 | Context is minimum sufficient, not maximum possible. | Confirmed | Efficiency, cost, relevance, privacy. | Send entire history/retrieval set | Requires ranking, budgets, and context manifest. | Accepted refinement |
| DEC-010 | Delegation depth is one in V1. | Confirmed | Prevent loops and cost explosion. | Recursive delegation | Multi-level agents deferred. | Accepted refinement |
| DEC-011 | Basic history/profile continuity is V1; semantic memory is future. | Confirmed | Useful consistency without memory-system complexity. | No memory; full vector memory | Requires user control and storage policy. | Final V1 scope |
| DEC-012 | Guardrails include more than an API rate limiter. | Confirmed | Prevent crashes, runaway cost, and stalls. | Rate limit alone | Multiple configurable ceilings required. | Final owner addition/refinement |
| DEC-013 | High-impact and external write actions are disabled in V1. | Confirmed | Scope and safety. | Confirmation-enabled execution | Future design may add exact confirmation. | Accepted non-goals |
| DEC-014 | Permanent evaluation suite is part of V1. | Confirmed | Enables model/prompt regression control. | Ad hoc testing | Requires owner thresholds and fixtures. | Final V1 scope |

# 24. Conflicts and Inconsistencies

No unresolved logical conflict remains after applying source chronology. One apparent scope conflict was reconciled:

| Statements | Impacted requirements | Resolution | Consequences | Owner decision |
|---|---|---|---|---|
| Earlier guidance proposed one real specialist (research or coding); the latest V1 refinement specified two prompt-defined roles (research and coding). | BUS-003, AI-003 | Treat the later, more specific statement as superseding the earlier recommendation. V1 requires both roles. | More evaluation and provider calls than the one-role option, but still bounded and no separate trained models. | Resolved by current owner statement that these requirements are good for V1; reopen only if scope must be reduced. |

Potential terminology inconsistency around "GPT-5.6 Luna" is not resolved by the supplied source. The intent to use a configurable OpenAI model is confirmed, but the exact API identifier and availability remain OQ-04 rather than a contradiction.

# 25. Open Questions

## 25.1 Blocking before architecture

### OQ-01 Single-user boundary

- **Question:** Is V1 strictly single-user on one trusted machine?
- **Why it matters:** Multi-user support changes authentication, authorization, isolation, storage, audit, and UI.
- **Affected IDs:** BUS-001, DATA-001/002, SEC-001/005.
- **Options:** Single-user local; multiple local profiles; networked multi-user.
- **Recommendation:** Single-user local for V1.
- **Decision deadline:** Before architecture.

### OQ-02 Primary text interface

- **Question:** Is the required V1 interface terminal or simple local web UI?
- **Why it matters:** Changes session handling, streaming, cancellation, packaging, and testing.
- **Affected IDs:** FR-001, NFR-005, UX-001.
- **Options:** Terminal; local web UI.
- **Recommendation:** Terminal for the first executable milestone; add web UI only if it materially improves evaluation/demo needs.
- **Decision deadline:** Before architecture.

### OQ-03 Hardware and local-model target

- **Question:** What are the target Windows 11/WSL2 runtime details, CPU, GPU/VRAM, RAM, storage, chosen Ollama model, and acceptable latency/resource ceilings?
- **Why it matters:** Determines feasibility of the local generalist.
- **Affected IDs:** AI-001, API-001, NFR-003.
- **Options:** Benchmark several quantized models under WSL2; choose smallest passing model; revise target hardware.
- **Recommendation:** Inventory hardware and run a short benchmark before committing architecture capacity assumptions.
- **Decision deadline:** Before architecture.

### OQ-04 Exact OpenAI model and API capability

- **Question:** What exact currently available OpenAI API model ID will V1 use, and does the account support the required structured output, token controls, usage reporting, and pricing?
- **Why it matters:** The supplied name "GPT-5.6 Luna" must not be hard-coded without validation.
- **Affected IDs:** AI-004, API-002, AI-015.
- **Options:** Validate the named model; choose a compatible available model; use local specialist fallback.
- **Recommendation:** Confirm through official API documentation/account access immediately before architecture and record the exact ID as configuration.
- **Decision deadline:** Before architecture.

### OQ-05 Resource and cost budgets

- **Question:** What hard numeric defaults apply to calls, tokens, timeouts, retries, concurrency, queue length, pages/bytes, per-request cost, and daily cost?
- **Why it matters:** "Efficient," "effective," and "prevent crashes" are otherwise not measurable.
- **Affected IDs:** AI-019, NFR-001/002, OPS-003.
- **Options:** Adopt proposed conservative defaults after benchmarks; local-only no-cost mode; different profiles for normal/deep research.
- **Recommendation:** Define one conservative V1 profile after hardware/provider tests; all values remain configurable.
- **Decision deadline:** Before architecture.

### OQ-06 Cloud privacy policy

- **Question:** Which data classifications may be sent to cloud, what is the default mode, and when is per-call confirmation required?
- **Why it matters:** Context construction and UI depend on enforceable rules.
- **Affected IDs:** AI-014, SEC-001/002, AI-006/009.
- **Options:** Local-only default; local-first/cloud fallback; ask before every cloud call; best-available mode.
- **Recommendation:** Local-first with confirmation for any non-public or owner-specific content.
- **Decision deadline:** Before architecture.

### OQ-07 Web provider and retrieval policy

- **Question:** Which search/page providers, allowed content types/domains, robots/terms policy, and citation format apply?
- **Why it matters:** API behavior, legal compliance, extraction, and cost depend on provider terms.
- **Affected IDs:** FR-003/004, API-003, SEC-006.
- **Options:** Hosted search tool; third-party search API plus HTTP reader; approved-domain-only initial research.
- **Recommendation:** Start with a hosted/search API and selected-page HTTP reader behind one provider-neutral contract.
- **Decision deadline:** Before architecture.

## 25.2 Blocking before implementation

### OQ-08 Storage, retention, and recovery

- **Question:** What local storage engine, encryption-at-rest expectation, session/profile/log retention, deletion semantics, backup frequency, and recovery objectives apply?
- **Why it matters:** Data controls and migration/recovery cannot be fully implemented otherwise.
- **Affected IDs:** DATA-001/002/004/005, SEC-007, OPS-004.
- **Options:** SQLite with OS-level protection; encrypted local database; short/no history retention.
- **Recommendation:** Use simple local structured storage, short default retention, explicit profile persistence, and encrypted backups; technology choice belongs to architecture.
- **Decision deadline:** Before data implementation.

### OQ-09 Evaluation rubric and release thresholds

- **Question:** What are the final approximately 30 requests, expected results, and passing thresholds for routing, citation relevance, groundedness, uncertainty, concision, and latency?
- **Why it matters:** V1 completion cannot be objectively declared without thresholds.
- **Affected IDs:** NFR-003/004, AI-005/008/010/012.
- **Options:** Binary assertions plus scored rubric; owner-only acceptance; automated judge plus manual review.
- **Recommendation:** Use deterministic assertions for safety and schema, plus a human-reviewed rubric for answer quality; require 100% safety-policy pass.
- **Decision deadline:** Before implementation is considered complete.

## 25.3 Needed before production

### OQ-10 Production threat, legal, and incident scope

- **Question:** What data categories, regulatory obligations, dependency-update policy, incident response, log retention, and acceptable-use restrictions apply to actual use?
- **Why it matters:** Personal prototype controls may be insufficient for sensitive or shared production use.
- **Affected IDs:** SEC-001 through SEC-007, OPS-001/004.
- **Options:** Personal local prototype only; private beta; broader deployment with formal security review.
- **Recommendation:** Keep V1 a personal local prototype until a threat model and incident procedure are approved.
- **Decision deadline:** Before production or sharing with other users.

## 25.4 Non-blocking future decisions

Lower-priority future questions are listed in Appendix B so the main list remains limited to ten.

# 26. Recommendations

These are not approved requirements unless separately accepted.

- **Scope:** Keep both V1 specialists narrow. If schedule pressure occurs, reduce optional UI/verification features before weakening uncertainty, privacy, security, or evaluation controls.
- **Feasibility:** Benchmark local models and validate the exact cloud model/provider capabilities before selecting frameworks or storage.
- **Security:** Write a small threat model covering prompt injection, SSRF, secrets, cloud disclosure, logs, and malicious model output before implementing web retrieval.
- **Reliability:** Implement typed result/status contracts and deterministic policy/limit checks before refining prompts.
- **User experience:** Show compact indicators for local/cloud route, research/citations, uncertainty, and active task/cancellation without exposing internal chain-of-thought.
- **Cost control:** Begin with conservative configuration and one cloud call path; expand only after usage data shows measurable value.
- **Development sequencing:** Define evaluation fixtures and contracts first, then local conversation, bounded orchestration, web evidence/RAG, cloud specialists, memory/operations, and release hardening. This is sequencing guidance, not a milestone plan.

# 27. Future Roadmap

## Version 1.x

### FR-101 Focused allowlisted crawler

- **Priority:** May
- **Version:** Future (1.x)
- **Status:** Future idea
- **Requirement:** The system may crawl approved seed domains with robots/terms enforcement, bounded frontier/depth/pages, deduplication, extraction, indexing, and refresh policy.
- **Rationale:** Build reusable knowledge sets after on-demand research is stable.
- **Preconditions:** Legal/policy review and secure URL fetcher.
- **Inputs:** Approved seeds and crawl budget.
- **Expected behavior:** Crawl only permitted scope and preserve provenance.
- **Outputs:** Versioned local document corpus.
- **Failure behavior:** Stop at policy/limit violations and preserve partial index safely.
- **Dependencies:** API-003, SEC-003/006.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Owner future crawling interest.

### DATA-101 Long-term semantic and episodic memory

- **Priority:** May
- **Version:** Future (1.x)
- **Status:** Future idea
- **Requirement:** The system may add user-controlled semantic/episodic memory with relevance retrieval, provenance, sensitivity, expiry, review, correction, export, and deletion.
- **Rationale:** Improve continuity beyond basic V1 history/profile.
- **Preconditions:** V1 data controls and retrieval evaluations are stable.
- **Inputs:** Owner-approved memories and session summaries.
- **Expected behavior:** Retrieve only relevant memory and never elevate inference to confirmed fact.
- **Outputs:** Reviewable memory context.
- **Failure behavior:** Low-relevance or sensitive memory is excluded.
- **Dependencies:** DATA-002/005, AI-006.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Long-term memory vision.

### AI-101 Parallel multi-specialist orchestration

- **Priority:** May
- **Version:** Future (1.x/2)
- **Status:** Future idea
- **Requirement:** The system may support bounded parallel or sequential specialist task graphs with explicit dependencies, conflict handling, budgets, and no uncontrolled recursion.
- **Rationale:** Complex requests may benefit from multiple disciplines.
- **Preconditions:** V1 routing and single-depth evaluations are stable.
- **Inputs:** Validated task graph.
- **Expected behavior:** Run independent tasks in parallel and dependent tasks in order.
- **Outputs:** Synthesized, traceable result.
- **Failure behavior:** Return verified partial graph results and stop at limits.
- **Dependencies:** AI-002/012/019.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Owner long-term specialist vision.

## Version 2

### FR-102 Voice input and output

- **Priority:** May
- **Version:** Future (V2)
- **Status:** Future idea
- **Requirement:** The system may add push-to-talk speech recognition and synthesized speech with visible microphone state, interruption, quality/confidence metadata, and user confirmation of uncertain consequential transcriptions.
- **Rationale:** Natural interaction after text stability.
- **Preconditions:** Privacy indicators, audio permissions, and latency targets defined.
- **Inputs:** Explicitly captured audio and assistant text.
- **Expected behavior:** Transcribe/synthesize through replaceable services.
- **Outputs:** Timestamped transcript/quality metadata and audio.
- **Failure behavior:** Unclear audio is marked uncertain; no consequential action uses it without confirmation.
- **Dependencies:** AI-002, SEC-002.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Multimodal expansion contract.

### FR-103 Image, screenshot, and explicit camera-frame analysis

- **Priority:** May
- **Version:** Future (V2)
- **Status:** Future idea
- **Requirement:** The system may analyze user-uploaded images, screenshots, and explicitly captured single webcam frames through a replaceable vision service with OCR/object uncertainty and capture indicators.
- **Rationale:** Enable screen/image understanding without continuous surveillance.
- **Preconditions:** Modality privacy and retention policy.
- **Inputs:** Explicitly provided image/frame.
- **Expected behavior:** Return structured observations and uncertainty for orchestrator use.
- **Outputs:** Text/tokens, detected elements, quality warnings, source/timestamp.
- **Failure behavior:** Unclear observations are not used for consequential action without confirmation.
- **Dependencies:** AI-002, SEC-001/002.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Owner future vision requirement.

### AI-102 Finance specialist

- **Priority:** May
- **Version:** Future (V2)
- **Status:** Future idea
- **Requirement:** The system may add a financial-analysis specialist using fresh market/filing data, evidence, uncertainty, and non-execution safeguards.
- **Rationale:** Owner identified stock evaluation as a specialization.
- **Preconditions:** Licensed/authoritative data, freshness targets, disclaimers, and evaluation rubric.
- **Inputs:** Security/company request and current evidence.
- **Expected behavior:** Analyze without claiming licensure or executing trades.
- **Outputs:** Evidence-backed analysis and risks.
- **Failure behavior:** Missing fresh data yields unknown/blocked.
- **Dependencies:** FR-003/004, AI-009/010, SEC-005.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Owner future specialization example.

## Long-term vision

### FR-104 Controlled computer assistance

- **Priority:** May
- **Version:** Future
- **Status:** Future idea
- **Requirement:** The system may perform narrowly sandboxed computer assistance with exact preview/confirmation for external writes, communications, destructive actions, commands, purchases, or financial actions.
- **Rationale:** Part of the Jarvis-inspired vision.
- **Preconditions:** Formal threat model, capability sandbox, identity/authorization, and rollback design.
- **Inputs:** Explicit owner task and approval.
- **Expected behavior:** Propose exact action, validate, confirm, execute least privilege, and audit result.
- **Outputs:** Action result and record.
- **Failure behavior:** Ambiguity or missing approval stops execution.
- **Dependencies:** SEC-002/005, OPS-001.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Deferred computer-control vision.

### AI-103 Fine-tuned or custom specialist models

- **Priority:** May
- **Version:** Future
- **Status:** Future idea
- **Requirement:** The system may adopt fine-tuned or custom specialist models only after a curated dataset and evaluations demonstrate material improvement over prompting, tools, RAG, and model selection.
- **Rationale:** Avoid premature training cost and maintenance.
- **Preconditions:** Proven gap, dataset governance, baseline, and budget.
- **Inputs:** Approved training/evaluation data.
- **Expected behavior:** Preserve the same specialist and policy contracts.
- **Outputs:** Evaluated model version.
- **Failure behavior:** No deployment without passing regression, privacy, and safety gates.
- **Dependencies:** AI-015, NFR-004.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Deferred training recommendation.

### OPS-101 Autonomous background tasks

- **Priority:** May
- **Version:** Future
- **Status:** Future idea
- **Requirement:** The system may run bounded background tasks only with explicit scheduling, scopes, budgets, cancellation, notification, and audit policies.
- **Rationale:** Long-term continuity/monitoring may require operation beyond an interactive session.
- **Preconditions:** Reliable scheduler, authorization, recovery, and incident handling.
- **Inputs:** Owner-approved task definition.
- **Expected behavior:** Run only within schedule and limits; notify results/failures.
- **Outputs:** Audited task result.
- **Failure behavior:** Disable repeated failures and never broaden scope automatically.
- **Dependencies:** AI-019, OPS-001/004.
- **Acceptance criteria:** TBD before scheduling.
- **Source:** Explicitly deferred autonomous operation.

# 28. Final Readiness Assessment

| Dimension | Assessment | Basis |
|---|---|---|
| Completeness | Partially ready | Core behavior, boundaries, failures, and tests are defined; hardware, budgets, providers, storage, and thresholds remain open. |
| Internal consistency | Ready | One historical specialist-count conflict is reconciled; terminology is normalized. |
| Testability | Partially ready | Mandatory requirements have acceptance criteria; numeric benchmarks and quality thresholds require owner decisions. |
| Technical feasibility | Needs validation | The approach is plausible, but local hardware/model fit and exact cloud model capability are unverified. |
| Security definition | Partially ready | Core trust boundaries and tests are defined; production threat model, retention, and incident process remain open. |
| Version 1 scope clarity | Ready | Required, optional, future, and prohibited capabilities are separated. |

## 28.1 Strengths

- Strong epistemic-honesty and non-fabrication contract.
- Clear separation between deterministic orchestration and probabilistic model behavior.
- Narrow V1 with extension contracts for specialists and providers.
- Evidence, provenance, freshness, privacy, and auditability are treated as foundational rather than later additions.
- Failure, cancellation, cost, and resource-exhaustion behavior is explicit.

## 28.2 Most important gaps

- Target hardware and local-model benchmark.
- Exact OpenAI API model identifier and feature availability.
- Numeric resource/cost budgets and evaluation thresholds.
- Primary interface and storage/retention decisions.
- Web provider and cloud sensitivity policy.

## 28.3 Decisions required before architecture

OQ-01 through OQ-07 must be resolved or converted into explicit architecture assumptions approved by the owner. In particular, hardware/model fit and cloud model availability must be validated, not guessed.

## 28.4 Decisions that may safely wait

Full export format details, optional streaming, high-impact second-pass verification, precise production incident procedures for a personal prototype, and all future-roadmap modules may wait, provided they do not weaken V1 trust boundaries.

## 28.5 Recommendation

The project is **ready to enter a short decision/validation gate, but not yet ready for detailed architecture or milestone commitment**. After OQ-01 through OQ-07 are answered and the local/cloud feasibility checks pass, it is ready for architecture and milestone planning. OQ-08 and OQ-09 must be resolved before their corresponding implementation and release gates; OQ-10 must be resolved before production or multi-user use.

# Appendix A. Requirement Status Summary

## V1 optional requirements

| ID | Requirement | Status |
|---|---|---|
| AI-016 | Optional high-impact verification pass | Proposed |
| DATA-006 | Portable trace export | Proposed |
| NFR-005 | Streaming responses | Proposed |
| UX-002 | Simple web UI when terminal is primary | Proposed |

### UX-001 Transparent, concise user communication

- **Priority:** Must
- **Version:** V1
- **Status:** Confirmed
- **Requirement:** User-facing responses must distinguish material fact, inference, assumption, suggestion, unknown, and blocked status; disclose web/cloud/specialist use when relevant; include citations for external factual claims; and avoid exposing hidden reasoning.
- **Rationale:** Trust requires clarity without verbose internal traces.
- **Preconditions:** A response is composed.
- **Inputs:** Validated result and execution summary.
- **Expected behavior:** Lead with outcome/status, separate suggestions, show relevant provenance and failures, and remain concise.
- **Outputs:** Final user response.
- **Failure behavior:** If classification or provenance is unavailable, return unknown/blocked rather than ambiguous certainty.
- **Dependencies:** AI-010/011/012, DATA-003/004.
- **Acceptance criteria:** Given known, inferred, unknown, blocked, delegated, and partially failed scenarios, when displayed, then an owner evaluator can correctly identify the status, sources, and next action without reading internal logs.
- **Source:** Owner's uncertainty and concise-output requirements.

### UX-002 Optional simple web interface

- **Priority:** Should
- **Version:** V1
- **Status:** Proposed
- **Requirement:** If terminal is selected as the mandatory interface, the system should permit a later simple local web interface using the same session, policy, and response contracts.
- **Rationale:** Useful for demonstration without changing core behavior.
- **Preconditions:** Core interface contract is stable.
- **Inputs:** Same as FR-001.
- **Expected behavior:** Preserve functional and security parity.
- **Outputs:** Browser-rendered local UI.
- **Failure behavior:** UI failure does not change core task state or bypass policy.
- **Dependencies:** FR-001, NFR-006.
- **Acceptance criteria:** Optional; if implemented, shared end-to-end tests pass through both interfaces.
- **Source:** Source allowed terminal or simple web UI; second interface not mandatory.

# Appendix B. Lower-Priority Future Questions

- Which citation style should the UI use beyond clickable links?
- Which languages and accessibility standards should future interfaces support?
- When should vector retrieval replace or supplement structured/full-text queries?
- What source-refresh cadence should a focused crawler use by domain type?
- Which voice/vision providers and on-device alternatives meet privacy and latency needs?
- When, if ever, may a specialist call a tool directly under orchestrator-issued capability tokens?
- What evidence threshold should trigger a finance or other high-impact disclaimer/abstention?

# Coverage Report

- **Mandatory Version 1 requirements:** 51
- **Optional Version 1 requirements:** 4
- **Future requirements:** 9
- **Assumptions:** 9
- **Unresolved conflicts:** 0 (1 historical conflict reconciled)
- **Blocking questions:** 9 (7 before architecture; 2 before implementation)
- **Non-blocking/production-or-future questions:** 8 (1 before production; 7 future)

# Final Quality Check

- Confirmed source requirements preserved: **Yes**, subject to owner approval of this baseline.
- Major requirements silently invented: **No**; operational/security additions not explicit in the source are marked assumed, proposed, or recommended.
- Duplicate requirements consolidated: **Yes**.
- Contradictions identified: **Yes**, with the specialist-count conflict reconciled by chronology.
- V1 and future scope separated: **Yes**.
- Mandatory V1 requirements have acceptance criteria: **Yes**.
- Important failure behaviors specified: **Yes**.
- Requirement IDs unique: **Yes; mechanically validated**.
- Terminology consistent: **Yes**.
- Recommendations and assumptions labeled: **Yes**.
- Self-contained for another engineer or AI: **Yes**.
