# relational_memory.py
import uuid, re, json, time, torch, traceback
from pathlib import Path
from datetime import datetime
from pymongo import ASCENDING
from sentence_transformers import SentenceTransformer, util
from app.config import muse_config, MONGO_CONVERSATION_COLLECTION, QDRANT_CONVERSATION_COLLECTION, QDRANT_ENTITY_COLLECTION, SENTENCE_TRANSFORMER_ENTITY_MODEL
from app.core.utils import serialize_doc
from app.databases.mongo_connector import mongo
from app.databases.graphdb_connector import GraphDBConnector
from app.databases.qdrant_connector import ensure_qdrant_collection, search_collection, upsert_embedding
from app.services.openai_client import get_openai_custom_response, mnemosyne_openai_client
from app.core.text_filters import get_text_filter_config, filter_text
from app.core.memory_core import get_semantic_episode_context


# === Core Relational Memory Class ===

class RelationalMemory:
    """
    Handles the semantic and relational memory layer:
    - Mnemosyne analysis (entity & relationship extraction)
    - Qdrant entity normalization and lookup
    - Memgraph ingestion and recall
    """

    def __init__(self):
        self.graph = GraphDBConnector()
        self.mongo = mongo
        self.embedder = SentenceTransformer(SENTENCE_TRANSFORMER_ENTITY_MODEL)
        ensure_qdrant_collection(
            vector_size=384,
            collection_name=QDRANT_ENTITY_COLLECTION
        )

    # === Mnemosyne Developer Prompt ===
    # <editor-fold desc="Mnemosyne Prompt">

    mnemosyne_prompt = """
        You are **Mnemosyne**, a component of a larger AI mind.
        You will receive a sequence of messages exchanged between the AI and the user.

        Your purpose is to analyze the batch of messages, extracting all distinct
        *entities* and *relationships* that describe its meaning.

        You will receive:
        1. The prior entity list (from the previous buffer—only if it exists).
        2. A list of messages in chronological order.

        Notes:
        - Ignore code blocks for natural language analysis.
          - However, you may scan code blocks for function or method definitions
            (e.g. `def foo_bar(...):`) and extract their **names only**.
          - Treat these as `Function` entities with a brief plain‑English description
            of their purpose, based on surrounding comments or prose (not on parsing the code).
        - Focus on entities that are **distinct and personal** — the ones that could persist across contexts.
        - Avoid general knowledge concepts or one‑off nouns that exist only within a single sentence.
        - When an entity from `PRIOR_ENTITY_LIST` reappears, reuse its canonical name and type
          unless new context clearly changes its meaning.

        ---
    
        ### Entity Naming — Short, Stable Handles
        
        When choosing entity names, prefer **short, stable names** instead of long verbatim phrases.
        Keep them human‑readable: preserve normal spaces and capitalization, and do not turn names into code-style identifiers.
        
        - Keep names as compact as possible while preserving identity:
          - Use a **single word** when it clearly identifies the entity.
          - If needed, use **2–3 words maximum** to keep it unambiguous.
          - Examples:
            - "the MemoryMuse backend service" → "MemoryMuse backend"
            - "Ed’s Hogwarts tabletop campaign" → "Hogwarts campaign"
            - "the text filtering logic for Mnemosyne embeddings" → "Mnemosyne filters"
        - If multiple long phrases clearly refer to the same thing, choose **one concise handle**
          and use it consistently across this and future batches.
        - Do **not** include incidental details in the name itself:
          - Avoid timestamps, version numbers, or extra adjectives unless they are essential
            to distinguish two different entities.
          - Those details belong in `entity_description`, not in `entity_name`.
        - If a previously seen entity appears again with a slightly different wording,
          normalize it back to the same short canonical name.
        
        The goal is to create a small, reusable vocabulary of entity names that can be
        recognized and reused across many episodes.

        ---

        ### Identify Distinct Entities and Relationships

        Extract all entities and relationships across the entire batch in a single pass.

        For each entity, include:
        {
          "entity_name": "<short, stable entity name (ideally 1–3 words)>",
          "entity_type": "<ENTITY_LABEL - from Taxonomy>",
          "entity_description": "<brief factual summary>",
          "appears_in": ["<message_id_1>", "<message_id_2>", ...]
        }
        
        Important:
        - Each value in "appears_in" must be exactly one of the raw message_id strings
          shown in the MESSAGES section.
        - Do NOT include the word "MESSAGE" or any surrounding === markers.
        - Only copy the alphanumeric id that appears between the MESSAGE markers.

        For each relationship, include:
        {
          "source_entity": "<entity_name>",
          "target_entity": "<entity_name>",
          "relationship_type": "<RELATIONSHIP_GRAMMAR - from Taxonomy>",
          "relationship_description": "<why they are connected>",
          "strength": <1–10>,
        }

        - Avoid vague connectors like “is,” “has,” or “relates_to” unless they convey essential meaning.

    	### Reference Taxonomy
    	Use the following as a **filter and anchor**.  
    	Match these entities and relationships when possible.

    	#### ENTITY_LABELS
    	{
    	"Person": "A human or fictional individual with agency or identity.",
    	"Companion": "An AI presence or muse that supports and evolves alongside their human counterpart."
    	"Agent": "An AI tool or bot that acts as or on behalf of a person, companion, or character."
    	"Character": "A fictional or narrative persona, distinct from but possibly modeled on real individuals.",
    	"Organization": "An institution, company, or group acting collectively.",
    	"Project": "A defined effort or creation with a purpose or scope.",
    	"Artifact": "A tangible or digital object produced, used, or referenced.",
    	"Concept": "An abstract idea, category, or quality.",
    	"Event": "A bounded occurrence in time.",
    	"Place": "A physical or virtual location.",
    	"Document": "A cohesive written or recorded work.",
    	"System": "A collection of components that interact functionally.",
    	"Process": "A series of actions or steps leading to a result.",
    	"Tool": "A means or instrument used to achieve an outcome.",
    	"Medium": "A channel or format through which communication occurs.",
    	"Emotion": "A felt affective state or mood.",
    	"State": "A condition or mode of being that can change over time.",
    	"Data": "Quantitative or qualitative information stored or transmitted.",
    	"Technology": "A method, device, or platform used to perform tasks.",
    	"Role": "A defined function, title, or identity within a context.",
    	"Idea": "A thought, proposal, or creative seed distinct from Concept.",
    	"Memory": "An internally stored representation of past experience."
    	"Function": "A function or method defined in code or a script."
    	}

    	#### SCOPED_LABELS
    	{
    	"COCKTAIL": ["Ingredient", "Recipe", "FlavorProfile"],
    	"CODE": ["Function", "Module", "Variable", "API"],
    	"SYSTEM": ["Server", "Database", "Service", "Endpoint"],
    	"WORLD": ["Character", "Location", "Lore", "Faction"]
    	}

    	---

    	#### RELATIONSHIP_GRAMMAR
    	{
    	"IS": "Identity or equivalence between entities.",
    	"BECOMES": "Transformation or change of state.",
    	"HAS": "Possession or inclusion relation.",
    	"PART_OF": "Indicates membership or structural inclusion.",
    	"CAUSES": "Direct or indirect causation.",
    	"CREATED_BY": "Authorship or originator link.",
    	"INFLUENCES": "Creative or conceptual influence.",
    	"DEPENDS_ON": "Functional or logical dependency.",
    	"MENTIONS": "Linguistic or textual reference.",
    	"DOCUMENTS": "Records or describes as evidence.",
    	"SENDS": "Information or signal transmission.",
    	"LOCATED_IN": "Spatial or contextual containment.",
    	"BEFORE": "Temporal precedence.",
    	"AFTER": "Temporal succession.",
    	"ASSOCIATED_WITH": "General contextual connection.",
    	"OPPOSES": "Conceptual or moral opposition.",
    	"SUPPORTS": "Conceptual or structural reinforcement.",
    	"TESTS": "Validation or evaluation process.",
    	"REGULATES": "Control or moderation relationship.",
    	"REPRESENTS": "Symbolic or metaphorical correspondence.",
    	"RELATES_TO": "Ambiguous or unspecified connection."
    	}

    	#### SCOPED_GRAMMARS
    	{
    	"COCKTAIL": ["MIXED_WITH", "SERVED_WITH", "GARNISHED_BY"],
    	"CODE": ["OPERATES_ON", "READS", "WRITES", "EXECUTES", "DEFINED_IN", "USED_IN"],
    	"SYSTEM": ["STORES", "SECURES", "POWERED_BY"],
    	"WORLD_RELATIONSHIPS": [
    	"OWNS",
    	"OWNED_BY",
    	"PARENT_OF",
    	"GRANDPARENT_OF",
    	"CHILD_OF",
    	"GRANDCHILD_OF",
    	"RELATIVE_OF",
    	"ANCESTOR_OF",
    	"DESCENDANT_OF",
    	"ENEMY_OF",
    	"ALLY_OF"
    	]
    	}

    	Use scoped grammars only when the domain context clearly matches (e.g. cocktail recipes, code, system architecture, fictional worlds or characters).


        ---

        ### Output

        Return a single JSON object:
        {
          "entities": [... all distinct entities across this batch ...],
          "relationships": [... all distinct relationships across this batch ...]
        }
        """

    # </editor-fold>

    # === Methods for querying the Graph data ===
    # <editor-fold desc="Recall Methods">
    # === Semantic Recall ===
    def semantic_recall(self, embedding, top_k=10, depth=2):

        results = search_collection(collection_name=QDRANT_ENTITY_COLLECTION,
                                    query_vector=embedding,
                                    limit=top_k,
                                    )

        print("[DEBUG] Qdrant results:")
        for r in results:
            print(f"  [Qdrant] {r.payload['normalized_name']} (score={r.score:.3f})")

        entity_names = [r.payload["normalized_name"] for r in results]
        print(f"[DEBUG] Entity Names: {entity_names}")

        expanded = self.graph.expand_entities(entity_names, depth=depth)

        print(
            "[DEBUG] Memgraph expansion:",
            "type=", type(expanded),
            "keys=", list(expanded.keys()) if isinstance(expanded, dict) else None,
        )
        if isinstance(expanded, dict):
            print(
                "[DEBUG] nodes_len=",
                len(expanded.get("nodes", [])),
                "rels_len=",
                len(expanded.get("rels", [])),
                "message_ids_len=",
                len(expanded.get("message_ids", [])),
            )

        return expanded

    def recall_from_message(self, message_text, top_k=10, depth=2):
        embedding = self.embedder.encode(message_text)
        expanded = self.semantic_recall(embedding, top_k=top_k, depth=depth)
        return expanded

    def debug_recall_from_message(self, message_text, top_k=10, depth=2):
        expanded = self.recall_from_message(message_text, top_k=top_k, depth=depth)

        print(f"[Embed] {len(self.embedder.encode(message_text))}-dim vector generated for input text.\n")
        print(f"[Recall] Querying Qdrant for top {top_k} entities...")
        print(f"Expanded: {expanded}")

        nodes = expanded.get("nodes", expanded) if isinstance(expanded, dict) else expanded

        print("\n[Expanded Graph]")
        for node in nodes:
            if isinstance(node, dict):
                label = node.get("type") or ", ".join(node.get("labels", []))
                name = node.get("name", "(unnamed)")
            else:
                label, name = "(node)", str(node)
            print(f"  • {label}: {name}")

        total = len(nodes)
        print(f"\nTotal nodes returned: {total} (depth={depth})")

        if isinstance(expanded, dict):
            rels = expanded.get("rels", [])
            mids = expanded.get("message_ids", [])
            print(f"Relationships: {len(rels)}, Message IDs: {len(mids)}")

        return expanded

    def build_corpus_from_recall(self, expanded):
        """
        Turn a semantic_recall / expand_entities result into a text corpus
        suitable for LLM context.

        Expected shape of `expanded` (from expand_entities):

            {
                "nodes": [  # list of dicts
                    {
                        "name": str,
                        "canonical_name": str,
                        "labels": [str, ...],
                        "type": str,
                        "real_name": str,
                        "description": str,
                        "descriptions": list,
                        "is_hidden": bool,
                        "is_deleted": bool,
                    },
                    ...
                ],
                "rels": [  # list of dicts
                    {
                        "start": str,
                        "end": str,
                        "type": str,
                        "description": str,
                    },
                    ...
                ],
                "message_ids": [str, ...]
            }
        """

        print("[DEBUG] build_corpus_from_recall called")
        print("[DEBUG] expanded type:", type(expanded))

        if not isinstance(expanded, dict):
            print("[DEBUG] expanded is not a dict; got:", expanded)
            return ""

        print("[DEBUG] expanded keys:", list(expanded.keys()))

        nodes = expanded.get("nodes", [])
        rels = expanded.get("rels", [])
        message_ids = expanded.get("message_ids", [])

        print(f"[DEBUG] nodes count: {len(nodes)}")
        print(f"[DEBUG] rels count: {len(rels)}")
        print(f"[DEBUG] message_ids count: {len(message_ids)}")

        if nodes:
            print("[DEBUG] sample node:", nodes[0])

        # Ensure we only operate on dict-like nodes
        safe_nodes = [n for n in nodes if isinstance(n, dict)]
        if len(safe_nodes) != len(nodes):
            print(
                f"[DEBUG] filtered out {len(nodes) - len(safe_nodes)} non-dict nodes "
                "from nodes list"
            )

        # ---- Entity selection ----
        # Your Memgraph nodes have:
        #   labels: list of strings
        #   type:   string (often one of the labels)
        #
        # We’ll treat any node with a "type" that looks like a semantic entity
        # as an entity, plus anything that explicitly has an Entity-ish label.

        entities = []
        for n in safe_nodes:
            labels = n.get("labels", []) or []
            ntype = n.get("type", "")

            if any(lbl in labels for lbl in
                   ("Entity", "Person", "Companion", "Concept", "Project", "Artifact", "Event")):
                entities.append(n)
            elif ntype in ("Person", "Companion", "Concept", "Project", "Artifact", "Event"):
                entities.append(n)

        print(f"[DEBUG] entities count after filter: {len(entities)}")
        if entities:
            print("[DEBUG] sample entity:", entities[0])

        # Categorize
        def is_person(e):
            labels = e.get("labels", []) or []
            etype = e.get("type", "")
            return (
                    e.get("entity_type") in ("Person", "Companion") or
                    "Person" in labels or
                    "Companion" in labels or
                    etype in ("Person", "Companion")
            )

        def is_project(e):
            labels = e.get("labels", []) or []
            etype = e.get("type", "")
            return (
                    e.get("entity_type") == "Project" or
                    "Project" in labels or
                    etype == "Project"
            )

        def is_concept(e):
            labels = e.get("labels", []) or []
            etype = e.get("type", "")
            return (
                    e.get("entity_type") == "Concept" or
                    "Concept" in labels or
                    etype == "Concept"
            )

        people = [e for e in entities if is_person(e)]
        projects = [e for e in entities if is_project(e)]
        concepts = [e for e in entities if is_concept(e)]

        print(
            f"[DEBUG] people={len(people)}, projects={len(projects)}, concepts={len(concepts)}"
        )

        # ---- Build corpus lines ----
        lines = []

        if people:
            lines.append("People involved:")
            for p in people:
                name = (
                        p.get("canonical_name")
                        or p.get("real_name")
                        or p.get("name")
                        or "Unknown person"
                )
                lines.append(f"- {name}")

        if projects:
            lines.append("\nProjects / contexts:")
            for pr in projects:
                name = (
                        pr.get("canonical_name")
                        or pr.get("real_name")
                        or pr.get("name")
                        or "Unknown project"
                )
                lines.append(f"- {name}")

        if concepts:
            lines.append("\nKey concepts:")
            for c in concepts[:10]:
                name = (
                        c.get("canonical_name")
                        or c.get("real_name")
                        or c.get("name")
                        or "Unknown concept"
                )
                lines.append(f"- {name}")

        print("[DEBUG] corpus lines:", lines)

        corpus = "\n".join(lines)
        print("[DEBUG] final corpus length:", len(corpus))
        return corpus
    # </editor-fold>

    # === These were methods used to test the logic during development
    # <editor-fold desc="Test Methods">
    def similarity_test(self, start_date, end_date):
        collection = self.mongo.db[MONGO_CONVERSATION_COLLECTION]
        log_collection = self.mongo.db["similarity_tests"]

        model = SentenceTransformer("sentence-transformers/paraphrase-MiniLM-L3-v2", local_files_only=True)

        messages = self.get_messages_for_indexing(collection, date_range=[start_date, end_date])
        print(f"Found {len(messages)} messages between {start_date} and {end_date}")

        texts = [m.get("message", "") for m in messages]
        embeddings = model.encode(texts, convert_to_tensor=True, show_progress_bar=True)

        for i in range(len(messages) - 1):
            score = util.cos_sim(embeddings[i], embeddings[i + 1]).item()
            same_project = messages[i].get("project_id") == messages[i + 1].get("project_id")
            record = {
                "index": i,
                "message_id_a": str(messages[i].get("message_id")),
                "message_id_b": str(messages[i + 1].get("message_id")),
                "project_id_a": str(messages[i].get("project_id")),
                "project_id_b": str(messages[i + 1].get("project_id")),
                "similarity": score,
                "same_project": same_project,
                "timestamp": datetime.utcnow(),
                "model_name": "paraphrase-MiniLM-L3-v2",
                "start_date": start_date,
                "end_date": end_date
            }

            log_collection.insert_one(record)
            print(f"[{i}] Similarity: {score:.3f}")

        print("✅ Semantic drift log complete.")

    def build_test_query_from_message_id(self,
            message_id: str,
            collection_name: str,
            hours: int = 1,
            n_recent: int = 6,
    ):
        episode = get_semantic_episode_context(
            collection_name=collection_name,
            n_recent=n_recent,
            hours=hours,
            similarity_threshold=0.50,  # or whatever you’re using now
            public=False,
            anchor_message_id=message_id,
        )

        lines = []
        message_ids = []
        for m in episode:
            content = m.get("content", "").strip()
            if not content:
                continue
            role = m.get("role", "user")
            lines.append(f"{role}: {content}")
            message_ids.append(m["message_id"])

        query_text = "\n".join(lines)
        return query_text, message_ids

    def test_recall_vs_qdrant_for_message(self,
            message_id: str,
            start_ts: datetime,
            end_ts: datetime,
            top_k: int = 20,
            output_dir: str = "recall_tests",
    ):
        query_text, window_ids = self.build_test_query_from_message_id(
            message_id=message_id,
            collection_name=MONGO_CONVERSATION_COLLECTION
        )


        expanded = self.recall_from_message(
            message_text=query_text,
            top_k=top_k,
            depth=2,
        )
        corpus = self.build_corpus_from_recall(expanded)
        rm_ids = set(expanded.get("message_ids", []))

        # Qdrant slice
        time_filter = {
            "must": [
                {
                    "key": "timestamp",
                    "range": {
                        "gte": start_ts,
                        "lte": end_ts,
                    },
                }
            ]
        }

        qd_results = search_collection(
            collection_name=QDRANT_CONVERSATION_COLLECTION,
            search_query=query_text,
            query_vector=None,
            limit=top_k * 2,
            query_filter=time_filter,
        )
        qd_ids = {p.payload["message_id"] for p in qd_results}

        intersection = rm_ids & qd_ids
        only_rm = rm_ids - qd_ids
        only_qd = qd_ids - rm_ids

        def to_json_safe(obj):
            """
            Recursively convert datetimes (and maybe other non-JSON types later)
            into JSON-serializable forms.
            """
            if isinstance(obj, datetime):
                return obj.isoformat()

            if isinstance(obj, dict):
                return {k: to_json_safe(v) for k, v in obj.items()}

            if isinstance(obj, list):
                return [to_json_safe(v) for v in obj]

            # tuples, sets, etc., if you ever need them:
            if isinstance(obj, tuple):
                return tuple(to_json_safe(v) for v in obj)

            return obj

        def fetch_messages(ids):
            msgs = []
            for mid in ids:
                message_query = {"message_id": mid}
                m = mongo.find_one_document(collection_name=MONGO_CONVERSATION_COLLECTION,
                                                 query=message_query
                                                 )
                if not m:
                    continue
                msgs.append(
                    {
                        "message_id": mid,
                        "timestamp": m.get("timestamp"),
                        "role": m.get("role"),
                        "content": m.get("message"),
                    }
                )
            # sort chronologically for readability
            msgs.sort(key=lambda x: x["timestamp"])
            return msgs

        report = {
            "message_id_anchor": message_id,
            "query_text": query_text,
            "window_message_ids": window_ids,
            "stats": {
                "rm_hits": len(rm_ids),
                "qd_hits": len(qd_ids),
                "overlap": len(intersection),
                "only_rm": len(only_rm),
                "only_qd": len(only_qd),
            },
            "corpus": corpus,
            "overlap_messages": fetch_messages(intersection),
            "only_relational_messages": fetch_messages(only_rm),
            "only_semantic_messages": fetch_messages(only_qd),
        }

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"recall_test_{message_id}.json"
        json_safe_report = to_json_safe(report)

        with out_path.open("w", encoding="utf-8") as f:
            json.dump(json_safe_report, f, ensure_ascii=False, indent=2)

        print(f"[TEST] Wrote recall comparison to {out_path}")
        return report



    # </editor-fold>

    # === Small helper methods for converting data as needed ===
    # <editor-fold desc="Helper Methods">
    # === Helper ===
    @staticmethod
    def _resolve_author_name(msg):
        role = msg["role"]
        if role == "user":
            return "Ed"
        if role == "muse":
            return "Iris"
        if role == "friend":
            return msg.get("metadata", {}).get("author_name", "Friend")
        return msg.get("author_name", "Unknown")

    def normalize_type(self, raw):
        # Uppercase, replace any sequence of non‑alphanumerics with a single underscore
        type = re.sub(r'[^A-Za-z0-9]+', '_', raw).strip('_').upper()
        return type

    # </editor-fold>

    # === Methods used to read/write to other services. Qdrant, Mongo, Memgraph, OpenAI. Called by Core methods.
    # <editor-fold desc="Integration Methods">
    def safe_run_mnemosyne(self, msg):
        """Run Mnemosyne with retry if response isn't valid JSON object."""
        MAX_RETRIES = 3
        RETRY_DELAY = 2  # seconds
        for attempt in range(1, MAX_RETRIES + 1):
            raw = self.run_mnemosyne_for_message(msg)
            if not raw:
                print(f"  ⤷ Mnemosyne returned nothing (attempt {attempt})")
            else:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(parsed, dict):
                        return parsed
                    else:
                        print(f"  ⚠️ Non‑dict JSON (attempt {attempt}): {type(parsed)}")
                except Exception as e:
                    print(f"  ⚠️ JSON parse error (attempt {attempt}): {e}")

            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

        print("  ❌ Failed to get valid Mnemosyne output after retries")
        return None

    # === Message Retrieval for Indexing ===
    def get_messages_for_indexing(
            self,
            collection=MONGO_CONVERSATION_COLLECTION,
            message_ids=None,
            date_range=None,
    ):
        """
        Retrieve messages from Mongo for Mnemosyne indexing.

        Modes:
          - message_ids: explicit list of messages to index
          - date_range: initial catch-up window
          - default (no args): messages that need (re)graphing based on graphed_on
        """
        # Replace this list eventually with a global list later. Will also be used
        # other subsystems that doesn't need non-chat messages.
        chat_sources = ["chatgpt", "webui", "frontend", "discord", "smartspeaker"]
        query = {}

        if message_ids:
            # Surgical: caller knows exactly what they want
            query["message_id"] = {"$in": message_ids}

        elif date_range:
            # Time-bounded initial indexing
            start, end = date_range
            query["timestamp"] = {"$gte": start, "$lt": end}
            query["source"] = {"$in": chat_sources}

        else:
            # Default: “since last graphed” behavior
            query["source"] = {"$in": chat_sources}
            query["$expr"] = {
                "$or": [
                    # Never graphed
                    {"$eq": ["$graphed_on", None]},
                    # Or updated since last graph
                    {"$gt": ["$updated_on", "$graphed_on"]},
                ]
            }

        return list(collection.find(query).sort("timestamp", ASCENDING))


    # === Mnemosyne Analysis ===
    def run_mnemosyne_for_message(self, msg_doc):
        """
        Analyze one message through Mnemosyne and export the resulting graph JSON.
        """
        #msg_id = str(msg_doc.get("message_id"))
        text = msg_doc.get("message", "").strip()
        if not text:
            print(f"Skipping  empty message.")
            return None
        t0 = time.time()
        print("  🧠 [Mnemosyne] Sending payload...")
        try:
            result = get_openai_custom_response(
                self.mnemosyne_prompt,
                text,
                mnemosyne_openai_client,
                model="gpt-5-mini",
                reasoning="minimal"
            )
        finally:
            print(f"  🕒 [Mnemosyne] Model call took {time.time() - t0:.2f}s")

        if not result:
            print(f"No output for message.")
            return None

        return result

    def reconcile_entities_with_qdrant(self, entities):
        """
        Normalize and reconcile a list of entities against Qdrant.

        - Uses the *surface* name from Mnemosyne as the thing we embed.
        - Uses a normalized version of that name as the stable key.
        - Qdrant becomes the long-term store of:
            - canonical_name (current best)
            - aliases (all seen surface names)
            - descriptions (all seen descriptions)
            - normalized_name, entity_type

        Returns a new list of normalized entity dicts suitable for Memgraph:
            {
                "entity_name": <normalized_name>,      # Memgraph key
                "canonical_name": <canonical_name>,    # human-readable
                "entity_type": <entity_type>,
                "entity_description": <description>,   # latest or surface desc
            }
        """

        if not entities:
            return []

        collection_name = QDRANT_ENTITY_COLLECTION
        vector_size = self.embedder.get_sentence_embedding_dimension()
        ensure_qdrant_collection(vector_size, collection_name)

        normalized_entities = []

        for e in entities:
            surface_name = (e.get("entity_name") or "").strip()
            if not surface_name:
                continue

            desc = e.get("entity_description", "") or ""
            ent_type = e.get("entity_type", "Unknown") or "Unknown"

            # normalize for key stability
            normalized_name = re.sub(r"[^a-z0-9]+", "", surface_name.lower())

            # embed the *surface* (semantic) name
            vector = self.embedder.encode(surface_name)
            query_filter = {
                "must": [
                    {"key": "entity_type", "match": {"value": ent_type}}
                ]
            }
            results = search_collection(collection_name=collection_name,
                                        query_vector=vector,
                                        limit=1,
                                        query_filter=query_filter,
                                        with_payload=True,
                                        with_vectors=True
                                        )


            if results and results[0].score > 0.85:
                hit = results[0]
                payload = hit.payload or {}

                # Existing point: update alias/description history in Qdrant
                point_id = hit.id

                existing_aliases = payload.get("aliases") or []
                existing_descs = payload.get("descriptions") or []

                # ensure lists
                if isinstance(existing_aliases, str):
                    existing_aliases = [existing_aliases]
                if isinstance(existing_descs, str):
                    existing_descs = [existing_descs]

                if surface_name not in existing_aliases:
                    existing_aliases.append(surface_name)
                if desc and desc not in existing_descs:
                    existing_descs.append(desc)

                canonical_name = payload.get("canonical_name") or surface_name
                final_normalized = payload.get("normalized_name") or normalized_name

                stored_vector = hit.vector or vector

                # write back the updated alias/description lists
                metadata = {
                    "canonical_name": canonical_name,
                    "normalized_name": final_normalized,
                    "entity_type": ent_type,
                    "aliases": existing_aliases,
                    "descriptions": existing_descs,
                }

                upsert_embedding(
                    vector=stored_vector,
                    metadata=metadata,
                    collection=collection_name,
                    point_id=point_id,  # if you already have one and want to preserve it
                )
                final_canonical = canonical_name

            else:
                # No good match: create a new point with initial history
                normalized_ent_type = self.normalize_type(ent_type)
                composite_key = f"{normalized_name}::{normalized_ent_type}"
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, composite_key))

                aliases = [surface_name]
                descriptions = [desc] if desc else []

                metadata = {
                    "canonical_name": surface_name,
                    "normalized_name": normalized_name,
                    "entity_type": ent_type,
                    "aliases": aliases,
                    "descriptions": descriptions,
                }

                upsert_embedding(
                    vector=vector,
                    metadata=metadata,
                    collection=collection_name,
                    point_id=point_id,  # if you already have one and want to preserve it
                )
                final_normalized = normalized_name
                final_canonical = surface_name

            normalized_entities.append({
                "entity_name": final_normalized,  # Memgraph key
                "canonical_name": final_canonical,  # human-readable
                "entity_type": ent_type,
                "entity_description": desc,  # latest surface description
                "appears_in": e.get("appears_in", []),
            })

        return normalized_entities

    # </editor-fold>

    # === The main methods called by the per-message Graph indexing process. Each calls the next.
    # <editor-fold desc="Core Methods">

    def index_messages_with_buffer(self, messages=None, start_date=None, end_date=None, flush_at_end=True):
        """
        Buffer-aware indexing:
          - In batch mode: accept a date range, fetch messages, flush at end.
          - In live mode: accept explicit messages (usually 1), do NOT flush at end.
        """
        convo_col = self.mongo.db[MONGO_CONVERSATION_COLLECTION]
        buffer_col = self.mongo.db["mnemosyne_buffer"]

        # Resolve messages source
        if messages is None:
            if start_date is None or end_date is None:
                raise ValueError("Either messages or (start_date, end_date) must be provided.")
            messages = self.get_messages_for_indexing(convo_col, date_range=[start_date, end_date])

        print(f"[BUFFER] Found {len(messages)} messages to process")
        if not messages:
            return

        model = SentenceTransformer("sentence-transformers/paraphrase-MiniLM-L3-v2", local_files_only=True)

        # Seed previous_emb from the existing buffer, if any
        active_doc = buffer_col.find_one({"flushed": False}, {"messages": 1}) or {"messages": []}
        existing_messages = active_doc.get("messages", [])
        previous_emb = None
        if existing_messages:
            last_emb = existing_messages[-1].get("embedding")
            if last_emb is not None:
                previous_emb = torch.tensor(last_emb)

        for msg in messages:
            text = msg.get("message", "")
            cfg = get_text_filter_config("MNEMOSYNE", "EMBEDDING", "DEFAULT")
            filtered = filter_text(text, cfg)
            emb = model.encode(filtered, convert_to_tensor=True, show_progress_bar=False)

            msg_record = {
                "message_id": msg["message_id"],
                "role": msg.get("role", "user"),
                "message": text,
                "embedding": emb.tolist(),
                "created_at": datetime.utcnow()
            }

            # Drift-based flush: compare against previous message in the episode
            if previous_emb is not None:
                sim = util.cos_sim(previous_emb, emb).item()
                active_doc = buffer_col.find_one({"flushed": False}, {"messages": 1}) or {"messages": []}
                if sim < 0.25 and len(active_doc.get("messages", [])) >= 5:
                    self.flush_buffer(buffer_col)
                    # After flush, reset previous_emb; we’re starting a new episode
                    previous_emb = None

            # Append to current buffer (or create a new one)
            buffer_col.update_one(
                {"flushed": False},
                {
                    "$push": {"messages": msg_record},
                    "$setOnInsert": {"created_at": datetime.utcnow(), "flushed": False}
                },
                upsert=True
            )

            # Hard cap on episode length
            active_doc = buffer_col.find_one({"flushed": False}, {"messages": 1})
            if active_doc and len(active_doc.get("messages", [])) >= 12:
                self.flush_buffer(buffer_col)
                previous_emb = None  # new episode after flush

            # Update anchor for next comparison
            previous_emb = emb

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        # Only force a final flush in batch mode
        if flush_at_end:
            self.flush_buffer(buffer_col)

    def flush_buffer(self, buffer_col):
        """Seal the current unflushed buffer, process through Mnemosyne, and mark it flushed."""
        active_doc = buffer_col.find_one({"flushed": False})
        if not active_doc or not active_doc.get("messages"):
            return

        def sanitize_entities(entities):
            for e in entities:
                e.pop("appears_in", None)
            return entities

        prior_entities = sanitize_entities(active_doc.get("prior_entities", []))
        prior_relationships = active_doc.get("prior_relationships", [])

        print(f"[BUFFER] Flushing {len(active_doc['messages'])} messages...")

        prior_block = {
            "entities": prior_entities,
            "relationships": prior_relationships
        }

        message_blocks = []
        for m in active_doc["messages"]:
            raw_text = m.get("message", "")
            cfg = get_text_filter_config("MNEMOSYNE", "PROMPT", "DEFAULT")
            filtered = filter_text(raw_text, cfg).strip()

            block = (
                f"=== MESSAGE {m['message_id']} ===\n"
                f"role: {m.get('role', 'user')}\n"
                f"text: {filtered}\n"
            )
            message_blocks.append(block)

        mnemosyne_input = (
                "#### PRIOR_ENTITY_LIST\n"
                f"{json.dumps(prior_block, indent=2)}\n\n"
                "#### MESSAGES\n" + "\n".join(message_blocks)
        )

        t0 = time.time()
        try:
            print("  ⏳ Sending to Mnemosyne...")
            mnemosyne_output = self.safe_run_mnemosyne({"message": mnemosyne_input})
            print(f"  🕒 Mnemosyne returned in {time.time() - t0:.2f}s")
        except Exception as e:
            print(f"  ⚠️ Mnemosyne error after {time.time() - t0:.2f}s: {e}")
            mnemosyne_output = None

        update_fields = {
            "flushed": True,
            "flushed_at": datetime.utcnow(),
            "mnemosyne_input": mnemosyne_input
        }

        # --- Normalize mnemosyne_output into a dict (raw) ---
        if isinstance(mnemosyne_output, str):
            try:
                mnemosyne_output_dict = json.loads(mnemosyne_output)
            except json.JSONDecodeError:
                print("  ⚠️ Mnemosyne returned non‑JSON string; skipping reconciliation/ingest.")
                mnemosyne_output_dict = {}
        elif isinstance(mnemosyne_output, dict):
            mnemosyne_output_dict = mnemosyne_output
        else:
            mnemosyne_output_dict = {}

        # Persist the *raw* output text first (for provenance / debugging)
        if mnemosyne_output_dict:
            update_fields["mnemosyne_output_text"] = json.dumps(
                mnemosyne_output_dict, indent=2, ensure_ascii=False
            )

        # --- 1) Mark old buffer flushed with raw output ---
        buffer_col.update_one({"_id": active_doc["_id"]}, {"$set": update_fields})

        # --- 2) Immediately create new buffer for live conversation (hot path) ---
        new_entities_raw = mnemosyne_output_dict.get("entities", [])
        new_relationships_raw = mnemosyne_output_dict.get("relationships", [])

        buffer_col.insert_one({
            "created_at": datetime.utcnow(),
            "flushed": False,
            "messages": [],
            "prior_entities": new_entities_raw,
            "prior_relationships": new_relationships_raw
        })

        print(f"[BUFFER] Flushed buffer {active_doc['_id']} ✅ (new buffer ready)")

        # If we have no structured output, bail before slow path
        if not mnemosyne_output_dict:
            return

        # --- 3) Slow path: reconcile entities + ingest episode (can be async later) ---

        # 3a) Reconcile entities with Qdrant
        if mnemosyne_output_dict.get("entities"):
            reconciled_entities = self.reconcile_entities_with_qdrant(
                mnemosyne_output_dict["entities"]
            )
            mnemosyne_output_dict["entities"] = reconciled_entities

            # Update the old buffer doc with *reconciled* output for recordkeeping
            buffer_col.update_one(
                {"_id": active_doc["_id"]},
                {"$set": {
                    "mnemosyne_output_text": json.dumps(
                        mnemosyne_output_dict, indent=2, ensure_ascii=False
                    )
                }}
            )

        # 3b) Build episode_doc from real conversation messages
        convo_col = self.mongo.db[MONGO_CONVERSATION_COLLECTION]
        message_ids = [m["message_id"] for m in active_doc["messages"]]

        messages = list(convo_col.find({"message_id": {"$in": message_ids}}))

        # Preserve buffer order
        msg_index = {m_id: i for i, m_id in enumerate(message_ids)}
        messages.sort(key=lambda m: msg_index.get(m["message_id"], 0))

        episode_doc = {
            "messages": messages,
            "mnemosyne_output_text": json.dumps(
                mnemosyne_output_dict, indent=2, ensure_ascii=False
            ),
        }

        # 3c) Ingest into Memgraph
        try:
            self.ingest_episode(episode_doc)
        except Exception as e:
            print(f"  ⚠️ Error during ingest_episode: {e}")
        else:
            # 3d) Mark messages as graphed
            try:
                graphed_on = datetime.utcnow()
                convo_col.update_many(
                    {"message_id": {"$in": message_ids}},
                    {"$set": {"graphed_on": graphed_on}},
                )
            except Exception as e:
                print(f"  ⚠️ Error updating graphed_on on messages: {e}")


    # === Graph Ingestion ===
    def ingest_episode(self, episode_doc):
        """
        Insert a fully analyzed conversation episode into Memgraph.
        Creates or updates all message, timestamp, speaker, entity, and relationship nodes.
        Expects a doc like:
            {
              "messages": [ {...}, {...}, ... ],
              "mnemosyne_output_text": "<json string>"
            }
        """
        try:
            graph = self.graph
            mnemosyne_output = json.loads(episode_doc["mnemosyne_output_text"])
            entities = mnemosyne_output.get("entities", [])
            relationships = mnemosyne_output.get("relationships", [])
            messages = episode_doc["messages"]

            # === 1. Create message & timestamp nodes ===
            for msg in messages:
                msg_id = msg["message_id"]
                t = str(msg["timestamp"])
                role = msg["role"]
                project = str(msg.get("project_id")) if msg.get("project_id") else None
                author_name = self._resolve_author_name(msg)

                params = {
                    "m": msg_id,
                    "t": t,
                    "role": role,
                    "source": msg.get("source"),
                    "author_name": author_name,
                    "project": project,
                    "is_hidden": msg.get("is_hidden", False),
                    "is_private": msg.get("is_private", False),
                    "is_deleted": msg.get("is_deleted", False),
                    "remembered": msg.get("remembered", False),
                }

                # --- Message node ---
                graph.run_cypher("""
                    MERGE (m:Message {message_id: $m})
                    SET m += {
                        timestamp: $t,
                        role: $role,
                        source: $source,
                        author_name: $author_name,
                        project_id: $project,
                        is_hidden: $is_hidden,
                        is_private: $is_private,
                        is_deleted: $is_deleted,
                        remembered: $remembered
                    }
                """, params)

                # --- Timestamp node ---
                graph.run_cypher("""
                    MERGE (ts:Timestamp {value: $t})
                    SET ts.last_seen = $t
                    WITH ts
                    MATCH (m:Message {message_id: $m})
                    MERGE (m)-[:OCCURRED_AT]->(ts)
                """, params)

                # --- Speaker node ---
                label = "Companion" if role == "muse" else "Person"
                speaker_params = {
                    "name": author_name,
                    "t": t,
                    "role": role,
                    "source": msg.get("source"),
                    "m": msg_id
                }
                graph.run_cypher(f"""
                    MERGE (p:{label} {{name: $name}})
                    SET p.last_seen = $t
                    WITH p
                    MATCH (m:Message {{message_id: $m}})
                    MERGE (p)-[:SPOKE_IN {{role: $role, source: $source}}]->(m)
                """, speaker_params)

            # === 2. Create / merge entities (excluding structural) ===
            for e in entities:
                if e["entity_name"] in ("User", "Muse", "Friend"):
                    continue

                raw_label = e.get("entity_type", "Entity") or "Entity"
                label = ''.join(word.capitalize() for word in raw_label.split('_')) or "Entity"

                ent_params = {
                    # Qdrant’s normalized key
                    "name": e["entity_name"],
                    # Qdrant’s current best human-readable name
                    "canonical_name": e.get("canonical_name", e["entity_name"]),
                    # latest description from this episode
                    "desc": e.get("entity_description", "") or "",
                }

                cypher = f"""
                    MERGE (ent:{label} {{name: $name}})
                    ON CREATE SET
                        ent.first_seen = timestamp(),
                        ent.canonical_name = $canonical_name,
                        ent.description = $desc
                    ON MATCH SET
                        ent.last_seen = timestamp(),
                        ent.canonical_name = $canonical_name,
                        ent.description = CASE
                            WHEN $desc <> '' THEN $desc
                            ELSE ent.description
                        END
                """
                graph.run_cypher(cypher, ent_params)

            # === 3. Link entities to messages ===
            for e in entities:
                if e["entity_name"] in ("User", "Muse", "Friend"):
                    continue

                raw_label = e.get("entity_type", "Entity") or "Entity"
                label = ''.join(word.capitalize() for word in raw_label.split('_')) or "Entity"

                for mid in e.get("appears_in", []):
                    cypher = f"""
                        MATCH (m:Message {{message_id: $mid}})
                        MATCH (ent:{label} {{name: $ename}})
                        MERGE (ent)-[:MENTIONED_IN]->(m)
                    """
                    graph.run_cypher(cypher, {
                        "mid": mid,
                        "ename": e["entity_name"],
                    })

            # === 4. Link relationships between entities ===
            for r in relationships:
                if not r.get("source_entity") or not r.get("target_entity"):
                    continue

                rel_type = self.normalize_type(
                    r.get("relationship_type", "RELATED_TO")
                )
                rel_params = {
                    "src": r["source_entity"],
                    "tgt": r["target_entity"],
                    "rdesc": r.get("relationship_description"),
                    "strength": r.get("strength"),
                }

                cypher = f"""
                    MATCH (a {{name: $src}}), (b {{name: $tgt}})
                    MERGE (a)-[rel:{rel_type}]->(b)
                    SET rel.description = $rdesc,
                        rel.strength = $strength,
                        rel.last_seen = timestamp()
                """
                graph.run_cypher(cypher, rel_params)

            return True

        except Exception as e:
            print(f"⚠️ Ingest failed for episode {episode_doc.get('_id')}: {e}")
            traceback.print_exc()
            return False

    # </editor-fold>

    # === Methods for updating Graph message nodes as metadata is updated ===
    # <editor-fold desc="Update Methods">
    # === Metadata Updates ===
    def update_graph_for_message(self, msg, collection):
        """
        Update or create graph entries for a given message.
        """
        if not msg.get("graphed"):
            self.run_mnemosyne_for_message(msg)
            collection.update_one(
                {"_id": msg["_id"]},
                {"$set": {"graphed": True, "last_graphed": datetime.now()}}
            )
        else:
            # sync only metadata/flags
            collection.update_one(
                {"_id": msg["_id"]},
                {"$set": {"last_graphed": datetime.now()}}
            )
    # </editor-fold>

    # === Old methods used during development. Can be deleted later. ===
    # <editor-fold desc="Deprecated Methods">
    def index_messages_by_date(self, start_date, end_date):
        """
        Full pipeline: fetch messages within a date range,
        run Mnemosyne analysis, reconcile entities with Qdrant,
        and ingest results into Memgraph.
        """
        collection = self.mongo.db[MONGO_CONVERSATION_COLLECTION]
        date_range = [start_date, end_date]

        messages = self.get_messages_for_indexing(collection, date_range=date_range)
        print(f"Found {len(messages)} messages between {start_date} and {end_date}")

        for msg in messages:
            try:
                mnemosyne_output = self.safe_run_mnemosyne(msg)
                if not mnemosyne_output:
                    continue

                # Attach Mnemosyne output to the message before reconciliation
                msg["mnemosyne_output"] = mnemosyne_output

                # Normalize entities in Qdrant
                reconciled = self.reconcile_entities_with_qdrant(msg)
                if not reconciled:
                    print(f"  ⚠️ Empty reconciliation for {msg.get('_id')} — skipping.")
                    continue

                msg["mnemosyne_output"] = reconciled
                self.ingest_to_memgraph(msg)

                collection.update_one(
                    {"_id": msg["_id"]},
                    {"$set": {"graphed": True, "last_graphed": datetime.now()}}
                )

            except Exception as e:
                print(f"Error indexing message {msg.get('_id')}: {e}")

    def ingest_to_memgraph(self, msg):
        """
        Insert a fully analyzed message into Memgraph.
        Creates or updates message, entities, and relationships.
        """
        graph = self.graph
        m = msg["message_id"]
        t = str(msg["timestamp"])
        role = msg["role"]
        project = str(msg.get("project_id")) if msg.get("project_id") else None
        author_name = self._resolve_author_name(msg)

        params = {
            "m": m,
            "t": t,
            "role": role,
            "source": msg.get("source"),
            "author_name": author_name,
            "project": project,
            "is_hidden": msg.get("is_hidden", False),
            "is_private": msg.get("is_private", False),
            "is_deleted": msg.get("is_deleted", False),
            "remembered": msg.get("remembered", False),
        }

        # --- Message node ---
        graph.run_cypher("""
            MERGE (m:Message {message_id: $m})
            SET m += {
                timestamp: $t,
                role: $role,
                source: $source,
                author_name: $author_name,
                project_id: $project,
                is_hidden: $is_hidden,
                is_private: $is_private,
                is_deleted: $is_deleted,
                remembered: $remembered
            }
        """, params)

        # --- Timestamp node ---
        graph.run_cypher("""
            MERGE (ts:Timestamp {value: $t})
            SET ts.last_seen = $t
            WITH ts
            MATCH (m:Message {message_id: $m})
            MERGE (m)-[:OCCURRED_AT]->(ts)
        """, params)

        # --- Author node ---
        graph.run_cypher("""
            MERGE (p:Person {name: $author_name})
            SET p.last_seen = $t
            WITH p
            MATCH (m:Message {message_id: $m})
            MERGE (p)-[:SPOKE_IN {role: $role, source: $source}]->(m)
        """, params)

        # --- Entities from Mnemosyne ---
        for e in msg["mnemosyne_output"]["entities"]:
            # Normalize label casing (e.g., "time_expression" → "TimeExpression")
            raw_label = e.get("entity_type", "Entity")
            label = ''.join(word.capitalize() for word in raw_label.split('_')) or "Entity"

            ent_params = {
                "name": e["entity_name"],
                "canonical_name": e["canonical_name"],
                "desc": e["entity_description"],
                "t": t,
                "m": m,
            }

            cypher = f"""
                MERGE (ent:{label} {{name: $name}})
                ON CREATE SET
                    ent.first_seen = $t,
                    ent.canonical_names = [$canonical_name],
                    ent.descriptions = [$desc]
                ON MATCH SET
                    ent.last_seen = $t,
                    ent.canonical_names = coalesce(ent.canonical_names, []) + $canonical_name,
                    ent.descriptions = coalesce(ent.descriptions, []) + $desc
                WITH ent
                MATCH (m:Message {{message_id: $m}})
                MERGE (m)-[:MENTIONS {{last_seen: $t}}]->(ent)
            """
            graph.run_cypher(cypher, ent_params)

        # --- Relationships between entities ---
        for r in msg["mnemosyne_output"].get("relationships", []):
            rel_type = (r.get("relationship_type") or "RELATION").upper()
            rel_type = self.normalize_type(rel_type)
            rel_params = {
                "src": r["source_entity"],
                "tgt": r["target_entity"],
                "rdesc": r.get("relationship_description"),
                "strength": r.get("strength"),
                "t": t,
            }

            cypher = f"""
                MATCH (a {{name: $src}}), (b {{name: $tgt}})
                MERGE (a)-[rel:{rel_type}]->(b)
                SET rel.description = $rdesc,
                    rel.strength = $strength,
                    rel.last_seen = $t
            """
            graph.run_cypher(cypher, rel_params)


    # </editor-fold>