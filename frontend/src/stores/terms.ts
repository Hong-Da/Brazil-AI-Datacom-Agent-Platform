import { defineStore } from 'pinia'
import { computed, shallowRef } from 'vue'
import { get } from '@/api'
import { i18n } from '@/i18n'
import { usePrefs } from '@/stores/prefs'
import { EMPTY_TERMS, STYLES, Terms, schemaIndex, toStyle, type SchemaNodeLite, type Style, type TermsData } from '@/terms/terms'

/**
 * 显示风格（REQ-026）：全站共用的术语表。第一次使用时加载 /kb/terms 与 /kb/schema（取节点编号与键名），
 * 当前风格保存在 prefs（每个浏览器记住；没选过时用 /kb/terms 的 default，即配置项 ui.term_style）。
 * 加载完成前 label / describe 按 Schema 编号兜底显示，不阻塞页面。
 */
export const useTerms = defineStore('terms', () => {
  const prefs = usePrefs()
  const terms = shallowRef<Terms>(new Terms(EMPTY_TERMS))
  const loaded = shallowRef(false)
  let inflight: Promise<void> | null = null

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    if (inflight) return inflight
    inflight = (async () => {
      try {
        const [data, schema] = await Promise.all([
          get<TermsData>('/kb/terms'),
          get<{ domains: { nodes: SchemaNodeLite[] }[] }>('/kb/schema').catch(() => ({ domains: [] })),
        ])
        terms.value = new Terms(data, schemaIndex(schema.domains))
        loaded.value = true
      } catch { /* 取不到术语表时按 Schema 编号显示 */ } finally { inflight = null }
    })()
    return inflight
  }
  void load()

  const style = computed<Style>({
    get: () => (prefs.termStyle ? toStyle(prefs.termStyle) : terms.value.defaultStyle),
    set: (s) => { prefs.termStyle = toStyle(s) },
  })
  const lang = () => String(i18n.global.locale.value)

  /** 对象节点的命令写法（schema + key）。 */
  function label(schema: string, key: unknown, s: string = style.value): string {
    return terms.value.label(schema, key, s)
  }
  /** 规范编号 → 当前风格的命令路径。 */
  function describe(nodeId: string, s: string = style.value, sep = ' › '): string {
    return terms.value.describe(nodeId, s, sep)
  }
  function describeParts(nodeId: string, s: string = style.value): string[] {
    return terms.value.describeParts(nodeId, s)
  }
  /** 对象类型的叫法（当前语言）。 */
  function name(schema: string, s: string = style.value): string {
    return terms.value.name(schema, s, lang())
  }
  /** 属性的命令关键字；没有登记时 null。 */
  function attr(schema: string, s: string = style.value): string | null {
    return terms.value.attr(schema, s)
  }
  /** Schema 节点的命令写法模板（对象的 label 候选或属性关键字）。 */
  function template(schema: string, s: string = style.value): string | null {
    return terms.value.template(schema, s)
  }
  function styleName(s: string): string {
    const m = terms.value.data.styles[s]
    return (m && (m[lang()] || m.en)) || s
  }

  return { terms, loaded, load, style, styles: STYLES, label, describe, describeParts, name, attr, template, styleName }
})
