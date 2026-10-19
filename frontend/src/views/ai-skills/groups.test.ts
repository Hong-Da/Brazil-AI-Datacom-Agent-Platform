import { describe, expect, it } from 'vitest'
import { groupChips, groupSkills, matches, type Groupable, type SkillGroup } from './groups'

const t = (zh: string, en = zh) => ({ 'zh-CN': zh, en, 'pt-BR': en })
const G: SkillGroup[] = [
  { id: 'qa', title: t('问答', 'Q&A'), count: 2 },
  { id: 'generate', title: t('配置生成'), count: 1 },
  { id: 'analysis', title: t('日常分析'), count: 0 },
  { id: 'kb', title: t('知识库构建'), count: 1 },
  { id: 'other', title: t('其他'), count: 0 },
]
const S: (Groupable & { n: number })[] = [
  { id: 'ask-query', title: t('问答：写图查询', 'Ask: write the query'), description: t('把问题转成图查询'), group: 'qa', used_by: 'ask', n: 1 },
  { id: 'ask-answer', title: t('问答：组织回答'), description: t('写回答'), group: 'qa', used_by: 'ask', n: 2 },
  { id: 'config-generate', title: t('配置生成'), description: t('生成配置'), group: 'generate', used_by: 'generate', n: 3 },
  { id: 'card-extract', title: t('命令卡语法修正'), description: t('修正抽取失败的命令'), group: 'kb', used_by: 'ingest', n: 4 },
  { id: 'odd', title: t('奇怪的'), description: t('组写错了'), group: 'nope', n: 5 },
]

describe('skill 分组', () => {
  it('按组排序，写错组的归入其他，空组默认不显示', () => {
    const b = groupSkills(G, S)
    expect(b.map((x) => x.group.id)).toEqual(['qa', 'generate', 'kb', 'other'])
    expect(b[0].skills.map((s) => s.id)).toEqual(['ask-query', 'ask-answer'])
    expect(b[3].skills.map((s) => s.id)).toEqual(['odd'])
  })
  it('showEmpty 时列出空组（搜索时不列）', () => {
    expect(groupSkills(G, S, { showEmpty: true }).map((x) => x.group.id)).toContain('analysis')
    expect(groupSkills(G, S, { showEmpty: true, q: 'ask' }).map((x) => x.group.id)).toEqual(['qa'])
  })
  it('按组筛选与跨组搜索（编号、标题、说明，各语言）', () => {
    expect(groupSkills(G, S, { group: 'kb' }).map((x) => x.skills.length)).toEqual([1])
    expect(groupSkills(G, S, { q: 'write the' })[0].skills.map((s) => s.id)).toEqual(['ask-query'])
    expect(groupSkills(G, S, { q: '配置' }).map((x) => x.group.id)).toEqual(['generate'])
    expect(groupSkills(G, S, { q: 'CARD' }).map((x) => x.group.id)).toEqual(['kb'])
    expect(groupSkills(G, S, { q: 'zzz' })).toEqual([])
    expect(groupSkills(G, S, { use: 'ask' }).map((x) => x.group.id)).toEqual(['qa'])
    const b = groupSkills(G, S, { q: '回答' })
    expect(b[0]).toMatchObject({ total: 2 })
    expect(b[0].skills).toHaveLength(1)
  })
  it('没有 other 组时补上；组选项带个数', () => {
    const noOther = G.filter((g) => g.id !== 'other')
    expect(groupSkills(noOther, S).at(-1)?.group.id).toBe('other')
    expect(groupChips(G, S)).toEqual([
      { id: 'qa', title: G[0].title, n: 2 }, { id: 'generate', title: G[1].title, n: 1 }, { id: 'kb', title: G[3].title, n: 1 }, { id: 'other', title: G[4].title, n: 1 },
    ])
    expect(matches(S[0], '')).toBe(true)
  })
})
