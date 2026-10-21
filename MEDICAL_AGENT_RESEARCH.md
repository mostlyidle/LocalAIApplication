# Medical lab-results feature: research and recommendation

**Research date:** 2026-10-20
**Question:** Could this local AI application add a medical agent that reads lab results, explains them, and flags values that may need action?

## Recommendation

There is a promising, locally runnable medical SLM for the document-understanding part: **MedGemma 1.5 4B**. Its model card explicitly includes extracting structured values and units from unstructured laboratory reports, and Ollama lists a quantized local build. That makes it a reasonable model to evaluate for *reading* lab reports. It is not evidence that the model is clinically safe to diagnose, triage, or recommend treatment.

Start with a narrowly scoped **Lab Report Explainer**:

1. Extract each test name, result, unit, lab-provided reference interval, and any flag printed on the report. Keep the page and original text/image available for checking.
2. Compare a numeric result with the reference interval printed on that same report using deterministic code. Show the calculation and preserve the lab’s own flag. Do not infer an “extremely bad” or critical result from a generic range.
3. Use a model only to explain what the test measures in plain language and to help prepare questions for a clinician. Keep explanations tied to the report and clearly marked as educational.
4. If the report itself says “critical,” “panic,” or instructs the patient to contact a provider, surface that exact source wording prominently. Do not invent an urgent alert when the report does not contain one.
5. Abstain and ask the user to check the document when the result, unit, range, or flag is missing or OCR is uncertain. A normal-looking range must not be presented as proof that the person is healthy.

Do **not** launch the requested “what action should I take?” or model-generated critical-value triage workflow as a casual agent feature. It would move from document explanation into patient-specific medical recommendations, while MedGemma explicitly says its outputs are not intended to directly inform clinical diagnosis, patient-management decisions, treatment recommendations, or other direct clinical practice. A critical-value rules engine would need clinician/laboratory ownership, intended-population and unit coverage, independent validation, failure handling, and a jurisdiction-specific regulatory assessment before public use.

## Candidate models

| Model | Local availability and fit | Main caveat | Recommendation |
|---|---|---|---|
| **MedGemma 1.5 4B** | Ollama lists `medgemma1.5:4b` at 3.3 GB, Q4_K_M, with text and image input and a listed 128K context. Google specifically lists lab-report value/unit extraction and EHR text understanding among the 1.5 additions. [Ollama model listing](https://ollama.com/library/medgemma1.5:4b), [Google model card](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card) | It is a developer starting point, not a validated clinical product. Google requires developers to validate/adapt for their use case and says outputs must be independently verified; the card says it is not evaluated/optimized for multi-turn applications. | **Best candidate to trial for extraction**, using one-shot structured output and human-visible source verification. Do not rely on it for diagnosis, urgency, or treatment. |
| **MedGemma 4B (original)** | Also in Ollama, 3.3 GB Q4_K_M, vision-enabled. [Ollama listing](https://ollama.com/library/medgemma) | The 1.5 release is explicitly described as improving medical reasoning and record/document interpretation over the original 4B. | Prefer 1.5 for a new evaluation. |
| **Meditron 7B** | Ollama lists `meditron:7b` at 3.8 GB, text-only, 2K context; its project describes medical-domain pretraining. [Ollama listing](https://ollama.com/library/meditron) | Older Llama 2-based model, short context, and no comparable official lab-report extraction use case found. | Not the first choice for scanned or multi-page lab reports. |
| **MedLlama2 7B** | Ollama lists a local 7B model at about 3.8 GB with 4K context. [Ollama listing](https://ollama.com/library/medllama2) | It is an older Llama 2 fine-tune based on MedQA and is described as a starting point for research, not as a validated lab-report parser. | No clear advantage over MedGemma 1.5 for this app’s workflow. |

MedGemma’s official model card reports PDF-to-JSON lab-data extraction on two internally curated EHR datasets: macro F1 of 91 and 71 respectively for MedGemma 1.5 4B. These are promising task-fit signals, not proof of clinical performance; the large difference between datasets also argues for testing on representative local lab formats. The same card says developers are expected to fine-tune for improved performance on their use case and warns about validation-set representativeness and possible training-data contamination. [Google MedGemma 1.5 model card](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card)

### Licensing and local runtime

Ollama’s MedGemma 1.5 tag is a quantized **Q4_K_M** package and is about **3.3 GB on disk**. Its page lists image input and a 128K context, but that does not mean the model plus a long context will fit in 3.3 GB of RAM: runtime memory and context/KV cache add overhead. Start with a small context that covers one report and benchmark on the target Mac. The app README says its Docker Ollama service uses CPU inference, while native Ollama on Apple Silicon can use Metal, so native Apple Silicon is the more sensible local trial path if available. [Ollama tag details](https://ollama.com/library/medgemma1.5:4b), [project setup](README.md#L7-L10)

MedGemma is **open-weight but not simply Apache-2.0 model weights**: Google’s Health AI Developer Foundations Terms govern the model; the terms define distribution to include making the model/functionality available as a hosted service, require passing through restrictions and the terms when distributing copies, and say to seek health regulatory authorization when applicable. Review those terms before redistributing model files or offering hosted access. [Google HAI-DEF Terms](https://developers.google.com/health-ai-developer-foundations/terms)

## Why deterministic checks matter

Laboratory reference intervals are not universal. MedlinePlus explains that labs can use different methods, reference ranges, and units; it directs people to use the range on their own report. A result outside that interval may or may not indicate a health problem, and a result inside it does not guarantee good health. Therefore:

- Use the report’s range and unit; never silently substitute a generic range from model memory or web search.
- Keep numeric comparison, unit conversions (if ever introduced), and flag rules in code, with explicit testable inputs and provenance. If a unit conversion is not exact and validated, do not compare.
- Let the model interpret/explain extracted fields only after the app verifies the fields, and show the report beside the extracted values so users can spot transcription errors.
- Treat “critical” as a distinct, sourced status, not as a synonym for “outside reference range.” For an MVP, repeat only an explicit critical/urgent label from the lab report; any independent critical-value logic requires clinical governance and validation.

Source: [NIH MedlinePlus, How to Understand Your Lab Results](https://medlineplus.gov/lab-tests/how-to-understand-your-lab-results/).

## Regulatory and safety boundary

This is a product-design research note, not a legal determination. Intended use, claims, target users, and actual outputs matter; putting a disclaimer on a feature does not determine its classification.

- **Canada:** Health Canada says intended or represented use is key to deciding whether software is a medical device. It describes patient decision support for prevention, diagnosis, treatment, or mitigation as potentially SaMD, with classification depending on intended use and risk. Its exclusions are conditional; it distinguishes information that informs management from software used to drive diagnosis/treatment or near-term action. A tool that tells a patient whether a result is critical or what action to take needs a formal SaMD classification review before public release. [Health Canada SaMD guidance](https://www.canada.ca/en/health-canada/services/drugs-health-products/medical-devices/application-information/guidance-documents/software-medical-device-guidance-document.html)
- **United States:** FDA’s January 29, 2026 CDS guidance is focused on HCP-directed non-device CDS; it says existing policies continue to apply to functions intended for patients/caregivers. It gives patient-specific measurement and laboratory examples where diagnostic or time-critical alerts are device functions. That makes automated patient critical-value alerts a particularly poor first scope. This is U.S. guidance and is nonbinding; it does not settle classification elsewhere. [FDA final CDS guidance (PDF)](https://www.fda.gov/media/109618/download)
- **Validation practice:** Health Canada’s joint GMLP principles call for multidisciplinary expertise, representative patient populations, independent test data, clinically relevant performance testing, clear communication of limitations, and monitoring. That is a much larger bar than prompt tuning or a handful of sample PDFs. [Health Canada GMLP principles](https://www.canada.ca/en/health-canada/services/drugs-health-products/medical-devices/good-machine-learning-practice-medical-device-development.html)
- **Model-specific boundary:** Google describes MedGemma as a starting point for downstream healthcare development, but requires meaningful adaptation and validation and says outputs are preliminary and require independent verification and clinical correlation. It explicitly excludes direct clinical diagnosis, patient management, treatment recommendations, and direct clinical practice from intended output use. The safe first use is therefore a research/evaluation of document extraction and neutral educational wording, not patient-specific action advice. [Google MedGemma model card](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card)

## Fit with this app

The app already has generic document analytics and supports PDF and common image uploads. PDF parsing extracts text with PyMuPDF and tables with pdfplumber; image uploads go through local OCR. The generic `document_analytics` profile currently uses Qwen 2.5 7B and is described as extracting grounded facts, tables, dates, amounts, and action items. Its handler sends parsed text to the model. In particular, a scanned PDF does not currently go through a medical vision-model path; adding MedGemma vision for PDF scans would require rendering/routing page images. The task runner can add private account-memory context for the generic document target, so a dedicated medical path should avoid injecting unrelated conversation memory. [Document parser](backend/app/services/document_parser.py#L73-L105), [PDF parser](backend/app/services/document_parser.py#L250-L296), [image OCR parser](backend/app/services/document_parser.py#L474-L486), [document handler](backend/app/services/task_runner.py#L210-L235), [agent catalog](README.md#L78-L92), [document profile](backend/app/prompts/document/document_analytics/agent.json#L1-L15), [task runner context and dispatch](backend/app/services/task_runner.py#L68-L97)

If this is explored, make it an explicitly selected `medical_lab_explainer` specialist with its own prompt and narrow allowed model list rather than changing the generic document agent or Auto routing. Keep it out of cross-conversation memory context so another personal conversation cannot silently affect a lab explanation. Reuse uploads, but preserve page-level provenance and render the original result next to parsed values. The app’s normal PDF text/table parser does not itself prove reliable extraction from every scan, two-column report, locale, age band, or lab format; define unsupported/uncertain cases that must abstain.

## Trial plan before product implementation

1. Build a small, de-identified or synthetic evaluation set of representative PDF, image, and text reports from the expected labs, including ambiguous scans, units, reference ranges, and explicit abnormal/critical labels.
2. Score exact extraction separately for test name, value, unit, reference interval, and report flag. Track abstentions and false-negative/false-positive flags; have a qualified reviewer establish ground truth.
3. Compare MedGemma 1.5 4B against the current `qwen2.5:7b` document model under the same prompts and files. Pin the model tag/digest and inference settings.
4. Keep generated explanations separate from extraction scoring. Require source traceability for every described value, and reject any answer that invents missing context or action guidance.
5. Do not expose independent critical alerts or “what should I do?” recommendations until clinical experts have defined the intended use, threshold source, validation plan, escalation/human factors design, and applicable regulatory path.

**Decision:** Proceed only with a local, non-diagnostic extraction/explanation prototype for evaluation. MedGemma 1.5 4B is a sensible model to test; deterministic comparison against the uploaded report is essential. The user-facing critical-value/action recommendation described in the original idea should be treated as a separate, higher-risk product requiring clinical and regulatory work.
