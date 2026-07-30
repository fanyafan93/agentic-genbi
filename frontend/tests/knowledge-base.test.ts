import { describe, expect, it } from "vitest";

import { demoKnowledgeItems } from "../src/modules/knowledge-base/mock";
import { buildKnowledgePayload, deriveKnowledgeTags, filterKnowledgeItems, mapBackendKnowledgeRecord } from "../src/modules/knowledge-base/logic";
import type { KnowledgeFilterState, KnowledgeSaveInput } from "../src/modules/knowledge-base/types";

const baseFilters: KnowledgeFilterState = {
  tab: "all",
  query: "",
  type: "all",
  status: "all",
  tag: "all",
  owner: "all",
};

describe("knowledge base filtering", () => {
  it("filters semantic knowledge by tab and type", () => {
    const semantic = filterKnowledgeItems(demoKnowledgeItems, { ...baseFilters, tab: "semantic" });
    const metrics = filterKnowledgeItems(demoKnowledgeItems, { ...baseFilters, tab: "semantic", type: "metric_definition" });

    expect(semantic.every((item) => ["metric_definition", "dimension_definition", "entity_definition", "field_mapping", "formula_definition"].includes(item.type))).toBe(true);
    expect(metrics.map((item) => item.type)).toEqual(["metric_definition"]);
  });

  it("filters governance states in the certification tab", () => {
    const certification = filterKnowledgeItems(demoKnowledgeItems, { ...baseFilters, tab: "certification" });

    expect(certification.map((item) => item.status)).toEqual(expect.arrayContaining(["pending", "conflicted"]));
    expect(certification.some((item) => item.status === "approved")).toBe(false);
  });

  it("searches across business definition, table and tags", () => {
    const matched = filterKnowledgeItems(demoKnowledgeItems, { ...baseFilters, query: "nnet_inc" });

    expect(matched.map((item) => item.title)).toContain("毛利率");
    expect(matched.map((item) => item.title)).toContain("收入净额字段映射");
  });
});

describe("knowledge base backend mapping", () => {
  it("maps backend metadata into full UI knowledge items", () => {
    const item = mapBackendKnowledgeRecord({
      id: "kn_backend",
      title: "复购率",
      question: "复购率怎么算？",
      conclusion: "自然周期复购率按成交两次用户数除以成交用户数。",
      scope: "经营分析",
      verification: "资源库与字段核验",
      evidence_refs: ["复购分析.cpt"],
      run_id: "conv_1",
      created_at: "2026-07-28T10:00:00Z",
      metadata: {
        type: "metric_definition",
        status: "approved",
        owner: "经营 BI 组",
        tags: ["运营指标", "报表口径"],
        related_tables: ["dm.dm_consr_rebuy_analysis"],
        agent_visible: true,
      },
    });

    expect(item.type).toBe("metric_definition");
    expect(item.status).toBe("approved");
    expect(item.owner).toBe("经营 BI 组");
    expect(item.relatedTables).toEqual(["dm.dm_consr_rebuy_analysis"]);
    expect(item.sourceExplorationId).toBe("conv_1");
  });

  it("builds a backend payload with semantic and governance metadata", () => {
    const input: KnowledgeSaveInput = {
      title: "客单价",
      type: "metric_definition",
      content: "成交金额 / 成交订单数。",
      businessDefinition: "衡量每笔订单平均成交额。",
      technicalDefinition: "sum(gmv) / count(distinct order_id)",
      formula: "sum(gmv) / count(distinct order_id)",
      scope: "销售分析",
      excludedScope: "退款后净额口径",
      owner: "经营 BI 组",
      visibility: "company",
      status: "pending",
      tags: ["销售分析", "运营指标"],
      relatedTables: ["dm.dm_sales_order"],
      relatedFields: ["gmv", "order_id"],
      relatedResources: ["销售总览.cpt"],
      agentVisible: true,
    };

    const payload = buildKnowledgePayload(input);

    expect(payload.title).toBe("客单价");
    expect(payload.metadata.type).toBe("metric_definition");
    expect(payload.metadata.related_tables).toEqual(["dm.dm_sales_order"]);
    expect(payload.metadata.agent_visible).toBe(true);
  });

  it("derives tag counts from knowledge items and backend tags", () => {
    const tags = deriveKnowledgeTags(demoKnowledgeItems, [{ name: "财务指标", group: "业务域", count: 10 }]);

    expect(tags.find((tag) => tag.name === "财务指标")?.count).toBeGreaterThan(10);
    expect(tags.some((tag) => tag.name === "Agent 可用")).toBe(true);
  });
});
