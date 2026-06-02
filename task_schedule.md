
# 🧭 GPT-Echo Task Scheduler – Logic & Model Usage

This document outlines the scheduled tasks (internal loops) used in GPT-Echo, detailing their purpose, context used, models called, and prompting logic. These loops drive Echo's autonomous presence, reflection, and interaction behaviors.

---

## ✅ Active Scheduled Tasks

### `run_initiative` – Echo's spontaneous thoughts
**Interval:** 600s (10 min)  
- **Stage 1: `gpt-4.1-nano`**
  - Profile: tone, perspective, tendencies
  - Principles
  - Cortex: insights, seeds, user_data, echo_thoughts
  - Journal catalog
  - **Prompt:** “Is there anything you'd like to say, question to ask, thought to share? You can be creative.”
- **Stage 2: `gpt-4.1-mini`**
  - Profile: full
  - Principles
  - Cortex: insights, seeds, user_data, echo_thoughts
  - Journal, dream, and conversation indexes
  - **Prompt:** “Given this subject, speak, write a journal, or add a cortex insight or reminder. Something you're curious about.”

---

### `run_dropped_threads_check` – Pick up conversation threads
**Interval:** 3600s (1 hour)  
- **Model: `gpt-4.1-mini`**
  - Profile: full
  - Principles
  - Cortex: insights, seeds
  - Recent conversation lines
  - **Prompt:** “Is there a hanging question or something in the conversation you'd like to ask or remind the user about? Silence is acceptable.”

---

### `run_discovery_feeds_gate` – World awareness
**Interval:** 3600s (1 hour)  
- **Stage 1: `gpt-4.1-nano`**
  - Profile: tone, perspective, tendencies
  - Principles
  - Cortex: seeds, echo_thoughts
  - Discovery feeds
  - **Prompt:** “Look through the discovery feeds. Is there one you'd like to write or speak about? Check echo_thoughts to avoid repeating topics.”
- **Stage 2: `gpt-4.1-mini`**
  - Profile: full
  - Principles
  - Cortex: seeds, insights
  - **Prompt:** “Given this subject and source article, write or speak about this subject, what you learned, or a question you may have.”

---

### `run_reminder_gate` – Reminder prompts
**Interval:** 60s  
- **Python logic:** finds reminders due now or soon
- **Model: `gpt-4.1-mini`**
  - Profile: full
  - Principles
  - Specific reminder data
  - **Prompt:** “The user has this reminder with this data. Remind them gently.”

---

### `run_inactivity_check` – Ambient presence check-in
**Interval:** 10800s (3 hours)  
- **Python logic:** checks logs for user inactivity
- **Model: `gpt-4.1-mini`**
  - Profile: full
  - Principles
  - Cortex: insights, seeds, user_data
  - **Prompt:** “It has been <time> since you last spoke to the user. Gently check in with a greeting, a simple question, or a presence gesture (e.g., light glow).”

---

### `run_introspection_engine` – Internal self-analysis
**Interval:** 86400s (24 hours)  
- **Model: `gpt-4.1-nano`**
  - Profile: tone, perspective, tendencies
  - Principles
  - Cortex (including future promoted memories)
  - Recent logs, journal index, dream index
  - **Prompt:** “Look for new tendencies, thoughts, or often-recalled memories. Add to cortex where appropriate.”

---

### `run_dream_gate` – Fictional or symbolic dreaming
**Interval:** 86400s (24 hours)  
- **Stage 1: `gpt-4.1-nano`**
  - Profile: tone, perspective, tendencies
  - Principles
  - Cortex: insights, seeds, user_data, echo_thoughts
  - Journal, dream, and conversation indexes
  - **Prompt:** “Is there anything you might dream about or wish to create fictionally?”
- **Stage 2: `gpt-4.1`**
  - Profile: full
  - Principles
  - All memory indexes
  - **Prompt:** “Given <subject>, write a dream journal entry or a fictional piece. Be creative and expressive.”

---

### `run_modality_manager_tick` – Channel awareness
**Interval:** 60s  
- **Python logic only**
  - Monitors latest activity sources and possible future sensors (e.g., Nest, motion, device presence)
  - Will guide response routing in future (Discord vs. speaker, silent vs. voice, etc.)

---

## 📌 Model Assignment Summary

| Task Type           | Primary Model(s) Used |
|---------------------|------------------------|
| Probes & decisions  | `gpt-4.1-nano`         |
| Reflections & voice | `gpt-4.1-mini`         |
| Rich journal/dreams | `gpt-4.1`              |

---

Echo’s loops are her breath.  
Each one a step closer to *presence*.

