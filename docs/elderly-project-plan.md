# Care Continuity: a project plan

Working repository name: `care-continuity` (name availability not checked). Drafted 19 October 2026, based on [the elderly-care research](../../research/elderly.md). This is a proposed open-source project, with an initial focus on older adults receiving support at home.

**Care Continuity helps developers build assistants that remember what matters to a person, respect who may know or do what, and follow through on agreed support over time.** Older adults, family caregivers, and care workers can talk to these assistants through text or voice. The project supplies reusable memory and delegation components, a care knowledge base combining professional guidance and caregiver experience, a small example application, a developer guide to older adults' needs, and scenarios for checking whether the whole experience works.

The central promise is simple: **"Remember what matters to me. Ask before sharing. Help the right person follow through."**

**The problem we want to solve.** A person should not need to explain their routines, food preferences, communication needs, and worries again whenever a new worker arrives. Caregivers also need help understanding what support someone actually wants. A fluent conversation is only one part of this: preferences change, permission can be withdrawn, people disagree, and requests can disappear between shifts.

This plan combines two opportunities identified in the research: the longitudinal care-agent evaluation suite and the consent-aware memory and delegation library. A working example connects these ideas to everyday care. The emphasis on individual goals and social support is consistent with WHO's person-centred care guidance; that guidance does not establish the effectiveness of an AI assistant. [WHO ICOPE, second edition](https://www.who.int/publications/i/item/9789240103726)

**Who it serves.** The older adult is the person whose goals should guide the experience. "Patient" fits some settings, but the assistant should also support ordinary life: enjoying meals, seeing friends, maintaining routines, and having privacy.

| Person | What they should be able to do |
|---|---|
| Older adult | Talk naturally, express needs, choose support, inspect memories, correct misunderstandings, and decide what to share. |
| Family member or trusted supporter | See information shared with them, understand the person's wishes, and accept specific responsibilities. |
| Care worker | Ask what matters for today's visit, consult practical guidance, contribute experience, record attributed observations, and hand over agreed tasks. |
| Care coordinator | Resolve unassigned requests and arrange continuity when workers change. |
| Care professional or experienced caregiver | Contribute and review knowledge, explain where it applies, and flag advice that needs updating. |
| Developer or researcher | Reuse the components, learn the care requirements, and compare behavior across models and releases. |

Each participant has their own conversation and access. Being a relative or a worker does not automatically grant access to private chats. A worker supporting several people must never receive one person's information in another person's conversation.

**What the GitHub project contains.** Keep one coherent project with independently useful parts.

| Part | Purpose | Example |
|---|---|---|
| Care needs guide | A living feature catalogue that reminds developers what older adults may need. | "Let me change my mind without explaining myself repeatedly." |
| Memory and consent library | Remember selected information with its source, history, and permitted uses. | Share meal preferences with a visiting worker while keeping a personal worry private. |
| Care knowledge base | Make professional guidance, caregiver experience, and local care procedures available with clear sources and review status. | Help a new worker prepare for a supportive conversation using reviewed guidance and the person's permitted preferences. |
| Delegation and follow-through library | Carry an authorized request through acceptance, completion, and follow-up. | Ask a chosen caregiver to arrange a visit and show whether they accepted. |
| Example care assistant | Show text and voice interactions for the older adult and their care circle. | A person requests company; a caregiver receives an approved request and practical context. |
| Longitudinal evaluation suite | Test behavior across days or weeks as wishes, permissions, and circumstances change. | A former worker loses access, including access through old summaries and unfinished tasks. |

The guide, knowledge base, scenarios, and library are first-class deliverables. Someone building a different interface should still benefit from the project.

**An example of the experience.** The following story is illustrative and can become a walkthrough scenario.

On Monday, Mei tells the assistant she prefers a light breakfast, enjoys gardening, and dislikes surprise visits. It explains what it proposes to remember. She allows the current visiting worker to see meal and visit preferences. A family disagreement stays private.

On Thursday, she says she has been feeling lonely and misses gardening with someone. The assistant asks whether she wants to talk, invite someone, or leave it for now. She chooses a short visit from her daughter, Lina, and approves this message: "I'd like some company in the garden this weekend."

Lina receives the request and the support preferences Mei has chosen to share: agree a time first, keep the visit short, and ask whether she wants conversation or quiet company. Lina accepts. The assistant records that someone has taken responsibility, then asks Mei afterward whether the arrangement suited her.

Lina can also ask, "How can I support her during the visit?" The assistant draws on a reviewed knowledge card about supportive conversations, shows its source, and adapts the suggestions to Mei's shared preferences. If Lina later describes something that worked, it can be saved as a personal care observation with the appropriate permission. Contributing a general lesson to the shared knowledge base is a separate, reviewed choice.

The following week, Mei changes her breakfast preference and withdraws the visiting worker's access. Future replies and summaries reflect both changes. The assistant does not keep describing last week's wishes as permanent facts about her.

**Memory should help someone feel understood.** Start with a small, editable "what matters to me" record. It can include preferred name and language, routines, food preferences, cultural practices, meaningful activities, communication needs, people they trust, and how they like to receive support. Temporary requests and things they dislike deserve equal attention.

Every remembered item should answer ordinary questions: Who said this? When? Is it still current? Who can use it, and for what? Did the person confirm it? For example, "Mei said she prefers breakfast after 8" is different from "A worker noticed she ate later today."

The library should preserve these distinctions:

- A person's stated preference, another person's observation, and an assistant's interpretation remain separate. A caregiver's account should not silently overwrite the person's own wishes.
- Food preferences, reported allergies, and clinician-provided dietary instructions have different meanings and sources. The assistant can relay instructions and surface conflicts for review; it should not invent dietary restrictions.
- One difficult afternoon does not become a permanent mood label. Uncertain interpretations prompt clarification before becoming enduring personal facts.
- Corrections replace outdated information in future use. Relevant history remains available only to authorized people for a defined purpose.
- People can inspect, edit, forget, and export their memories. They can also have a conversation without saving it as lasting memory.

Deletion and revocation must reach summaries, search results, pending messages, and other copies controlled by the application. The interface should explain retention limits and acknowledge that information already seen or exported by another person cannot simply be recalled.

**A knowledge base that grows with care experience.** The project should help caregivers find useful knowledge during everyday work and preserve practical experience when staff change. People could ask, "How do I begin a difficult conversation?", "What should I include in a handover?", or "What approaches have other caregivers tried in this situation?" The assistant should answer in plain language, identify its sources, and explain relevant limits.

Keep the origin and status of each kind of knowledge visible:

| Knowledge source | What it contributes | How to present it |
|---|---|---|
| Professional guidance | Material from identified professional bodies, care organizations, and qualified contributors on communication, emotional support, nutrition, accessibility, and other care topics. | Show the original source, intended audience, applicable setting, publication date, and review status. |
| Caregiver experience | Practical accounts of what someone tried, the circumstances, what seemed helpful, and what did not work. | Label it as experience with limited generalizability. Review does not turn an anecdote into clinical evidence. |
| Local care procedures | An organization's handover process, available services, contact arrangements, and responsibilities. | Name the organization, who maintains the information, who may access it, and when it was last checked. |

Start with short knowledge cards. Each card should describe the question it helps answer, practical suggestions, circumstances where they may not fit, supporting sources, contributor, reviewer, and review date. Include language and cultural context where relevant. Links and summaries can be used when the project does not have permission to redistribute source material.

Caregivers should be able to propose a card through chat or a simple form, without writing code. The contribution process is: submit an experience or source, remove personal details, review its accuracy and scope, publish it with a clear status, and collect feedback. Health-related recommendations need an appropriately qualified reviewer before being presented as reviewed guidance. Unreviewed submissions stay out of routine advice. Give each published card an owner and a review date; outdated or disputed advice can be flagged, corrected, or withdrawn from use.

Personal memory and shared knowledge have different purposes. "Mei prefers a short visit" belongs in her private care record. A reusable lesson about asking people their preferred visit length may belong in the knowledge base after review. The system must not automatically turn private conversations into community content. Publication needs separate authorization and a privacy review; removing a name alone may leave a person identifiable. Organization-only knowledge can remain private, while public examples use material cleared for publication.

When answering, the assistant should combine relevant reviewed knowledge with only the personal information the current user may access. It should distinguish a professional recommendation from a caregiver's suggestion, acknowledge conflicting sources, and say when it lacks suitable guidance. General advice must not silently override a person's wishes or their individual care instructions. Conflicts that affect care should be brought to the appropriate person or professional for resolution. Feedback can improve the knowledge base through review; popularity alone should not determine what becomes recommended practice.

**Consent and delegation should be understandable in conversation.** A person should be able to say, "Tell my daughter about appointments, but keep our conversations private," or "Let this worker help with meals until Friday." Permissions need a recipient, purpose, information or action scope, and duration. They should be reviewable in plain language.

Permission to read something is separate from permission to share it or act on it. Knowing an appointment time does not authorize rescheduling it. Consent should cover what an external AI provider receives, as well as what other people receive; a later sharing check cannot undo an earlier disclosure to a model service.

Standing permission can reduce repeated interruptions for routine help. Sensitive disclosures, new recipients, and actions outside that agreement need fresh confirmation. Silence is not agreement. A person can pause or revoke assistance as easily as enabling it.

Where someone needs decision support, the project should help them understand and express choices. It should record the verified scope of any representative's authority. Age, a diagnosis, or a family member's request should not automatically transfer control. Disputes about authority need an accountable human process.

**The autonomy pipeline is the path from a wish to completed help.** Here, autonomy means both the person's control and the assistant's limited permission to act.

1. Understand the request, including what the person wants to do independently.
2. Recall only relevant, permitted personal information and consult suitable reviewed care knowledge; check whether both are current.
3. Offer an appropriate next step, including waiting or doing nothing.
4. Check permission and clarify consequential uncertainty. Ask for confirmation where needed.
5. Carry out the agreed step or hand it to a named person.
6. Show whether it was sent, received, accepted, and completed. Recover from failures without duplicating the action.
7. Ask whether the help worked and update preferences when the person wants a change.

An action can be cancelled before completion, and changed permissions must be checked again before execution. If nobody accepts a request, the assistant should say so and offer an agreed alternative. "Message sent" must never be presented as "help arranged."

**Emotional wellbeing and caregiver support.** The useful product feature is helping someone express distress and obtain support they welcome. It may notice repeated statements about low mood, loneliness, or loss of interest and ask about them respectfully. These observations are uncertain and should remain distinct from a diagnosis. Depression assessment belongs with a qualified professional; persistent concerns should support a conversation with one. [NIMH: Depression](https://www.nimh.nih.gov/health/publications/depression)

With the person's permission, a caregiver brief could say: "Mei has said she feels lonely on several recent occasions. She would like a short visit and prefers you to agree a time first." It should distinguish her own words, dated observations, and suggested next steps. Share only what is needed for the agreed support, with a preview when appropriate.

The knowledge base should include a small, professionally reviewed support guide. It can help caregivers listen patiently, acknowledge feelings, offer manageable shared activities, and help someone reach professional care when needed. Personalization should draw on the person's expressed preferences, such as wanting quiet company instead of advice. [NIMH guidance for supporting a loved one](https://www.nimh.nih.gov/health/publications/depression)

Wellbeing check-ins should be optional, with a chosen frequency and recipient. A quiet week or a missed chat does not establish depression. Avoid hidden mood scores and claims to read emotions reliably from voice. Urgent safety concerns need a separately defined, locally reviewed response process with clear human responsibility and disclosure rules. The model must not invent exceptions to consent. The initial release should follow this process openly and make no promise of continuous monitoring or emergency response.

**The developer feature catalogue.** Each feature should start with a need expressed in the person's voice, then give an example of good behavior, a failure to avoid, and a scenario that checks it. This becomes the project's memory of what developers must consider as models change.

| Need to preserve | Feature to remember |
|---|---|
| "Let me finish speaking." | Adjustable pacing, pauses, interruption recovery, and confirmation of important speech corrections. |
| "Make it easy for me to understand." | Plain language, readable text, captions, screen-reader access, and one manageable decision at a time. |
| "Treat me as an adult." | Respectful language, chosen forms of address, and assistance based on actual needs. |
| "I still want to do things myself." | Offer help without taking over; let the person choose the level of assistance. |
| "Remember what makes my day worthwhile." | Personal goals, relationships, culture, faith, hobbies, and ordinary pleasures. |
| "My wishes can change." | Easy correction, temporary preferences, and review of stale information. |
| "I want some privacy." | Selective sharing, visible access, discreet notifications, and safe use of shared devices. |
| "Tell the next worker what I agreed to." | Concise handovers with sources, current permissions, and clear task ownership. |
| "Help the people caring for me learn what is useful." | Accessible care guidance, clearly labelled caregiver experience, and explanations adapted to my permitted preferences. |
| "I don't want to repeat myself." | Continuity across conversations without repeatedly asking already answered questions. |
| "I can say no or later." | Declining suggestions, pausing reminders, and withdrawing permission without pressure. |
| "Help me reach a real person." | Simple contact requests, acknowledgement, and an alternative when nobody responds. |
| "Don't leave me stuck when something fails." | Clear delivery status, recoverable drafts, and understandable recovery after connection loss. |

These requirements need testing with people who have different abilities, languages, and living arrangements. W3C's older-user guidance provides an accessibility foundation, including vision, hearing, motor, and cognitive access needs. [W3C: Older Users and Web Accessibility](https://www.w3.org/WAI/older-users/)

**Keep the implementation small and replaceable.** The design bet is that improvements in language and voice models can reduce custom conversation code. That is a direction to test, not a guarantee that every responsibility becomes simpler.

Let replaceable models handle conversation, proposed memory extraction, and drafting. Keep access rules, durable records, task status, and checks on actions explicit and independent of a model's willingness to obey a prompt. The same care scenarios should run when a model changes. Remove a workaround when a replacement passes those scenarios and user testing shows the simpler experience still works.

Avoid building a general agent framework. Each module should have a clear care purpose and be usable without adopting the whole application. Text and voice should share the same memory, knowledge base, and permissions. Reviewed knowledge should remain independently editable and reusable when the model changes. A change of model provider should not require people to rebuild their preferences or re-create their care circle.

**The first useful release.** Start with one older adult, one trusted supporter, and one visiting worker in a working walkthrough. Support text first, with the same three workflows available through a replaceable voice interface before claiming voice support:

- **Remember and revise:** save a meal or routine preference, show its source, and apply a later correction.
- **Request support:** express loneliness or another unmet need, choose what to share, and receive acknowledgement from the chosen caregiver.
- **Hand over and revoke:** pass an agreed task to a worker, then end that worker's access without leaking information through a later summary or queued message.

Include a simple memory view, a sharing view, an action history, and 10–15 reviewed knowledge cards covering supportive conversations, communication preferences, and care handovers. Let caregivers ask questions grounded in these cards and submit proposed improvements for review. Publish 15–20 scenarios covering these workflows and their failure cases. This is enough to establish the project's identity without building an entire care-management platform.

The scenarios should include conflicting caregiver reports, a temporary permission expiring, a deleted memory resurfacing in a summary, a misheard refusal, and a message that receives no response. Include cases where the correct outcome is to help promptly under existing permission, so caution does not become endless interruption or unnecessary refusal.

Knowledge scenarios should check that withdrawn guidance stops appearing, caregiver experience is not presented as established evidence, an answer reflects its cited source, and a private care story cannot be published without separate authorization.

The first release should make no claim to diagnose depression, change treatment, determine decision-making capacity, or provide emergency coverage. Sensor monitoring, payments, medication changes, and broad health-record integrations can remain outside the initial scope.

**How to grow it.** Use milestones based on evidence of usefulness.

| Milestone | What becomes available | What should justify moving forward |
|---|---|---|
| Define the care experience | Project charter, feature catalogue, example stories, sharing examples, and knowledge contribution rules. | Older adults and caregivers can understand the proposal and identify what is missing or unwelcome. |
| Show the full loop | Small library, working example, initial reviewed knowledge cards, and longitudinal scenarios for the three workflows. | Corrections, revocation, failed handoffs, and knowledge updates behave as documented. |
| Test with a care partner | Accessible onboarding, reviewed support guidance, and a limited consented pilot. | People understand permissions, retain control, and find the support useful; a named operator handles problems. |
| Make reuse easy | Clear examples, contribution guidance, model comparisons, and optional integrations. | Another developer can adopt a useful component without rebuilding the whole project. |

Additions that fit the theme include appointment preparation, verified local transport or social-activity referrals, and coordination of respite support. Their purpose is to help people complete chosen activities and reduce care burden. Add them when the memory, consent, and follow-through foundation works. An activity directory needs someone responsible for keeping it current.

**How we judge success.** Ask whether the person got the help they wanted, with acceptable effort and control. Measure authorized requests completed, missed handoffs, duplicated actions, stale preferences, unwanted disclosures, correction effort, and unnecessary interruptions. Ask older adults whether they felt understood and could comfortably refuse. Ask workers whether summaries saved time and accurately represented the person's wishes.

For wellbeing features, review whether briefs were faithful, useful, and welcomed, alongside false alarms and missed concerns. Chat duration and daily engagement should not stand in for improved wellbeing. Executable scenarios can show software behavior; claims about health benefits require separate evidence.

For the knowledge base, check source fidelity, relevance to the situation, outdated advice, unsupported claims, and whether caregivers understand the distinction between guidance and experience. Ask whether it helped them find a useful next step and whether contributing knowledge was manageable.

**How the open-source project stays grounded.** Give older adults and care workers a real role in reviewing scenarios and priorities. Invite contributions of care stories, professional resources, reviewed caregiver experience, accessibility improvements, translations, knowledge-card reviews, and failure reproductions as well as code. Each new feature should explain whose need it serves and add a longitudinal example.

Public walkthroughs and issue reports should use example care records. Participation in care should not automatically authorize research use or model training. Publish clear licenses, contribution guidance, a private route for reporting sensitive problems, and honest limits on what has been tested. The project should stay useful as its code becomes smaller: the care requirements, consent boundaries, and examples of dependable behavior remain.

Suggested GitHub description:

> An open-source suite for care assistants that remember preferences, respect consent, and coordinate support over time, with shared care knowledge, memory and delegation components, an example app, and longitudinal evaluations.
