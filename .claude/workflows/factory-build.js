export const meta = {
  name: 'factory-build',
  description: 'Build an approved Northvaine milestone: per wave, builders in isolated worktrees, review + fix loop, then integrator merges and gates',
  whenToUse: 'After the founder approves factory/board/M<n>/. args: {milestone: number, only?: string[] (ticket ids)}',
  phases: [
    { title: 'Load', detail: 'read approved tickets from the board' },
    { title: 'Build', detail: 'builder per ticket in its own git worktree' },
    { title: 'Review', detail: 'reviewer per ticket, up to 2 fix rounds' },
    { title: 'Integrate', detail: 'integrator merges approved branches per wave and runs the gate' },
    { title: 'Verify', detail: 'milestone-level check of acceptance, gate and demo path' },
  ],
}

// Model per role (override any with args.models, e.g. {builder: 'opus'}).
const MODELS = { architect: 'opus', reviewer: 'opus', builder: 'sonnet', 'test-engineer': 'sonnet', researcher: 'sonnet', integrator: 'sonnet', loader: 'haiku', ...((args && args.models) || {}) }
const M = args && args.milestone
if (!M) throw new Error('args.milestone is required')
const ONLY = (args && args.only) || null
const MAX_FIX_ROUNDS = 2
// Lean mode: Opus reviews contract tickets (wave 0); Sonnet reviews the rest. args.models.reviewer forces one model.
const reviewModel = t => ((args && args.models && args.models.reviewer) || (t.wave === 0 ? 'opus' : 'sonnet'))
const builderRole = t => (t.role === 'test-engineer' ? 'test-engineer' : 'builder')
const role = r => `Act as the ${r} defined in .claude/agents/${r}.md (read it first) and follow docs/FACTORY.md.`

const LOAD = {
  type: 'object',
  properties: {
    tickets: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' }, title: { type: 'string' }, file: { type: 'string' },
          role: { type: 'string' }, wave: { type: 'integer' }, status: { type: 'string' },
          depends_on: { type: 'array', items: { type: 'string' } },
          writes: { type: 'array', items: { type: 'string' } },
        },
        required: ['id', 'title', 'file', 'role', 'wave', 'status', 'depends_on', 'writes'],
      },
    },
  },
  required: ['tickets'],
}
const BUILD = {
  type: 'object',
  properties: {
    ticket_id: { type: 'string' },
    status: { type: 'string', enum: ['done', 'blocked'] },
    worktree_path: { type: 'string' }, branch: { type: 'string' }, commit: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    gate_passed: { type: 'boolean' },
    notes: { type: 'string' },
    contract_change_requests: { type: 'array', items: { type: 'string' } },
    questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['ticket_id', 'status', 'worktree_path', 'branch', 'gate_passed', 'notes'],
}
const REVIEW = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['approve', 'changes'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['blocking', 'should_fix', 'nit'] },
          file: { type: 'string' }, line: { type: 'integer' }, issue: { type: 'string' }, fix: { type: 'string' },
        },
        required: ['severity', 'issue', 'fix'],
      },
    },
  },
  required: ['verdict', 'findings'],
}
const INTEGRATE = {
  type: 'object',
  properties: {
    merged: { type: 'array', items: { type: 'object', properties: { ticket_id: { type: 'string' }, merge_sha: { type: 'string' } }, required: ['ticket_id'] } },
    blocked: { type: 'array', items: { type: 'object', properties: { ticket_id: { type: 'string' }, reason: { type: 'string' } }, required: ['ticket_id', 'reason'] } },
    main_gate_passed: { type: 'boolean' },
    notes: { type: 'string' },
  },
  required: ['merged', 'blocked', 'main_gate_passed'],
}
const VERIFY = {
  type: 'object',
  properties: {
    milestone_met: { type: 'boolean' },
    gate_passed: { type: 'boolean' },
    unmet_acceptance: { type: 'array', items: { type: 'string' } },
    demo_path: { type: 'string' },
    report_file: { type: 'string' },
    follow_ups: { type: 'array', items: { type: 'string' } },
  },
  required: ['milestone_met', 'gate_passed', 'unmet_acceptance', 'report_file'],
}

// ---- Load
phase('Load')
const board = await agent(
  `Read every ticket file in factory/board/M${M}/ (not PLAN.md). Parse each one's frontmatter and return them all. Do not modify anything.`,
  { model: MODELS.loader, label: 'load-board', schema: LOAD, effort: 'low' },
)
let tickets = board.tickets.filter(t => (ONLY ? ONLY.includes(t.id) : t.status === 'approved'))
const skipped = board.tickets.filter(t => !tickets.includes(t)).map(t => `${t.id}(${t.status})`)
if (skipped.length) log(`Not building: ${skipped.join(', ')}`)
if (!tickets.length) return { milestone: M, built: [], note: 'No approved tickets. Approve tickets in factory/board first.' }

// ---- Waves: group by wave number, then split any write-scope overlap into sequential batches
const norm = p => p.replace(/\\/g, '/').replace(/\/+$/, '')
const overlaps = (a, b) => { a = norm(a); b = norm(b); return a === b || a.startsWith(b + '/') || b.startsWith(a + '/') }
const clash = (x, y) => x.writes.some(a => y.writes.some(b => overlaps(a, b)))
const waveNums = [...new Set(tickets.map(t => t.wave))].sort((a, b) => a - b)
const batches = []
for (const w of waveNums) {
  const subs = []
  for (const t of tickets.filter(t => t.wave === w).sort((a, b) => a.id.localeCompare(b.id))) {
    const home = subs.find(s => !s.some(o => clash(o, t)))
    home ? home.push(t) : subs.push([t])
  }
  if (subs.length > 1) log(`Wave ${w}: write-scope overlap, split into ${subs.length} sequential batches`)
  subs.forEach((s, i) => batches.push({ label: subs.length > 1 ? `${w}.${i}` : `${w}`, tickets: s }))
}

// ---- Per-ticket chain: build -> review -> fix loop
const reviewPrompt = (t, b, round) => `${role('reviewer')}
Review ticket ${t.id} "${t.title}" (ticket file: ${t.file}). Review round ${round}.
Builder worktree: ${b.worktree_path}  branch: ${b.branch}
Inspect with: git -C "${b.worktree_path}" diff main...HEAD   and run the gate inside that worktree.
Builder notes: ${b.notes}`

async function buildTicket(t) {
  const b = await agent(
    `${role(builderRole(t))}
Implement ticket ${t.id} "${t.title}". Ticket file: ${t.file}. You may write ONLY: ${t.writes.join(', ')}.
You are in an isolated git worktree. Commit your work on the current branch when the gate passes.`,
    { model: MODELS[builderRole(t)], label: `build:${t.id}`, phase: 'Build', isolation: 'worktree', schema: BUILD },
  )
  if (!b) return { ticket: t, status: 'blocked', reason: 'builder failed' }
  if (b.status !== 'done') return { ticket: t, build: b, status: 'blocked', reason: b.notes }

  let review = await agent(reviewPrompt(t, b, 1), { model: reviewModel(t), label: `review:${t.id}`, phase: 'Review', schema: REVIEW })
  for (let round = 1; review && review.verdict !== 'approve' && round <= MAX_FIX_ROUNDS; round++) {
    const blocking = review.findings.filter(f => f.severity !== 'nit')
    const fix = await agent(
      `${role(builderRole(t))}
Fix review findings for ticket ${t.id} (ticket file: ${t.file}).
IMPORTANT: your work is in the existing worktree ${b.worktree_path} on branch ${b.branch}. Run every shell command with
cd "${b.worktree_path}" (or git -C) and edit files only under that path. Never touch the main checkout.
Allowed paths: ${t.writes.join(', ')}. Re-run the gate there, then commit.
Findings: ${JSON.stringify(blocking)}`,
      { model: MODELS[builderRole(t)], label: `fix:${t.id}#${round}`, phase: 'Review', schema: BUILD },
    )
    if (!fix || fix.status !== 'done') return { ticket: t, build: b, review, status: 'blocked', reason: 'fix failed' }
    review = await agent(reviewPrompt(t, { ...b, notes: fix.notes }, round + 1), { model: reviewModel(t), label: `review:${t.id}#${round + 1}`, phase: 'Review', schema: REVIEW })
  }
  if (!review || review.verdict !== 'approve') return { ticket: t, build: b, review, status: 'blocked', reason: 'review not approved after fix rounds' }
  return { ticket: t, build: b, review, status: 'approved' }
}

// ---- Run batches in order; integrate after each
const outcome = []
let mainGreen = true
for (const batch of batches) {
  if (!mainGreen) { log(`Stopping before wave ${batch.label}: main gate is red`); break }
  // a ticket whose dependency is blocked can't run
  const blockedIds = new Set(outcome.filter(o => o.status !== 'merged').map(o => o.ticket.id))
  const runnable = batch.tickets.filter(t => !t.depends_on.some(d => blockedIds.has(d)))
  batch.tickets.filter(t => !runnable.includes(t)).forEach(t => outcome.push({ ticket: t, status: 'blocked', reason: 'dependency blocked' }))
  if (!runnable.length) continue

  log(`Wave ${batch.label}: ${runnable.map(t => t.id).join(', ')}`)
  const results = (await pipeline(runnable, t => buildTicket(t))).filter(Boolean)
  const approved = results.filter(r => r.status === 'approved')
  results.filter(r => r.status !== 'approved').forEach(r => outcome.push(r))
  if (!approved.length) continue

  const integ = await agent(
    `${role('integrator')}
Merge these approved branches into main, in this order, following your role exactly:
${approved.map(r => `- ${r.ticket.id} "${r.ticket.title}": branch ${r.build.branch}, worktree ${r.build.worktree_path}, ticket file ${r.ticket.file}`).join('\n')}`,
    { model: MODELS.integrator, label: `integrate:wave-${batch.label}`, phase: 'Integrate', schema: INTEGRATE },
  )
  mainGreen = !!(integ && integ.main_gate_passed)
  const mergedIds = new Set(((integ && integ.merged) || []).map(m => m.ticket_id))
  approved.forEach(r => outcome.push(mergedIds.has(r.ticket.id)
    ? { ...r, status: 'merged' }
    : { ...r, status: 'blocked', reason: ((integ && integ.blocked) || []).find(x => x.ticket_id === r.ticket.id)?.reason || 'not merged' }))
}

// ---- Milestone verification
phase('Verify')
const verify = await agent(
  `${role('reviewer')}
Milestone-level verification for M${M} on the main checkout (branch main).
Read factory/board/M${M}/PLAN.md. Run uv run python scripts/gate.py. Check each milestone acceptance criterion and the demo path described in the plan.
Write factory/reports/M${M}.md (what was built, merged tickets, blocked tickets with reasons, gate output summary, unmet criteria, follow-ups) and commit it on main.
Ticket outcomes: ${JSON.stringify(outcome.map(o => ({ id: o.ticket.id, status: o.status, reason: o.reason || '' })))}`,
  { model: MODELS.reviewer, label: 'verify:milestone', schema: VERIFY },
)

return {
  milestone: M,
  merged: outcome.filter(o => o.status === 'merged').map(o => o.ticket.id),
  blocked: outcome.filter(o => o.status !== 'merged').map(o => ({ id: o.ticket.id, reason: o.reason || '' })),
  questions: outcome.flatMap(o => (o.build && o.build.questions) || []),
  contract_change_requests: outcome.flatMap(o => (o.build && o.build.contract_change_requests) || []),
  verify,
}
