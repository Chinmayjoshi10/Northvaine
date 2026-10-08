# Connect the dots: graph storage, frameworks, temporal model, NVIDIA, entity resolution, visuals

Date checked: 2026-10-09. Researcher note (docs/FACTORY.md rule 7). No secrets in this file.
Tags: **C** = confirmed in docs/primary source, **I** = inferred, **U** = unknown (command given to confirm).
"Fetched summary" means the page was read through a summarising fetch tool, not copied verbatim.

## 1. Summary and recommendation

- **Stay in Postgres for v0 and v1.** Neon does not list Apache AGE, so no Cypher in Postgres. Plain edge
  table plus recursive CTEs (with the built-in `CYCLE` clause) is enough for 2 to 4 hop chains over the
  data volume of a hackathon, keeps provenance in the same transaction as `claims`, and adds no new
  service. Neon lists `ltree`, `pg_trgm`, `unaccent`, `fuzzystrmatch`, `pgrouting`, `pg_graphql`.
- **Do not adopt a graph framework (GraphRAG, LightRAG, PropertyGraphIndex, Graphiti, Cognee) in v0.** They
  extract edges with an LLM straight from text and would bypass our ledger (rule 2: code verifies the
  quote before anything is used). Most also need a graph server we do not run. Steal one idea only:
  Graphiti's bi-temporal edges (valid time vs recorded time) and "every edge traces to episodes".
- **Kuzu is dead as an option**: its repo was archived 10 Oct 2025.
- **Graph server (Neo4j/Memgraph/FalkorDB) only if v1 needs real graph algorithms at scale.** Not before the
  hackathon.
- **NVIDIA graph tech (cuGraph/nx-cugraph) is not worth it** for the hackathon: Linux plus NVIDIA GPU only,
  and our graph is small. The "built with NVIDIA" story is Nemotron on Token Factory, already in place.
- **Visuals:** hero = `react-force-graph-2d` (canvas, MIT, about 60 KB gzip, has `dagMode`, directional
  particles, `nodeVisibility`). Large explorer later = Sigma.js v3 + graphology (WebGL, MIT).

## 2. Facts table

| # | Fact | Source | Tag |
|---|---|---|---|
| S1 | Neon's extension page does not list Apache AGE. It lists `ltree` (1.2 on PG14-16, 1.3 on 17-18), `pg_trgm` 1.6, `unaccent` 1.1, `fuzzystrmatch` 1.1 (PG14-15) or 1.2 (PG16+), `pgrouting` (needs PostGIS), `pg_graphql`. | https://neon.com/docs/extensions/pg-extensions (fetched summary) | C (absence on the page as fetched; confirm live: `SELECT * FROM pg_available_extensions WHERE name='age';` on the Neon branch, expect 0 rows) |
| S2 | Apache AGE = PostgreSQL extension giving openCypher and SQL over one storage layer. Supported PG versions and licence were not on the fetched page. | https://age.apache.org/age-manual/master/intro/overview.html | C for what it is; U for versions/licence |
| S3 | Nebius Managed PG ships only pgvector 0.8 and pgcrypto; no other extensions can be installed, so AGE is impossible there too. | docs/integrations/postgres-hosting.md (N2-N4) | C |
| S4 | Postgres recursive CTEs: built-in `SEARCH DEPTH/BREADTH FIRST` and `CYCLE col SET is_cycle USING path` (PG14+). `LIMIT` stopping recursion must not be relied on. | https://www.postgresql.org/docs/16/queries-with.html | C |
| S5 | Kuzu repo "was archived by the owner on Oct 10, 2025. It is now read-only." MIT licence. README says the team is "working on something new". Latest release v0.11.3. Community forks exist (e.g. LadybugDB, via a third-party blog). | https://github.com/kuzudb/kuzu (fetched summary); https://www.puppygraph.com/blog/what-is-kuzudb (blog, last resort) | C for archived; blog-only for the acquirer and forks |
| S6 | Neo4j AuraDB Professional starts at $0.09 per GB per hour, 1 GB minimum; paused paid instances cost about 20 percent. Free-tier node/relationship caps are not on the pricing page. | https://neo4j.com/pricing/ ; https://neo4j.com/blog/auradb/pause-neo4j-aura-instance-save-80-percent/ | C for price; U for free caps |
| S7 | AuraDB Free auto-pauses after 72 hours without writes; no manual pause; secondary sources say 30 days (or 90) paused before deletion and 200k nodes / 400k relationships. | web search results quoting Neo4j support text; third-party tracker | **third-party, unverified**. Confirm in the Aura console or https://neo4j.com/docs/aura/ |
| S8 | FalkorDB is a Redis module, openCypher-compatible, licence **SSPLv1**; hosted "Try Free" exists, limits unknown. | https://github.com/FalkorDB/FalkorDB | C licence; U cloud limits |
| S9 | Memgraph Community is **BSL**, Enterprise is MEL; in-memory engine; markets "Atomic GraphRAG" and an MCP server; cloud free tier not stated on the repo page. | https://github.com/memgraph/memgraph | C licence; U cloud pricing |
| S10 | Neon Free: 1 GB per project, 100 CU-hours per month, scale to zero after 5 min. | docs/integrations/postgres-hosting.md (E3) | C |
| F1 | Graphiti (Apache-2.0) backends: Neo4j 5.26, FalkorDB 1.1.2, Amazon Neptune (+OpenSearch); Kuzu 0.11.2 listed but deprecated. **No Postgres.** | https://github.com/getzep/graphiti | C |
| F2 | Graphiti works with OpenAI-compatible endpoints via `OpenAIGenericClient`; structured output mode `json_schema` (default) or `json_object`; warns smaller models can break ingestion. | same | C |
| F3 | Graphiti: bi-temporal edges, outdated facts invalidated not deleted, every entity/edge traces back to source episodes. Field names (valid_at etc.) not confirmed on the pages read. | same; https://help.getzep.com/graphiti/getting-started/overview | C concept; U field names |
| F4 | Microsoft GraphRAG: MIT, **maintenance mode** (no new features), indexing "can be an expensive operation". Uses LiteLLM; model must support JSON-schema structured output; proxied models often return malformed JSON; built and tested mainly on GPT-4 series. | https://github.com/microsoft/graphrag ; https://microsoft.github.io/graphrag/config/models/ | C |
| F5 | LightRAG: MIT; PostgreSQL can serve all four storage types (KV, vector, graph, doc status); caps source chunks/files per entity or relation (`MAX_SOURCE_IDS_PER_RELATION`, `MAX_FILE_PATHS`); citation support added March 2025. OpenAI-compatible phrase not on the page read. | https://github.com/HKUDS/LightRAG | C; U on exact OpenAI-compatible config |
| F6 | LlamaIndex PropertyGraphIndex: extractors take any `llm`; stores: Simple (in-memory), Neo4j, Nebula, TiDB, FalkorDB. **No Postgres graph store.** Chunks stored as nodes linked by `HAS_SOURCE`. | https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/ | C |
| F7 | Cognee: Apache-2.0; Postgres/pgvector documented, but "Using Postgres as a graph store is currently released as a demo feature"; production version is a licensed product. No temporal features described. | https://github.com/topoteretes/cognee | C |
| F8 | Neo4j LLM Graph Builder: not researched in this pass (needs a Neo4j server and its own LLM wiring). | n/a | U |
| N1 | nx-cugraph: Apache-2.0; NVIDIA Volta+ (compute capability 7.0+), CUDA 12.2+, Python 3.11-3.13, **Linux only**; enabled by `NX_CUGRAPH_AUTOCONFIG=True` or `backend="cugraph"`. | https://github.com/rapidsai/nx-cugraph (fetched summary); https://docs.rapids.ai/api/cugraph/stable/nx_cugraph/installation | C |
| N2 | NVIDIA's RAG blueprint (NeMo Retriever, Nemotron, Elasticsearch/Milvus) has no graph component. An older cuGraph + NetworkX + Milvus knowledge-graph RAG sample exists in GenerativeAIExamples (a PR), dated, uses Nemotron-4 340B for synthetic data. | https://github.com/NVIDIA-AI-Blueprints/rag ; https://github.com/NVIDIA/GenerativeAIExamples/pull/144 | C for absence in the blueprint; sample is old |
| N3 | Nebius GPU VMs exist (H100, H200, L40S, B200) but "availability depends on region and project". Whether Serverless Jobs can run a GPU container for us: not checked. | https://docs.nebius.com/compute/virtual-machines/types | C for list; U for Serverless GPU |
| E1 | GLEIF API supports fuzzy name matching and parent/child relationship search. Rate limit, key requirement and data licence were not readable in the pages fetched. | https://www.gleif.org/en/lei-data/gleif-api ; https://api.gleif.org/docs (redirects to a Postman doc) | C for features; U for limits/licence. Confirm: `curl -s "https://api.gleif.org/api/v1/fuzzycompletions?field=entity.legalName&q=siemens"` and read the response headers |
| E2 | Neon has `pg_trgm`, `unaccent`, `fuzzystrmatch`, and pgvector 0.8.0 (PG14-17), which we already use for embedding similarity. | S1 above; docs/integrations/postgres-hosting.md E2 | C |
| V1 | react-force-graph: MIT; 2D = canvas (`force-graph`), 3D = ThreeJS/WebGL; props `linkDirectionalParticles`, `emitParticle`, `dagMode` (acyclic only), `nodeVisibility`, `pauseAnimation`, `autoPauseRedraw`. No benchmarks given. | https://github.com/vasturiano/react-force-graph | C |
| V2 | Sigma.js: MIT; WebGL; built on graphology; aimed at "thousands of nodes and edges" (project's wording, no benchmark). | https://github.com/jacomyal/sigma.js | C; 50k-node performance is **I** |
| V3 | Cytoscape.js: MIT; optional renderer (canvas/WebGL not stated on the page read). | https://github.com/cytoscape/cytoscape.js | C licence; U renderer detail |
| V4 | Reagraph: Apache-2.0; WebGL for React; layouts incl. force, tree, radial; path finding, clustering, edge bundling. Releases not shown. | https://github.com/reaviz/reagraph | C |
| V5 | cosmos.gl: MIT; GPU force layout and rendering in WebGL 2 (luma.gl); "hundreds of thousands of points and links on modern hardware" (project claim); no React wrapper on the page; known gaps on some iOS and Android devices. **Cosmograph (the product/library) licence not found** (the cosmograph repo URL returned 404; the site shows a Pricing page). | https://github.com/cosmograph-org/cosmos ; https://cosmograph.app/ | C for cosmos.gl; **U for Cosmograph commercial use** |
| V6 | Bundle sizes (minified, gzip) from bundlephobia API: sigma 3.0.2 = 96 KB (25.8 KB gzip); graphology 0.25.4 = 73 KB (14 KB gzip); react-force-graph-2d 1.29.0 = 186 KB (60.5 KB gzip); cytoscape 3.30.0 = 372 KB (117 KB gzip). reagraph, deck.gl, cosmos.gl not measured (reagraph pulls three.js: **I**, large). | https://bundlephobia.com/api/size?package=... | C for the numbers; versions may not be the latest |
| V7 | deck.gl and D3-force were not fetched. D3-force is a layout-only library (no renderer): **I** from general knowledge. | n/a | I/U |

## 3. Storage options judged for our case

| Option | Cost | Ops burden | 3-week fit | Scale later | Verdict |
|---|---|---|---|---|---|
| Postgres edge table + recursive CTE (Neon) | $0 extra | none, same DB, same migrations, same Neon branches for tests | Best: 1 to 2 sessions | Fine to millions of edges for 2-4 hop queries with indexes; deep multi-hop analytics gets slow (**I**) | **v0 and v1** |
| Apache AGE | n/a | cannot be installed on Neon (S1) or Nebius Managed PG (S3) | Blocked | Would need self-hosted Postgres | Reject |
| Kuzu (embedded) | free | archived (S5), no maintained upstream; forks unvetted | Risky | Dead end | Reject |
| Neo4j AuraDB Free/Pro | Free (caps and pause rules unconfirmed, S7); Pro from $0.09/GB-h (S6) | second store to sync; provenance rule enforcement must be rebuilt; auto-pause on Free would break a live demo | Possible, but costs a session of sync code | Strongest ecosystem and Graphiti/PropertyGraphIndex both support it | v1 candidate only if algorithms demand it |
| Memgraph | BSL community; cloud pricing unknown | in-memory, a service to run | Same as Neo4j | Good | Later |
| FalkorDB | SSPL licence (check legal fit for an open-source repo); cloud limits unknown | Redis-style service | Same | Good, small footprint | Later |

Postgres stays the single source of truth for provenance. If a graph server is ever added, treat it as a
rebuildable read-model projected from Postgres (never the system of record).

## 4. Frameworks: fit with Nebius (OpenAI-compatible) and per-edge provenance

| Framework | Works with OpenAI-compatible endpoint | Per-edge provenance | Graph store | Fit |
|---|---|---|---|---|
| GraphRAG | via LiteLLM; needs reliable JSON-schema output; custom `api_base` not documented on the page read (U); maintenance mode (F4) | text units (U, not read) | parquet files | No |
| LightRAG | likely (U) | caps list of source chunks/files per relation (F5) | can use Postgres alone (F5) | Closest to our stack, but extracts without our code quote check; use only as inspiration |
| PropertyGraphIndex | yes, pass any `llm` (F6) | `HAS_SOURCE` chunk links (F6) | no Postgres store | No |
| Graphiti | yes via `OpenAIGenericClient` (F2) | episodes per edge (F3) | Neo4j/FalkorDB/Neptune only (F1) | No for v0; best temporal model to copy |
| Cognee | custom endpoint not documented on the page read | document metadata on chunks | Postgres graph = demo (F7) | No |
| Neo4j LLM Graph Builder | U | U | Neo4j | No |

Why not for us (inferred, from rules 2, 3 and 7): every framework lets the LLM assert edges from raw text.
Our rule is that a link exists only if a verified claim (quote found in the document by code) supports it.
We already extract claims and events with Nemotron through `northvaine/brain/llm.py`; the graph should be
built from those rows by code, not extracted again by a framework. Dependencies on our Nemotron models
returning perfect JSON are also a known risk in F2/F4.

## 5. Graph v0 (1 to 2 sessions, on current Postgres)

### 5.1 Model

Nodes are not a new copy of the world. They are existing rows, addressed by (kind, id):

| Node kind | Table | Notes |
|---|---|---|
| `company` | `companies` | buyers, sellers, contractors, authorities |
| `event` | `events` | tender_published, contract_awarded, facility_opened, hiring_surge ... (generic `event_type` / `event_concepts`) |
| `procedure` | derived from `documents.group_key` (e.g. TED procedure id) | a project/tender as one node grouping its notices; optional in v0 (can be an `events` cluster via `cluster_id`) |
| `document` | `documents` | only as evidence, drawn as a small satellite on click, not a main node |

Edges: one new table (name suggested `links`; schema.sql is canonical so this needs a ticket and a migration):

```
links(
  id uuid pk,
  workspace_id uuid null,            -- null = shared/public layer
  src_kind text, src_id uuid,        -- company | event
  dst_kind text, dst_id uuid,
  rel text,                          -- generic relation label from a data vocabulary, not hardcoded
  derivation text check in ('stated','related','inferred'),   -- same labels as D84
  claim_ids uuid[] not null,         -- verified claims that support it; never empty
  valid_from date, valid_to date,    -- when the relation held in the world (valid time)
  recorded_at timestamptz,           -- when we learned it (document available_at)
  confidence real,                   -- for inferred links only
  fingerprint text unique            -- idempotent, like events/claims
)
index (src_kind, src_id, rel), (dst_kind, dst_id, rel), (valid_from)
```

Rules that keep it inside the non-negotiables:
1. **No source, no link.** A DB check (or insert path) requires `claim_ids` non-empty and every id in
   `verified_claims`. The existing view `verified_claims` is the only read path.
2. **Stated vs inferred.** `stated` = one document says it (award notice names winner). `related` = same
   `group_key`/cluster. `inferred` = our pattern (this award type usually leads to purchases); its
   `claim_ids` are the premises and the UI draws it dashed with the label "inferred". Inferred links never
   count as evidence in a case.
3. **Relation vocabulary is data**, same pattern as `event_concepts` (labels like `awarded_to`,
   `funded_by`, `follows`, `subcontracts_to`, `supplies`), proposed by the model, approved by code rules.
   No industry words in code. Industry words appear only in data rows.
4. **Edge provenance is the array**: click an edge to get claims, then `documents.url`, then `source_quote`.
5. **Privacy**: edges from private documents (`documents.workspace_id` not null) carry that workspace id and are
   never returned to others (same rule as claims).

How edges get built (all code, no LLM at query time):
- `event` to `company` edges come for free from `events.company_id` (the "subject").
- `follows` between events of one procedure: same `documents.group_key` (already used by D81 for TED), ordered
  by `occurred_on`. Stage order (plan, funding, tender, award) comes from `event_concepts`.
- `awarded_to`: from structured award records (already code-verified in D81 bidders path).
- `supplies`/`buys_from` between companies: only from a claim that says so (statement + quote); otherwise
  nothing. The LLM may propose the claim; the code check decides.

### 5.2 Example queries (SQL sketches, design only)

1. **Who will buy after this award?** Start from the award event, hop to the winner company, then to
   "downstream" edges and to historical analogues:

```sql
-- (a) stated chain from an award
WITH RECURSIVE chain AS (
  SELECT l.dst_kind, l.dst_id, l.rel, 1 AS depth, ARRAY[l.id] AS via
  FROM links l WHERE l.src_kind='event' AND l.src_id = :award_event
  UNION ALL
  SELECT l.dst_kind, l.dst_id, l.rel, c.depth+1, c.via || l.id
  FROM links l JOIN chain c ON l.src_kind=c.dst_kind AND l.src_id=c.dst_id
  WHERE c.depth < 3 AND l.derivation <> 'inferred'
) CYCLE dst_id SET is_cycle USING path
SELECT * FROM chain WHERE NOT is_cycle;

-- (b) inferred: companies that, after similar awards (same concept), later showed a purchase event
--     within N months. Base rate = count(follow-ups) / count(awards) from events + links; store the
--     result as a `beliefs` row (learner 'world'), create `expectations` rows with window_start/end.
```

2. **Chain trace for the UI** (hero): all links within 3 hops of a case's company, joined to claims and
   documents, ordered by `valid_from`; returns nodes, edges, and per-edge `source_quote` + `url`.
3. **Expected next events**: for an open procedure, take its last stage concept, look up in `beliefs` the
   learned lag distribution to the next concept, insert `expectations` (company, concept, window); when a
   matching event arrives mark `met_event_id`, else `missed` (this is the existing learning loop).
4. **Same company everywhere** (entity check): `SELECT ... FROM companies c JOIN company_identifiers i ...
   WHERE i.scheme='lei' AND i.value=:lei` (see section 7).
5. **Likely bidders (D81) as a graph query**: companies with `awarded_to` edges to events of the same
   concept in the same country in the last 365 days, ranked by count and recency (already implemented
   without the table; the graph just makes it a query).

### 5.3 What v0 delivers
Migration + `links` + builder from existing events/claims + a trace endpoint returning
`{nodes:[], edges:[{claim_ids, quote, url, derivation}]}` + 3 saved queries. Decision needed in
`docs/DECISIONS.md` and a ticket on the board. Note D86: `events` are not yet saved to the canonical schema
by `radar/persist.py` ("Not saved yet: events"), so v0 first needs events persisted, or must build
edges from claims and documents (`group_key`) directly. This is the main dependency.

## 6. Temporal model and link prediction (v1, using existing tables)

- **Two times per edge** (copied from Graphiti's idea, F3): `valid_from/valid_to` (world) and `recorded_at`
  (when knowable, `documents.available_at`). This also keeps the time-machine backtest honest: the replay
  only sees edges whose `recorded_at` is before the as-of date.
- **Project lifecycle** = ordered `event_concepts` along one `procedure`/cluster. Stage lags (plan to tender,
  tender to award, award to first purchase) are learned parameters in `beliefs`; each prediction is an
  `expectations` row (`origin` world/buying) that resolves met or missed. This is the "link prediction":
  P(next concept within N months | previous concept, sector codes, country). Start with simple counted
  frequencies and credible intervals; no graph neural nets (**I**, adequate for our data size).
- **Missed expectations** are lessons, consistent with ARCHITECTURE v2 (expectations table and learners).
- Inferred links created from these predictions are `derivation='inferred'` with the belief id in details.

## 7. Entity resolution (foundation)

- Today: `companies.primary_domain` unique, `aliases[]`, `country`. TED, FTS and news give names and
  sometimes registry ids; domains are often absent.
- Suggested table (design): `company_identifiers(company_id, scheme, value, source_document_id)` with
  unique (scheme, value). Schemes as data: `lei`, `ted_org_id`, `company_number:GB`, `vat`, `domain`.
  Matching ladder in code, strict to loose: exact identifier, then domain, then normalised name + country
  (`unaccent`, lowercase, strip legal-form words from a data list) with `pg_trgm` similarity, then embedding
  similarity as a **suggestion only**. Merges below a high threshold go to the `questions` queue for a person.
  Wrong merges contaminate the whole graph, so prefer a missed merge to a false one (**I**).
- Multilingual names: `unaccent` handles accents (S1); transliteration (Cyrillic, CJK, Arabic) is not covered
  by those extensions (**I**); embeddings (Nemotron Embed, already 1024-dim) can propose pairs.
- GLEIF: fuzzy name search and parent/child relationships exist (E1). Free use, rate limit, key and licence:
  **unknown** (command in E1). Parent/child relations would also give `part_of`/`owned_by` edges
  with a stated source.
- Do not use LinkedIn (CLAUDE.md rule 9). OpenCorporates and national registers: not researched.

## 8. NVIDIA angle

- cuGraph/nx-cugraph needs a CUDA 12.2+ NVIDIA GPU on Linux (N1). Our v0/v1 graph algorithms (hop queries,
  counts) run in Postgres; GPU adds nothing at our size (**I**). Nebius has GPU VMs (N3) but our deploy plan is
  Serverless Endpoints/Jobs; GPU there is unconfirmed. Recommendation: skip for the hackathon.
- NVIDIA's RAG blueprint has no graph piece (N2); the older cuGraph KG sample is dated. Not worth copying.
- Best NVIDIA story: Nemotron (extraction, event classification, relation proposals, embeddings) on Token
  Factory, with the claims ledger turning those outputs into verified links. Stating "Nemotron proposes,
  code verifies, graph shows" is accurate and demonstrable.
- NeMo Retriever with graphs: no source found (**U**).

## 9. Visual stack

| Library | Beauty/animation | 1k to 50k nodes | Licence | Size (gzip) | Verdict |
|---|---|---|---|---|---|
| react-force-graph-2d | good out of the box; particles along links, `dagMode` left to right for a timeline, reveal via `nodeVisibility`; canvas so easy custom node drawing | fine to a few thousand (**I**); 50k not advised | MIT | 60.5 KB (V6) | **Hero** |
| react-force-graph-3d | impressive in 3D but harder to read; three.js weight | WebGL, better than 2D (**I**) | MIT | large (not measured) | Optional ad flourish |
| Sigma.js + graphology | WebGL, clean, controllable via reducers; straight edges; custom edge programs needed for drawn-line animation (**I**) | best of the DOM-free options; claim "thousands" only (V2); 50k plausible (**I**, test it) | MIT | 25.8 + 14 KB (V6) | **v1 explorer** |
| Cytoscape.js | mature layouts and analysis (e.g. dagre), dated look | thousands (**I**) | MIT | 117 KB | Skip |
| Reagraph | WebGL, 2D/3D, good looks, edge bundling, path finding | WebGL (**I**) | Apache-2.0 | heavy (three.js, **I**) | Alternative |
| Cosmograph / cosmos.gl | GPU layout, hundreds of thousands (claim); looks like "dots" aesthetic; no React wrapper in cosmos.gl; Cosmograph licence **unknown** | best | MIT (cosmos.gl only) | not measured | v2 for huge graphs; check licence first |
| deck.gl, D3-force | not researched; D3-force is only layout (I) | n/a | n/a | n/a | D3-force useful for a precomputed layout |

Fit with the stored design memory (captivating, Muse/Grok/dots aesthetic): the "dots" look suggests a dark
canvas, small glowing nodes, thin lines. That is achievable with canvas drawing in react-force-graph-2d
(custom `nodeCanvasObject`) and recorded cleanly for the ad.

### Hero animation sketch ("the chain lights up")

Data: the trace endpoint returns 6 to 12 nodes and their edges for one case (all linked to claims).
1. Dark canvas, a faint field of grey dots (the background world, a few hundred nodes, low opacity).
2. t=0: the first event dot (for example "plan approved") glows and a one-line caption fades in with its
   verified quote and source name.
3. Each next stage: a line is drawn from the previous dot (dash-offset or particles flowing along the
   link), the next dot pops and takes a colour from its event kind, caption updates. Camera eases to keep the
   active node centred (`centerAt`, `zoom`).
4. Final stage: the winner company pulses, and dashed "inferred" lines fan out to likely buyers with
   confidence. Solid = stated and sourced; dashed = inferred, labelled so.
5. Click any line: a drawer shows the quote and a link to the source page (the proof moment).
Implementation notes (design): precompute positions (left-to-right by date) so the animation is
deterministic for the video; drive reveal state with one timeline value; capture with the browser
screen recorder or a headless capture for the ad.

## 10. Limits and risks
- Postgres CTE traversal cost grows with branching factor; cap depth at 3 to 4 and index both edge ends (I).
- Neon free tier: 1 GB storage, scale-to-zero cold start affects a live demo (S10).
- Sigma 50k nodes, Reagraph and deck.gl performance not verified: run a quick spike before committing.
- Hosted Neo4j/FalkorDB cloud tiers' limits and terms unverified.
- `events` not yet persisted (D86) is the true prerequisite for v0.

## 11. Open questions for the founder or next research
1. Is `events` persistence (D86 follow-up) scheduled before the graph ticket? (blocks v0)
2. Does the hackathon repo licence interact with SSPL (FalkorDB) or BSL (Memgraph)? Only matters for v1.
3. Check GLEIF limits: run the curl in E1. Check Neon AGE: the SQL in S1. Check Aura Free caps: Aura console.
4. Cosmograph commercial licence: read https://cosmograph.app pricing/library page before any use.
5. Multilingual company name matching: need a sample of real TED vs FTS vs news names to test the ladder.
6. Does Nebius Serverless support GPU containers? Only relevant if NVIDIA GPU graph tech is ever wanted.
