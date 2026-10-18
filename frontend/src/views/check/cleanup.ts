/** 冗余清理页的纯逻辑：孤儿对象树、级联勾选、按选中对象过滤删除命令、脚本文本。 */
import type { CleanupCommand, CleanupObject, CleanupResult } from './types'

export interface TreeRow { o: CleanupObject; depth: number; parent: string | null }

/** 级联孤儿挂在第一个仍在清单里的引用方下面；顺序与后端一致（引用方在前）。 */
export function orphanTree(objects: CleanupObject[]): TreeRow[] {
  const ids = new Set(objects.map((o) => o.node))
  const parentOf = (o: CleanupObject) => (o.reason === 'cascade' ? (o.via.find((v) => ids.has(v) && v !== o.node) ?? null) : null)
  const kids = new Map<string, CleanupObject[]>()
  for (const o of objects) {
    const p = parentOf(o)
    if (p) kids.set(p, [...(kids.get(p) ?? []), o])
  }
  const out: TreeRow[] = []
  const seen = new Set<string>()
  const visit = (o: CleanupObject, depth: number, parent: string | null) => {
    if (seen.has(o.node)) return
    seen.add(o.node)
    out.push({ o, depth, parent })
    for (const c of kids.get(o.node) ?? []) visit(c, depth + 1, o.node)
  }
  for (const o of objects) if (!parentOf(o)) visit(o, 0, null)
  for (const o of objects) visit(o, 0, null)
  return out
}

/** 级联孤儿只要还有一个引用方没被选中删除，它就仍被引用，不能单独删除（锁定）。 */
export function isLocked(o: CleanupObject, picked: Set<string>, objects: CleanupObject[]): boolean {
  if (o.reason !== 'cascade') return false
  const ids = new Set(objects.map((x) => x.node))
  return o.via.some((v) => ids.has(v) && !picked.has(v))
}

/** 勾选 / 取消：取消一个对象时，依赖它的级联孤儿（递归）一起取消；锁定的对象不能勾选。 */
export function togglePick(picked: Set<string>, node: string, on: boolean, objects: CleanupObject[]): Set<string> {
  const next = new Set(picked)
  const obj = objects.find((o) => o.node === node)
  if (!obj) return next
  if (on) {
    if (!isLocked(obj, next, objects)) next.add(node)
    return next
  }
  const stack = [node]
  while (stack.length) {
    const cur = stack.pop()!
    next.delete(cur)
    for (const o of objects) if (o.reason === 'cascade' && o.via.includes(cur) && next.has(o.node)) stack.push(o.node)
  }
  return next
}

export const allPicked = (objects: CleanupObject[]): Set<string> => new Set(objects.map((o) => o.node))

/** 只保留选中对象的删除命令（后端暂不支持按对象生成，前端过滤；顺序沿用后端的依赖顺序）。 */
export function filterCommands(commands: CleanupCommand[], picked: Set<string>): CleanupCommand[] {
  return commands.filter((c) => picked.has(c.object))
}

export function exitWord(family: string, commands: CleanupCommand[]): string {
  return family.startsWith('huawei') || commands.some((c) => c.text.startsWith('undo ')) ? 'quit' : 'exit'
}

export type ScriptRow =
  | { type: 'frame'; text: string; indent: number }
  | { type: 'cmd'; cmd: CleanupCommand; indent: number }

/** 界面上的脚本行：进入视图的原命令、删除命令（缩进到视图内）、退出视图。 */
export function scriptRows(commands: CleanupCommand[], exit: string): ScriptRow[] {
  const out: ScriptRow[] = []
  for (const c of commands) {
    c.context.forEach((t, i) => out.push({ type: 'frame', text: t, indent: i }))
    out.push({ type: 'cmd', cmd: c, indent: c.context.length })
    for (let i = 0; i < c.context.length; i++) out.push({ type: 'frame', text: exit, indent: c.context.length - 1 - i })
  }
  return out
}

/**
 * 脚本文本：全部选中时直接用后端的 script；部分选中时按后端 script_text 的格式重建
 * （! 注释行注明对象与原配置行号，兜底命令标 FALLBACK），并注明选中的对象数。
 */
export function scriptText(res: CleanupResult, picked: Set<string>): string {
  const cmds = filterCommands(res.commands, picked)
  if (cmds.length === res.commands.length && picked.size >= res.objects.length) return res.script
  const exit = exitWord(res.family, res.commands)
  const out = [
    `! lmesh cleanup: ${res.device} (${res.profile}), ${cmds.length} command(s)`,
    `! selected ${res.objects.filter((o) => picked.has(o.node)).length}/${res.objects.length} object(s)`,
  ]
  cmds.forEach((c, i) => {
    const depth = c.context.length
    out.push(`! [${i + 1}] ${c.object} @${c.lines.join(',')}` + (c.fallback ? ' FALLBACK' : ''))
    c.context.forEach((t, j) => out.push(' '.repeat(j) + t))
    out.push(' '.repeat(depth) + c.text)
    for (let j = 0; j < depth; j++) out.push(' '.repeat(depth - 1 - j) + exit)
  })
  return out.join('\n') + '\n'
}

export const scriptFile = (device: string | null): string =>
  `cleanup-${(device || 'config').replace(/[^\w.-]+/g, '_')}.txt`

/** 选中对象原配置中要删除的行数（对象子树的全部行）。 */
export function removedLines(objects: CleanupObject[], picked: Set<string>): number {
  const s = new Set<number>()
  for (const o of objects) if (picked.has(o.node)) o.lines.forEach((n) => s.add(n))
  return s.size
}
