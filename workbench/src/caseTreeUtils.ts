import type { CaseTreeNode, CaseTreeCategory, WorkbenchCase } from "./types";

// Subset → Chinese label + emoji
export const SUBSET_META: Record<string, { label: string; emoji: string }> = {
  generalized_mvp: { label: "基础集", emoji: "🧪" },
  synthetic_seeded_v1: { label: "Synthetic 世界", emoji: "🧬" },
  generalization: { label: "泛化集", emoji: "🧠" },
};

// Category → Chinese label + emoji
export const CATEGORY_META: Record<string, { label: string; emoji: string }> = {
  auth: { label: "身份认证", emoji: "🔐" },
  lookup: { label: "订单查询", emoji: "📋" },
  cancel: { label: "取消订单", emoji: "✅" },
  guard: { label: "写保护", emoji: "🛡️" },
  confirmation: { label: "确认流程", emoji: "🔄" },
  transfer: { label: "转接", emoji: "📞" },
  modify_items: { label: "修改商品", emoji: "📦" },
  modify_payment: { label: "修改支付", emoji: "💳" },
  modify_address: { label: "修改地址", emoji: "📮" },
  modify_shipping: { label: "配送修改", emoji: "🚚" },
  exchange: { label: "换货", emoji: "↩️" },
  return: { label: "退货", emoji: "📤" },
};

export function buildCaseTree(allCases: WorkbenchCase[]): CaseTreeNode[] {
  const bySubset = new Map<string, WorkbenchCase[]>();
  for (const c of allCases) {
    const key = c.subset || "other";
    if (!bySubset.has(key)) bySubset.set(key, []);
    bySubset.get(key)!.push(c);
  }

  const tree: CaseTreeNode[] = [];
  for (const [subsetKey, cases] of bySubset) {
    // Group cases within subset by category
    const byCategory = new Map<string, WorkbenchCase[]>();
    for (const c of cases) {
      const catKey = c.category || "other";
      if (!byCategory.has(catKey)) byCategory.set(catKey, []);
      byCategory.get(catKey)!.push(c);
    }

    const categories: CaseTreeCategory[] = [];
    for (const [catKey, catCases] of byCategory) {
      const meta = CATEGORY_META[catKey] || { label: catKey, emoji: "📁" };
      categories.push({
        key: catKey,
        label: meta.label,
        emoji: meta.emoji,
        cases: catCases,
      });
    }

    // Sort categories by defined order
    const categoryOrder = Object.keys(CATEGORY_META);
    categories.sort((a, b) => {
      const ia = categoryOrder.indexOf(a.key);
      const ib = categoryOrder.indexOf(b.key);
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });

    const subsetMeta = SUBSET_META[subsetKey] || { label: subsetKey, emoji: "📦" };
    tree.push({
      key: subsetKey,
      label: subsetMeta.label,
      emoji: subsetMeta.emoji,
      categories,
    });
  }

  // Sort subsets: generalized_mvp first, then synthetic, then others
  const subsetOrder = ["generalized_mvp", "synthetic_seeded_v1"];
  tree.sort((a, b) => {
    const ia = subsetOrder.indexOf(a.key);
    const ib = subsetOrder.indexOf(b.key);
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
  });

  return tree;
}