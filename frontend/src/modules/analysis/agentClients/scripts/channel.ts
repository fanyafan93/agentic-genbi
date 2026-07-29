export const channelScript = {
  startQuestion: "请基于当前数据，分析上个月各渠道的销售占比，并指出增长最快的渠道。",
  replyByOption: {
    "ask-channel-measure": (option: string) => option === "销售额",
    "ask-channel-next": (option: string) => option,
  },
  nodes: {
    firstAsk: {
      question: "你想按什么衡量渠道表现？",
      options: [
        { id: "销售额", label: "销售额" },
        { id: "毛利率", label: "毛利率" },
        { id: "订单数", label: "订单数" },
      ],
    },
    followAsk: {
      question: "想怎么处理这个发现？",
      options: [
        { id: "继续", label: "继续深挖" },
        { id: "报告", label: "出新报告" },
        { id: "审批", label: "创建审批" },
      ],
    },
  },
};
