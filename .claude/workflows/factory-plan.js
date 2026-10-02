export const meta = {
  name: 'factory-plan',
  description: 'Plan a Northvaine milestone: draft contracts + tickets, research external facts, critique, and save the board',
  whenToUse: 'Before building a milestone. args: {milestone: number, today: "YYYY-MM-DD", notes?: string}',
  phases: [
    { title: 'Draft', detail: 'architect drafts waves, contracts, tickets, research list' },
    { title: 'Research', detail: 'one researcher per external topic, sourced notes in docs/integrations/' },
    { title: 'Critique', detail: 'reviewer + mechanical write-scope check' },
    { title: 'Finalize', detail: 'architect revises and writes factory/board/M<n>/' },
  ],
}

// Model per role (override any with args.models, e.g. {builder: 'opus'}).
const MODELS = { architect: 'opus', reviewer: 'opus', builder: 'sonnet', 'test-engineer': 'sonnet', researcher: 'sonnet', integrator: 'sonnet', loader: 'haiku', ...((args && args.models) || {}) }
const M = args && args.milestone
if (!M) throw new Error('args.milestone is required, e.g. {milestone: 1, today: "2026-10-02"}')
const TODAY = (args && args.today) || 'today'
const NOTES = (args && args.notes) || 'none'
const role = r => `Act as the ${r} defined in .claude/agents/${r}.md (read it first) and follow docs/FACTORY.md.`

const TICKET = {
  type: 'object',
  properties: {
    id: { type: 'string' }, title: { type: 'string' },
    role: { type: 'string', enum: ['builder', 'test-engineer', 'researcher'] },
    lane: { type: 'string' }, wave: { type: 'integer' },
    depends_on: { type: 'array', items: { type: 'string' } },
    writes: { type: 'array', items: { type: 'string' } },
    reads: { type: 'array', items: { type: 'string' } },
    acceptance: { type: 'array', items: { type: 'string' } },
  },
  required: ['id', 'title', 'role', 'lane', 'wave', 'depends_on', 'writes', 'acceptance'],
}
const PLAN = {
  type: 'object',
  properties: {
    goal: { type: 'string' },
    summary: { type: 'string' },
    research_needed: {
      type: 'array',
      items: {
        type: 'object',
        properties: { topic: { type: 'string' }, questions: { type: 'array', items: { type: 'string' } } },
        required: ['topic', 'questions'],
      },
    },
    tickets: { type: 'array', items: TICKET },
    risks: { type: 'array', items: { type: 'string' } },
    decisions_proposed: { type: 'array', items: { type: 'string' } },
    questions_for_founder: { type: 'array', items: { type: 'string' } },
    parked: { type: 'array', items: { type: 'string' } },
    files_written: { type: 'array', items: { type: 'string' } },
  },
  required: ['goal', 'summary', 'research_needed', 'tickets', 'risks', 'questions_for_founder'],
}
const RESEARCH = {
  type: 'object',
  properties: {
    topic: { type: 'string' }, file: { type: 'string' },
    confirmed: { type: 'array', items: { type: 'string' } },
    unconfirmed: { type: 'array', items: { type: 'string' } },
  },
  required: ['topic', 'file', 'confirmed', 'unconfirmed'],
}
const CRITIQUE = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['approve', 'changes'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: { severity: { type: 'string' }, ticket: { type: 'string' }, issue: { type: 'string' }, fix: { type: 'string' } },
        required: ['severity', 'issue', 'fix'],
      },
    },
  },
  required: ['verdict', 'findings'],
}

const norm = p => p.replace(/\\/g, '/').replace(/\/+$/, '')
const overlaps = (a, b) => { a = norm(a); b = norm(b); return a === b || a.startsWith(b + '/') || b.startsWith(a + '/') }
function scopeConflicts(tickets) {
  const out = []
  for (let i = 0; i < tickets.length; i++)
    for (let j = i + 1; j < tickets.length; j++) {
      const a = tickets[i], b = tickets[j]
      if (a.wave !== b.wave) continue
      for (const pa of a.writes) for (const pb of b.writes)
        if (overlaps(pa, pb)) out.push(`wave ${a.wave}: ${a.id} and ${b.id} both write ${pa} / ${pb}`)
    }
  return out
}

phase('Draft')
const draft = await agent(
  `${role('architect')}
Draft the plan for milestone ${M} (date: ${TODAY}). Founder notes: ${NOTES}
Inspect the repository as it is now (existing code may be partial or broken; plan to fix it, not ignore it).
Do NOT write any files yet. Return the plan. Ticket ids look like T${M}.0, T${M}.1, ...; wave 0 is the contracts ticket(s).
List under research_needed ONLY external facts that are new for this milestone and not already confirmed in docs/integrations/ (no research for well-known libraries already in use). Prefer fewer, larger tickets (aim 4-7) over many small ones.`,
  { model: MODELS.architect, label: 'architect:draft', schema: PLAN },
)
log(`Draft: ${draft.tickets.length} tickets, ${draft.research_needed.length} research topics`)

phase('Research')
const research = (await parallel(draft.research_needed.map(r => () =>
  agent(`${role('researcher')}
Topic: ${r.topic}. Date checked: ${TODAY}.
Questions:\n- ${r.questions.join('\n- ')}
Write docs/integrations/${r.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.md (create docs/integrations/ if needed; only that file).`,
    { model: MODELS.researcher, label: `research:${r.topic}`, schema: RESEARCH }),
))).filter(Boolean)

phase('Critique')
const mechanical = scopeConflicts(draft.tickets)
if (mechanical.length) log(`Write-scope conflicts in draft: ${mechanical.length}`)
const critique = await agent(
  `${role('reviewer')}
Review this milestone ${M} PLAN (not code). Research results are included; flag any ticket that relies on an unconfirmed fact.
Mechanical write-scope conflicts already detected: ${JSON.stringify(mechanical)}
PLAN: ${JSON.stringify(draft)}
RESEARCH: ${JSON.stringify(research)}`,
  { model: MODELS.reviewer, label: 'reviewer:plan', schema: CRITIQUE },
)

phase('Finalize')
const final = await agent(
  `${role('architect')}
Finalize milestone ${M}. Revise the draft using the research and the critique (fix every blocking finding and every write-scope conflict).
Then WRITE the board: factory/board/M${M}/PLAN.md and one ticket file per ticket from factory/templates/ticket.md, all with status: proposed.
Write nothing outside factory/board/M${M}/. Return the final plan with files_written.
DRAFT: ${JSON.stringify(draft)}
RESEARCH: ${JSON.stringify(research)}
CRITIQUE: ${JSON.stringify(critique)}
MECHANICAL CONFLICTS: ${JSON.stringify(mechanical)}`,
  { model: MODELS.architect, label: 'architect:final', schema: PLAN },
)

const remaining = scopeConflicts(final.tickets)
if (remaining.length) log(`WARNING: write-scope conflicts remain: ${remaining.join('; ')}`)
return {
  milestone: M,
  goal: final.goal,
  summary: final.summary,
  tickets: final.tickets.map(t => ({ id: t.id, title: t.title, wave: t.wave, role: t.role, writes: t.writes })),
  research: research.map(r => ({ topic: r.topic, file: r.file, unconfirmed: r.unconfirmed })),
  critique_verdict: critique.verdict,
  remaining_scope_conflicts: remaining,
  risks: final.risks,
  decisions_proposed: final.decisions_proposed || [],
  questions_for_founder: final.questions_for_founder,
  parked: final.parked || [],
  files_written: final.files_written || [],
}
