import { describe, expect, it } from 'vitest'
import {
  allPicked, exitWord, filterCommands, isLocked, orphanTree, removedLines, scriptFile, scriptRows, scriptText, togglePick,
} from './cleanup'
import type { CleanupCommand, CleanupObject, CleanupResult } from './types'

const obj = (node: string, via: string[] = [], lines: number[] = [1]): CleanupObject => ({
  node, schema: node.replace(/\[.*$/, ''), key: node.replace(/^.*\[(.*)\]$/, '$1'),
  reason: via.length ? 'cascade' : 'orphan', via, lines,
})
const cmd = (seq: number, object: string, text: string, extra: Partial<CleanupCommand> = {}): CleanupCommand => ({
  seq, text, context: [], object, lines: [seq], card: 'c', fallback: false, ...extra,
})

// RM1 是孤儿；CL1 只被 RM1 引用；PL 被 RM1 与 CL1 引用（理论构造，用来测多个引用方）
const RM1 = obj('rp.policy[RM1]', [], [6, 7, 8])
const CL1 = obj('rp.community_list[CL1]', ['rp.policy[RM1]'], [4])
const PL = obj('rp.prefix_list[PL]', ['rp.policy[RM1]', 'rp.community_list[CL1]'], [3, 4])
const OTHER = obj('bridge_domain[1500]', [], [260])
const objects = [RM1, CL1, PL, OTHER]

describe('孤儿对象树', () => {
  it('级联孤儿挂在第一个引用方下面', () => {
    expect(orphanTree(objects).map((r) => [r.o.key, r.depth, r.parent])).toEqual([
      ['RM1', 0, null],
      ['CL1', 1, 'rp.policy[RM1]'],
      ['PL', 1, 'rp.policy[RM1]'],
      ['1500', 0, null],
    ])
  })
  it('取消父对象时级联孤儿一起取消并锁定；重新勾选父对象后才能勾选子对象', () => {
    let p = allPicked(objects)
    p = togglePick(p, RM1.node, false, objects)
    expect([...p]).toEqual([OTHER.node])
    expect(isLocked(CL1, p, objects)).toBe(true)
    expect([...togglePick(p, CL1.node, true, objects)]).toEqual([OTHER.node])
    p = togglePick(p, RM1.node, true, objects)
    expect(isLocked(CL1, p, objects)).toBe(false)
    expect(isLocked(PL, p, objects)).toBe(true) // CL1 还没选
    p = togglePick(p, CL1.node, true, objects)
    p = togglePick(p, PL.node, true, objects)
    expect(p.size).toBe(4)
  })
  it('只取消子对象不影响父对象；取消中间层会带走依赖它的对象', () => {
    let p = allPicked(objects)
    p = togglePick(p, CL1.node, false, objects)
    expect(p.has(RM1.node)).toBe(true)
    expect(p.has(PL.node)).toBe(false)
  })
})

describe('删除脚本', () => {
  const res: CleanupResult = {
    device: 'R1', profile: 'cisco-iosxe-asr920-17.15', family: 'cisco-iosxe',
    objects: [RM1, CL1, OTHER],
    commands: [
      cmd(1, RM1.node, 'no route-map RM1 permit 10', { lines: [6], fallback: true, card: 'cisco-iosxe.route-map' }),
      cmd(2, CL1.node, 'no ip community-list standard CL1', { lines: [4] }),
      cmd(3, OTHER.node, 'no bridge-domain 1500', { lines: [260], context: ['router x', 'af y'] }),
    ],
    skipped: [], fallbacks: 1,
    script: 'BACKEND SCRIPT\n',
  }
  it('全部选中时用后端脚本原文', () => {
    expect(scriptText(res, allPicked(res.objects))).toBe('BACKEND SCRIPT\n')
  })
  it('部分选中时按后端格式重建，并注明选中的对象数', () => {
    const p = togglePick(allPicked(res.objects), RM1.node, false, res.objects)
    expect(filterCommands(res.commands, p).map((c) => c.seq)).toEqual([3])
    expect(scriptText(res, p)).toBe(
      [
        '! lmesh cleanup: R1 (cisco-iosxe-asr920-17.15), 1 command(s)',
        '! selected 1/3 object(s)',
        '! [1] bridge_domain[1500] @260',
        'router x',
        ' af y',
        '  no bridge-domain 1500',
        ' exit',
        'exit',
        '',
      ].join('\n'),
    )
  })
  it('与后端 script_text 的格式一致（兜底命令标 FALLBACK）', () => {
    const p = new Set([RM1.node])
    expect(scriptText(res, p).split('\n').slice(2, 4)).toEqual(['! [1] rp.policy[RM1] @6 FALLBACK', 'no route-map RM1 permit 10'])
  })
  it('界面脚本行：进入视图、删除命令、退出视图', () => {
    const rows = scriptRows([res.commands[2]], 'quit')
    expect(rows.map((r) => [r.type, r.type === 'frame' ? r.text : r.cmd.text, r.indent])).toEqual([
      ['frame', 'router x', 0], ['frame', 'af y', 1], ['cmd', 'no bridge-domain 1500', 2], ['frame', 'quit', 1], ['frame', 'quit', 0],
    ])
  })
  it('退出视图的命令按平台族；文件名与删除行数', () => {
    expect(exitWord('huawei-vrp8', [])).toBe('quit')
    expect(exitWord('cisco-iosxe', [])).toBe('exit')
    expect(scriptFile('PE ASR/01')).toBe('cleanup-PE_ASR_01.txt')
    expect(removedLines(objects, new Set([CL1.node, PL.node]))).toBe(2)
  })
})
